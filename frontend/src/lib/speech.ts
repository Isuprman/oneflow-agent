// 浏览器语音能力封装（Web Speech API，免费无 Key）+ 桌面端本地识别桥。
// SpeechRecognition / SpeechSynthesis 不在 lib.dom 的 TS 类型里，
// 这里统一用 any 显式断言，避免 TS 报错。
import { startLocalMic, stopLocalMic } from './localVoice'

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
let _audioReject: (() => void) | null = null

// 返回 Promise，真实播放结束（ended）才 resolve；加载/播放失败 reject；
// 被 stopAudio() 打断时以 Error('interrupted') reject，供分句播报链中止。
export function playBlob(blob: Blob): Promise<void> {
  stopAudio()
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    _audio = audio
    _audioReject = () => {
      _audioReject = null
      URL.revokeObjectURL(url)
      reject(new Error('interrupted'))
    }
    audio.onended = () => {
      URL.revokeObjectURL(url)
      if (_audio === audio) _audio = null
      if (_audioReject) { _audioReject = null }
      resolve()
    }
    audio.onerror = () => {
      URL.revokeObjectURL(url)
      if (_audio === audio) _audio = null
      if (_audioReject) { _audioReject = null }
      reject(new Error('audio-play-failed'))
    }
    audio.play().catch((reason) => {
      URL.revokeObjectURL(url)
      if (_audio === audio) _audio = null
      if (_audioReject) { _audioReject = null }
      reject(reason instanceof Error ? reason : new Error('audio-play-failed'))
    })
  })
}

export function stopAudio(): void {
  const rejector = _audioReject
  _audioReject = null
  if (_audio) {
    _audio.pause()
    _audio = null
  }
  if (rejector) rejector()
}

/** 分句：按句号/感叹号/问号切，短碎片并入相邻句，超长按逗号再切。
 *  供分句流水线播报：首句合成完即开播，把出声延迟从“全文”降到“首句”。 */
