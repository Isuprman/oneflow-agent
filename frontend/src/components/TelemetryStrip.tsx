import { useEffect, useState } from 'react'

interface TelemetryStripProps {
  sessionId: number | null
  status: string
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function formatElapsed(total: number): string {
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return `${pad(h)}:${pad(m)}:${pad(s)}`
}

/** 环境感信号条：rAF 驱动的轻微随机波动（纯视觉指示，非业务数据）。 */
function SignalBars() {
  const [heights, setHeights] = useState<number[]>([4, 7, 10, 12])

  useEffect(() => {
    let raf = 0
    let last = 0
    const bases = [4, 7, 10, 12]
    const tick = (time: number) => {
      if (time - last > 170) {
        last = time
        setHeights(() =>
          bases.map((base, index) => {
            const jitter = Math.round((Math.random() - 0.5) * (index + 1) * 2)
            return Math.max(3, Math.min(16, base + jitter))
          }),
        )
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <span className="telemetry-signal">
      {heights.map((height, index) => (
        <span key={index} className="signal-bar" style={{ height }} />
      ))}
    </span>
  )
}

/** 右侧细遥测栏：实时秒表 / 时间 / 日期 / 会话链接 / 信号条 + 系统状态。 */
export default function TelemetryStrip({ sessionId, status }: TelemetryStripProps) {
  const [now, setNow] = useState(() => new Date())
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(new Date())
      setElapsed((value) => value + 1)
    }, 1000)
    return () => window.clearInterval(id)
  }, [])

  return (
    <aside className="telemetry-rail" aria-hidden="true">
      <div className="telemetry-cell">
        <span className="telemetry-cell__label">UPTIME</span>
        <span className="telemetry-cell__value">{formatElapsed(elapsed)}</span>
      </div>
      <div className="telemetry-cell">
        <span className="telemetry-cell__label">TIME</span>
        <span className="telemetry-cell__value">
          {pad(now.getHours())}:{pad(now.getMinutes())}
        </span>
        <span className="telemetry-cell__value telemetry-cell__value--dim">
          {pad(now.getSeconds())}
        </span>
      </div>
      <div className="telemetry-cell">
        <span className="telemetry-cell__label">DATE</span>
        <span className="telemetry-cell__value">
          {now.getMonth() + 1}/{now.getDate()}
        </span>
      </div>
      <div className="telemetry-cell">
        <span className="telemetry-cell__label">LINK</span>
        <span className="telemetry-cell__value">{sessionId ? `#${sessionId}` : '—'}</span>
      </div>
      <div className="telemetry-cell">
        <span className="telemetry-cell__label">SYS</span>
        <SignalBars />
        <span className="telemetry-cell__status">{status}</span>
      </div>
    </aside>
  )
}
