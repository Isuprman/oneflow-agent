// 桌面端本地识别待命（Electron + sherpa-onnx，全程离线）。
// 与 asr.startStandby 同语义：onInterim 实时转写、onWake 命中唤醒/指令；
// 唤醒判定复用 wake 状态机的 wakeState/wakeBuffer/变体表，播报期间由调用方暂停避免回声。
// 防假唤醒三件套：启动冷却期（丢 TTS 余音）+ 垃圾短文本过滤 + 决策日志。
import { startLocalMic, stopLocalMic } from '../localVoice'
import { getDesktopBridge } from './bridge'
import { enterConvo, findWakeWord, stripPunct, tryConvoRoute, wakeBuffer, wakeState, WAKE_BUFFER_MAX, WAKE_SLOT_MS, type ConvoCallback } from './wake'

const LOCAL_COOLDOWN_MS = 1200

export function startLocalStandby(
  onInterim: (t: string) => void,
  onWake: (command: string) => void,
  onEnd?: () => void,
  onError?: (message: string) => void,
  onConvo?: ConvoCallback,
): () => void {
  const bridge = getDesktopBridge()
  if (!bridge) {
    onError?.('桌面语音桥不可用')
    return () => {}
  }
  let stopped = false
  const armedAt = Date.now()
  const bridgeLog = (msg: string) => {
    try { bridge.log?.(msg) } catch { /* 日志失败不影响主流程 */ }
  }

  bridge.onEvent((event) => {
    if (stopped) return
    if (event.type === 'partial') {
      onInterim(event.text ?? '')
      return
    }
    if (event.type === 'error') {
      onError?.(event.text ?? '本地识别异常')
      return
    }
    if (event.type !== 'final') return
    const text = (event.text ?? '').trim()
    // final 上屏：复用「转写」展示位（现有机制 2.2s 自动淡出），问题可观察
    onInterim(text)
    if (!text) return

    // 冷却期：监听（重）启动后短窗口内的结果丢弃——挡播报余音/设备噪声造成的假唤醒
    if (Date.now() - armedAt < LOCAL_COOLDOWN_MS) {
      bridgeLog(`丢弃(冷却期): ${text}`)
      return
    }

    // 会话模式：免唤醒直接派发/退下词检测（优先于跟随窗口与唤醒扫描）
    if (tryConvoRoute(text, onWake, onConvo)) {
      bridgeLog(`会话模式处理: ${text}`)
      return
    }

    const now = Date.now()

    // 已唤醒且等指令：窗口内免唤醒词直接当指令；超时回落需重新唤醒
    if (wakeState.woken && wakeState.awaiting) {
      if (now - wakeState.wakeAt <= WAKE_SLOT_MS) {
        // 垃圾过滤：去掉标点后 ≤1 字的短文本不配当指令（防噪声抢占管道）
        if (stripPunct(text).length <= 1) {
          bridgeLog(`丢弃(垃圾短文本): ${text}`)
          return
        }
        const hit = findWakeWord(text)
        if (hit) {
          const rest = text.slice(hit.end).trim()
          if (rest) {
            bridgeLog(`派发(窗口内含唤醒词): ${rest}`)
            onWake(rest)
            wakeState.woken = false
            wakeState.awaiting = false
          } else {
            bridgeLog(`刷新窗口(仅唤醒词): ${text}`)
            wakeState.wakeAt = now
          }
          return
        }
        bridgeLog(`派发(窗口内免唤醒): ${text}`)
        onWake(text)
        wakeState.woken = false
        wakeState.awaiting = false
        return
      }
      wakeState.woken = false
      wakeState.awaiting = false
      wakeBuffer.text = ''
    }

    // 未唤醒：滑动窗口 + 同音字变体扫描
    wakeBuffer.text = (wakeBuffer.text + text).slice(-WAKE_BUFFER_MAX)
    const hit = findWakeWord(wakeBuffer.text)
    if (!hit) {
      bridgeLog(`未命中唤醒词: ${text}`)
      return
    }
    wakeBuffer.text = ''
    wakeState.woken = true
    wakeState.wakeAt = now
    enterConvo(onConvo)
    const inlineHit = findWakeWord(text)
    const rest = inlineHit ? text.slice(inlineHit.end).trim() : ''
    if (rest) {
      bridgeLog(`唤醒+指令: ${rest}`)
      onWake(rest)
      wakeState.woken = false
      wakeState.awaiting = false
    } else {
      bridgeLog('仅唤醒，等待指令')
      wakeState.awaiting = true
      onWake('')
    }
  })

  bridge.startAsr() // 启动失败会通过 error 事件上抛
  const micOk = startLocalMic((samples) => {
    if (!stopped) bridge.sendAudio(samples)
  })
  if (!micOk) onError?.('麦克风不可用')

  return () => {
    stopped = true
    stopLocalMic()
    bridge.stopAsr()
    onEnd?.()
  }
}
