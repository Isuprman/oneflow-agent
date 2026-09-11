import { useState } from 'react'
import HudCorners from '../../components/HudCorners'

// 信任等级：贾维斯的自治程度（本机偏好；后端以 trust.level 设置为准，默认 standard）
type TrustLevel = 'ask_all' | 'standard' | 'auto'
const TRUST_STORAGE_KEY = 'oneflow_trust_level'
const TRUST_ITEMS: Array<{ value: TrustLevel; label: string; desc: string }> = [
  { value: 'ask_all', label: '每次询问', desc: '每个工具调用前都先征得同意，最稳妥' },
  { value: 'standard', label: '标准（默认）', desc: '仅写操作需要确认，学习提案始终要批准' },
  { value: 'auto', label: '自动执行', desc: '普通写操作直接执行；删除类高危与学习提案仍需确认' },
]

function getTrustLevel(): TrustLevel {
  try {
    const raw = localStorage.getItem(TRUST_STORAGE_KEY)
    if (raw === 'ask_all' || raw === 'auto') return raw
  } catch {
    // 忽略读取失败（如隐私模式），回退默认
  }
  return 'standard'
}

// 信任等级：三选一，选中即保存
export default function TrustSection() {
  const [trustLevel, setTrustLevel] = useState<TrustLevel>(getTrustLevel)

  const changeTrustLevel = (level: TrustLevel) => {
    setTrustLevel(level)
    try {
      localStorage.setItem(TRUST_STORAGE_KEY, level)
    } catch {
      // 忽略写入失败（如隐私模式）
    }
  }

  return (
    <section className="section-card">
      <HudCorners />
      <header className="module-head">
        <div>
          <p className="module-head__kicker">TRUST LEVEL</p>
          <h2>信任等级</h2>
        </div>
        <span className={`led ${trustLevel !== 'standard' ? 'is-ready' : ''}`} aria-hidden="true" />
      </header>
      <p className="section-description">决定贾维斯执行工具时的自治程度；学习提案的审批在任何等级下都不跳过。</p>

      <div className="ledger">
        <div className="ledger-field ledger-field--full">
          <span className="ledger-field__label">自治程度</span>
          <div className="chip-group" role="radiogroup" aria-label="信任等级">
            {TRUST_ITEMS.map((item) => (
              <button
                key={item.value}
                type="button"
                role="radio"
                aria-checked={trustLevel === item.value}
                className={`chip ${trustLevel === item.value ? 'is-active' : ''}`}
                onClick={() => changeTrustLevel(item.value)}
              >
                <span className="chip__dot" aria-hidden="true" />
                {item.label}
              </button>
            ))}
          </div>
          <p className="ledger-hint">{TRUST_ITEMS.find((item) => item.value === trustLevel)?.desc}</p>
        </div>
      </div>
    </section>
  )
}
