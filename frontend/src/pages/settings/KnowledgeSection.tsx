import { useEffect, useRef, useState } from 'react'
import { deleteKnowledge, listKnowledge, uploadKnowledge, type KnowledgeDocOut } from '../../api/knowledge'
import HudCorners from '../../components/HudCorners'

// 状态徽章文案 / 配色
const STATUS_BADGES: Record<string, string> = { pending: '处理中', ready: '✅就绪', failed: '失败' }
const STATUS_CLASS: Record<string, string> = { ready: 'trace-success', failed: 'trace-failure', pending: 'ledger-hint' }

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// RAG 知识库：上传 txt/md/pdf → 后台切块 embedding → 贾维斯可用 search_knowledge 检索作答
export default function KnowledgeSection() {
  const [docs, setDocs] = useState<KnowledgeDocOut[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const load = () => {
    listKnowledge()
      .then(setDocs)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)))
  }

  useEffect(() => {
    load()
  }, [])

  // 存在处理中的文档时 4s 轮询刷新状态
  useEffect(() => {
    if (docs == null || !docs.some((doc) => doc.status === 'pending')) return
    const timer = window.setInterval(load, 4000)
    return () => window.clearInterval(timer)
  }, [docs])

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setBusy(true); setError('')
    try {
      for (const file of Array.from(files)) {
        await uploadKnowledge(file)
      }
      load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const remove = async (doc: KnowledgeDocOut) => {
    setError('')
    try {
      await deleteKnowledge(doc.id)
      setDocs((items) => (items ?? []).filter((item) => item.id !== doc.id))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  return (
    <section className="section-card">
      <HudCorners />
      <header className="module-head">
        <div>
          <p className="module-head__kicker">KNOWLEDGE BASE</p>
          <h2>知识库</h2>
        </div>
        <span className={`led ${docs != null && docs.length > 0 ? 'is-ready' : ''}`} aria-hidden="true" />
      </header>
      <p className="section-description">
        上传 txt / md / pdf（≤10MB），贾维斯切块后记住全部内容——提问涉及文档时自动检索引用。
      </p>

      {error && <p className="error-note" role="alert">{error}</p>}
      <div className="save-bar" style={{ justifyContent: 'flex-start' }}>
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.md,.pdf"
          multiple
          style={{ display: 'none' }}
          onChange={(event) => void handleFiles(event.target.files)}
        />
        <button className="primary-button" disabled={busy} onClick={() => fileInputRef.current?.click()}>
          {busy ? '上传中…' : '上传文档'}
        </button>
        <button className="outline-button" onClick={load}>刷新</button>
      </div>

      {docs === null ? (
        <p className="loading-state">加载中…</p>
      ) : docs.length === 0 ? (
        <p className="empty-copy">知识库还是空的。上传一份文档试试，比如项目笔记或说明书。</p>
      ) : (
        <ul className="memory-list">
          {docs.map((doc) => (
            <li className="memory-row" key={doc.id}>
              <div className="memory-row__copy">
                <p>
                  <strong>{doc.filename}</strong>{' '}
                  <span className={STATUS_CLASS[doc.status] ?? 'ledger-hint'}>
                    [{STATUS_BADGES[doc.status] ?? doc.status}]
                  </span>{' '}
                  <span className="ledger-hint">{formatSize(doc.size)} · {doc.chunk_count} 块</span>
                </p>
                {doc.status === 'failed' && doc.error && <p>{doc.error}</p>}
                {doc.created_at && <time>{new Date(doc.created_at).toLocaleString()}</time>}
              </div>
              <button className="outline-button" onClick={() => void remove(doc)}>删除</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
