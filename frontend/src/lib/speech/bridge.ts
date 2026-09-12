// 桌面端本地识别桥（Electron + sherpa-onnx）
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
