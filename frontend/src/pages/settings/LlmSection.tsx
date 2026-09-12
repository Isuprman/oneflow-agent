import { useEffect, useState } from 'react'
import { getLlmConfig, saveLlmConfig } from '../../api/settings'
import type { LlmConfig } from '../../api/types'
import HudCorners from '../../components/HudCorners'
import { DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL, DEFAULT_LLM_PROVIDER, LLM_PROVIDERS } from '../../theme/llmModels'

// LLM 配置：连接模型提供商，设定当前终端的推理引擎
export default function LlmSection() {
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null)
  const [provider, setProvider] = useState(DEFAULT_LLM_PROVIDER)
  const [model, setModel] = useState(DEFAULT_LLM_MODEL)
  const [apiKey, setApiKey] = useState('')
  const [llmBaseUrl, setLlmBaseUrl] = useState(DEFAULT_LLM_BASE_URL)
  const [savingLlm, setSavingLlm] = useState(false)
  const [llmMessage, setLlmMessage] = useState('')
  const [llmError, setLlmError] = useState('')

  useEffect(() => {
    getLlmConfig()
      .then((config) => {
        setLlmConfig(config)
        const savedProvider = config.provider || DEFAULT_LLM_PROVIDER
        setProvider(savedProvider)
        setModel(config.model || LLM_PROVIDERS[savedProvider]?.models[0] || DEFAULT_LLM_MODEL)
        setLlmBaseUrl(config.base_url || LLM_PROVIDERS[savedProvider]?.defaultBaseUrl || '')
      })
      .catch((reason: unknown) => setLlmError(reason instanceof Error ? reason.message : String(reason)))
  }, [])

  const selectProvider = (next: string) => {
    if (next === provider) return
    const target = LLM_PROVIDERS[next]
    setProvider(next)
    // 模型：优先沿用当前模型（若属于该提供商），否则取该提供商第一个内置模型
    setModel(target?.models.includes(model) ? model : (target?.models[0] ?? DEFAULT_LLM_MODEL))
    // Base URL：自动带出默认值；无默认则留空让用户填
    setLlmBaseUrl(target?.defaultBaseUrl ?? '')
  }

  const saveLlm = async () => {
    setSavingLlm(true); setLlmMessage(''); setLlmError('')
    try {
      const config = await saveLlmConfig({ provider, model: model.trim(), api_key: apiKey, base_url: llmBaseUrl.trim() })
      setLlmConfig(config); setApiKey(''); setLlmMessage(`已保存：${config.provider}/${config.model}`)
    } catch (reason) {
      setLlmError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSavingLlm(false)
    }
  }

  return (
    <section className="section-card">
      <HudCorners />
      <header className="module-head">
        <div>
          <p className="module-head__kicker">LLM CONFIGURATION</p>
          <h2>LLM 配置</h2>
        </div>
        <span className={`led ${llmConfig?.configured ? 'is-ready' : ''}`} aria-hidden="true" />
      </header>
      <p className="section-description">连接模型提供商，设定当前终端的推理引擎。</p>

      <div className="ledger">
        <div className="ledger-field ledger-field--full">
          <span className="ledger-field__label">提供商</span>
          <div className="chip-group">
            {Object.entries(LLM_PROVIDERS).map(([key, item]) => (
              <button
                key={key}
                type="button"
                className={`chip ${provider === key ? 'is-active' : ''}`}
                onClick={() => selectProvider(key)}
              >
                <span className="chip__dot" aria-hidden="true" />
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="ledger-field">
          <label htmlFor="model">模型</label>
          <input id="model" list="llm-model-options" value={model} onChange={(event) => setModel(event.target.value)} placeholder="deepseek-v4-flash / gpt-5.6-sol" />
          <datalist id="llm-model-options">
            {LLM_PROVIDERS[provider]?.models.map((item) => <option key={item} value={item} />)}
          </datalist>
        </div>

        <div className="ledger-field">
          <label htmlFor="llm-key">API 密钥</label>
          <input id="llm-key" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-..." />
          {llmConfig?.api_key_set && <small className="ledger-hint">已设置，留空表示不修改</small>}
        </div>

        <div className="ledger-field ledger-field--full">
          <label>Base URL（系统按供应商自动配置）</label>
          <p className="ledger-hint">{llmBaseUrl ? `自动使用：${llmBaseUrl}` : '无需填写，系统自动选择端点'}</p>
        </div>
      </div>

      <p className={`status-line ${llmConfig?.configured ? 'is-ready' : ''}`}>
        {llmConfig?.configured ? `已连接：${llmConfig.provider}/${llmConfig.model}` : '尚未配置'}
      </p>
      {llmMessage && <p className="success-note">{llmMessage}</p>}
      {llmError && <p className="error-note" role="alert">{llmError}</p>}
      <div className="save-bar">
        <button className="primary-button" disabled={savingLlm} onClick={() => void saveLlm()}>
          {savingLlm ? '保存中…' : '保存 LLM 配置'}
        </button>
      </div>
    </section>
  )
}
