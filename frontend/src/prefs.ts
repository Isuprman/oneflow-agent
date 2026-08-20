// 浏览器本地偏好（localStorage），供设置页写入、聊天页读取。
export interface VoicePrefs {
  standby: boolean
  voice: boolean
  audioDrive: boolean
  showInput: boolean
  /** edge-tts 音色（设置页可选） */
  ttsVoice: string
  /** 主动搭话：闲置很久时贾维斯偶尔主动说一句（每会话最多 2 次） */
  chitchat: boolean
}

const KEY = 'oneflow_prefs'

// 默认音色：晓晓（女声，温和）
export const DEFAULT_TTS_VOICE = 'zh-CN-XiaoxiaoNeural'

// 默认：待命监听开、语音播报开、声音驱动关、显示输入框关（语音优先）、主动搭话开。
export const DEFAULT_PREFS: VoicePrefs = {
  standby: true,
  voice: true,
  audioDrive: false,
  showInput: false,
  ttsVoice: DEFAULT_TTS_VOICE,
  chitchat: true,
}

export function getPrefs(): VoicePrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const p = JSON.parse(raw)
      return {
        standby: !!p.standby,
        voice: !!p.voice,
        audioDrive: !!p.audioDrive,
        showInput: !!p.showInput,
        ttsVoice: typeof p.ttsVoice === 'string' && p.ttsVoice ? p.ttsVoice : DEFAULT_TTS_VOICE,
        chitchat: p.chitchat === undefined ? true : !!p.chitchat,
      }
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
