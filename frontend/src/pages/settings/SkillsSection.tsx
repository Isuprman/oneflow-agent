import { useEffect, useState } from 'react'
import { listLearnProposals, type LearnProposalOut } from '../../api/learn'
import HudCorners from '../../components/HudCorners'
import { formatTime, truncateText } from './shared'

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

// 技能工厂：自学习提案的状态总览（审批动作在聊天页的提案卡片完成）
export default function SkillsSection() {
  const [proposals, setProposals] = useState<LearnProposalOut[]>([])
  const [proposalsLoading, setProposalsLoading] = useState(true)
  const [proposalsError, setProposalsError] = useState('')

  const loadProposals = () => {
    setProposalsLoading(true); setProposalsError('')
    listLearnProposals()
      .then(setProposals)
      .catch((reason: unknown) => setProposalsError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setProposalsLoading(false))
  }

  useEffect(() => {
    loadProposals()
  }, [])

  return (
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
  )
}
