import { AnimatePresence, motion } from 'framer-motion'
import type { ReactNode } from 'react'
import type { Conversation } from '../api/types'
import HudCorners from './HudCorners'

interface HoloTrayProps {
  open: boolean
  onToggle: () => void
  conversations: Conversation[]
  activeId: number | null
  onSelect: (id: number) => void
  onNew: () => void
}

function isToday(iso: string): boolean {
  const d = new Date(iso)
  const now = new Date()
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  )
}

/** 左侧可收起全息抽屉：默认只留「记录」竖 tab，展开后按 今日/更早 分组。 */
export default function HoloTray({
  open,
  onToggle,
  conversations,
  activeId,
  onSelect,
  onNew,
}: HoloTrayProps) {
  const today = conversations.filter((c) => isToday(c.created_at))
  const earlier = conversations.filter((c) => !isToday(c.created_at))

  const renderGroup = (label: string, list: Conversation[]): ReactNode => {
    if (list.length === 0) return null
    return (
      <div className="tray-group" key={label}>
        <span className="tray-group__label">{label}</span>
        {list.map((conversation) => (
          <button
            key={conversation.id}
            className={`tray-item ${conversation.id === activeId ? 'is-active' : ''}`}
            onClick={() => {
              if (conversation.id !== activeId) onSelect(conversation.id)
            }}
          >
            <span className="tray-item__title">{conversation.title ?? `对话 ${conversation.id}`}</span>
            <span className="tray-item__id">#{conversation.id}</span>
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="holo-tray">
      <button className="tray-tab" onClick={onToggle} aria-label="历史会话" aria-expanded={open}>
        <span className="tray-tab__mark" />
        记录
      </button>
      <AnimatePresence>
        {open && (
          <motion.aside
            className="tray-panel"
            initial={{ x: -340, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: -340, opacity: 0 }}
            transition={{ duration: 0.24, ease: 'easeOut' }}
          >
            <HudCorners />
            <span className="tray-scan" aria-hidden="true" />
            <div className="tray-head">
              <span className="tray-head__title">全息记录</span>
              <span className="tray-head__count">{conversations.length}</span>
            </div>
            <button className="tray-new" onClick={onNew}>
              ＋ 新建对话
            </button>
            <nav className="tray-list" aria-label="历史会话">
              {renderGroup('今日', today)}
              {renderGroup('更早', earlier)}
              {conversations.length === 0 && (
                <p className="tray-empty">
                  尚未建立会话。
                  <br />
                  开始新的协作。
                </p>
              )}
            </nav>
          </motion.aside>
        )}
      </AnimatePresence>
    </div>
  )
}
