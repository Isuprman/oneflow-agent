// 自学习提案卡片 — 解析助手消息里的 [LEARN_PROPOSAL] 标记，提供批准/拒绝操作与历史状态回显
// 历史提案（跨会话）按持久化的 status 渲染终态文案，不再出现空白块
import { useState } from 'react'
import { approveLearnProposal, rejectLearnProposal } from '../api/client'

interface ProposalInfo {
  id: number
  slug: string
  title: string
  required_keys: Record<string, string>
  status: string
}

// 终态横幅文案 — approved 用 trace-success 高亮，failed 整块灰显
const TERMINAL_STATUS: Record<string, { text: string; success?: boolean; gray?: boolean }> = {
  approved: { text: '✅ 该技能已上线', success: true },
  rejected: { text: '已放弃' },
  failed: { text: '构建失败', gray: true },
}

function extractProposal(content: string): ProposalInfo | null {
  const match = content.match(/\[LEARN_PROPOSAL\]([\s\S]*?)\[\/LEARN_PROPOSAL\]/)
  if (!match) return null
  try {
    return JSON.parse(match[1]) as ProposalInfo
  } catch {
    return null
  }
}

export default function LearnProposalCard({ content }: { content: string }) {
  const info = extractProposal(content)
  const [status, setStatus] = useState(info ? info.status : 'pending')
  const [busyAction, setBusyAction] = useState<'' | 'approve' | 'reject'>('')
  const [missingKeys, setMissingKeys] = useState<Record<string, string> | null>(null)
  const [errorText, setErrorText] = useState('')
  const [keys, setKeys] = useState<Record<string, string>>({})

  if (!info) return null

  // 历史终态：只读横幅，带提案标识便于回溯
  if (status !== 'pending') {
    const banner = TERMINAL_STATUS[status]
    if (!banner) return null
    return (
      <div
        className="trace-block"
        style={banner.gray ? { opacity: 0.55, filter: 'grayscale(1)' } : undefined}
      >
        <div className="trace-step__head">
          <span>技能提案 #{info.id} · {info.slug}</span>
        </div>
        <p className={banner.success ? 'trace-success' : undefined} style={{ margin: '4px 0 0' }}>
          {banner.text}
        </p>
      </div>
    )
  }

  const needsKeys = Object.keys(info.required_keys || {})
  const busy = busyAction !== ''

  const onApprove = async () => {
    setBusyAction('approve')
    setErrorText('')
    try {
      const result = await approveLearnProposal(info.id, keys)
      if (result.ok) {
        setStatus('approved')
      } else if (result.missing_keys && Object.keys(result.missing_keys).length > 0) {
        setMissingKeys(result.missing_keys)
      } else {
        setErrorText(result.message || '批准失败，请重试')
      }
    } catch {
      setErrorText('网络错误，请重试')
    } finally {
      setBusyAction('')
    }
  }

  const onReject = async () => {
    setBusyAction('reject')
    setErrorText('')
    try {
      const result = await rejectLearnProposal(info.id)
      if (result.ok) setStatus('rejected')
      else setErrorText(result.message || '操作失败，请重试')
    } catch {
      setErrorText('网络错误，请重试')
    } finally {
      setBusyAction('')
    }
  }

  return (
    <div className="trace-block">
      <div className="trace-step__head">
        <span>新技能提案 #{info.id} · {info.slug}</span>
      </div>
      {needsKeys.map((name) => (
        <p key={name}>
          <input
            value={keys[name] ?? ''}
            onChange={(event) => setKeys((previous) => ({ ...previous, [name]: event.target.value }))}
            placeholder={`${name}（${info.required_keys[name]}）`}
            style={{ width: '100%' }}
          />
        </p>
      ))}
      <button className="trace-toggle" onClick={onApprove} disabled={busy}>
        {busyAction === 'approve' ? '⏳ 上线中…' : '✔ 合并上线'}
      </button>{' '}
      <button className="trace-toggle" onClick={onReject} disabled={busy}>
        {busyAction === 'reject' ? '放弃中…' : '✖ 放弃'}
      </button>
      {missingKeys && (
        <div style={{ marginTop: 6 }}>
          <p>还缺密钥：</p>
          {Object.entries(missingKeys).map(([name, description]) => (
            <p key={name}>· {description ? `${name}（${description}）` : name}</p>
          ))}
          <p>在聊天里发「key {info.id} 名称=密钥」补填后重试</p>
        </div>
      )}
      {errorText && (
        <p className="trace-failure" style={{ margin: '6px 0 0' }}>⚠️ {errorText}</p>
      )}
    </div>
  )
}
