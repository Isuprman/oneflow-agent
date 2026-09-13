import { useEffect, useState } from 'react'
import { listPlans, setPlanStatus, type PlanOut } from '../../api/plans'
import HudCorners from '../../components/HudCorners'

const STATUS_BADGES: Record<string, string> = {
  active: '进行中',
  paused: '已暂停',
  done: '✅已完成',
  cancelled: '已放弃',
}
const STATUS_CLASS: Record<string, string> = {
  done: 'trace-success',
  cancelled: 'ledger-hint',
  paused: 'ledger-hint',
  active: '',
}

// 长程计划：跨会话大目标的进度总览；推进在对话/每日自动进行，这里可暂停/恢复/放弃
export default function PlansSection() {
  const [plans, setPlans] = useState<PlanOut[] | null>(null)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)

  const load = () => {
    listPlans()
      .then(setPlans)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)))
  }

  useEffect(() => {
    load()
  }, [])

  const changeStatus = async (plan: PlanOut, status: PlanOut['status']) => {
    setBusyId(plan.id); setError('')
    try {
      const updated = await setPlanStatus(plan.id, status)
      setPlans((items) => (items ?? []).map((item) => (item.id === plan.id ? updated : item)))
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
          <p className="module-head__kicker">LONG-TERM PLANS</p>
          <h2>长程计划</h2>
        </div>
        <span className={`led ${plans != null && plans.some((p) => p.status === 'active') ? 'is-ready' : ''}`} aria-hidden="true" />
      </header>
      <p className="section-description">
        跨会话的大目标：贾维斯每天自动推进一步并汇报；对它说「继续」也能手动推进。
      </p>

      {error && <p className="error-note" role="alert">{error}</p>}
      {plans === null ? (
        <p className="loading-state">加载中…</p>
      ) : plans.length === 0 ? (
        <p className="empty-copy">暂无计划。对贾维斯说“帮我规划准备 11 月的考试”，它会拆好步骤每天推进。</p>
      ) : (
        <ul className="memory-list">
          {plans.map((plan) => {
            const done = plan.steps.filter((s) => s.status === 'done').length
            const next = plan.steps.find((s) => s.status === 'todo' || s.status === 'doing')
            const recent = [...plan.steps].reverse().find((s) => s.status === 'done' && s.note)
            return (
              <li className="memory-row" key={plan.id}>
                <div className="memory-row__copy">
                  <p>
                    <strong>{plan.title}</strong>{' '}
                    <span className={STATUS_CLASS[plan.status] ?? 'trace-success'}>
                      [{STATUS_BADGES[plan.status] ?? plan.status}]
                    </span>{' '}
                    <span className="ledger-hint">{done}/{plan.steps.length} 步</span>
                  </p>
                  {next && plan.status === 'active' && <p>下一步：{next.description}</p>}
                  {recent?.note && <p>最近进展：{recent.note}</p>}
                </div>
                {plan.status === 'active' && (
                  <button
                    className="outline-button"
                    disabled={busyId === plan.id}
                    onClick={() => void changeStatus(plan, 'paused')}
                  >
                    暂停
                  </button>
                )}
                {plan.status === 'paused' && (
                  <button
                    className="outline-button"
                    disabled={busyId === plan.id}
                    onClick={() => void changeStatus(plan, 'active')}
                  >
                    恢复
                  </button>
                )}
                {(plan.status === 'active' || plan.status === 'paused') && (
                  <button
                    className="outline-button"
                    disabled={busyId === plan.id}
                    onClick={() => void changeStatus(plan, 'cancelled')}
                  >
                    放弃
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
