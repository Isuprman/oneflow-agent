// 唤醒/会话模式状态机（两个识别通道共享的核心）：
// 模块级唤醒状态跨识别实例保留（识别会话结束自动重挂后不丢）。
// 唤醒词同音字/近音变体：中文 ASR 常把人名听成同音字，逐个硬匹配容错。

export const WAKE_WORDS = ['贾维斯', '小翼', '你好小助手', '小助手']

const WAKE_VARIANTS: Record<string, string[]> = {
  '贾维斯': ['贾维斯', '加维斯', '佳维斯', '嘉维斯', '家维斯', '假维斯', '查维斯'],
  '小翼': ['小翼', '小易', '小义', '小毅', '小艺'],
  '你好小助手': ['你好小助手', '你好小住手', '你好小助守'],
  '小助手': ['小助手', '小住手', '小助守'],
}

/** 在 text 中找唤醒词（含变体）：返回 { start, end }，未命中返回 null。 */
export function findWakeWord(text: string): { start: number; end: number } | null {
  for (const word of WAKE_WORDS) {
    for (const variant of WAKE_VARIANTS[word] ?? [word]) {
      const idx = text.indexOf(variant)
      if (idx >= 0) return { start: idx, end: idx + variant.length }
    }
  }
  return null
}

// 唤醒后免唤醒词连说的窗口时长（短窗口，减少误派发）
export const WAKE_SLOT_MS = 8000
// 滑动窗口上限：既覆盖唤醒词跨 final 被切断的情况，又避免旧文本重复命中
export const WAKE_BUFFER_MAX = 40
// 模块级唤醒状态：跨识别实例保留（识别会话结束自动重挂后不丢）
export const wakeState = { woken: false, awaiting: false, wakeAt: 0 }
// 滑动窗口文本（对象持有：识别通道模块需要跨模块读写，ES module 导入绑定只读）
export const wakeBuffer = { text: '' }

// ---- 会话模式（长对话）：唤醒即进入，免唤醒词直接对话，说“退下”或闲置超时才退出 ----
export interface ConvoEvent { type: 'enter' | 'exit'; reason?: 'user' | 'timeout' }
export type ConvoCallback = (event: ConvoEvent) => void

// 退出通道永远比进入通道宽：包含即退，同音字/漏词都能退
const EXIT_PATTERNS = ['退下', '没事了', '没事儿了', '你先休息', '先休息吧', '没你事了', '不用你了']
// 闲置自动退下时长：会话中这么久没说话，贾维斯自己告退
const CONVO_IDLE_MS = 90000

const convoState = { active: false, timer: null as number | null }
let lastConvoCb: ConvoCallback | null = null

/** 会话存活时刷新闲置计时（TTS 播报暂停期间防超时退出）。 */
export function bumpConvoIdle(): void {
  if (convoState.active) armConvoTimer(lastConvoCb ?? undefined)
}

export function isConvoActive(): boolean {
  return convoState.active
}

function isExitPhrase(text: string): boolean {
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

export function enterConvo(onConvo?: ConvoCallback): void {
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
export function tryConvoRoute(text: string, onWake: (command: string) => void, onConvo?: ConvoCallback): boolean {
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

/** 归零唤醒状态（手动关闭待命时调用，之后需重新唤醒才能下指令）。
 *  keepConvo=true：TTS 播报暂停等临时场景——保留会话模式，播完恢复后继续免唤醒对话。 */
export function resetWakeState(keepConvo = false): void {
  wakeState.woken = false
  wakeState.awaiting = false
  wakeState.wakeAt = 0
  wakeBuffer.text = ''
  // 一并退出会话模式（静默，不触发告别播报）；播报暂停场景保留会话
  if (keepConvo && convoState.active) return
  if (convoState.timer !== null) {
    window.clearTimeout(convoState.timer)
    convoState.timer = null
  }
  convoState.active = false
}

export function stripPunct(t: string): string {
  return t.replace(/[\s，。！？、,.!?;；:："'“”‘’（）()【】《》…~·-]/g, '')
}
