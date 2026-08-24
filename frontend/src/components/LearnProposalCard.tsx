// 自学习提案卡片 — 解析助手消息里的 [LEARN_PROPOSAL] 标记，提供批准/拒绝操作
import { useState } from 'react'
import { approveLearnProposal, rejectLearnProposal } from '../api/client'

interface ProposalInfo {
  id: number
  slug: string
  title: string
  required_keys: Record<string, string>
  status: string
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
  const [done, setDone] = useState('')
  const [busy, setBusy] = useState(false)
  const [keys, setKeys] = useState<Record<string, string>>({})

  if (!info || info.status !== 'pending' || done) {
    if (!info) return null
    return done ? <div className="trace-block">🛠 {done}</div> : null
  }

  const needsKeys = Object.keys(info.required_keys || {})

  const onApprove = async () => {
    setBusy(true)
    try {
      const result = await approveLearnProposal(info.id, keys)
      if (result.ok) setDone(`已上线（${result.tool_name ?? info.slug}），贾维斯现在就能用它`)
      else if (result.missing_keys) setDone(`还缺密钥：${Object.keys(result.missing_keys).join('、')} —— 在聊天里发「key ${info.id} 名称=密钥」补填`)
      else setDone('批准失败，请重试')
    } catch {
      setDone('网络错误，请重试')
    } finally {
      setBusy(false)
    }
  }

  const onReject = async () => {
    setBusy(true)
    try {
      await rejectLearnProposal(info.id)
      setDone('已放弃，现场已清理')
    } catch {
      setDone('网络错误，请重试')
    } finally {
      setBusy(false)
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
      <button className="trace-toggle" onClick={onApprove} disabled={busy}>✔ 合并上线</button>{' '}
      <button className="trace-toggle" onClick={onReject} disabled={busy}>✖ 放弃</button>
    </div>
  )
}
