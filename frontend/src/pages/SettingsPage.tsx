import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { addMcpServer, deleteMcpServer, listLearnProposals, listMcpServers, refreshMcpServer, toggleMcpServer, deleteMemory, deleteNotification, deleteTask, getBriefing, getHotelConfig, getLlmConfig, listMemories, listNotifications, listTasks, saveBriefing, saveHotelConfig, saveLlmConfig, updateTask, type LearnProposalOut, type McpServerOut } from '../api/client'
import type { AppNotification, BriefingConfig, HotelConfig, LlmConfig, Memory, TaskInfo } from '../api/types'
import ParticleField from '../components/ParticleField'
import HudCorners from '../components/HudCorners'
import { getPrefs, savePrefs, type VoicePrefs } from '../prefs'
import { DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL, DEFAULT_LLM_PROVIDER, LLM_PROVIDERS } from '../theme/llmModels'
import { TTS_VOICES } from '../theme/ttsVoices'

const PREF_ITEMS: Array<{ key: keyof VoicePrefs; label: string; desc: string }> = [
  { key: 'standby', label: '待命监听', desc: '唤醒词：贾维斯、小翼、你好小助手（同音字也能唤醒）；切换后返回聊天页生效' },
  { key: 'voice', label: '默认语音播报', desc: '助手回复自动朗读' },
  { key: 'chitchat', label: '主动搭话', desc: '闲置很久时贾维斯偶尔主动说一句（每次会话最多 2 次）' },
  { key: 'audioDrive', label: '声音驱动', desc: '3D 核心随你的音量形变' },
  { key: 'showInput', label: '显示输入框', desc: '默认关；开=聊天页出现打字框' },
]

// 通知类型 → 中文标签
const NOTE_KIND_LABELS: Record<string, string> = {
  task: '定时播报',
  reminder: '日程提醒',
  care: '情景关怀',
  habit: '习惯洞察',
  system_error: '系统自检',
}
const WEEKDAY_LABELS = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']

// 信任等级：贾维斯的自治程度（本机偏好；后端以 trust.level 设置为准，默认 standard）
type TrustLevel = 'ask_all' | 'standard' | 'auto'
const TRUST_STORAGE_KEY = 'oneflow_trust_level'
const TRUST_ITEMS: Array<{ value: TrustLevel; label: string; desc: string }> = [
  { value: 'ask_all', label: '每次询问', desc: '每个工具调用前都先征得同意，最稳妥' },
  { value: 'standard', label: '标准（默认）', desc: '仅写操作需要确认，学习提案始终要批准' },
  { value: 'auto', label: '自动执行', desc: '普通写操作直接执行；删除类高危与学习提案仍需确认' },
]

