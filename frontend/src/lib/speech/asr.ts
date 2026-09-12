// Web Speech 连续待命识别（浏览器通道，免费无 Key，Chrome 需可达 Google 服务）。
// SpeechRecognition 不在 lib.dom 的 TS 类型里，这里统一用 any 显式断言，避免 TS 报错。
import { enterConvo, findWakeWord, tryConvoRoute, wakeBuffer, wakeState, WAKE_BUFFER_MAX, WAKE_SLOT_MS } from './wake'

// 启动待命监听：持续识别，命中唤醒词后把后续指令回传。
// 返回停止函数；onWake 收到指令文本，空字符串表示「已唤醒但没带指令，等下一句」。
// 只用最终结果（isFinal）判定派发，绝不用临时半截；唤醒后 8s 窗口内免唤醒词连说。
// 命中策略：每条 final 取全部候选（maxAlternatives>1）逐个做同音字变体扫描，
// 最优候选另拼入滑动窗口覆盖跨 final 切断的情况。
// onError 透传识别错误码；onend 总在 onerror 之后触发，由调用方据错误码决定重挂或停止。
export function startStandby(
  onInterim: (t: string) => void,
  onWake: (command: string) => void,
  onEnd?: () => void,
  onError?: (code: string) => void,
  onConvo?: import('./wake').ConvoCallback,
): () => void {
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SR) return () => {}

  const rec = new SR()
  rec.lang = 'zh-CN'
  rec.continuous = true
  rec.interimResults = true
  rec.maxAlternatives = 3

  rec.onresult = (event: any) => {
    const resultIndex: number = event?.resultIndex ?? 0
    const results: any[] = event?.results ?? []
    let live = ''
    const finalAlts: string[] = []
    let finalBest = ''
    for (let i = resultIndex; i < results.length; i++) {
      const alts: any[] = results[i] ?? []
      if (i === results.length - 1) {
        live = (alts[0]?.transcript ?? '') as string
      }
      if (results[i]?.isFinal === true) {
        // 所有候选都参与唤醒扫描，提高命中率
        for (let a = 0; a < alts.length; a++) {
          const t = alts[a]?.transcript
          if (typeof t === 'string' && t.trim()) {
            finalAlts.push(t)
            if (!finalBest) finalBest = t
          }
        }
      }
    }
    // 仅用于显示，不影响指令逻辑
    onInterim(live)

    if (finalAlts.length === 0) return

    // 会话模式：免唤醒直接派发/退下词检测（优先于跟随窗口与唤醒扫描）
    if (tryConvoRoute(finalAlts[0], onWake, onConvo)) return

    const now = Date.now()

    // 已唤醒且等指令：窗口内免唤醒词直接当指令；超时回落需重新唤醒
    if (wakeState.woken && wakeState.awaiting) {
      if (now - wakeState.wakeAt > WAKE_SLOT_MS) {
        wakeState.woken = false
        wakeState.awaiting = false
        wakeBuffer.text = ''
        return
      }
      const text = finalAlts[0].trim()
      wakeBuffer.text = ''
      const hit = findWakeWord(text)
      if (hit) {
        const rest = text.slice(hit.end).trim()
        if (rest) {
          onWake(rest)
          wakeState.woken = false
          wakeState.awaiting = false
        } else {
          // 又只说了唤醒词：刷新窗口、维持等指令
          wakeState.wakeAt = now
        }
        return
      }
      // 不含唤醒词：免唤醒词连说，派发后复位
      if (text) onWake(text)
      wakeState.woken = false
      wakeState.awaiting = false
      return
    }

    // 未唤醒（或超时回落）分支：滑动窗口只拼最优候选（防多候选拼成乱码），
    // 全部候选逐个做变体扫描，防唤醒词跨 final 被切断
    let hit: { start: number; end: number } | null = null
    for (const alt of finalAlts) {
      const variantHit = findWakeWord(alt)
      if (variantHit && !hit) hit = variantHit
    }
    wakeBuffer.text = (wakeBuffer.text + finalBest).slice(-WAKE_BUFFER_MAX)
    if (!hit) hit = findWakeWord(wakeBuffer.text)
    if (!hit) return
    wakeBuffer.text = ''
    wakeState.woken = true
    wakeState.wakeAt = now
    enterConvo(onConvo)
    const rest = wakeStateAwaitingRest(finalAlts)
    if (rest) {
      onWake(rest)
      wakeState.woken = false
      wakeState.awaiting = false
    } else {
      // 只唤醒没带指令：置 awaiting，等下一句作为指令
      wakeState.awaiting = true
      onWake('')
    }
  }

  // 唤醒同句带指令：取命中候选里唤醒词之后的部分
  function wakeStateAwaitingRest(finalAlts: string[]): string {
    for (const alt of finalAlts) {
      const variantHit = findWakeWord(alt)
      if (variantHit) {
        const rest = alt.slice(variantHit.end).trim()
        if (rest) return rest
      }
    }
    return ''
  }

  // 不在此自动重启，重启由 ChatPage 的 onEnd/重挂处理；模块级 wakeState 跨实例保留
  rec.onend = () => {
    onEnd?.()
  }
  rec.onerror = (event: any) => {
    onError?.(String(event?.error ?? 'unknown'))
  }

  rec.start()

  return () => {
    try {
      rec.stop()
    } catch {
      // ignore
    }
  }
}
