import { useState } from 'react'
import { exportData, purgeData } from '../../api/privacy'
import HudCorners from '../../components/HudCorners'
import { downloadJson } from '../../lib/download'

// 数据主权：一键导出全部个人数据（单份 JSON）/ 确认式彻底清除（行数收据）
export default function PrivacySection() {
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [confirmText, setConfirmText] = useState('')
  const [purging, setPurging] = useState(false)
  const [purgeError, setPurgeError] = useState('')
  const [receipt, setReceipt] = useState<Record<string, number> | null>(null)

  const handleExport = async () => {
    setExporting(true); setExportError('')
    try {
      const data = await exportData()
      downloadJson(`oneflow-export-${new Date().toISOString().slice(0, 10)}.json`, data)
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setExporting(false)
    }
  }

  const handlePurge = async () => {
    setPurging(true); setPurgeError('')
    try {
      const result = await purgeData()
      setReceipt(result.receipt)
      setConfirmText('')
    } catch (reason) {
      setPurgeError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setPurging(false)
    }
  }

  return (
    <section className="section-card">
      <HudCorners />
      <header className="module-head">
        <div>
          <p className="module-head__kicker">DATA SOVEREIGNTY</p>
          <h2>数据主权</h2>
        </div>
        <span className="led" aria-hidden="true" />
      </header>
      <p className="section-description">你的数据属于你：随时打包带走，也随时彻底抹去。</p>

      {/* 导出 */}
      {exportError && <p className="error-note" role="alert">{exportError}</p>}
      <div className="save-bar" style={{ justifyContent: 'flex-start' }}>
        <button className="primary-button" disabled={exporting} onClick={() => void handleExport()}>
          {exporting ? '导出中…' : '导出全部数据（JSON）'}
        </button>
      </div>

      {/* 清除：双保险——显式输入 DELETE 才能触发真删 */}
      <div className="ledger">
        <div className="ledger-field ledger-field--full">
          <label htmlFor="purge-confirm">彻底清除全部数据</label>
          <p className="ledger-hint">
            按外键层级真删记忆/画像/会话/提案/任务等全部数据，<strong>不可恢复</strong>。
            在下方输入 <strong>DELETE</strong> 解除按钮锁定。
          </p>
          <input
            id="purge-confirm"
            value={confirmText}
            onChange={(event) => setConfirmText(event.target.value)}
            placeholder="输入 DELETE 以确认"
            autoComplete="off"
          />
        </div>
      </div>
      {purgeError && <p className="error-note" role="alert">{purgeError}</p>}
      <div className="save-bar">
        <button
          className="primary-button"
          disabled={purging || confirmText.trim() !== 'DELETE'}
          onClick={() => void handlePurge()}
        >
          {purging ? '清除中…' : '彻底清除我的全部数据'}
        </button>
      </div>

      {/* 清除收据 */}
      {receipt && (
        <>
          <p className="success-note">已彻底清除。各表删除行数：</p>
          <ul className="memory-list">
            {Object.entries(receipt).map(([table, rows]) => (
              <li className="memory-row" key={table}>
                <div className="memory-row__copy">
                  <p>{table}</p>
                </div>
                <span className="ledger-hint">{rows} 行</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
