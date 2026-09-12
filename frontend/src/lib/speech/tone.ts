// 音频解锁与唤醒音效（WebAudio；浏览器自动播放限制需要用户手势解锁）

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
