// 声音驱动核心（voice-reactive）：独立一路麦克风 → AnalyserNode 读取音波做可视化。
// 与语音识别（speech.ts）完全独立并存：此处的 stream 只用于频率分析，绝不喂给识别。

export interface AudioReactiveHandle {
  analyser: AnalyserNode
  audioCtx: AudioContext
  /** 停止跟踪：断开节点、停掉轨道、关闭上下文。 */
  cleanup: () => void
}

/**
 * 启动麦克风分析链路（audio: {echoCancellation, noiseSuppression} 降低回声/噪声干扰）。
 * getUserMedia 失败（无权限 / 无麦克风）时 reject，由调用方提示并保持逻辑驱动。
 */
export async function startMicAnalyser(): Promise<AudioReactiveHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
  })
  const Ctor: typeof AudioContext =
    window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
  const audioCtx = new Ctor()
  const src = audioCtx.createMediaStreamSource(stream)
  const analyser = audioCtx.createAnalyser()
  analyser.fftSize = 512
  analyser.smoothingTimeConstant = 0.85
  src.connect(analyser)
  return {
    analyser,
    audioCtx,
    cleanup: () => {
      try {
        src.disconnect()
      } catch {
        // ignore
      }
      stream.getTracks().forEach((track) => track.stop())
      void audioCtx.close()
    },
  }
}

/**
 * 从 analyser 读出频域并归一化：
 * - vol：全频段平均振幅（0..1）
 * - low：低频段（0~1/3 频段）平均振幅（0..1）
 * dataArray 建议每帧复用（长度 = analyser.frequencyBinCount）。
 */
export function getLevel(analyser: AnalyserNode, dataArray: Uint8Array<ArrayBuffer>): { vol: number; low: number } {
  analyser.getByteFrequencyData(dataArray)
  const binCount = dataArray.length
  const lowEnd = Math.max(1, Math.floor(binCount / 3))
  let sum = 0
  let lowSum = 0
  for (let i = 0; i < binCount; i += 1) {
    sum += dataArray[i]
    if (i < lowEnd) lowSum += dataArray[i]
  }
  return {
    vol: binCount > 0 ? sum / binCount / 255 : 0,
    low: lowEnd > 0 ? lowSum / lowEnd / 255 : 0,
  }
}