export function splitSentences(text: string): string[] {
  const raw = text.match(/[^。！？!?；;\n]+[。！？!?；;]*\n?/g) ?? [text]
  const merged: string[] = []
  for (const part of raw) {
    const piece = part.trim()
    if (!piece) continue
    const last = merged[merged.length - 1]
    if (last !== undefined && last.length < 10 && !/[。！？!?；;]$/.test(last)) {
      merged[merged.length - 1] = last + piece
    } else {
      merged.push(piece)
    }
  }
  const out: string[] = []
  for (const sentence of merged) {
    if (sentence.length <= 60) { out.push(sentence); continue }
    const clauses = sentence.match(/[^，、,：:]+[，、,：:]*/g) ?? [sentence]
    let buf = ''
    for (const clause of clauses) {
      if (buf.length + clause.length > 60 && buf) { out.push(buf); buf = clause } else { buf += clause }
    }
    if (buf) out.push(buf)
  }
  return out.length > 0 ? out : [text]
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

// 唤醒后免唤醒词连说的窗口时长（短窗口，减少误派发）
const WAKE_SLOT_MS = 8000
// 滑动窗口上限：既覆盖唤醒词跨 final 被切断的情况，又避免旧文本重复命中
const WAKE_BUFFER_MAX = 40
// 模块级唤醒状态：跨识别实例保留（识别会话结束自动重挂后不丢）
let wakeState = { woken: false, awaiting: false, wakeAt: 0 }
let wakeBuffer = ''

// ---- 会话模式（长对话）：唤醒即进入，免唤醒词直接对话，说“退下”或闲置超时才退出 ----
export interface ConvoEvent { type: 'enter' | 'exit'; reason?: 'user' | 'timeout' }
export type ConvoCallback = (event: ConvoEvent) => void

// 退出通道永远比进入通道宽：包含即退，同音字/漏词都能退
const EXIT_PATTERNS = ['退下', '没事了', '没事儿了', '你先休息', '先休息吧', '没你事了', '不用你了']
// 闲置自动退下时长：会话中这么久没说话，贾维斯自己告退
const CONVO_IDLE_MS = 90000

let convoState = { active: false, timer: null as number | null }
let lastConvoCb: ConvoCallback | null = null

/** 会话存活时刷新闲置计时（TTS 播报暂停期间防超时退出）。 */
export function bumpConvoIdle(): void {
  if (convoState.active) armConvoTimer(lastConvoCb ?? undefined)
}

export function isConvoActive(): boolean {
  return convoState.active
}

export function isExitPhrase(text: string): boolean {
  return EXIT_PATTERNS.some((pattern) => text.includes(pattern))
}

function armConvoTimer(onConvo?: ConvoCallback): void {
  if (convoState.timer !== null) window.clearTimeout(convoState.timer)
  convoState.timer = window.setTimeout(() => {
    convoState.timer = null
    convoState.active = false
    onConvo?.({ type: 'exit', reason: 'timeout' })
  }, CONVO_IDLE_MS)
}

function enterConvo(onConvo?: ConvoCallback): void {
  convoState.active = true
  lastConvoCb = onConvo ?? null
  onConvo?.({ type: 'enter' })
  armConvoTimer(onConvo)
}

function exitConvo(onConvo?: ConvoCallback, reason: 'user' | 'timeout' = 'user'): void {
  if (convoState.timer !== null) {
    window.clearTimeout(convoState.timer)
    convoState.timer = null
  }
  convoState.active = false
  onConvo?.({ type: 'exit', reason })
}

/** 会话模式下处理一条 final：退出词/垃圾过滤/免唤醒派发。未处于会话模式返回 false。 */
function tryConvoRoute(text: string, onWake: (command: string) => void, onConvo?: ConvoCallback): boolean {
  if (!convoState.active) return false
  const clean = text.trim()
  if (!clean) return true
  if (isExitPhrase(clean)) {
    exitConvo(onConvo, 'user')
    return true
  }
  if (stripPunct(clean).length <= 1) return true
  armConvoTimer(onConvo)
  // 句首带唤醒词则去掉（唤醒后连说“贾维斯，xx”的场景），其余原样派发
  const hit = findWakeWord(clean)
  let cmd = clean
  if (hit && clean.slice(0, hit.start).trim() === '') {
    cmd = clean.slice(hit.end).trim()
  }
  if (cmd) onWake(cmd)
  return true
}

/** 免唤醒词跟随窗口：播报结束后调用，之后直接说话即当指令（复用 awaiting 机制）。 */
export function enterFollowUpWindow(): void {
  wakeState.woken = true
  wakeState.awaiting = true
  wakeState.wakeAt = Date.now()
}

// ---- 音频解锁（浏览器自动播放限制）----
let _toneCtx: AudioContext | null = null

/** 在用户手势（pointerdown/keydown）中调用：创建并 resume AudioContext，
 *  否则无手势时浏览器会把上下文挂起，唤醒音效等 WebAudio 声音全部静音。 */
export function unlockAudio(): void {
  try {
    const w = window as any
    const Ctor = w.AudioContext ?? w.webkitAudioContext
    if (!Ctor) return
    const ctx: AudioContext = _toneCtx ?? new Ctor()
    _toneCtx = ctx
    if (ctx.state === 'suspended') void ctx.resume()
  } catch {
    // 解锁失败不影响主流程
  }
}

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

// ---- 桌面端本地识别桥（Electron + sherpa-onnx）----
// preload 注入 window.oneflowDesktop；浏览器环境为 undefined → 自动回退 Web Speech
export interface DesktopBridge {
  asrAvailable: () => boolean
  startAsr: () => void
  stopAsr: () => void
  sendAudio: (samples: Int16Array) => void
  onEvent: (callback: (event: { type: string; text?: string }) => void) => void
  /** 语音链路决策日志（输出到 Electron 终端，排查用） */
  log?: (message: string) => void
}
export function getDesktopBridge(): DesktopBridge | null {
  return ((window as any).oneflowDesktop as DesktopBridge | undefined) ?? null
}

/** 归零唤醒状态（手动关闭待命时调用，之后需重新唤醒才能下指令）。
 *  keepConvo=true：TTS 播报暂停等临时场景——保留会话模式，播完恢复后继续免唤醒对话。 */
export function resetWakeState(keepConvo = false): void {
  wakeState.woken = false
  wakeState.awaiting = false
  wakeState.wakeAt = 0
  wakeBuffer = ''
  // 一并退出会话模式（静默，不触发告别播报）；播报暂停场景保留会话
  if (keepConvo && convoState.active) return
  if (convoState.timer !== null) {
    window.clearTimeout(convoState.timer)
    convoState.timer = null
  }
  convoState.active = false
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
  onConvo?: ConvoCallback,
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

export function stopStandby(stop: () => void): void {
  stop()
}

// ---- 桌面端本地识别待命（Electron + sherpa-onnx）----
// 与 startStandby 同语义：onInterim 实时转写、onWake 命中唤醒/指令；
// 唤醒判定复用模块内 wakeState/wakeBuffer/变体表，播报期间由调用方暂停避免回声。
// 防假唤醒三件套：启动冷却期（丢 TTS 余音）+ 垃圾短文本过滤 + 决策日志。
const LOCAL_COOLDOWN_MS = 1200

function stripPunct(t: string): string {
  return t.replace(/[\s，。！？、,.!?;；:："'“”‘’（）()【】《》…~·-]/g, '')
}

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
      wakeBuffer = ''
    }

    // 未唤醒：滑动窗口 + 同音字变体扫描
    wakeBuffer = (wakeBuffer + text).slice(-WAKE_BUFFER_MAX)
    const hit = findWakeWord(wakeBuffer)
    if (!hit) {
      bridgeLog(`未命中唤醒词: ${text}`)
      return
    }
    wakeBuffer = ''
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
