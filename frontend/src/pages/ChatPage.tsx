import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MotionConfig, AnimatePresence, motion, type Variants } from 'framer-motion'
import { createConversation, getMessages, getIdleHint, listConversations, listNotifications, markNotificationRead, streamChat, tts, type StreamStep } from '../api/client'
import type { Conversation, Message, ToolStep } from '../api/types'
import AiCore, { type ReactiveLevel } from '../components/AiCore'
import ParticleField from '../components/ParticleField'
import SceneFX from '../components/SceneFX'
import CommandDock from '../components/CommandDock'
import HoloTray from '../components/HoloTray'
import HudCorners from '../components/HudCorners'
import TelemetryStrip from '../components/TelemetryStrip'
import { getPrefs, savePrefs } from '../prefs'
import { useAuthStore } from '../store/auth'
import { enterFollowUpWindow, getDesktopBridge, playBlob, playWakeTone, resetWakeState, speak as speakFallback, startLocalStandby, startStandby, stopAudio, stopSpeaking, unlockAudio } from '../lib/speech'
import { getLevel, startMicAnalyser } from '../lib/audioReactive'
import { toPlainText } from '../lib/plain'

interface ChatMessage { id: string; role: 'user' | 'assistant'; content: string; trace?: ToolStep[]; isStreaming?: boolean }
// 致命识别错误码：命中则不再假装监听，停掉待命并明确提示；其余（no-speech/aborted 等）由重挂自愈
const FATAL_SR_ERRORS = ['not-allowed', 'service-not-allowed', 'network', 'bad-grammar']
function isRenderable(message: Message): message is Message & { role: 'user' | 'assistant'; content: string } { return (message.role === 'user' || message.role === 'assistant') && message.content !== null }

/** 全息 glitch-in 入场：轻微位移 + 透明度 + blur 收敛；用户/AI 分别。 */
const msgVariants: Record<'user' | 'assistant', Variants> = {
  user: {
    hidden: { opacity: 0, y: 16, filter: 'blur(6px)' },
    show: { opacity: 1, y: 0, filter: 'blur(0px)', transition: { duration: 0.3, ease: 'easeOut' } },
  },
  assistant: {
    hidden: { opacity: 0, y: -10, filter: 'blur(9px)' },
    show: {
      opacity: 1,
      y: 0,
      x: [0, 1.6, -1.2, 0],
      filter: ['blur(9px)', 'blur(4px)', 'blur(0px)'],
      transition: { duration: 0.32, ease: 'easeOut' },
    },
  },
}

