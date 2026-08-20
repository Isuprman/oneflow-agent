import { useEffect, useRef } from 'react'

interface Star {
  x: number
  y: number
  r: number
  base: number
  speed: number
  phase: number
}

/** 2D 画布星云：稀疏星点 + 极淡星座连接线，rAF 轻微闪烁。 */
function ConstellationField() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let stars: Star[] = []
    let raf = 0

    const regenerate = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
      canvas.width = Math.max(1, Math.floor(window.innerWidth * dpr))
      canvas.height = Math.max(1, Math.floor(window.innerHeight * dpr))
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      stars = Array.from({ length: 84 }, () => ({
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        r: Math.random() * 0.9 + 0.4,
        base: 0.08 + Math.random() * 0.2,
        speed: 0.4 + Math.random() * 1.4,
        phase: Math.random() * Math.PI * 2,
      }))
    }
    regenerate()
    window.addEventListener('resize', regenerate)

    const draw = (t: number) => {
      const w = window.innerWidth
      const h = window.innerHeight
      ctx.clearRect(0, 0, w, h)

      // 星座连接线（克制：极低透明度）
      ctx.strokeStyle = 'rgba(125, 211, 252, 0.045)'
      ctx.lineWidth = 1
      for (let i = 0; i < stars.length; i += 1) {
        for (let j = i + 1; j < stars.length; j += 1) {
          const dx = stars[i].x - stars[j].x
          const dy = stars[i].y - stars[j].y
          if (dx * dx + dy * dy < 128 * 128) {
            ctx.beginPath()
            ctx.moveTo(stars[i].x, stars[i].y)
            ctx.lineTo(stars[j].x, stars[j].y)
            ctx.stroke()
          }
        }
      }

      for (const star of stars) {
        const alpha = reduced
          ? star.base
          : star.base * (0.55 + 0.45 * Math.sin((t / 1000) * star.speed + star.phase))
        ctx.fillStyle = `rgba(186, 230, 253, ${alpha.toFixed(3)})`
        ctx.beginPath()
        ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2)
        ctx.fill()
      }

      if (!reduced) raf = requestAnimationFrame(draw)
    }

    if (reduced) {
      draw(0)
    } else {
      raf = requestAnimationFrame(draw)
    }

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', regenerate)
    }
  }, [])

  return <canvas ref={canvasRef} className="scene-constellation" aria-hidden="true" />
}

/** 场景气场：全息网格地面 + 星云星座 + 晕影/胶片颗粒 + 扫描扫掠。纯视觉，pointer-events 关闭。 */
export default function SceneFX() {
  return (
    <div className="scene-fx" aria-hidden="true">
      <div className="scene-grid-floor" />
      <ConstellationField />
      <div className="scene-vignette" />
      <div className="scene-grain" />
      <div className="scene-scan" />
    </div>
  )
}
