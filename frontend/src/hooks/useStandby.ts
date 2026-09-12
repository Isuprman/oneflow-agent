import { useCallback, useEffect, useRef, useState } from 'react'
import { getPrefs, savePrefs } from '../prefs'
import { startStandby } from '../lib/speech/asr'
import { startLocalStandby } from '../lib/speech/local'
import { bumpConvoIdle, isConvoActive, resetWakeState, type ConvoEvent } from '../lib/speech/wake'
import { getDesktopBridge } from '../lib/speech/bridge'
import { pickQuip, resetQuipProgress } from '../lib/quips'
import { stopAudio, stopSpeaking } from '../lib/speech/playback'
import { playWakeTone } from '../lib/speech/tone'

// 致命识别错误码：命中则不再假装监听，停掉待命并明确提示；其余（no-speech/aborted 等）由重挂自愈
const FATAL_SR_ERRORS = ['not-allowed', 'service-not-allowed', 'network', 'bad-grammar']

export interface StandbyDispatch {
  doSend: (text: string) => void
  speakReply: (plain: string, followUp?: boolean) => void
  // 忙闲/播报链镜像（俏皮话守卫与打断恢复判断用）
  sendingRef: { current: boolean }
  voiceLiveRef: { current: boolean }
  speakChainRef: { current: number }
  lastSpeakEndRef: { current: number }
  bumpInteraction: () => void
}

interface UseStandbyOpts {
  setError: (message: string) => void
  showJarvisEcho: (text: string | null) => void
}

