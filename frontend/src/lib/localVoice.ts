// OneFlow 桌面端本地拾音 — 麦克风 → AudioWorklet 采集 → 主线程重采样 16kHz Int16 → IPC
// 与 Web Speech 完全独立：音频不经过任何云服务，直送本地 sherpa-onnx。
let audioCtx: AudioContext | null = null
let mediaStream: MediaStream | null = null
let workletNode: AudioWorkletNode | null = null

// AudioWorklet 处理器：只负责收集原始 Float32 采样并批量上抛（重采样放主线程，逻辑集中）
const WORKLET_CODE = `
class PcmCollector extends AudioWorkletProcessor {
  constructor() { super(); this._buf = []; }
  process(inputs) {
    const input = inputs[0];
    if (input && input[0]) {
      const ch = input[0];
      for (let i = 0; i < ch.length; i++) this._buf.push(ch[i]);
      if (this._buf.length >= 4800) {
        this.port.postMessage(Float32Array.from(this._buf));
        this._buf = [];
      }
    }
    return true;
  }
}
registerProcessor('pcm-collector', PcmCollector);
`

/** 线性插值重采样：srcRate → 16kHz，输出 Int16。 */
function resample16k(samples: Float32Array, srcRate: number): Int16Array {
  if (srcRate === 16000) {
    const out = new Int16Array(samples.length)
    for (let i = 0; i < samples.length; i++) {
      out[i] = Math.max(-32768, Math.min(32767, Math.round(samples[i] * 32767)))
    }
    return out
  }
  const ratio = srcRate / 16000
  const outLen = Math.floor(samples.length / ratio)
  const out = new Int16Array(outLen)
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio
    const idx = Math.floor(pos)
    const frac = pos - idx
    const a = samples[idx] ?? 0
    const b = samples[idx + 1] ?? a
    const value = a + (b - a) * frac
    out[i] = Math.max(-32768, Math.min(32767, Math.round(value * 32767)))
  }
  return out
}

/** 启动拾音；每帧 16kHz Int16 通过 onSamples 上抛。返回是否成功发起（权限失败返回 false）。 */
export function startLocalMic(onSamples: (samples: Int16Array) => void): boolean {
  if (!navigator.mediaDevices?.getUserMedia) return false
  void (async () => {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      })
      const Ctor: typeof AudioContext =
        window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      audioCtx = new Ctor()
      const blobUrl = URL.createObjectURL(new Blob([WORKLET_CODE], { type: 'application/javascript' }))
      await audioCtx.audioWorklet.addModule(blobUrl)
      URL.revokeObjectURL(blobUrl)
      const src = audioCtx.createMediaStreamSource(mediaStream)
      workletNode = new AudioWorkletNode(audioCtx, 'pcm-collector')
      workletNode.port.onmessage = (event: MessageEvent) => {
        const floats = event.data as Float32Array
        onSamples(resample16k(floats, audioCtx ? audioCtx.sampleRate : 48000))
      }
      src.connect(workletNode)
      // 不连 destination：只采集不播放
    } catch (e) {
      console.error('[localMic] 启动失败:', e)
      stopLocalMic()
    }
  })()
  return true
}

/** 停止拾音并释放全部资源。 */
export function stopLocalMic(): void {
  try {
    workletNode?.disconnect()
  } catch {
    // ignore
  }
  workletNode = null
  mediaStream?.getTracks().forEach((track) => track.stop())
  mediaStream = null
  if (audioCtx) {
    void audioCtx.close().catch(() => {})
    audioCtx = null
  }
}
