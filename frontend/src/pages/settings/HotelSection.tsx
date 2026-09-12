import { useEffect, useState } from 'react'
import { getHotelConfig, saveHotelConfig } from '../../api/settings'
import type { HotelConfig } from '../../api/types'
import HudCorners from '../../components/HudCorners'

// 酒店配置：设定酒店服务的连接地址与访问密钥
export default function HotelSection() {
  const [hotelConfig, setHotelConfig] = useState<HotelConfig | null>(null)
  const [hotelBaseUrl, setHotelBaseUrl] = useState('')
  const [hotelApiKey, setHotelApiKey] = useState('')
  const [savingHotel, setSavingHotel] = useState(false)
  const [hotelMessage, setHotelMessage] = useState('')
  const [hotelError, setHotelError] = useState('')

  useEffect(() => {
    getHotelConfig()
      .then((config) => { setHotelConfig(config); setHotelBaseUrl(config.base_url) })
      .catch((reason: unknown) => setHotelError(reason instanceof Error ? reason.message : String(reason)))
  }, [])

  const saveHotel = async () => {
    setSavingHotel(true); setHotelMessage(''); setHotelError('')
    try {
      const config = await saveHotelConfig({ base_url: hotelBaseUrl.trim(), api_key: hotelApiKey })
      setHotelConfig(config); setHotelApiKey(''); setHotelMessage('酒店配置已保存')
    } catch (reason) {
      setHotelError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSavingHotel(false)
    }
  }

  return (
    <section className="section-card">
      <HudCorners />
      <header className="module-head">
        <div>
          <p className="module-head__kicker">HOTEL CONFIGURATION</p>
          <h2>酒店配置</h2>
        </div>
        <span className={`led ${hotelConfig?.configured ? 'is-ready' : ''}`} aria-hidden="true" />
      </header>
      <p className="section-description">设定酒店服务的连接地址与访问密钥。</p>

      <div className="ledger">
        <div className="ledger-field">
          <label htmlFor="hotel-url">Base URL</label>
          <input id="hotel-url" value={hotelBaseUrl} onChange={(event) => setHotelBaseUrl(event.target.value)} placeholder="https://..." />
        </div>
        <div className="ledger-field">
          <label htmlFor="hotel-key">API 密钥</label>
          <input id="hotel-key" type="password" value={hotelApiKey} onChange={(event) => setHotelApiKey(event.target.value)} placeholder="..." />
          {hotelConfig?.api_key_set && <small className="ledger-hint">已设置，留空表示不修改</small>}
        </div>
      </div>

      <p className={`status-line ${hotelConfig?.configured ? 'is-ready' : ''}`}>
        {hotelConfig?.configured ? '酒店服务已连接' : '尚未配置'}
      </p>
      {hotelMessage && <p className="success-note">{hotelMessage}</p>}
      {hotelError && <p className="error-note" role="alert">{hotelError}</p>}
      <div className="save-bar">
        <button className="primary-button" disabled={savingHotel} onClick={() => void saveHotel()}>
          {savingHotel ? '保存中…' : '保存酒店配置'}
        </button>
      </div>
    </section>
  )
}
