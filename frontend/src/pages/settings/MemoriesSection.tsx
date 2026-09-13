import { useEffect, useState } from 'react'
import { deleteMemory, listMemories, updateMemory } from '../../api/memories'
import type { Memory } from '../../api/types'
import HudCorners from '../../components/HudCorners'
import { formatTime } from './shared'

// 长期记忆：Agent 保留的长期信息，可逐条编辑/删除（保存后后端自动重嵌向量）
export default function MemoriesSection() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [memoryError, setMemoryError] = useState('')
  const [deletingId, setDeletingId] = useState<number | null>(null)
  // 行内编辑：editingId 非空表示该条处于编辑态，draft 为编辑框内容
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [savingId, setSavingId] = useState<number | null>(null)

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

  const startEdit = (memory: Memory) => {
    setEditingId(memory.id); setDraft(memory.content); setMemoryError('')
  }

  const saveEdit = async (id: number) => {
    const content = draft.trim()
    if (!content) { setMemoryError('记忆内容不能为空'); return }
    setSavingId(id); setMemoryError('')
    try {
      await updateMemory(id, content)
      setMemories((items) => items.map((item) => (item.id === id ? { ...item, content } : item)))
      setEditingId(null)
    } catch (reason) {
      setMemoryError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSavingId(null)
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
      <p className="section-description">Agent 会保留你透露的长期信息，供后续对话引用；记错了可直接改。</p>

      {memoryError && <p className="error-note" role="alert">{memoryError}</p>}
      {memories.length === 0 ? (
        <p className="empty-copy">暂无长期记忆。</p>
      ) : (
        <ul className="memory-list">
          {memories.map((memory) => (
            <li className="memory-row" key={memory.id}>
              <div className="memory-row__copy">
                {editingId === memory.id ? (
                  <>
                    <textarea
                      aria-label="编辑记忆"
                      value={draft}
                      rows={3}
                      onChange={(event) => setDraft(event.target.value)}
                    />
                    <div className="save-bar" style={{ justifyContent: 'flex-start', marginTop: 6 }}>
                      <button className="primary-button" disabled={savingId === memory.id} onClick={() => void saveEdit(memory.id)}>
                        {savingId === memory.id ? '保存中…' : '保存'}
                      </button>
                      <button className="outline-button" disabled={savingId === memory.id} onClick={() => setEditingId(null)}>
                        取消
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <p>{memory.content}</p>
                    <time>{formatTime(memory.created_at)}</time>
                  </>
                )}
              </div>
              {editingId !== memory.id && (
                <button className="outline-button" onClick={() => startEdit(memory)}>编辑</button>
              )}
              <button
                className="outline-button"
                disabled={deletingId === memory.id || savingId === memory.id}
                onClick={() => void deleteOneMemory(memory.id)}
              >
                {deletingId === memory.id ? '删除中…' : '删除'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
