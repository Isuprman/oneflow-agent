import { useEffect, useState } from 'react'
import { deleteNotification, listNotifications } from '../../api/notifications'
import type { AppNotification } from '../../api/types'
import HudCorners from '../../components/HudCorners'
import { formatTime } from './shared'

// 通知类型 → 中文标签
const NOTE_KIND_LABELS: Record<string, string> = {
  task: '定时播报',
  reminder: '日程提醒',
  care: '情景关怀',
  habit: '习惯洞察',
  system_error: '系统自检',
}

// 通知中心：贾维斯主动播报过的历史都可回看
export default function NotificationsSection() {
  const [notes, setNotes] = useState<AppNotification[]>([])

  useEffect(() => {
    listNotifications(false).then(setNotes)
  }, [])

  const removeNote = async (id: number) => {
    await deleteNotification(id)
    setNotes((previous) => previous.filter((item) => item.id !== id))
  }
  const clearNotes = async () => {
    for (const note of notes) await deleteNotification(note.id)
    setNotes([])
  }

  return (
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
  )
}
