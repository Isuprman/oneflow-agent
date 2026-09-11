import { useEffect, useState } from 'react'
import { addMcpServer, deleteMcpServer, listMcpServers, refreshMcpServer, toggleMcpServer, type McpServerOut } from '../../api/mcp'
import HudCorners from '../../components/HudCorners'
import { truncateText } from './shared'

// MCP 状态徽章文案
const MCP_STATUS_LABELS: Record<string, string> = {
  connected: '已连接',
  error: '连接失败',
  off: '未连接',
}

// MCP 服务：外部工具生态接入（连接成功后工具自动并入贾维斯能力清单）
export default function McpSection() {
  const [mcpServers, setMcpServers] = useState<McpServerOut[]>([])
  const [mcpError, setMcpError] = useState('')
  const [mcpName, setMcpName] = useState('')
  const [mcpCommand, setMcpCommand] = useState('')
  const [mcpUrl, setMcpUrl] = useState('')
  const [addingMcp, setAddingMcp] = useState(false)
  const [mcpBusyId, setMcpBusyId] = useState<number | null>(null)

  useEffect(() => {
    listMcpServers()
      .then(setMcpServers)
      .catch((reason: unknown) => setMcpError(reason instanceof Error ? reason.message : String(reason)))
  }, [])

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

  return (
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
  )
}
