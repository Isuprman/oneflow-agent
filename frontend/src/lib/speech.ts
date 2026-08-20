// 浏览器语音能力封装（Web Speech API，免费无 Key）。
// SpeechRecognition / SpeechSynthesis 不在 lib.dom 的 TS 类型里，
// 这里统一用 any 显式断言，避免 TS 报错。

export function getRecognition(): any | null {
  const w = window as any
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition
  if (!Ctor) return null
  try {
    return new Ctor()
  } catch {
    return null
  }
}

export function startListening(
  onResult: (text: string) => void,
  onEnd: () => void,
  onError: (e: unknown) => void,
): void | null {
  const rec = getRecognition()
  if (!rec) return null

  rec.lang = 'zh-CN'
  rec.interimResults = false
  rec.continuous = false
  rec.maxAlternatives = 1

  rec.onresult = (event: any) => {
    const transcript: string | undefined = event?.results?.[0]?.[0]?.transcript
    if (typeof transcript === 'string' && transcript.length > 0) {
      onResult(transcript)
    }
  }
  rec.onend = () => onEnd()
  // 不再吞错：把浏览器给出的错误描述透传给调用方展示
  rec.onerror = (event: any) => onError(event?.error ?? event)

  try {
    rec.start()
  } catch (e) {
    onError(e)
  }
}

// 浏览器自带语音兜底：返回 Promise，播完 resolve（出错/被打断 reject），
// 供调用方按真实播放结束时机恢复待命监听。
export function speak(text: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const synth = (window as any).speechSynthesis
    if (!synth || !text) { resolve(); return }
    synth.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = 'zh-CN'
    const voices: any[] = synth.getVoices?.() ?? []
    const zhVoice = voices.find((v) => String(v?.lang ?? '').toLowerCase().startsWith('zh'))
    if (zhVoice) {
      utterance.voice = zhVoice
    }
    utterance.onend = () => resolve()
    // cancel() 后被打断的 utterance 会以 onerror(error='interrupted'/'canceled') 回调
    utterance.onerror = () => reject(new Error('speech-interrupted'))
    synth.speak(utterance)
  })
}

export function stopSpeaking(): void {
  const synth = (window as any).speechSynthesis
  if (synth) synth.cancel()
}

export const speechSupported: boolean = getRecognition() != null

let _audio: HTMLAudioElement | null = null

// 返回 Promise，真实播放结束（ended）才 resolve；加载/播放失败 reject。
// 调用方据此决定何时恢复待命监听，替代按字数估算时长。
export function playBlob(blob: Blob): Promise<void> {
  stopAudio()
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    _audio = audio
    audio.onended = () => {
      URL.revokeObjectURL(url)
      if (_audio === audio) _audio = null
      resolve()
    }
    audio.onerror = () => {
      URL.revokeObjectURL(url)
      if (_audio === audio) _audio = null
      reject(new Error('audio-play-failed'))
    }
    audio.play().catch((reason) => {
      URL.revokeObjectURL(url)
      if (_audio === audio) _audio = null
      reject(reason instanceof Error ? reason : new Error('audio-play-failed'))
    })
  })
}

export function stopAudio(): void {
  if (_audio) {
    _audio.pause()
    _audio = null
  }
}

// 常驻待命（语音唤醒）相关
export const WAKE_WORDS = ['贾维斯', '小翼', '你好小助手', '小助手']

// 唤醒词同音字/近音变体：中文 ASR 常把人名听成同音字，逐个硬匹配容错。
const WAKE_VARIANTS: Record<string, string[]> = {
  '贾维斯': ['贾维斯', '加维斯', '佳维斯', '嘉维斯', '家维斯', '假维斯', '查维斯'],
  '小翼': ['小翼', '小易', '小义', '小毅', '小艺'],
  '你好小助手': ['你好小助手', '你好小住手', '你好小助守'],
  '小助手': ['小助手', '小住手', '小助守'],
}

/** 在 text 中找唤醒词（含变体）：返回 { start, end }，未命中返回 null。 */
function findWakeWord(text: string): { start: number; end: number } | null {
  for (const word of WAKE_WORDS) {
    for (const variant of WAKE_VARIANTS[word] ?? [word]) {
      const idx = text.indexOf(variant)
      if (idx >= 0) return { start: idx, end: idx + variant.length }
    }
  }
  return null
}