export default function ChatPage() {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [error, setError] = useState('')
  const [expandedTraces, setExpandedTraces] = useState<Set<string>>(new Set())
  const [standbyOn, setStandbyOn] = useState(false)
  const [wakeStatus, setWakeStatus] = useState('')
  const [standbyLive, setStandbyLive] = useState('')
  // 右上角 hud-transcript 展示用的转写（与识别主流程解耦，仅控制展示态）
  const [shownTranscript, setShownTranscript] = useState('')
  // 发消息错误 → 单个右上 Toast
  const [toast, setToast] = useState<string | null>(null)
  // 右上角「OPERATOR 刚说的话」：只在此显示一次，~2s 自动消失（时间线不重复显示用户消息）
  const [echo, setEcho] = useState<string | null>(null)
  const echoTimerRef = useRef<number | null>(null)
  // 右上角「JARVIS 回复」：完成后 ~3s 自动消失（时间线仍保留回复记录）
  const [jarvisEcho, setJarvisEcho] = useState<string | null>(null)
  const jarvisEchoTimerRef = useRef<number | null>(null)
  // 真流式：累积 delta 增量，实时刷新 JARVIS 回显；出错标记防播报错误文本
  const liveTextRef = useRef('')
  const hadErrorRef = useRef(false)
  // 忙闲标记（供通知轮询判断是否顺延，避免播报撞车）
  const sendingRef = useRef(false)
  const voiceLiveRef = useRef(false)
  // 闲置轻推：最近一次交互时间 + 本会话搭话次数（频控上限 2）
  const lastInteractionRef = useRef(Date.now())
  const chatterCountRef = useRef(0)
  const [trayOpen, setTrayOpen] = useState(false)
  const [voiceLive, setVoiceLive] = useState(false)
  const [corePulse, setCorePulse] = useState(0)
  // 真流式：当前正在调用的工具名（执行完清空，驱动遥测状态）
  const [liveTool, setLiveTool] = useState('')
  // 高危操作待确认（engine 暂存，等用户确认/取消）
  const [pendingConfirm, setPendingConfirm] = useState<{ tool: string; summary: string } | null>(null)
  const [showInput] = useState(() => getPrefs().showInput)
  const [micAvailable] = useState(() => typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia)
  const standbyStopRef = useRef<(() => void) | null>(null)
  const standbyOnRef = useRef(false)
  const voiceOnRef = useRef(false)
  // 语音播报期间暂停待命：true 表示播报前已暂停、播完要恢复
  const resumeStandbyRef = useRef(false)
  // 播报前暂停 / 播完恢复待命的动作（armStandby/stopStandbyLocal 定义在下方，经 ref 供 doSend 回调访问最新实现）
  const standbyActionsRef = useRef<{ pause: () => void; resume: () => void }>({ pause: () => {}, resume: () => {} })
  const standbyTimerRef = useRef<number | null>(null)
  // 待命识别的最近一次错误码（onerror 先于 onend，供重挂决策区分致命/瞬态）
  const standbyErrorRef = useRef<string>('')
  // 播报安全网定时器：音频 ended 事件异常不触发时兜底恢复监听
  const voiceSafetyRef = useRef<number | null>(null)
  const voiceTimerRef = useRef<number | null>(null)
  const transcriptTimerRef = useRef<number | null>(null)
  const toastTimerRef = useRef<number | null>(null)
  // 声音驱动链路（rAF 每帧写 ref，避免每帧 setState）
  const voiceReactiveOnRef = useRef(false)
  // 播报律动：voiceLive 期间向 AiCore 写入模拟音频幅度（音频驱动开关时让位给真实麦克风）
  const speakAnimRef = useRef<number | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const dataArrayRef = useRef<Uint8Array<ArrayBuffer> | null>(null)
  const analyserCleanupRef = useRef<(() => void) | null>(null)
  const voiceRafRef = useRef<number | null>(null)
  const reactiveLevelRef = useRef<ReactiveLevel>({ vol: 0, low: 0 })

  const loadMessages = useCallback(async (id: number) => {
    setLoadingMessages(true); setError('')
    try { const loaded = await getMessages(id); setMessages(loaded.filter(isRenderable).filter((message) => message.role !== 'user' && message.role !== 'assistant').map((message) => ({ id: `history-${message.id}`, role: message.role, content: message.content }))); setExpandedTraces(new Set()) }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setMessages([]) }
    finally { setLoadingMessages(false) }
  }, [])

  useEffect(() => { listConversations().then((list) => { setConversations(list); if (list[0]) { setActiveId(list[0].id); void loadMessages(list[0].id) } }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason))) }, [loadMessages])

  const clearToast = useCallback(() => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current)
    toastTimerRef.current = null
    setToast(null)
  }, [])

  /** 弹一个 ~2.5s 自动消失的顶部居中 Toast（重复错误会重置计时器）。 */
  const showToast = useCallback((message: string) => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current)
    setToast(message)
    toastTimerRef.current = window.setTimeout(() => {
      toastTimerRef.current = null
      setToast(null)
    }, 2500)
  }, [])

  /** 语音播报一段纯文本：暂停待命防回声 → edge-tts 播放 → 真实播完恢复待命。
   *  followUp=true 时（仅对话回复）播完进免唤醒跟随窗口；通知/搭话播报不开。 */
  const speakReply = useCallback((plain: string, followUp = false) => {
    if (!voiceOnRef.current || !plain) return
    setVoiceLive(true); voiceLiveRef.current = true
    // 播报开始前暂停待命监听，避免扬声器声音被识别成指令（回声/循环）
    if (standbyOnRef.current && !resumeStandbyRef.current) {
      resumeStandbyRef.current = true
      standbyActionsRef.current.pause()
    }
    // 全息核心随播报律动（音频驱动开启时不覆盖真实麦克风数据）
    if (!voiceReactiveOnRef.current && speakAnimRef.current === null) {
      const startedAt = performance.now()
      const loop = () => {
        const t = (performance.now() - startedAt) / 1000
        const vol = 0.22 + 0.14 * Math.abs(Math.sin(t * 7.3)) + Math.random() * 0.06
        reactiveLevelRef.current = { vol, low: vol * 0.85 }
        speakAnimRef.current = window.requestAnimationFrame(loop)
      }
      speakAnimRef.current = window.requestAnimationFrame(loop)
    }
    const stopSpeakAnim = () => {
      if (speakAnimRef.current !== null) window.cancelAnimationFrame(speakAnimRef.current)
      speakAnimRef.current = null
      if (!voiceReactiveOnRef.current) reactiveLevelRef.current = { vol: 0, low: 0 }
    }
    // 恢复待命：以真实播放结束为准 + 缓冲，不再按字数估算；播报中被打断也算结束
    const resumeAfterSpeak = () => {
      if (voiceTimerRef.current) window.clearTimeout(voiceTimerRef.current)
      voiceTimerRef.current = window.setTimeout(() => {
        setVoiceLive(false); voiceLiveRef.current = false
        stopSpeakAnim()
        if (resumeStandbyRef.current) {
          resumeStandbyRef.current = false
          if (!standbyOnRef.current) standbyActionsRef.current.resume()
          // 免唤醒跟随窗口：仅对话回复后开启，直接说话即当指令
          if (followUp && standbyOnRef.current) enterFollowUpWindow()
        }
      }, 400)
    }
    // 安全网：ended 事件异常不触发时兜底（按纯文本字数放宽估算 + 富余量）
    if (voiceSafetyRef.current) window.clearTimeout(voiceSafetyRef.current)
    voiceSafetyRef.current = window.setTimeout(() => {
      voiceSafetyRef.current = null
      resumeAfterSpeak()
    }, Math.min(5000 + plain.length * 320, 90000))
    void tts(plain, getPrefs().ttsVoice)
      .then((blob) => playBlob(blob).then(resumeAfterSpeak, resumeAfterSpeak))
      .catch(() => speakFallback(plain).then(resumeAfterSpeak, resumeAfterSpeak))
  }, [])

  const doSend = useCallback((rawText: string) => {
    const text = rawText.trim()
    if (!text) return
    // 忙时不再静默丢弃：明确告知用户上一件事还在处理
    if (sending) { showToast('正在处理上一件事，请稍候'); return }
    clearToast()
    lastInteractionRef.current = Date.now()
    setInput(''); setSending(true); sendingRef.current = true; setError('')
    // 右上角「OPERATOR + 内容」只显示一次，~2s 自动消失；不再进左侧时间线
    setEcho(text)
    if (echoTimerRef.current) window.clearTimeout(echoTimerRef.current)
    echoTimerRef.current = window.setTimeout(() => setEcho(null), 2000)
    setCorePulse((value) => value + 1)
    liveTextRef.current = ''
    hadErrorRef.current = false
    setLiveTool('')
    setPendingConfirm(null)
    void streamChat(activeId, text, (piece) => {
      // 真流式打字机：delta 增量实时进右上角 JARVIS 回显
      if (hadErrorRef.current) return
      liveTextRef.current += piece
      setJarvisEcho(liveTextRef.current)
      if (jarvisEchoTimerRef.current) { window.clearTimeout(jarvisEchoTimerRef.current); jarvisEchoTimerRef.current = null }
    }, (response) => {
      setLiveTool('')
      if (activeId === null) { setActiveId(response.conversation_id); listConversations().then(setConversations).catch(() => {}) }
      // 本轮出过错：不重复展示/播报错误文本（Toast 已提示）
      if (hadErrorRef.current) return
      // 右上角 JARVIS 回复回显：完成后 ~3s 自动消失；不再进左侧时间线（显示净化后的纯文本）
      setJarvisEcho(toPlainText(response.reply))
      if (jarvisEchoTimerRef.current) window.clearTimeout(jarvisEchoTimerRef.current)
      jarvisEchoTimerRef.current = window.setTimeout(() => setJarvisEcho(null), 3000)
      speakReply(toPlainText(response.reply), true)
    }, (reason) => {
      // 发送失败/服务端 error 事件：顶部 Toast；标记出错防播报错误文本
      hadErrorRef.current = true
      setLiveTool('')
      setJarvisEcho(null)
      showToast(reason.message)
    }, (step: StreamStep) => {
      // 工具步骤实时上遥测：calling 显示工具名，done 回落思考态
      setLiveTool(step.status === 'calling' ? step.tool : '')
    }, (pending) => {
      // 高危操作待确认：弹确认条，点按钮或语音说“确认/取消”均可
      setPendingConfirm(pending)
    }).finally(() => { setSending(false); sendingRef.current = false })
  }, [activeId, sending, clearToast, showToast, speakReply])

  const handleWake = useCallback((command: string) => {
    lastInteractionRef.current = Date.now()
    setWakeStatus('已唤醒'); stopAudio(); stopSpeaking(); playWakeTone()
    const text = command.trim()
    if (text) { doSend(text); return }
    // 唤醒未带指令：按时段问候，管家式仪式感
    const hour = new Date().getHours()
    const greet = hour < 5 ? '夜深了' : hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好'
    setWakeStatus(`${greet}，先生。请说指令`)
  }, [doSend])
  const handleWakeRef = useRef(handleWake); handleWakeRef.current = handleWake
  const stopStandbyLocal = useCallback(() => { standbyOnRef.current = false; if (standbyTimerRef.current) window.clearTimeout(standbyTimerRef.current); standbyStopRef.current?.(); standbyStopRef.current = null; resetWakeState(); setStandbyOn(false); setStandbyLive(''); setWakeStatus('') }, [])
  // 致命识别错误：不再假装监听，停掉待命并明确提示；瞬态错误（no-speech/aborted 等）由重挂自愈
  const handleStandbyError = useCallback((code: string) => {
    standbyErrorRef.current = code
    if (!FATAL_SR_ERRORS.includes(code)) return
    stopStandbyLocal()
    savePrefs({ ...getPrefs(), standby: false })
    setError(code === 'network'
      ? '语音识别服务不可达（Chrome 识别需连 Google 服务）：待命已关闭，可用输入框或检查网络后重新开启'
      : '麦克风不可用（权限被拒）：请在浏览器设置允许麦克风后重新开启待命')
  }, [stopStandbyLocal])
  const handleStandbyErrorRef = useRef(handleStandbyError); handleStandbyErrorRef.current = handleStandbyError
  const armStandbyRef = useRef<() => void>(() => {})
  const armStandby = useCallback(() => {
    standbyStopRef.current?.()
    standbyErrorRef.current = ''
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
      )
    } else {
      standbyStopRef.current = startStandby(
        (live) => { if (standbyOnRef.current) setStandbyLive(live) },
        (command) => handleWakeRef.current(command),
        rearm,
        (code) => handleStandbyErrorRef.current(code),
      )
    }
    standbyOnRef.current = true; setStandbyOn(true); setStandbyLive(''); setWakeStatus(useLocal ? '正在监听…（本地识别）' : '正在监听…')
  }, [])
  armStandbyRef.current = armStandby
  standbyActionsRef.current = { pause: stopStandbyLocal, resume: armStandby }

  const stopVoiceReactive = useCallback(() => {
    voiceReactiveOnRef.current = false
    if (voiceRafRef.current !== null) window.cancelAnimationFrame(voiceRafRef.current)
    voiceRafRef.current = null
    reactiveLevelRef.current = { vol: 0, low: 0 }
    analyserCleanupRef.current?.()
    analyserCleanupRef.current = null
    analyserRef.current = null
    dataArrayRef.current = null
  }, [])

  const startVoiceReactive = useCallback(() => {
    if (voiceReactiveOnRef.current) return
    if (!micAvailable) { setError('当前设备不支持麦克风'); return }
    setError('')
    startMicAnalyser()
      .then(({ analyser, cleanup }) => {
        analyserRef.current = analyser
        analyserCleanupRef.current = cleanup
        dataArrayRef.current = new Uint8Array(analyser.frequencyBinCount)
        voiceReactiveOnRef.current = true
        const loop = () => {
          if (!voiceReactiveOnRef.current || !analyserRef.current || !dataArrayRef.current) return
          reactiveLevelRef.current = getLevel(analyserRef.current, dataArrayRef.current)
          voiceRafRef.current = window.requestAnimationFrame(loop)
        }
        voiceRafRef.current = window.requestAnimationFrame(loop)
      })
      .catch(() => {
        voiceReactiveOnRef.current = false
        setError('无法启用声音驱动（麦克风无权限）')
      })
  }, [micAvailable])
  const startVoiceReactiveRef = useRef(startVoiceReactive); startVoiceReactiveRef.current = startVoiceReactive

  useEffect(() => {
    const prefs = getPrefs(); voiceOnRef.current = prefs.voice
    const unlock = () => { unlockAudio(); const audio = new Audio(); audio.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA='; audio.volume = 0; audio.play().catch(() => {}); window.removeEventListener('pointerdown', unlock); window.removeEventListener('keydown', unlock) }
    window.addEventListener('pointerdown', unlock); window.addEventListener('keydown', unlock)
    // 桌面端但本地语音模型未下载：提示下载方式，自动回退浏览器识别
    const bridge = getDesktopBridge()
    if (bridge && !bridge.asrAvailable()) setError('本地语音模型未下载：在 desktop 目录执行 npm run models（当前已回退浏览器识别）')
    if (prefs.standby) standbyTimerRef.current = window.setTimeout(armStandby, 400)
    if (prefs.audioDrive) startVoiceReactiveRef.current()
    return () => { resumeStandbyRef.current = false; stopStandbyLocal(); stopVoiceReactive(); if (speakAnimRef.current !== null) window.cancelAnimationFrame(speakAnimRef.current); if (voiceTimerRef.current) window.clearTimeout(voiceTimerRef.current); if (voiceSafetyRef.current) window.clearTimeout(voiceSafetyRef.current); if (transcriptTimerRef.current !== null) window.clearTimeout(transcriptTimerRef.current); if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current); if (echoTimerRef.current !== null) window.clearTimeout(echoTimerRef.current); if (jarvisEchoTimerRef.current !== null) window.clearTimeout(jarvisEchoTimerRef.current); window.removeEventListener('pointerdown', unlock); window.removeEventListener('keydown', unlock) }
  }, [armStandby, stopStandbyLocal, stopVoiceReactive])

  // 主动通知轮询：定时任务播报/日程提醒 → 右上角展示 + 语音播报 + 标记已读
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      // 忙时顺延：对话进行中或正在播报时不打断，下一轮再拉
      if (cancelled || sendingRef.current || voiceLiveRef.current) return
      const list = await listNotifications()
      if (cancelled || list.length === 0) return
      const latest = list[0]
      // 页面隐藏时升级成系统通知（需用户授权，拒绝则静默）
      if (document.hidden && typeof Notification !== 'undefined') {
        if (Notification.permission === 'default') {
          Notification.requestPermission().catch(() => {})
        }
        if (Notification.permission === 'granted') {
          try {
            new Notification(latest.title, { body: toPlainText(latest.content).slice(0, 120), icon: '/icon.svg' })
          } catch {
            // 部分浏览器要求走 ServiceWorker 注册，失败则退回页内展示
          }
        }
      }
      lastInteractionRef.current = Date.now()
      const display = list.length === 1
        ? `【${latest.title}】${toPlainText(latest.content)}`
        : `【${latest.title}】等 ${list.length} 条新通知`
      setJarvisEcho(display)
      if (jarvisEchoTimerRef.current) window.clearTimeout(jarvisEchoTimerRef.current)
      jarvisEchoTimerRef.current = window.setTimeout(() => setJarvisEcho(null), 6000)
      // 多条合并成一段播报；system_error 类只展示不播报（避免 TTS 读报错详情）
      const speakable = list.filter((note) => note.kind !== 'system_error')
      if (speakable.length > 0) {
        const speakText = speakable
          .map((note) => `${note.title}：${toPlainText(note.content)}`)
          .join('。')
          .slice(0, 500)
        speakReply(speakText)
      }
      for (const note of list) void markNotificationRead(note.id)
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 15000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [speakReply])

  // 闲置轻推：长时间无交互时贾维斯主动说一句（每会话最多 2 次，宁缺毋滥）
  useEffect(() => {
    const IDLE_MS = 20 * 60 * 1000
    const timer = window.setInterval(async () => {
      if (!getPrefs().chitchat) return
      if (sendingRef.current || voiceLiveRef.current || !standbyOnRef.current) return
      if (chatterCountRef.current >= 2) return
      if (Date.now() - lastInteractionRef.current < IDLE_MS) return
      const hint = await getIdleHint()
      if (!hint || !hint.text || chatterCountRef.current >= 2) return
      chatterCountRef.current += 1
      lastInteractionRef.current = Date.now()
      setJarvisEcho(hint.text)
      if (jarvisEchoTimerRef.current) window.clearTimeout(jarvisEchoTimerRef.current)
      jarvisEchoTimerRef.current = window.setTimeout(() => setJarvisEcho(null), 6000)
      speakReply(hint.text)
    }, 60000)
    return () => window.clearInterval(timer)
  }, [speakReply])

  const newChat = async () => { setError(''); try { const conversation = await createConversation(); setConversations((previous) => [conversation, ...previous.filter((item) => item.id !== conversation.id)]); setActiveId(conversation.id); setMessages([]); setInput(''); setExpandedTraces(new Set()) } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) } }

  const hasConversation = messages.length > 0
  const coreState = sending ? 'thinking' : voiceLive ? 'speaking' : standbyOn ? 'standby' : undefined
  const telemetry = sending ? (liveTool ? `CALL ${liveTool} 调用中…` : 'THINKING 思考中…') : voiceLive ? 'SPEAKING 播报中…' : standbyOn ? 'STANDBY 正在监听…' : 'SYSTEM READY 就绪'
  const standbyText = standbyOn ? (standbyLive ? `转写 ${standbyLive}` : wakeStatus) : ''
  const sysStatus = sending ? (liveTool ? 'CALL' : 'THINK') : voiceLive ? 'SPEAK' : standbyOn ? 'STANDBY' : 'READY'

  // 转写展示：说话时显示，静音 ~2.2s 后淡出消失（仅影响右上角展示态，不动识别主流程）
  useEffect(() => {
    if (!standbyOn) {
      if (transcriptTimerRef.current !== null) window.clearTimeout(transcriptTimerRef.current)
      transcriptTimerRef.current = null
      setShownTranscript('')
      return
    }
    if (standbyText) {
      setShownTranscript(standbyText)
      if (transcriptTimerRef.current !== null) window.clearTimeout(transcriptTimerRef.current)
      transcriptTimerRef.current = window.setTimeout(() => {
        transcriptTimerRef.current = null
        setShownTranscript('')
      }, 2200)
    } else {
      setShownTranscript('')
    }
  }, [standbyText, standbyOn])

  return (
    <MotionConfig reducedMotion="user">
      <div className="hud-shell">
        <ParticleField />
        <SceneFX />
        <AnimatePresence>
          {echo && (
            <motion.div
              className="hud-echo"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              aria-live="polite"
            >
              <span className="holo-card__role">OPERATOR</span>
              <span className="holo-card__copy">{echo}</span>
            </motion.div>
          )}
        </AnimatePresence>
        <AnimatePresence>
          {jarvisEcho && (
            <motion.div
              className="hud-jarvis"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.22, ease: 'easeOut' }}
              aria-live="polite"
            >
              <span className="holo-card__role">JARVIS</span>
              <span className="holo-card__copy">{jarvisEcho}</span>
            </motion.div>
          )}
        </AnimatePresence>
        <AnimatePresence>
          {toast && (
            <div className="hud-toast" role="alert">
              <motion.div
                className="hud-toast__inner"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.22, ease: 'easeOut' }}
              >
                <span className="hud-toast__icon">⚠</span>
                <span className="hud-toast__msg">{toast}</span>
              </motion.div>
            </div>
          )}
        </AnimatePresence>
        <TelemetryStrip sessionId={activeId} status={sysStatus} />
        <HoloTray
          open={trayOpen}
          onToggle={() => setTrayOpen((value) => !value)}
          conversations={conversations}
          activeId={activeId}
          onSelect={(id) => { setActiveId(id); void loadMessages(id) }}
          onNew={() => void newChat()}
        />
        <main className="war-stage">
          <div className="stage-core">
            <motion.div
              className={`stage-core__inner ${hasConversation ? 'stage-core__inner--behind' : ''}`}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
            >
              <AiCore state={coreState} compact={hasConversation} pulse={corePulse} reactiveLevelRef={reactiveLevelRef} />
            </motion.div>
          </div>

          {error && <p className="feedback" role="alert">{error}</p>}

          {loadingMessages ? (
            <div className="stage-center">
              <span className="stage-scanline" aria-hidden="true" />
              <p className="loading-state">正在读取会话…</p>
            </div>
          ) : !hasConversation ? (
            <div className="stage-empty">
              <motion.p
                className="tagline"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.28, delay: 0.08, ease: 'easeOut' }}
              >
                我在，等待指令
              </motion.p>
              <div className="core-status">
                <span className={`core-dot ${standbyOn || sending ? 'is-live' : ''}`} />
                <span className="core-status__label">{standbyOn ? 'STANDBY LISTENING' : 'SYSTEM READY'}</span>
              </div>
            </div>
          ) : (
            <div className="holo-timeline">
              <span className="timeline-rail" aria-hidden="true" />
              {messages.map((message) => (
                <motion.div
                  key={message.id}
                  className={`holo-message ${message.role}${message.isStreaming ? ' is-streaming' : ''}`}
                  variants={msgVariants[message.role]}
                  initial="hidden"
                  animate="show"
                >
                  <div className={`holo-card ${message.role === 'assistant' ? 'holo-card--core' : ''}`}>
                    <HudCorners />
                    <span className="holo-card__role" title={message.role === 'user' ? '操作员（您）' : 'AI 贾维斯'}>{message.role === 'user' ? 'OPERATOR' : 'JARVIS'}</span>
                    <div className="holo-card__copy">
                      {message.content}
                      {message.isStreaming && <span className="type-cursor">▍</span>}
                    </div>
                    {message.trace && message.trace.length > 0 && (
                      <>
                        <button
                          className="trace-toggle"
                          onClick={() => setExpandedTraces((previous) => { const next = new Set(previous); if (next.has(message.id)) next.delete(message.id); else next.add(message.id); return next })}
                        >
                          {expandedTraces.has(message.id) ? '▾' : '▸'} 工具轨迹（{message.trace.length}步）
                        </button>
                        {expandedTraces.has(message.id) && (
                          <div className="trace-block">
                            {message.trace.map((step, index) => (
                              <div className="trace-step" key={`${step.tool}-${index}`}>
                                <div className="trace-step__head">
                                  <span>{step.tool}</span>
                                  <span className={step.success ? 'trace-success' : 'trace-failure'}>{step.success ? '成功' : '失败'}</span>
                                </div>
                                <p>参数：{JSON.stringify(step.arguments)}</p>
                                <p>结果：{JSON.stringify(step.result)}</p>
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </main>

        {pendingConfirm && !sending && (
          <div className="confirm-bar" role="alertdialog" aria-label="高危操作确认">
            <span className="confirm-bar__text">{pendingConfirm.summary}</span>
            <button className="confirm-bar__btn confirm-bar__btn--ok" onClick={() => doSend('确认')}>确认执行</button>
            <button className="confirm-bar__btn" onClick={() => doSend('取消')}>取消</button>
          </div>
        )}

        <CommandDock
          input={input}
          onInput={setInput}
          onSend={() => doSend(input)}
          sending={sending}
          showInput={showInput}
          username={user?.username ?? ''}
          onLogout={() => { logout(); navigate('/login') }}
          telemetry={telemetry}
          transcript={shownTranscript}
        />
      </div>
    </MotionConfig>
  )
}
