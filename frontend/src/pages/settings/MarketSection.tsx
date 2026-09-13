import { useEffect, useState } from 'react'
import { exportSkill, installSkill, listMarketSkills, type MarketSkill } from '../../api/market'
import HudCorners from '../../components/HudCorners'
import { downloadJson } from '../../lib/download'
import { truncateText } from './shared'

// 技能市场：浏览/安装/导出所有用户已上线的技能；安装走既有门禁+沙箱重验后热上线
export default function MarketSection() {
  const [skills, setSkills] = useState<MarketSkill[] | null>(null)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    listMarketSkills()
      .then(setSkills)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)))
  }, [])

  const install = async (skill: MarketSkill) => {
    setBusyId(skill.id); setError(''); setMessage('')
    try {
      const result = await installSkill(skill.id)
      const missing = Object.keys(result.required_keys ?? {})
      setMessage(
        missing.length > 0
          ? `${result.message}。还需补齐 key：${missing.join('、')}（在聊天里回复 key 提案编号 名称=值）`
          : result.message,
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyId(null)
    }
  }

  const exportOne = async (skill: MarketSkill) => {
    setBusyId(skill.id); setError(''); setMessage('')
    try {
      const payload = await exportSkill(skill.id)
      downloadJson(`oneflow-skill-${skill.slug}.json`, payload)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="section-card">
      <HudCorners />
      <header className="module-head">
        <div>
          <p className="module-head__kicker">SKILL MARKET</p>
          <h2>技能市场</h2>
        </div>
        <span className={`led ${skills != null && skills.length > 0 ? 'is-ready' : ''}`} aria-hidden="true" />
      </header>
      <p className="section-description">
        所有用户已上线的技能都在这里：安装走同一套安全门禁 + 沙箱重验，「他会的」一键变成「你也会」。
      </p>

      {error && <p className="error-note" role="alert">{error}</p>}
      {message && <p className="success-note">{message}</p>}
      {skills === null ? (
        <p className="loading-state">加载中…</p>
      ) : skills.length === 0 ? (
        <p className="empty-copy">市场还是空的。先用技能工厂学会一个技能，它就会出现在这里供他人安装。</p>
      ) : (
        <ul className="memory-list">
          {skills.map((skill) => (
            <li className="memory-row" key={skill.id}>
              <div className="memory-row__copy">
                <p>
                  <strong>{skill.slug}</strong>{' '}
                  {skill.author && <span className="ledger-hint">作者：{skill.author}</span>}
                </p>
                {skill.description && <p>{truncateText(skill.description)}</p>}
              </div>
              <button
                type="button"
                className="outline-button"
                disabled={busyId === skill.id}
                onClick={() => void install(skill)}
              >
                {busyId === skill.id ? '处理中…' : '安装'}
              </button>
              <button
                type="button"
                className="outline-button"
                disabled={busyId === skill.id}
                onClick={() => void exportOne(skill)}
              >
                导出
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
