import { useEffect, useState } from 'react'
import { deleteMemory, listMemories } from '../../api/memories'
import type { Memory } from '../../api/types'
import HudCorners from '../../components/HudCorners'
import { formatTime } from './shared'

// 长期记忆：Agent 保留的长期信息，可逐条删除
export default function MemoriesSection() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [memoryError, setMemoryError] = useState('')
  const [deletingId, setDeletingId] = useState<number | null>(null)

  useEffect(() => {
    listMemories()
      .then(setMemories)
      .catch((reason: unknown) => setMemoryError(reason instanceof Error ? reason.message : String(reason)))
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

  return (
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
  )
}
