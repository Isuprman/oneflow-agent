import { useEffect, useState } from 'react'
import { approveLearnProposal, listLearnProposals, rejectLearnProposal, type LearnProposalOut } from '../../api/learn'
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

// 技能工厂：自学习提案的状态总览 + 待审批提案的界面化审批（批准=merge+热注册）
export default function SkillsSection() {
  const [proposals, setProposals] = useState<LearnProposalOut[]>([])
  const [proposalsLoading, setProposalsLoading] = useState(true)
  const [proposalsError, setProposalsError] = useState('')
  const [keyDrafts, setKeyDrafts] = useState<Record<number, Record<string, string>>>({})
  const [busyId, setBusyId] = useState<number | null>(null)
  const [actionMessage, setActionMessage] = useState('')

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

  const setKeyDraft = (proposalId: number, keyName: string, value: string) => {
    setKeyDrafts((previous) => ({
      ...previous,
      [proposalId]: { ...(previous[proposalId] ?? {}), [keyName]: value },
    }))
  }

  const approve = async (proposal: LearnProposalOut) => {
    setBusyId(proposal.id); setProposalsError(''); setActionMessage('')
    try {
      const result = await approveLearnProposal(proposal.id, keyDrafts[proposal.id] ?? {})
      if (!result.ok) {
        const missing = Object.keys(result.missing_keys ?? {})
        setProposalsError(missing.length > 0 ? `还缺这些密钥：${missing.join('、')}——填好后再批准` : '批准未完成，请重试')
        return
      }
      setActionMessage(`✅ ${result.message ?? `技能 ${proposal.slug} 已上线`}${result.tool_name ? `（工具 ${result.tool_name}${result.live ? ' 已热注册生效' : ''}）` : ''}`)
      loadProposals()
    } catch (reason) {
      setProposalsError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyId(null)
    }
  }

  const reject = async (proposal: LearnProposalOut) => {
    setBusyId(proposal.id); setProposalsError(''); setActionMessage('')
    try {
      const result = await rejectLearnProposal(proposal.id)
      setActionMessage(result.message || `已放弃 ${proposal.slug}`)
      loadProposals()
    } catch (reason) {
      setProposalsError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyId(null)
    }
  }

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
      <p className="section-description">贾维斯自学技能的提案记录：待审批的直接在这里批准/放弃（聊天里回复「批准 编号」同样有效）。</p>

      <div className="save-bar" style={{ justifyContent: 'flex-start' }}>
        <button className="outline-button" disabled={proposalsLoading} onClick={loadProposals}>
          {proposalsLoading ? '刷新中…' : '刷新'}
        </button>
      </div>

      {actionMessage && <p className="success-note">{actionMessage}</p>}
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
                  <>
                    {Object.keys(proposal.required_keys ?? {}).length > 0 ? (
                      <div className="ledger" style={{ marginTop: 8 }}>
                        {Object.entries(proposal.required_keys).map(([keyName, desc]) => (
                          <div className="ledger-field" key={keyName}>
                            <label htmlFor={`skill-key-${proposal.id}-${keyName}`}>{keyName}（{desc}）</label>
                            <input
                              id={`skill-key-${proposal.id}-${keyName}`}
                              type="password"
                              value={keyDrafts[proposal.id]?.[keyName] ?? ''}
                              onChange={(event) => setKeyDraft(proposal.id, keyName, event.target.value)}
                              placeholder="填入密钥后批准"
                              autoComplete="off"
                            />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <small className="ledger-hint" style={{ display: 'block', marginTop: 4 }}>无需外部密钥，可直接批准</small>
                    )}
                    <div className="save-bar" style={{ justifyContent: 'flex-start', marginTop: 8 }}>
                      <button
                        className="primary-button"
                        disabled={busyId === proposal.id}
                        onClick={() => void approve(proposal)}
                      >
                        {busyId === proposal.id ? '处理中…' : '批准上线'}
                      </button>
                      <button
                        className="outline-button"
                        disabled={busyId === proposal.id}
                        onClick={() => void reject(proposal)}
                      >
                        放弃
                      </button>
                      <small className="ledger-hint">或在聊天里回复 批准 {proposal.id}</small>
                    </div>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
