import { Canvas, useFrame } from '@react-three/fiber'
import { memo, useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { Group } from 'three'

export type CoreState = 'standby' | 'thinking' | 'speaking'

/** 声音驱动振幅：vol 全频段 0..1，low 低频段 0..1。 */
export interface ReactiveLevel { vol: number; low: number }

interface AiCoreProps {
  /** 核心状态：standby 呼吸 / thinking 高速自转 / speaking 持续扩散环；缺省为静默。 */
  state?: CoreState
  compact?: boolean
  /** 事件脉冲：由 ChatPage 发送时递增，触发一次性冲击波环。 */
  pulse?: number
  /** 声音驱动幅度（0..1）；静态传入缺省 0。 */
  reactiveLevel?: number
  /** 性能路径：ChatPage 每帧写入 {vol, low} 供 useFrame 读取，优先于静态 prop，避免每帧 setState。 */
  reactiveLevelRef?: { current: ReactiveLevel }
}

/** 冲击波环复用池大小（speaking 循环 + pulse 一次性共用）。 */
const SHOCK_POOL = 6

interface Shockwave { start: number; dur: number }

function CoreMesh({
  state,
  pulse,
  reactiveLevel = 0,
  reactiveLevelRef,
}: {
  state?: CoreState
  pulse?: number
  reactiveLevel?: number
  reactiveLevelRef?: { current: ReactiveLevel }
}) {
  const groupRef = useRef<Group>(null)
  const spinRef = useRef<Group>(null)
  const ringsRef = useRef<Group>(null)
  const shellRef = useRef<THREE.Mesh>(null)
  const nucleusRef = useRef<THREE.Mesh>(null)
  const glowRef = useRef<THREE.Mesh>(null)
  const glowMatRef = useRef<THREE.MeshBasicMaterial>(null)
  const timeRef = useRef(0)
  const lastSpawnRef = useRef(-100)
  const mouseTarget = useRef({ x: 0, y: 0 })
  const reducedRef = useRef(
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  const activeShocks = useRef<Shockwave[]>([])
  const shockRefs = useRef<Array<THREE.Mesh | null>>([])
  const shockMatRefs = useRef<Array<THREE.MeshBasicMaterial | null>>([])

  const spawnShock = () => {
    activeShocks.current.push({ start: timeRef.current, dur: 1.15 })
    if (activeShocks.current.length > SHOCK_POOL) {
      activeShocks.current.splice(0, activeShocks.current.length - SHOCK_POOL)
    }
  }

  // 鼠标视差目标（归一化 -1..1）
  useEffect(() => {
    if (typeof window === 'undefined') return
    const onMove = (event: PointerEvent) => {
      mouseTarget.current.x = (event.clientX / window.innerWidth) * 2 - 1
      mouseTarget.current.y = (event.clientY / window.innerHeight) * 2 - 1
    }
    window.addEventListener('pointermove', onMove)
    return () => window.removeEventListener('pointermove', onMove)
  }, [])

  // 事件脉冲：pulse 递增 -> 一次性冲击波环
  useEffect(() => {
    if (pulse == null || pulse <= 0 || reducedRef.current) return
    spawnShock()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pulse])

  // 轨道粒子：沿 3 条倾斜环分布（数量克制，≤300）
  const orbitParticles = useMemo(() => {
    const rings = [
      { radius: 1.58, euler: [Math.PI / 2.8, 0, 0] },
      { radius: 1.74, euler: [0.58, 0.4, 0.88] },
      { radius: 1.92, euler: [1.2, 0.5, 0.3] },
    ]
    const euler = new THREE.Euler()
    const point = new THREE.Vector3()
    const points: number[] = []
    rings.forEach((ring) => {
      euler.set(ring.euler[0], ring.euler[1], ring.euler[2])
      const count = 70
      for (let i = 0; i < count; i += 1) {
        const angle = (i / count) * Math.PI * 2
        point.set(Math.cos(angle) * ring.radius, Math.sin(angle) * ring.radius, 0)
        point.applyEuler(euler)
        points.push(point.x, point.y, point.z)
      }
    })
    return new Float32Array(points)
  }, [])

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime()
    timeRef.current = t
    const reduced = reducedRef.current
    const group = groupRef.current
    const spin = spinRef.current
    if (!group || !spin) return

    // —— 状态参数 ——
    let pulseScale = 1
    let spinSpeed = 0.18
    let baseTilt = 0.12
    if (state === 'standby') {
      pulseScale = 1 + Math.sin(t * 2.6) * 0.05
      spinSpeed = 0.2
    } else if (state === 'thinking') {
      pulseScale = 1 + Math.sin(t * 11) * 0.07
      spinSpeed = 0.72
      baseTilt = 0.22
    } else if (state === 'speaking') {
      pulseScale = 1 + Math.sin(t * 4.4) * 0.05
      spinSpeed = 0.34
    }
    if (reduced) {
      pulseScale = 1
      spinSpeed *= 0.12
    }

    // —— 声音驱动（vol>0 且未 reduced 时生效，覆盖静默/呼吸的幅度感）——
    const reactiveSrc = reactiveLevelRef?.current
    const vol = reactiveSrc ? reactiveSrc.vol : reactiveLevel
    const low = reactiveSrc ? reactiveSrc.low : 0
    const voice = !reduced && vol > 0.001
    if (voice) {
      // 轨道环/自转转速随 vol 微增
      spinSpeed += vol * 0.55
    }

    // —— 鼠标视差：lerp 平滑，三维用 rAF 帧循环 ——
    const targetRotY = mouseTarget.current.x * 0.5
    const targetRotX = -mouseTarget.current.y * 0.32 + Math.sin(t * 0.5) * baseTilt
    const lerp = reduced ? 0.01 : 0.07
    group.rotation.y += (targetRotY - group.rotation.y) * lerp
    group.rotation.x += (targetRotX - group.rotation.x) * lerp

    // —— 自转 + 呼吸 ——
    spin.rotation.y = t * spinSpeed
    spin.scale.setScalar(pulseScale)
    if (ringsRef.current) ringsRef.current.rotation.z = Math.sin(t * 0.55) * 0.12

    // —— 冲击波环（speaking 持续循环 / pulse 一次性）——
    if (!reduced && state === 'speaking' && t - lastSpawnRef.current > 0.95) {
      lastSpawnRef.current = t
      spawnShock()
    }
    activeShocks.current = activeShocks.current.filter((shock) => t - shock.start < shock.dur)
    const shockColor = state === 'speaking' ? '#38bdf8' : '#22d3ee'
    activeShocks.current.forEach((shock, index) => {
      const mesh = shockRefs.current[index]
      const material = shockMatRefs.current[index]
      if (!mesh || !material) return
      const progress = (t - shock.start) / shock.dur
      mesh.scale.setScalar(0.9 + progress * 1.35)
      material.color.set(shockColor)
      material.opacity = (1 - progress) * 0.5
    })
    for (let i = activeShocks.current.length; i < SHOCK_POOL; i += 1) {
      const material = shockMatRefs.current[i]
      if (material) material.opacity = 0
    }

    // —— 声音驱动形变 / 亮度（外层线框随 vol 起伏、核芯随 low 放大、光晕随 vol 提亮）——
    if (shellRef.current) shellRef.current.scale.setScalar(voice ? 1 + vol * 0.15 : 1)
    if (nucleusRef.current) nucleusRef.current.scale.setScalar(voice ? 1 + low * 0.4 : 1)
    if (glowRef.current) glowRef.current.scale.setScalar(voice ? 1.45 * (1 + vol * 0.32) : 1.45)
    if (glowMatRef.current) glowMatRef.current.opacity = voice ? Math.min(0.3 + vol * 0.5, 0.82) : 0.3
  })

  const shellColor = state === 'thinking' ? '#7dd3fc' : state === 'speaking' ? '#22d3ee' : '#38bdf8'
  const shellOpacity = state == null ? 0.42 : state === 'thinking' ? 0.78 : 0.62
  const nucleusColor = state === 'speaking' ? '#a5f3fc' : state === 'thinking' ? '#bae6fd' : '#dff6ff'
  const glowColor = state === 'speaking' ? '#22d3ee' : state === 'thinking' ? '#7dd3fc' : '#38bdf8'

  return (
    <group ref={groupRef}>
      <group ref={spinRef}>
        {/* 内层亮核 + 光晕 */}
        <mesh ref={nucleusRef}>
          <sphereGeometry args={[0.34, 24, 24]} />
          <meshBasicMaterial color={nucleusColor} />
        </mesh>
        <mesh ref={glowRef} scale={1.45}>
          <sphereGeometry args={[0.34, 24, 24]} />
          <meshBasicMaterial
            ref={glowMatRef}
            color={glowColor}
            transparent
            opacity={0.3}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
          />
        </mesh>
        {/* 外层线框球 */}
        <mesh ref={shellRef}>
          <icosahedronGeometry args={[1.28, 3]} />
          <meshBasicMaterial color={shellColor} wireframe transparent opacity={shellOpacity} />
        </mesh>
        {/* 陀螺仪式倾斜轨道环 + 轨道粒子 */}
        <group ref={ringsRef}>
          <mesh rotation={[Math.PI / 2.8, 0, 0]}>
            <torusGeometry args={[1.58, 0.012, 8, 96]} />
            <meshBasicMaterial color="#38bdf8" transparent opacity={0.85} />
          </mesh>
          <mesh rotation={[0.58, 0.4, 0.88]}>
            <torusGeometry args={[1.74, 0.009, 8, 96]} />
            <meshBasicMaterial color="#22d3ee" transparent opacity={0.55} />
          </mesh>
          <mesh rotation={[1.2, 0.5, 0.3]}>
            <torusGeometry args={[1.92, 0.007, 8, 96]} />
            <meshBasicMaterial color="#7dd3fc" transparent opacity={0.35} />
          </mesh>
          <points>
            <bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[orbitParticles, 3]} />
            </bufferGeometry>
            <pointsMaterial color="#e0f2fe" size={0.024} sizeAttenuation transparent opacity={0.8} />
          </points>
        </group>
      </group>
      {/* 冲击波环（面向镜头扩散，复用池） */}
      {Array.from({ length: SHOCK_POOL }).map((_, index) => (
        <mesh
          key={index}
          ref={(element) => {
            shockRefs.current[index] = element
          }}
        >
          <torusGeometry args={[1, 0.012, 8, 96]} />
          <meshBasicMaterial
            ref={(element) => {
              shockMatRefs.current[index] = element
            }}
            color="#22d3ee"
            transparent
            opacity={0}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  )
}

const AiCore = memo(function AiCore({
  state,
  compact = false,
  pulse,
  reactiveLevel = 0,
  reactiveLevelRef,
}: AiCoreProps) {
  return (
    <div
      className={['ai-core', compact ? 'ai-core--compact' : '', state ? `ai-core--${state}` : ''].filter(Boolean).join(' ')}
      aria-hidden="true"
    >
      <Canvas
        camera={{ position: [0, 0, 5.6], fov: 38 }}
        dpr={[1, 1.5]}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
      >
        <CoreMesh state={state} pulse={pulse} reactiveLevel={reactiveLevel} reactiveLevelRef={reactiveLevelRef} />
      </Canvas>
    </div>
  )
})

export default AiCore
