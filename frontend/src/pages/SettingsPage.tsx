import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { deleteMemory, getBriefing, getHotelConfig, getLlmConfig, listMemories, saveBriefing, saveHotelConfig, saveLlmConfig } from '../api/client'
import type { BriefingConfig, HotelConfig, LlmConfig, Memory } from '../api/types'
import ParticleField from '../components/ParticleField'
import HudCorners from '../components/HudCorners'
import { getPrefs, savePrefs, type VoicePrefs } from '../prefs'
import { DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL, DEFAULT_LLM_PROVIDER, LLM_PROVIDERS } from '../theme/llmModels'
import { TTS_VOICES } from '../theme/ttsVoices'

const PREF_ITEMS: Array<{ key: keyof VoicePrefs; label: string; desc: string }> = [
  { key: 'standby', label: '待命监听', desc: '唤醒词：贾维斯、小翼、你好小助手（同音字也能唤醒）；切换后返回聊天页生效' },
  { key: 'voice', label: '默认语音播报', desc: '助手回复自动朗读' },
  { key: 'audioDrive', label: '声音驱动', desc: '3D 核心随你的音量形变' },
  { key: 'showInput', label: '显示输入框', desc: '默认关；开=聊天页出现打字框' },
]

export default function SettingsPage() {
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null)
  const [provider, setProvider] = useState(DEFAULT_LLM_PROVIDER)
  const [model, setModel] = useState(DEFAULT_LLM_MODEL)
  const [apiKey, setApiKey] = useState('')
  const [llmBaseUrl, setLlmBaseUrl] = useState(DEFAULT_LLM_BASE_URL)
  const [savingLlm, setSavingLlm] = useState(false)
  const [llmMessage, setLlmMessage] = useState('')
  const [llmError, setLlmError] = useState('')
  const [hotelConfig, setHotelConfig] = useState<HotelConfig | null>(null)
  const [hotelBaseUrl, setHotelBaseUrl] = useState('')
  const [hotelApiKey, setHotelApiKey] = useState('')
  const [savingHotel, setSavingHotel] = useState(false)
  const [hotelMessage, setHotelMessage] = useState('')
  const [hotelError, setHotelError] = useState('')
  const [memories, setMemories] = useState<Memory[]>([])
  const [memoryError, setMemoryError] = useState('')
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [prefs, setPrefs] = useState<VoicePrefs>(getPrefs)
  // 晨间简报：预置的每日定时播报（天气+日程）
  const [briefing, setBriefing] = useState<BriefingConfig>({ enabled: false, hour: 8, minute: 0 })
  const [briefingTime, setBriefingTime] = useState('08:00')
  const [savingBriefing, setSavingBriefing] = useState(false)
  const [briefingMessage, setBriefingMessage] = useState('')

  useEffect(() => {
    getLlmConfig()
      .then((config) => {
        setLlmConfig(config)
        const savedProvider = config.provider || DEFAULT_LLM_PROVIDER
        setProvider(savedProvider)
        setModel(config.model || LLM_PROVIDERS[savedProvider]?.models[0] || DEFAULT_LLM_MODEL)
        setLlmBaseUrl(config.base_url || LLM_PROVIDERS[savedProvider]?.defaultBaseUrl || '')
      })
      .catch((reason: unknown) => setLlmError(reason instanceof Error ? reason.message : String(reason)))
    getHotelConfig()
      .then((config) => { setHotelConfig(config); setHotelBaseUrl(config.base_url) })
      .catch((reason: unknown) => setHotelError(reason instanceof Error ? reason.message : String(reason)))
    listMemories()
      .then(setMemories)
      .catch((reason: unknown) => setMemoryError(reason instanceof Error ? reason.message : String(reason)))
    getBriefing()
      .then((config) => {
        setBriefing(config)
        setBriefingTime(`${String(config.hour).padStart(2, '0')}:${String(config.minute).padStart(2, '0')}`)
      })
      .catch(() => {})
  }, [])

  const selectProvider = (next: string) => {
    if (next === provider) return
    const target = LLM_PROVIDERS[next]
    setProvider(next)
    // 模型：优先沿用当前模型（若属于该提供商），否则取该提供商第一个内置模型
    setModel(target?.models.includes(model) ? model : (target?.models[0] ?? DEFAULT_LLM_MODEL))
    // Base URL：自动带出默认值；无默认则留空让用户填
    setLlmBaseUrl(target?.defaultBaseUrl ?? '')
  }

  const saveLlm = async () => {
    setSavingLlm(true); setLlmMessage(''); setLlmError('')
    try {
      const config = await saveLlmConfig({ provider, model: model.trim(), api_key: apiKey, base_url: llmBaseUrl.trim() })
      setLlmConfig(config); setApiKey(''); setLlmMessage(`已保存：${config.provider}/${config.model}`)
    } catch (reason) {
      setLlmError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSavingLlm(false)
    }
  }
  const saveHotel = async () => {
    setSavingHotel(true); setHotelMessage(''); setHotelError('')
    try {
      const config = await saveHotelConfig({ base_url: hotelBaseUrl.trim(), api_key: hotelApiKey })
      setHotelConfig(config); setHotelApiKey(''); setHotelMessage('酒店配置已保存')
    } catch (reason) {
      setHotelError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSavingHotel(false)
    }
  }
  const deleteOneMemory = async (id: number) => {
    setDeletingId(id); setMemoryError('')
    try {
      await deleteMemory(id)
      setMemories((items) => items.filter((item) => item.id !== id))
    } catch (reason) {
      setMemoryError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setDeletingId(null)
    }
  }
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
  const formatTime = (value: string) => {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
  }

  return (
    <main className="settings-page">
      <ParticleField />
      <div className="settings-wrap">
        <header className="settings-header">
          <div>
            <p className="section-kicker">SYSTEM CONFIGURATION</p>
            <h1>控制台设置</h1>
          </div>
          <Link className="back-link" to="/">返回聊天</Link>
        </header>

        {/* LLM 配置 */}
        <section className="section-card">
          <HudCorners />
          <header className="module-head">
            <div>
              <p className="module-head__kicker">LLM CONFIGURATION</p>
              <h2>LLM 配置</h2>
            </div>
            <span className={`led ${llmConfig?.configured ? 'is-ready' : ''}`} aria-hidden="true" />
          </header>
          <p className="section-description">连接模型提供商，设定当前终端的推理引擎。</p>

          <div className="ledger">
            <div className="ledger-field ledger-field--full">
              <span className="ledger-field__label">提供商</span>
              <div className="chip-group">
                {Object.entries(LLM_PROVIDERS).map(([key, item]) => (
                  <button
                    key={key}
                    type="button"
                    className={`chip ${provider === key ? 'is-active' : ''}`}
                    onClick={() => selectProvider(key)}
                  >
                    <span className="chip__dot" aria-hidden="true" />
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="ledger-field">
              <label htmlFor="model">模型</label>
              <input id="model" list="llm-model-options" value={model} onChange={(event) => setModel(event.target.value)} placeholder="deepseek-v4-flash / gpt-5.6-sol" />
              <datalist id="llm-model-options">
                {LLM_PROVIDERS[provider]?.models.map((item) => <option key={item} value={item} />)}
              </datalist>
            </div>

            <div className="ledger-field">
              <label htmlFor="llm-key">API 密钥</label>
              <input id="llm-key" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-..." />
              {llmConfig?.api_key_set && <small className="ledger-hint">已设置，留空表示不修改</small>}
            </div>

            <div className="ledger-field ledger-field--full">
              <label>Base URL（系统按供应商自动配置）</label>
              <p className="ledger-hint">{llmBaseUrl ? `自动使用：${llmBaseUrl}` : '无需填写，系统自动选择端点'}</p>
            </div>
          </div>

          <p className={`status-line ${llmConfig?.configured ? 'is-ready' : ''}`}>
            {llmConfig?.configured ? `已连接：${llmConfig.provider}/${llmConfig.model}` : '尚未配置'}
          </p>
          {llmMessage && <p className="success-note">{llmMessage}</p>}
          {llmError && <p className="error-note" role="alert">{llmError}</p>}
          <div className="save-bar">
            <button className="primary-button" disabled={savingLlm} onClick={() => void saveLlm()}>
              {savingLlm ? '保存中…' : '保存 LLM 配置'}
            </button>
          </div>
        </section>

        {/* 酒店配置 */}
        <section className="section-card">
          <HudCorners />
          <header className="module-head">
            <div>
              <p className="module-head__kicker">HOTEL CONFIGURATION</p>
              <h2>酒店配置</h2>
            </div>
            <span className={`led ${hotelConfig?.configured ? 'is-ready' : ''}`} aria-hidden="true" />
          </header>
          <p className="section-description">设定酒店服务的连接地址与访问密钥。</p>

          <div className="ledger">
            <div className="ledger-field">
              <label htmlFor="hotel-url">Base URL</label>
              <input id="hotel-url" value={hotelBaseUrl} onChange={(event) => setHotelBaseUrl(event.target.value)} placeholder="https://..." />
            </div>
            <div className="ledger-field">
              <label htmlFor="hotel-key">API 密钥</label>
              <input id="hotel-key" type="password" value={hotelApiKey} onChange={(event) => setHotelApiKey(event.target.value)} placeholder="..." />
              {hotelConfig?.api_key_set && <small className="ledger-hint">已设置，留空表示不修改</small>}
            </div>
          </div>

          <p className={`status-line ${hotelConfig?.configured ? 'is-ready' : ''}`}>
            {hotelConfig?.configured ? '酒店服务已连接' : '尚未配置'}
          </p>
          {hotelMessage && <p className="success-note">{hotelMessage}</p>}
          {hotelError && <p className="error-note" role="alert">{hotelError}</p>}
          <div className="save-bar">
            <button className="primary-button" disabled={savingHotel} onClick={() => void saveHotel()}>
              {savingHotel ? '保存中…' : '保存酒店配置'}
            </button>
          </div>
        </section>

        {/* 语音与待命 */}
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

        {/* 长期记忆 */}
        <section className="section-card">
          <HudCorners />
          <header className="module-head">
            <div>
              <p className="module-head__kicker">LONG-TERM MEMORY</p>
              <h2>长期记忆</h2>
            </div>
            <span className={`led ${memories.length > 0 ? 'is-ready' : ''}`} aria-hidden="true" />
          </header>
          <p className="section-description">Agent 会保留你透露的长期信息，供后续对话引用。</p>

          {memoryError && <p className="error-note" role="alert">{memoryError}</p>}
          {memories.length === 0 ? (
            <p className="empty-copy">暂无长期记忆。</p>
          ) : (
            <ul className="memory-list">
              {memories.map((memory) => (
                <li className="memory-row" key={memory.id}>
                  <div className="memory-row__copy">
                    <p>{memory.content}</p>
                    <time>{formatTime(memory.created_at)}</time>
                  </div>
                  <button className="outline-button" disabled={deletingId === memory.id} onClick={() => void deleteOneMemory(memory.id)}>
                    {deletingId === memory.id ? '删除中…' : '删除'}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  )
}