function getTrustLevel(): TrustLevel {
  try {
    const raw = localStorage.getItem(TRUST_STORAGE_KEY)
    if (raw === 'ask_all' || raw === 'auto') return raw
  } catch {
    // 忽略读取失败（如隐私模式），回退默认
  }
  return 'standard'
}

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
  // 定时任务管理（不含晨间简报，它有专属开关）
  const [tasks, setTasks] = useState<TaskInfo[]>([])
  const [taskError, setTaskError] = useState('')
  // 通知中心（历史全量）
  const [notes, setNotes] = useState<AppNotification[]>([])
  // 技能工厂：自学习提案状态总览
  const [proposals, setProposals] = useState<LearnProposalOut[]>([])
  const [proposalsLoading, setProposalsLoading] = useState(true)
  const [proposalsError, setProposalsError] = useState('')
  // 信任等级：三选一，选中即保存
  const [trustLevel, setTrustLevel] = useState<TrustLevel>(getTrustLevel)
  // MCP 服务：外部工具生态接入（连接成功后工具自动并入贾维斯能力清单）
  const [mcpServers, setMcpServers] = useState<McpServerOut[]>([])
  const [mcpError, setMcpError] = useState('')
  const [mcpName, setMcpName] = useState('')
  const [mcpCommand, setMcpCommand] = useState('')
  const [mcpUrl, setMcpUrl] = useState('')
  const [addingMcp, setAddingMcp] = useState(false)
  const [mcpBusyId, setMcpBusyId] = useState<number | null>(null)

  // MCP 状态徽章文案
  const MCP_STATUS_LABELS: Record<string, string> = {
    connected: '已连接',
    error: '连接失败',
    off: '未连接',
  }

  const loadMcpServers = () => {
    listMcpServers()
      .then(setMcpServers)
      .catch((reason: unknown) => setMcpError(reason instanceof Error ? reason.message : String(reason)))
  }

  // 提案状态 → 中文徽章文案 / 徽章配色 class
  const PROPOSAL_BADGES: Record<string, string> = {
    pending: '待审批',
    approved: '✅已上线',
    rejected: '已放弃',
    failed: '失败',
  }
  const PROPOSAL_BADGE_CLASS: Record<string, string> = {
    approved: 'trace-success',
    failed: 'trace-failure',
    rejected: 'ledger-hint',
  }

  const loadProposals = () => {
    setProposalsLoading(true); setProposalsError('')
    listLearnProposals()
      .then(setProposals)
      .catch((reason: unknown) => setProposalsError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setProposalsLoading(false))
  }

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
    listTasks().then(setTasks).catch((reason: unknown) => setTaskError(reason instanceof Error ? reason.message : String(reason)))
    listNotifications(false).then(setNotes)
    loadProposals()
    loadMcpServers()
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
  const changeTrustLevel = (level: TrustLevel) => {
    setTrustLevel(level)
    try {
      localStorage.setItem(TRUST_STORAGE_KEY, level)
    } catch {
      // 忽略写入失败（如隐私模式）
    }
  }
  // ─── MCP 服务 ───────────────────────────────────────────────────
  const addServer = async () => {
    setAddingMcp(true); setMcpError('')
    try {
      // command 与 url 二选一：填了哪个就用哪个
      const payload = mcpUrl.trim()
        ? { name: mcpName.trim(), url: mcpUrl.trim() }
        : { name: mcpName.trim(), command: mcpCommand.trim() }
      const created = await addMcpServer(payload)
      setMcpServers((previous) => [...previous, created])
      setMcpName(''); setMcpCommand(''); setMcpUrl('')
    } catch (reason) {
      setMcpError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setAddingMcp(false)
    }
  }
  const toggleServer = async (server: McpServerOut) => {
    setMcpBusyId(server.id); setMcpError('')
    try {
      const updated = await toggleMcpServer(server.id, !server.enabled)
      setMcpServers((previous) => previous.map((item) => (item.id === server.id ? updated : item)))
    } catch (reason) {
      setMcpError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setMcpBusyId(null)
    }
  }
  const refreshServer = async (server: McpServerOut) => {
    setMcpBusyId(server.id); setMcpError('')
    try {
      const updated = await refreshMcpServer(server.name)
      setMcpServers((previous) => previous.map((item) => (item.id === server.id ? updated : item)))
    } catch (reason) {
      setMcpError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setMcpBusyId(null)
    }
  }
  const removeServer = async (server: McpServerOut) => {
    setMcpBusyId(server.id); setMcpError('')
    try {
      await deleteMcpServer(server.id)
      setMcpServers((previous) => previous.filter((item) => item.id !== server.id))
    } catch (reason) {
      setMcpError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setMcpBusyId(null)
    }
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
  const toggleTask = async (task: TaskInfo) => {
    setTaskError('')
    try {
      const updated = await updateTask(task.id, { enabled: !task.enabled })
      setTasks((previous) => previous.map((item) => (item.id === task.id ? updated : item)))
    } catch (reason) {
      setTaskError(reason instanceof Error ? reason.message : String(reason))
    }
  }
  const removeTask = async (task: TaskInfo) => {
    setTaskError('')
    try {
      await deleteTask(task.id)
      setTasks((previous) => previous.filter((item) => item.id !== task.id))
    } catch (reason) {
      setTaskError(reason instanceof Error ? reason.message : String(reason))
    }
  }
  const removeNote = async (id: number) => {
    await deleteNotification(id)
    setNotes((previous) => previous.filter((item) => item.id !== id))
  }
  const clearNotes = async () => {
    for (const note of notes) await deleteNotification(note.id)
    setNotes([])
  }
  const formatTime = (value: string) => {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
  }
  const truncateText = (text: string, max = 60) => (text.length > max ? `${text.slice(0, max)}…` : text)

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

        {/* 定时任务管理（晨间简报在上方专属开关，此处不重复展示） */}
        <section className="section-card">
          <HudCorners />
          <header className="module-head">
            <div>
              <p className="module-head__kicker">SCHEDULED TASKS</p>
              <h2>定时任务</h2>
            </div>
            <span className={`led ${tasks.some((task) => task.enabled) ? 'is-ready' : ''}`} aria-hidden="true" />
          </header>
          <p className="section-description">到点后自动执行并主动播报的任务；也可以直接对贾维斯说“取消某某任务”。</p>

          {taskError && <p className="error-note" role="alert">{taskError}</p>}
          {tasks.length === 0 ? (
            <p className="empty-copy">暂无定时任务。试着对贾维斯说：“每天晚上9点提醒我喝水”。</p>
          ) : (
            <div className="toggle-list">
              {tasks.map((task) => (
                <div key={task.id} className="toggle-chip">
                  <span className="toggle-chip__body">
                    <span className="toggle-chip__label">{task.title}</span>
                    <span className="toggle-chip__desc">
                      {task.kind_label}
                      {task.kind === 'weekly' && task.weekday ? ` ${WEEKDAY_LABELS[task.weekday]}` : ''}
                      {` ${String(task.hour).padStart(2, '0')}:${String(task.minute).padStart(2, '0')}`}
                      {task.next_run_at ? ` · 下次：${formatTime(task.next_run_at)}` : ' · 已停用'}
                    </span>
                  </span>
                  <button
                    type="button"
                    className={`toggle-chip ${task.enabled ? 'is-on' : ''}`}
                    style={{ padding: '4px 10px' }}
                    onClick={() => void toggleTask(task)}
                  >
                    <span className="toggle-chip__state">{task.enabled ? 'ON' : 'OFF'}</span>
                  </button>
                  <button type="button" className="outline-button" onClick={() => void removeTask(task)}>删除</button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 通知中心：贾维斯主动播报过的历史都可回看 */}
        <section className="section-card">
          <HudCorners />
          <header className="module-head">
            <div>
              <p className="module-head__kicker">NOTIFICATION CENTER</p>
              <h2>通知中心</h2>
            </div>
            <span className={`led ${notes.length > 0 ? 'is-ready' : ''}`} aria-hidden="true" />
          </header>
          <p className="section-description">定时播报、日程提醒、情景关怀与习惯洞察的历史记录。</p>

          {notes.length === 0 ? (
            <p className="empty-copy">暂无通知。</p>
          ) : (
            <>
              <ul className="memory-list">
                {notes.map((note) => (
                  <li className="memory-row" key={note.id}>
                    <div className="memory-row__copy">
                      <p>
                        <strong>[{NOTE_KIND_LABELS[note.kind] ?? note.kind}] {note.title}</strong>
                        {' '}{note.content}
                      </p>
                      <time>{formatTime(note.created_at)}</time>
                    </div>
                    <button className="outline-button" onClick={() => void removeNote(note.id)}>删除</button>
                  </li>
                ))}
              </ul>
              <div className="save-bar">
                <button className="outline-button" onClick={() => void clearNotes()}>清空全部</button>
              </div>
            </>
          )}
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

        {/* 技能工厂：自学习提案的状态总览 */}
        <section className="section-card">
          <HudCorners />
          <header className="module-head">
            <div>
              <p className="module-head__kicker">SKILL FACTORY</p>
              <h2>🛠 技能工厂</h2>
            </div>
            <span className={`led ${proposals.length > 0 ? 'is-ready' : ''}`} aria-hidden="true" />
          </header>
          <p className="section-description">贾维斯自学技能的提案记录；待审批的技能在聊天里回复「批准 编号」即可上线。</p>

          <div className="save-bar" style={{ justifyContent: 'flex-start' }}>
            <button className="outline-button" disabled={proposalsLoading} onClick={loadProposals}>
              {proposalsLoading ? '刷新中…' : '刷新'}
            </button>
          </div>

          {proposalsError && <p className="error-note" role="alert">{proposalsError}</p>}
          {proposalsLoading ? (
            <p className="loading-state">加载中…</p>
          ) : proposals.length === 0 ? (
            <p className="empty-copy">暂无学习提案。试着对贾维斯说：“教我一个新技能”。</p>
          ) : (
            <ul className="memory-list">
              {proposals.map((proposal) => (
                <li className="memory-row" key={proposal.id}>
                  <div className="memory-row__copy">
                    <p>
                      <strong>{proposal.slug}</strong>{' '}
                      <span className={PROPOSAL_BADGE_CLASS[proposal.status] ?? ''}>{PROPOSAL_BADGES[proposal.status] ?? proposal.status}</span>
                    </p>
                    {proposal.description && <p>{truncateText(proposal.description)}</p>}
                    {proposal.created_at ? <time>{formatTime(proposal.created_at)}</time> : null}
                    {proposal.status === 'pending' && (
                      <small className="ledger-hint" style={{ display: 'block', marginTop: 4 }}>
                        在聊天里回复 批准 {proposal.id} 上线
                      </small>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 信任等级：贾维斯的自治程度 */}
        <section className="section-card">
          <HudCorners />
          <header className="module-head">
            <div>
              <p className="module-head__kicker">TRUST LEVEL</p>
              <h2>信任等级</h2>
            </div>
            <span className={`led ${trustLevel !== 'standard' ? 'is-ready' : ''}`} aria-hidden="true" />
          </header>
          <p className="section-description">决定贾维斯执行工具时的自治程度；学习提案的审批在任何等级下都不跳过。</p>

          <div className="ledger">
            <div className="ledger-field ledger-field--full">
              <span className="ledger-field__label">自治程度</span>
              <div className="chip-group" role="radiogroup" aria-label="信任等级">
                {TRUST_ITEMS.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    role="radio"
                    aria-checked={trustLevel === item.value}
                    className={`chip ${trustLevel === item.value ? 'is-active' : ''}`}
                    onClick={() => changeTrustLevel(item.value)}
                  >
                    <span className="chip__dot" aria-hidden="true" />
                    {item.label}
                  </button>
                ))}
              </div>
              <p className="ledger-hint">{TRUST_ITEMS.find((item) => item.value === trustLevel)?.desc}</p>
            </div>
          </div>
        </section>

        {/* MCP 服务：外部工具生态接入 */}
        <section className="section-card">
          <HudCorners />
          <header className="module-head">
            <div>
              <p className="module-head__kicker">MCP SERVICES</p>
              <h2>MCP 服务</h2>
            </div>
            <span className={`led ${mcpServers.some((s) => s.status === 'connected') ? 'is-ready' : ''}`} aria-hidden="true" />
          </header>
          <p className="section-description">
            连接任意 MCP server（Model Context Protocol），其工具自动并入贾维斯的能力清单；command 与 url 二选一。
          </p>

          {mcpError && <p className="error-note" role="alert">{mcpError}</p>}
          {mcpServers.length === 0 ? (
            <p className="empty-copy">暂无 MCP 服务。在下方添加一个即可接入其工具。</p>
          ) : (
            <ul className="memory-list">
              {mcpServers.map((server) => (
                <li className="memory-row" key={server.id}>
                  <div className="memory-row__copy">
                    <p>
                      <strong>{server.name}</strong>{' '}
                      <span className={server.status === 'connected' ? 'trace-success' : server.status === 'error' ? 'trace-failure' : 'ledger-hint'}>
                        [{MCP_STATUS_LABELS[server.status] ?? server.status}]
                      </span>
                    </p>
                    <p>{truncateText(server.command || server.url, 48)}</p>
                    <small className="ledger-hint">
                      {server.enabled
                        ? server.tools.length > 0
                          ? `已注册 ${server.tools.length} 个工具`
                          : '尚未注册工具'
                        : '已停用'}
                    </small>
                  </div>
                  <button
                    type="button"
                    className={`toggle-chip ${server.enabled ? 'is-on' : ''}`}
                    style={{ padding: '4px 10px' }}
                    disabled={mcpBusyId === server.id}
                    onClick={() => void toggleServer(server)}
                  >
                    <span className="toggle-chip__state">{server.enabled ? 'ON' : 'OFF'}</span>
                  </button>
                  <button
                    type="button"
                    className="outline-button"
                    disabled={mcpBusyId === server.id || !server.enabled}
                    onClick={() => void refreshServer(server)}
                  >
                    刷新
                  </button>
                  <button
                    type="button"
                    className="outline-button"
                    disabled={mcpBusyId === server.id}
                    onClick={() => void removeServer(server)}
                  >
                    删除
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="ledger">
            <div className="ledger-field">
              <label htmlFor="mcp-name">服务名</label>
              <input id="mcp-name" value={mcpName} onChange={(event) => setMcpName(event.target.value)} placeholder="filesystem / fetch ..." />
            </div>
            <div className="ledger-field">
              <label htmlFor="mcp-command">启动命令（stdio）</label>
              <input id="mcp-command" value={mcpCommand} onChange={(event) => setMcpCommand(event.target.value)} placeholder="npx -y @modelcontextprotocol/server-filesystem /tmp" />
            </div>
            <div className="ledger-field ledger-field--full">
              <label htmlFor="mcp-url">或 HTTP 端点（url）</label>
              <input id="mcp-url" value={mcpUrl} onChange={(event) => setMcpUrl(event.target.value)} placeholder="https://example.com/mcp" />
            </div>
          </div>
          <div className="save-bar">
            <button
              className="primary-button"
              disabled={addingMcp || !mcpName.trim() || (!mcpCommand.trim() && !mcpUrl.trim())}
              onClick={() => void addServer()}
            >
              {addingMcp ? '连接中…' : '添加并连接'}
            </button>
          </div>
        </section>
      </div>
    </main>
  )
}
