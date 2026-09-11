import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { addMcpServer, deleteMcpServer, listMcpServers, refreshMcpServer, toggleMcpServer, type McpServerOut } from '../api/mcp'
import { listLearnProposals, type LearnProposalOut } from '../api/learn'
import { deleteMemory, listMemories } from '../api/memories'
import { deleteNotification, listNotifications } from '../api/notifications'
import { deleteTask, listTasks, updateTask } from '../api/tasks'
import type { AppNotification, Memory, TaskInfo } from '../api/types'
import ParticleField from '../components/ParticleField'
import HudCorners from '../components/HudCorners'
import { formatTime, truncateText } from './settings/shared'
import LlmSection from './settings/LlmSection'
import HotelSection from './settings/HotelSection'
import VoiceSection from './settings/VoiceSection'

// ─── 情境剧本：与 /api/scenes 直连的轻量客户端（仅本页使用，独立封装避免扩 API 层）───
interface SceneInfo {
  id: number
  name: string
  steps: string[]
  step_count: number
  enabled: boolean
  created_at: string | null
}
interface SceneRunResult {
  step: string
  reply: string
  success: boolean
}

async function scenesRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('oneflow_token')
  const res = await fetch(`/api/scenes${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    let detail = ''
    try {
      const data = (await res.json()) as { detail?: string }
      detail = data.detail ?? ''
    } catch {
      detail = await res.text()
    }
    throw new Error(detail || `请求失败（HTTP ${res.status}）`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const listScenes = () => scenesRequest<SceneInfo[]>('')
const createScene = (name: string, steps: string[]) =>
  scenesRequest<SceneInfo>('', { method: 'POST', body: JSON.stringify({ name, steps }) })
const toggleSceneApi = (id: number, enabled: boolean) =>
  scenesRequest<SceneInfo>(`/${id}`, { method: 'PUT', body: JSON.stringify({ enabled }) })
const deleteSceneApi = (id: number) => scenesRequest<void>(`/${id}`, { method: 'DELETE' })
const runSceneApi = (id: number) =>
  scenesRequest<SceneRunResult[]>(`/${id}/run`, { method: 'POST' })

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
  const [memories, setMemories] = useState<Memory[]>([])
  const [memoryError, setMemoryError] = useState('')
  const [deletingId, setDeletingId] = useState<number | null>(null)
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
  // 情境剧本：预置指令集，聊天里发「场景 名字」或本页「立即执行」一键顺序跑
  const [scenes, setScenes] = useState<SceneInfo[]>([])
  const [sceneError, setSceneError] = useState('')
  const [sceneName, setSceneName] = useState('')
  const [sceneStepsText, setSceneStepsText] = useState('')
  const [addingScene, setAddingScene] = useState(false)
  const [sceneBusyId, setSceneBusyId] = useState<number | null>(null)
  const [sceneToast, setSceneToast] = useState('')

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
    listMemories()
      .then(setMemories)
      .catch((reason: unknown) => setMemoryError(reason instanceof Error ? reason.message : String(reason)))
    listTasks().then(setTasks).catch((reason: unknown) => setTaskError(reason instanceof Error ? reason.message : String(reason)))
    listNotifications(false).then(setNotes)
    loadProposals()
    loadMcpServers()
    listScenes().then(setScenes).catch((reason: unknown) => setSceneError(reason instanceof Error ? reason.message : String(reason)))
  }, [])

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
  // ─── 情境剧本 ───────────────────────────────────────────────────
  const showSceneToast = (message: string) => {
    setSceneToast(message)
    window.setTimeout(() => setSceneToast(''), 3000)
  }
  const addScene = async () => {
    setAddingScene(true); setSceneError('')
    try {
      const steps = sceneStepsText.split('\n').map((line) => line.trim()).filter(Boolean)
      const created = await createScene(sceneName.trim(), steps)
      setScenes((previous) => [...previous, created])
      setSceneName(''); setSceneStepsText('')
      showSceneToast(`剧本「${created.name}」已保存（${created.step_count} 步）`)
    } catch (reason) {
      setSceneError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setAddingScene(false)
    }
  }
  const toggleSceneItem = async (item: SceneInfo) => {
    setSceneBusyId(item.id); setSceneError('')
    try {
      const updated = await toggleSceneApi(item.id, !item.enabled)
      setScenes((previous) => previous.map((it) => (it.id === item.id ? updated : it)))
    } catch (reason) {
      setSceneError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSceneBusyId(null)
    }
  }
  const removeSceneItem = async (item: SceneInfo) => {
    setSceneBusyId(item.id); setSceneError('')
    try {
      await deleteSceneApi(item.id)
      setScenes((previous) => previous.filter((it) => it.id !== item.id))
    } catch (reason) {
      setSceneError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSceneBusyId(null)
    }
  }
  const executeScene = async (item: SceneInfo) => {
    setSceneBusyId(item.id); setSceneError('')
    try {
      const results = await runSceneApi(item.id)
      const ok = results.filter((result) => result.success).length
      showSceneToast(`「${item.name}」执行完成：${ok}/${results.length} 步成功`)
    } catch (reason) {
      setSceneError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSceneBusyId(null)
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

        <LlmSection />

        <HotelSection />

        <VoiceSection />

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

        {/* 情境剧本：预置指令集，聊天里发「场景 名字」一键顺序执行 */}
        <section className="section-card">
          <HudCorners />
          <header className="module-head">
            <div>
              <p className="module-head__kicker">SCENES</p>
              <h2>情境剧本</h2>
            </div>
            <span className={`led ${scenes.some((s) => s.enabled) ? 'is-ready' : ''}`} aria-hidden="true" />
          </header>
          <p className="section-description">预置一串指令，在聊天里发「场景 名字」即可按顺序执行；单步失败不中断后续。</p>

          {sceneError && <p className="error-note" role="alert">{sceneError}</p>}
          {sceneToast && <p className="success-note">{sceneToast}</p>}
          {scenes.length === 0 ? (
            <p className="empty-copy">暂无情境剧本。在下方新建一个试试。</p>
          ) : (
            <ul className="memory-list">
              {scenes.map((item) => (
                <li className="memory-row" key={item.id}>
                  <div className="memory-row__copy">
                    <p>
                      <strong>{item.name}</strong>{' '}
                      <span className="ledger-hint">{item.step_count} 步</span>
                    </p>
                    <p>{item.steps[0]}{item.step_count > 1 ? ` …` : ''}</p>
                  </div>
                  <button
                    type="button"
                    className={`toggle-chip ${item.enabled ? 'is-on' : ''}`}
                    style={{ padding: '4px 10px' }}
                    disabled={sceneBusyId === item.id}
                    onClick={() => void toggleSceneItem(item)}
                  >
                    <span className="toggle-chip__state">{item.enabled ? 'ON' : 'OFF'}</span>
                  </button>
                  <button
                    type="button"
                    className="outline-button"
                    disabled={sceneBusyId === item.id}
                    onClick={() => void executeScene(item)}
                  >
                    立即执行
                  </button>
                  <button
                    type="button"
                    className="outline-button"
                    disabled={sceneBusyId === item.id}
                    onClick={() => void removeSceneItem(item)}
                  >
                    删除
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="ledger">
            <div className="ledger-field">
              <label htmlFor="scene-name">剧本名</label>
              <input
                id="scene-name"
                value={sceneName}
                onChange={(event) => setSceneName(event.target.value)}
                placeholder="出差 / 晨间准备 ..."
              />
            </div>
            <div className="ledger-field ledger-field--full">
              <label htmlFor="scene-steps">步骤（每行一条指令，最多 10 行）</label>
              <textarea
                id="scene-steps"
                rows={4}
                value={sceneStepsText}
                onChange={(event) => setSceneStepsText(event.target.value)}
                placeholder={'查一下今天的天气\n汇总今天的日程'}
              />
            </div>
          </div>
          <div className="save-bar">
            <button
              className="primary-button"
              disabled={addingScene || !sceneName.trim() || sceneStepsText.split('\n').filter((line) => line.trim()).length === 0}
              onClick={() => void addScene()}
            >
              {addingScene ? '保存中…' : '保存剧本'}
            </button>
          </div>
        </section>
      </div>
    </main>
  )
}