// 唤醒后免唤醒词连说的窗口时长
const WAKE_SLOT_MS = 25000
// 滑动窗口上限：既覆盖唤醒词跨 final 被切断的情况，又避免旧文本重复命中
const WAKE_BUFFER_MAX = 40
// 模块级唤醒状态：跨识别实例保留（识别会话结束自动重挂后不丢）
let wakeState = { woken: false, awaiting: false, wakeAt: 0 }
let wakeBuffer = ''

// ---- 播报回声过滤（barge-in 基础设施） ----
// 播报期间保持监听：与播报内容一致的转写判为回声忽略；不一致则视为用户打断
let speakGuard = { active: false, text: '' }

/** 去除标点/空白，供回声包含判定用。 */
function normalizeSpeech(t: string): string {
  return t.replace(/[\s，。！？、,.!?;；:："'“”‘’（）()【】《》\[\]…—~·-]/g, '')
}

/** 开启/关闭播报回声过滤；spokenText 为正在播报的纯文本。 */
export function setSpeakGuard(active: boolean, spokenText = ''): void {
  speakGuard = { active, text: normalizeSpeech(spokenText) }
}

/** 免唤醒词跟随窗口：播报结束后调用，之后直接说话即当指令（复用 awaiting 机制）。 */
export function enterFollowUpWindow(): void {
  wakeState.woken = true
  wakeState.awaiting = true
  wakeState.wakeAt = Date.now()
}

// ---- 唤醒音效（WebAudio 合成，无需音频资源） ----
let _toneCtx: AudioContext | null = null

/** 短促上行“叮”：唤醒成功的仪式感反馈。 */
export function playWakeTone(): void {
  try {
    const w = window as any
    const Ctor = w.AudioContext ?? w.webkitAudioContext
    if (!Ctor) return
    const ctx: AudioContext = _toneCtx ?? new Ctor()
    _toneCtx = ctx
    if (ctx.state === 'suspended') void ctx.resume()
    const t0 = ctx.currentTime
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = 'sine'
    osc.frequency.setValueAtTime(880, t0)
    osc.frequency.exponentialRampToValueAtTime(1760, t0 + 0.12)
    gain.gain.setValueAtTime(0.0001, t0)
    gain.gain.exponentialRampToValueAtTime(0.18, t0 + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.3)
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.start(t0)
    osc.stop(t0 + 0.32)
  } catch {
    // 音效失败不影响主流程
  }
}

/** 归零唤醒状态（手动关闭待命时调用，之后需重新唤醒才能下指令）。 */
export function resetWakeState(): void {
  wakeState.woken = false
  wakeState.awaiting = false
  wakeState.wakeAt = 0
  wakeBuffer = ''
}

// 启动待命监听：持续识别，命中唤醒词后把后续指令回传。
// 返回停止函数；onWake 收到指令文本，空字符串表示「已唤醒但没带指令，等下一句」。
// 只用最终结果（isFinal）判定派发，绝不用临时半截；唤醒后 25s 窗口内免唤醒词连说。
// 命中策略：每条 final 取全部候选（maxAlternatives>1）逐个做同音字变体扫描，
// 最优候选另拼入滑动窗口覆盖跨 final 切断的情况。
// onError 透传识别错误码；onend 总在 onerror 之后触发，由调用方据错误码决定重挂或停止。
export function startStandby(
  onInterim: (t: string) => void,
  onWake: (command: string) => void,
  onEnd?: () => void,
  onError?: (code: string) => void,
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

    // 打断检测（barge-in）：播报期间监听不断，非回声的转写 = 用户在说话，直接当指令派发
    if (speakGuard.active) {
      const norm = normalizeSpeech(finalBest)
      // 空转写或与播报内容重合→回声，忽略
      if (!norm || (speakGuard.text !== '' && speakGuard.text.includes(norm))) return
      speakGuard.active = false
      wakeBuffer = ''
      onWake(finalBest.trim())
      return
    }

    const now = Date.now()

    // 已唤醒且等指令：窗口内免唤醒词直接当指令；超时回落需重新唤醒
    if (wakeState.woken && wakeState.awaiting) {
      if (now - wakeState.wakeAt > WAKE_SLOT_MS) {
        wakeState.woken = false
        wakeState.awaiting = false
        wakeBuffer = ''
        return
      }
      const text = finalAlts[0].trim()
      wakeBuffer = ''
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
    wakeBuffer = (wakeBuffer + finalBest).slice(-WAKE_BUFFER_MAX)
    if (!hit) hit = findWakeWord(wakeBuffer)
    if (!hit) return
    wakeBuffer = ''
    wakeState.woken = true
    wakeState.wakeAt = now
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

export function stopStandby(stop: () => void): void {
  stop()
}
