// 浏览器本地偏好（localStorage），供设置页写入、聊天页读取。
export interface VoicePrefs {
  standby: boolean
  voice: boolean
  audioDrive: boolean
  showInput: boolean
}

const KEY = 'oneflow_prefs'

// 默认：待命监听开、语音播报开、声音驱动关、显示输入框关（语音优先）。
export const DEFAULT_PREFS: VoicePrefs = { standby: true, voice: true, audioDrive: false, showInput: false }

export function getPrefs(): VoicePrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const p = JSON.parse(raw)
      return { standby: !!p.standby, voice: !!p.voice, audioDrive: !!p.audioDrive, showInput: !!p.showInput }
    }
  } catch {
    // 忽略解析错误，回退到默认值
  }
  return { ...DEFAULT_PREFS }
}

export function savePrefs(p: VoicePrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(p))
  } catch {
    // 忽略写入失败（如隐私模式）
  }
}
