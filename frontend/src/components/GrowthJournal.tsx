// GrowthJournal — 成长档案页（/journal）：顶部统计条 + 成长时间线
//
// 数据：GET /api/journal（JWT 取自 localStorage.oneflow_token，里程碑按时间升序，
// 最早一条即「第一个技能」）。视觉沿用作战中心体系：#0F1420 深空底、电光蓝点缀、
// 玻璃发丝卡；复用全局 section-card / settings-header 骨架，本文件只补充 gj- 前缀样式。
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { MotionConfig, motion, useSpring, useTransform } from 'framer-motion'
import axios from 'axios'
import HudCorners from './HudCorners'
import ParticleField from './ParticleField'

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

/** 数字滚动：弹簧从当前值滚到目标值（数据到位后触发一次）。 */
function RollingNumber({ value }: { value: number }) {
  const spring = useSpring(0, { stiffness: 46, damping: 15 })
  useEffect(() => {
    spring.set(value)
  }, [spring, value])
  const text = useTransform(spring, (latest) => Math.round(latest).toLocaleString())
  return <motion.span>{text}</motion.span>
}

const GJ_STYLES = `
  .gj-stats { position: relative; z-index: 1; display: flex; align-items: stretch; gap: clamp(22px, 6vw, 60px); }
  .gj-stat { display: grid; gap: 3px; justify-items: start; min-width: 0; }
  .gj-stat__value { color: #f0f9ff; font-size: clamp(30px, 4.5vw, 38px); font-weight: 600; line-height: 1.12; letter-spacing: .02em; font-variant-numeric: tabular-nums; text-shadow: 0 0 26px rgba(56,189,248,.32); }
  .gj-stat__label { color: #b5d0dc; font-size: 13px; letter-spacing: .05em; }
  .gj-stat__kicker { color: #5d7b8d; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10px; font-weight: 700; letter-spacing: .2em; }
  .gj-divider { width: 1px; background: linear-gradient(180deg, transparent, rgba(125,211,252,.35), transparent); }

  .gj-timeline { position: relative; z-index: 1; display: grid; gap: 14px; list-style: none; margin: 6px 0 0; padding: 0; }
  .gj-item { display: grid; grid-template-columns: 92px 22px minmax(0, 1fr); align-items: stretch; }
  @media (max-width: 560px) { .gj-item { grid-template-columns: 74px 18px minmax(0, 1fr); } }
  .gj-item__date { padding-top: 15px; color: #7ca0b4; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; letter-spacing: .08em; text-align: right; white-space: nowrap; }
  .gj-axis { position: relative; }
  .gj-axis::before { content: ""; position: absolute; top: 0; bottom: -14px; left: 50%; width: 1px; transform: translateX(-.5px); background: rgba(125,211,252,.16); }
  /* 末个节点即最新里程碑：轴线到圆点为止 */
  .gj-item:last-child .gj-axis::before { bottom: auto; height: 19px; }
  .gj-dot { position: absolute; top: 19px; left: 50%; width: 9px; height: 9px; transform: translate(-50%, -50%); border-radius: 50%; background: #38bdf8; box-shadow: 0 0 10px rgba(56,189,248,.75); }
  .gj-dot--latest::after { content: ""; position: absolute; inset: -5px; border-radius: 50%; border: 1px solid rgba(56,189,248,.55); animation: gj-ping 2.2s ease-out infinite; }
  @keyframes gj-ping { 0% { transform: scale(.55); opacity: .9; } 70%, 100% { transform: scale(1.75); opacity: 0; } }

  .gj-card { display: flex; align-items: baseline; gap: 12px; margin-bottom: 3px; padding: 13px 16px; border: 1px solid rgba(125,211,252,.12); border-radius: 8px; background: rgba(56,189,248,.045); box-shadow: inset 0 0 22px rgba(56,189,248,.03); transition: border-color 160ms ease-out; }
  .gj-card:hover { border-color: rgba(56,189,248,.35); }
  .gj-card__index { flex: none; color: #5d7b8d; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10px; letter-spacing: .18em; }
  .gj-card__title { margin: 0; min-width: 0; color: #eaf1ff; font-size: 14.5px; line-height: 1.55; overflow-wrap: anywhere; }
  .gj-tag { flex: none; padding: 2px 9px; border: 1px solid rgba(56,189,248,.4); border-radius: 999px; color: #7dd3fc; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10px; letter-spacing: .14em; white-space: nowrap; }

  .gj-empty { align-items: center; justify-items: center; gap: 4px; text-align: center; padding: 46px 24px 42px; }
  .gj-rings { width: 116px; height: 116px; }
  .gj-ring-slow, .gj-ring-fast { transform-origin: 60px 60px; }
  .gj-ring-slow { animation: gj-spin 46s linear infinite; }
  .gj-ring-fast { animation: gj-spin-rev 30s linear infinite; }
  @keyframes gj-spin { to { transform: rotate(360deg); } }
  @keyframes gj-spin-rev { to { transform: rotate(-360deg); } }
  .gj-empty__copy { margin: 20px 0 0; color: #dbeef7; font-size: 15px; line-height: 1.85; }
  .gj-empty__cta { display: inline-flex; align-items: center; margin-top: 18px; min-height: 42px; padding: 0 22px; text-decoration: none; }
  .gj-empty__hint { margin: 13px 0 0; color: #597386; font-size: 12.5px; line-height: 1.7; }
`

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
    <MotionConfig reducedMotion="user">
      <main className="settings-page">
        <ParticleField />
        <style>{GJ_STYLES}</style>
        <div className="settings-wrap">
          <header className="settings-header">
            <div>
              <p className="section-kicker">GROWTH ARCHIVE</p>
              <h1>贾维斯的成长日记</h1>
            </div>
            <Link className="back-link" to="/">
              返回聊天
            </Link>
          </header>

          {/* 统计条：单条玻璃横带两项，中间发丝分隔（不做同质卡片阵列） */}
          <motion.section
            className="section-card gj-stats"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.32, ease: 'easeOut' }}
          >
            <HudCorners />
            <div className="gj-stat">
              <span className="gj-stat__value">
                {data ? <RollingNumber value={data.learned_count} /> : '—'}
              </span>
              <span className="gj-stat__label">学会技能数</span>
              <span className="gj-stat__kicker">SKILLS MASTERED</span>
            </div>
            <span className="gj-divider" aria-hidden="true" />
            <div className="gj-stat">
              <span className="gj-stat__value">
                {data ? <RollingNumber value={data.total_tool_calls} /> : '—'}
              </span>
              <span className="gj-stat__label">累计调用次数</span>
              <span className="gj-stat__kicker">TOOL INVOCATIONS</span>
            </div>
          </motion.section>

          {!errorText && !data && (
            <section className="section-card">
              <HudCorners />
              <p className="loading-state">正在读取成长记录…</p>
            </section>
          )}

          {errorText && (
            <section className="section-card">
              <HudCorners />
              <p className="error-note" role="alert">{errorText}</p>
            </section>
          )}

          {!errorText && data && empty && (
            <motion.section
              className="section-card gj-empty"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.34, delay: 0.08, ease: 'easeOut' }}
            >
              <HudCorners />
              {/* 空态插画：待机核心线稿——虚线环缓转，中心菱形待点亮 */}
              <svg className="gj-rings" viewBox="0 0 120 120" aria-hidden="true">
                <circle className="gj-ring-slow" cx="60" cy="60" r="54" fill="none" stroke="rgba(56,189,248,.16)" strokeWidth="1" strokeDasharray="4 9" />
                <circle className="gj-ring-fast" cx="60" cy="60" r="38" fill="none" stroke="rgba(56,189,248,.26)" strokeWidth="1" strokeDasharray="2 7" />
                <rect x="53.5" y="53.5" width="13" height="13" fill="rgba(56,189,248,.06)" stroke="#38bdf8" strokeWidth="1.2" transform="rotate(45 60 60)" />
              </svg>
              <p className="gj-empty__copy">
                贾维斯的成长日记还是空白
                <br />
                ——去教会它第一个技能吧
              </p>
              <Link className="primary-button gj-empty__cta" to="/">
                去聊天教学
              </Link>
              <p className="gj-empty__hint">在聊天里对它说「你要是能……就好了」，它就会自己学。</p>
            </motion.section>
          )}

          {!errorText && data && !empty && (
            <section className="section-card">
              <HudCorners />
              <header className="module-head">
                <div>
                  <p className="module-head__kicker">TIMELINE</p>
                  <h2>成长时间线</h2>
                </div>
                <span className="led is-ready" aria-hidden="true" />
              </header>

              <ol className="gj-timeline">
                {data.milestones.map((m, i) => (
                  <motion.li
                    key={`${m.title}-${i}`}
                    className="gj-item"
                    initial={{ opacity: 0, x: -14, filter: 'blur(4px)' }}
                    animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
                    transition={{ duration: 0.34, delay: Math.min(i * 0.07, 0.5), ease: 'easeOut' }}
                  >
                    <time className="gj-item__date">{formatDate(m.date)}</time>
                    <span className="gj-axis" aria-hidden="true">
                      <span className={`gj-dot${i === data.milestones.length - 1 ? ' gj-dot--latest' : ''}`} />
                    </span>
                    <div className="gj-card">
                      <span className="gj-card__index">{String(i + 1).padStart(2, '0')}</span>
                      <p className="gj-card__title">{m.title}</p>
                      {i === 0 && <span className="gj-tag">第一个技能</span>}
                    </div>
                  </motion.li>
                ))}
              </ol>
            </section>
          )}
        </div>
      </main>
    </MotionConfig>
  )
}
