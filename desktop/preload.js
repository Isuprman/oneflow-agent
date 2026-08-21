// OneFlow 桌面端 preload — 安全暴露本地语音桥（contextIsolation）
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('oneflowDesktop', {
  /** 本地 ASR 是否可用（模型已下载 + 引擎可加载）。 */
  asrAvailable: () => ipcRenderer.sendSync('asr:available'),
  /** 启动本地识别管线。 */
  startAsr: () => ipcRenderer.send('asr:start'),
  /** 停止本地识别管线。 */
  stopAsr: () => ipcRenderer.send('asr:stop'),
  /** 发送一帧 16kHz Int16 PCM。 */
  sendAudio: (samplesInt16) => ipcRenderer.send('asr:audio', samplesInt16),
  /** 订阅识别事件 {type:'partial'|'final'|'error', text}；重复订阅会替换旧监听，防泄漏。 */
  onEvent: (callback) => {
    ipcRenderer.removeAllListeners('asr:event')
    ipcRenderer.on('asr:event', (_event, payload) => callback(payload))
  },
  /** 语音链路决策日志 → Electron 终端（排查唤醒/派发问题用）。 */
  log: (message) => ipcRenderer.send('asr:log', message),
})
