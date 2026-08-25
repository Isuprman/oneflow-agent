// GrowthJournal — 贾维斯的成长日记（时间线组件）
//
// 用法：组件自带数据拉取（GET /api/journal，JWT 取自 localStorage.oneflow_token），
// 未接入路由菜单，后续在任意页面直接嵌入：
//   import GrowthJournal from '../components/GrowthJournal'
//   <GrowthJournal />
import { useEffect, useState } from 'react'
import axios from 'axios'

interface Milestone {
  date: string | null
  title: string
}

interface JournalData {
  first_skill: Milestone | null
  learned_count: number
  rejected_count: number
  milestones: Milestone[]
  total_tool_calls: number
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export default function GrowthJournal() {
  const [data, setData] = useState<JournalData | null>(null)
  const [errorText, setErrorText] = useState('')

  useEffect(() => {
    let cancelled = false
    const token = localStorage.getItem('oneflow_token')
    axios
      .get<JournalData>('/api/journal', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      .then((resp) => {
        if (!cancelled) setData(resp.data)
      })
      .catch(() => {
        if (!cancelled) setErrorText('成长档案加载失败，请重试')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const empty = data !== null && data.milestones.length === 0

  return (
    <div className="gj-root">
      <style>{`
        .gj-root { background: #0F1420; color: #C9D4E8; border-radius: 14px; padding: 20px; font-size: 14px; }
        .gj-stats { display: flex; gap: 12px; margin-bottom: 18px; }
        .gj-stat-card { flex: 1; background: #161D2E; border: 1px solid #232D44; border-radius: 10px; padding: 14px 16px; }
        .gj-stat-value { font-size: 26px; font-weight: 600; color: #EAF1FF; line-height: 1.2; }
        .gj-stat-label { margin-top: 4px; font-size: 12px; color: #7C89A6; }
        .gj-timeline { list-style: none; margin: 0; padding: 0; }
        .gj-item { position: relative; padding: 0 0 16px 22px; border-left: 1px solid #232D44; }
        .gj-item:last-child { border-left-color: transparent; padding-bottom: 0; }
        .gj-dot { position: absolute; left: -5px; top: 3px; width: 9px; height: 9px; border-radius: 50%; background: #4F8CFF; box-shadow: 0 0 6px rgba(79,140,255,.7); }
        .gj-item-title { color: #EAF1FF; }
        .gj-item-date { margin-top: 2px; font-size: 12px; color: #7C89A6; }
        .gj-empty { text-align: center; padding: 28px 12px; color: #7C89A6; }
        .gj-error { margin-top: 10px; color: #FF8A8A; font-size: 12px; }
      `}</style>

      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 600, color: '#EAF1FF' }}>
        贾维斯的成长日记
      </h3>

      <div className="gj-stats">
        <div className="gj-stat-card">
          <div className="gj-stat-value">{data ? data.learned_count : '—'}</div>
          <div className="gj-stat-label">学会 N 个技能</div>
        </div>
        <div className="gj-stat-card">
          <div className="gj-stat-value">{data ? data.total_tool_calls : '—'}</div>
          <div className="gj-stat-label">累计调用 N 次</div>
        </div>
      </div>

      {errorText && <p className="gj-error">{errorText}</p>}

      {empty ? (
        <p className="gj-empty">贾维斯还没学会第一个技能，去聊天里说『你要是能…』吧</p>
      ) : (
        <ol className="gj-timeline">
          {(data?.milestones ?? []).map((m, i) => (
            <li key={i} className="gj-item">
              <span className="gj-dot" />
              <div className="gj-item-title">{m.title}</div>
              <div className="gj-item-date">{formatDate(m.date)}</div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
