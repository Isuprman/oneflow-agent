import { useEffect, useState } from 'react'
import { getBriefing, saveBriefing } from '../../api/briefing'
import type { BriefingConfig } from '../../api/types'
import HudCorners from '../../components/HudCorners'
import { getPrefs, savePrefs, type VoicePrefs } from '../../prefs'
import { TTS_VOICES } from '../../theme/ttsVoices'

const PREF_ITEMS: Array<{ key: keyof VoicePrefs; label: string; desc: string }> = [
  { key: 'standby', label: '待命监听', desc: '唤醒词：贾维斯、小翼、你好小助手（同音字也能唤醒）；切换后返回聊天页生效' },
  { key: 'voice', label: '默认语音播报', desc: '助手回复自动朗读' },
  { key: 'chitchat', label: '主动搭话', desc: '闲置很久时贾维斯偶尔主动说一句（每次会话最多 2 次）' },
  { key: 'audioDrive', label: '声音驱动', desc: '3D 核心随你的音量形变' },
  { key: 'showInput', label: '显示输入框', desc: '默认关；开=聊天页出现打字框' },
]

// 语音与待命：本机偏好（待命/播报/搭话/音色）+ 晨间简报开关
export default function VoiceSection() {
  const [prefs, setPrefs] = useState<VoicePrefs>(getPrefs)
  // 晨间简报：预置的每日定时播报（天气+日程）
  const [briefing, setBriefing] = useState<BriefingConfig>({ enabled: false, hour: 8, minute: 0 })
  const [briefingTime, setBriefingTime] = useState('08:00')
  const [savingBriefing, setSavingBriefing] = useState(false)
  const [briefingMessage, setBriefingMessage] = useState('')

  useEffect(() => {
    getBriefing()
      .then((config) => {
        setBriefing(config)
        setBriefingTime(`${String(config.hour).padStart(2, '0')}:${String(config.minute).padStart(2, '0')}`)
      })
      .catch(() => {})
  }, [])

  const togglePref = (key: keyof VoicePrefs) => {
    const next: VoicePrefs = { ...prefs, [key]: !prefs[key] }
    setPrefs(next)
    savePrefs(next)
  }

  const changeTtsVoice = (voiceId: string) => {
    const next: VoicePrefs = { ...prefs, ttsVoice: voiceId }
    setPrefs(next)
    savePrefs(next)
  }

  const toggleBriefing = async (enabled: boolean) => {
    setSavingBriefing(true); setBriefingMessage('')
    try {
      const [hour, minute] = briefingTime.split(':').map((part) => Number(part) || 0)
      const saved = await saveBriefing({ enabled, hour, minute })
      setBriefing(saved)
      setBriefingMessage(enabled ? `已开启：每天 ${briefingTime} 主动播报天气与日程` : '已关闭晨间简报')
    } catch (reason) {
      setBriefingMessage(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSavingBriefing(false)
    }
  }

  return (
    <section className="section-card">
      <HudCorners />
      <header className="module-head">
        <div>
          <p className="module-head__kicker">VOICE &amp; STANDBY</p>
          <h2>语音与待命</h2>
        </div>
        <span className={`led ${prefs.standby ? 'is-ready' : ''}`} aria-hidden="true" />
      </header>
      <p className="section-description">这些是本机偏好，统一管理语音与待命行为；切换后返回聊天页生效。</p>

      <div className="toggle-list">
        {PREF_ITEMS.map(({ key, label, desc }) => (
          <button
            key={key}
            type="button"
            className={`toggle-chip ${prefs[key] ? 'is-on' : ''}`}
            onClick={() => togglePref(key)}
          >
            <span className="toggle-chip__switch"><span className="toggle-chip__knob" /></span>
            <span className="toggle-chip__body">
              <span className="toggle-chip__label">{label}</span>
              <span className="toggle-chip__desc">{desc}</span>
            </span>
            <span className="toggle-chip__state">{prefs[key] ? 'ON' : 'OFF'}</span>
          </button>
        ))}

        {/* 晨间简报：预置每日定时任务，到点自动查天气+日程并主动播报 */}
        <div className={`toggle-chip ${briefing.enabled ? 'is-on' : ''}`} style={{ cursor: 'default' }}>
          <span className="toggle-chip__body">
            <span className="toggle-chip__label">晨间简报</span>
            <span className="toggle-chip__desc">每天到点自动播报今日天气与日程（贾维斯式早安）</span>
          </span>
          <input
            type="time"
            aria-label="简报时间"
            value={briefingTime}
            onChange={(event) => setBriefingTime(event.target.value)}
          />
          <button
            type="button"
            className="outline-button"
            disabled={savingBriefing}
            onClick={() => void toggleBriefing(!briefing.enabled)}
          >
            {savingBriefing ? '保存中…' : briefing.enabled ? '关闭' : '开启'}
          </button>
        </div>
      </div>
      {/* 播报音色：edge-tts 中文音色任选，管家气质自选 */}
      <div className="toggle-chip" style={{ cursor: 'default' }}>
        <span className="toggle-chip__body">
          <span className="toggle-chip__label">播报音色</span>
          <span className="toggle-chip__desc">{TTS_VOICES.find((v) => v.id === prefs.ttsVoice)?.desc ?? '默认音色'}</span>
        </span>
        <select
          aria-label="播报音色"
          value={prefs.ttsVoice}
          onChange={(event) => changeTtsVoice(event.target.value)}
        >
          {TTS_VOICES.map((voice) => (
            <option key={voice.id} value={voice.id}>{voice.label}</option>
          ))}
        </select>
      </div>
      {briefingMessage && <p className="success-note">{briefingMessage}</p>}
    </section>
  )
}
