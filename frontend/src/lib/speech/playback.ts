// 语音播报管道：edge-tts 音频流播放 + 分句 + 浏览器 speechSynthesis 兜底。
// 合成请求在 api/tts.ts；这里只管「真实播放结束时机」与打断。

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