// 常驻待命（语音唤醒 + 会话模式）：唤醒词命中→派发指令、免唤醒连说、
// 空唤醒俏皮话、致命错误处理与重挂循环；传输层自动选择本地识别/Web Speech。
// 发送与播报的实现经 bind() 注入（彼此互调，用最新实现 ref 解环）。
export function useStandby(opts: UseStandbyOpts) {
  const { setError, showJarvisEcho } = opts
  const [standbyOn, setStandbyOn] = useState(false)
  const [wakeStatus, setWakeStatus] = useState('')
  const [standbyLive, setStandbyLive] = useState('')
  // 会话模式（唤醒即进入，说“退下”或闲置超时退出）
  const [convoOn, setConvoOn] = useState(false)
  const standbyStopRef = useRef<(() => void) | null>(null)
  const standbyOnRef = useRef(false)
  // 语音播报期间暂停待命：true 表示播报前已暂停、播完要恢复
  const resumeStandbyRef = useRef(false)
  // 播报前暂停 / 播完恢复待命的动作（armStandby/stopStandbyLocal 定义在下方，经 ref 供播报方访问最新实现）
  const standbyActionsRef = useRef<{ pause: () => void; resume: () => void }>({ pause: () => {}, resume: () => {} })
  const standbyTimerRef = useRef<number | null>(null)
  // 待命识别的最近一次错误码（onerror 先于 onend，供重挂决策区分致命/瞬态）
  const standbyErrorRef = useRef<string>('')
  // 连续空唤醒计数 + 俏皮话定时器
  const emptyWakeCountRef = useRef(0)
  const quipTimerRef = useRef<number | null>(null)
  const dispatchRef = useRef<StandbyDispatch | null>(null)

  const bind = (dispatch: StandbyDispatch) => { dispatchRef.current = dispatch }

  const stopStandbyLocal = useCallback((keepOpts?: { keepConvo?: boolean }) => { standbyOnRef.current = false; if (standbyTimerRef.current) window.clearTimeout(standbyTimerRef.current); standbyStopRef.current?.(); standbyStopRef.current = null; resetWakeState(keepOpts?.keepConvo ?? false); if (keepOpts?.keepConvo) bumpConvoIdle(); setStandbyOn(false); setStandbyLive(''); setWakeStatus('') }, [])

  const handleWake = useCallback((command: string) => {
    const dispatch = dispatchRef.current
    if (!dispatch) return
    dispatch.bumpInteraction()
    setWakeStatus('已唤醒'); stopAudio(); stopSpeaking()
    playWakeTone()
    // 播报链被打断后，若 1.5s 内没有新播报接管，恢复待命（防卡在暂停态）
    window.setTimeout(() => {
      if (dispatch.speakChainRef.current === 0 && resumeStandbyRef.current) {
        resumeStandbyRef.current = false
        if (!standbyOnRef.current) standbyActionsRef.current.resume()
      }
    }, 1500)
    // 任何一句真话到达：取消待发的俏皮话
    if (quipTimerRef.current) { window.clearTimeout(quipTimerRef.current); quipTimerRef.current = null }
    const text = command.trim()
    if (text) {
      // 正常指令：重置空唤醒递进（他“原谅”你了）
      emptyWakeCountRef.current = 0
      resetQuipProgress()
      dispatch.doSend(text)
      return
    }
    // 仅唤醒：时段问候 + 3.5s 内没指令则来一句俏皮话
    const hour = new Date().getHours()
    const greet = hour < 5 ? '夜深了' : hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好'
    setWakeStatus(`${greet}，先生。请说指令`)
    emptyWakeCountRef.current += 1
    const count = emptyWakeCountRef.current
    quipTimerRef.current = window.setTimeout(() => {
      quipTimerRef.current = null
      if (dispatch.sendingRef.current || dispatch.voiceLiveRef.current || !isConvoActive()) return
      const quip = pickQuip(count, {
        night: hour >= 23 || hour < 5,
        afterSpeak: Date.now() - dispatch.lastSpeakEndRef.current < 60000,
      })
      showJarvisEcho(quip)
      dispatch.speakReply(quip)
    }, 3500)
  }, [showJarvisEcho])
  const handleWakeRef = useRef(handleWake); handleWakeRef.current = handleWake

  // 会话模式事件：进入 → UI 状态；退出（用户说退下/闲置超时）→ 告别播报
  const handleConvo = useCallback((event: ConvoEvent) => {
    if (event.type === 'enter') { setConvoOn(true); return }
    setConvoOn(false)
    setWakeStatus('')
    const line = event.reason === 'timeout' ? '那我先退下了，先生。' : '好的，先生，我先退下了。'
    showJarvisEcho(line)
    dispatchRef.current?.speakReply(line)
  }, [showJarvisEcho])
  const handleConvoRef = useRef(handleConvo); handleConvoRef.current = handleConvo

  // 致命识别错误：不再假装监听，停掉待命并明确提示；瞬态错误（no-speech/aborted 等）由重挂自愈
  const handleStandbyError = useCallback((code: string) => {
    standbyErrorRef.current = code
    if (!FATAL_SR_ERRORS.includes(code)) return
    stopStandbyLocal()
    savePrefs({ ...getPrefs(), standby: false })
    setError(code === 'network'
      ? '语音识别服务不可达（Chrome 识别需连 Google 服务）：待命已关闭，可用输入框或检查网络后重新开启'
      : '麦克风不可用（权限被拒）：请在浏览器设置允许麦克风后重新开启待命')
  }, [stopStandbyLocal, setError])
  const handleStandbyErrorRef = useRef(handleStandbyError); handleStandbyErrorRef.current = handleStandbyError

  const armStandbyRef = useRef<() => void>(() => {})
  const armStandby = useCallback(() => {
    standbyStopRef.current?.()
    standbyErrorRef.current = ''
    // 播完恢复监听：会话模式存活则刷新闲置计时（长播报不把会话拖到超时）
    if (isConvoActive()) bumpConvoIdle()
    // 传输层自动选择：桌面端且本地模型就绪 → sherpa-onnx 离线识别；否则回退浏览器 Web Speech
    const bridge = getDesktopBridge()
    const useLocal = !!bridge && bridge.asrAvailable()
    const rearm = () => { if (standbyOnRef.current) standbyTimerRef.current = window.setTimeout(() => { if (standbyOnRef.current) armStandbyRef.current() }, 800) }
    if (useLocal) {
      standbyStopRef.current = startLocalStandby(
        (live) => { if (standbyOnRef.current) setStandbyLive(live) },
        (command) => handleWakeRef.current(command),
        rearm,
        (message) => setError(message),
        (event) => handleConvoRef.current(event),
      )
    } else {
      standbyStopRef.current = startStandby(
        (live) => { if (standbyOnRef.current) setStandbyLive(live) },
        (command) => handleWakeRef.current(command),
        rearm,
        (code) => handleStandbyErrorRef.current(code),
        (event) => handleConvoRef.current(event),
      )
    }
    standbyOnRef.current = true; setStandbyOn(true); setStandbyLive(''); setWakeStatus(useLocal ? '正在监听…（本地识别）' : '正在监听…')
  }, [setError])
  armStandbyRef.current = armStandby
  standbyActionsRef.current = { pause: () => stopStandbyLocal({ keepConvo: true }), resume: armStandby }

  // 挂载：按偏好自动进入待命；卸载：停监听并复位桥接
  useEffect(() => {
    const prefs = getPrefs()
    if (prefs.standby) standbyTimerRef.current = window.setTimeout(() => armStandbyRef.current(), 400)
    return () => { resumeStandbyRef.current = false; stopStandbyLocal(); if (quipTimerRef.current !== null) window.clearTimeout(quipTimerRef.current) }
  }, [stopStandbyLocal])

  return { standbyOn, wakeStatus, standbyLive, convoOn, standbyOnRef, resumeStandbyRef, standbyActionsRef, bind }
}
