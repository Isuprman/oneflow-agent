import { useCallback, useEffect, useRef } from 'react'
import { getLevel, startMicAnalyser } from '../lib/audioReactive'
import { getPrefs } from '../prefs'
import type { ReactiveLevel } from '../components/AiCore'

// 3D 核心的声动数据源：rAF 每帧写 reactiveLevelRef（避免每帧 setState）。
// 两个写入方共用一个 ref，优先级：麦克风音频驱动 > 播报模拟律动。
export function useCoreReactive(micAvailable: boolean, onError: (message: string) => void) {
  const voiceReactiveOnRef = useRef(false)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const dataArrayRef = useRef<Uint8Array<ArrayBuffer> | null>(null)
  const analyserCleanupRef = useRef<(() => void) | null>(null)
  const voiceRafRef = useRef<number | null>(null)
  // 播报律动 rAF id
  const speakAnimRef = useRef<number | null>(null)
  const reactiveLevelRef = useRef<ReactiveLevel>({ vol: 0, low: 0 })

  const stopVoiceReactive = useCallback(() => {
    voiceReactiveOnRef.current = false
    if (voiceRafRef.current !== null) window.cancelAnimationFrame(voiceRafRef.current)
    voiceRafRef.current = null
    reactiveLevelRef.current = { vol: 0, low: 0 }
    analyserCleanupRef.current?.()
    analyserCleanupRef.current = null
    analyserRef.current = null
    dataArrayRef.current = null
  }, [])

  const startVoiceReactive = useCallback(() => {
    if (voiceReactiveOnRef.current) return
    if (!micAvailable) { onError('当前设备不支持麦克风'); return }
    onError('')
    startMicAnalyser()
      .then(({ analyser, cleanup }) => {
        analyserRef.current = analyser
        analyserCleanupRef.current = cleanup
        dataArrayRef.current = new Uint8Array(analyser.frequencyBinCount)
        voiceReactiveOnRef.current = true
        const loop = () => {
          if (!voiceReactiveOnRef.current || !analyserRef.current || !dataArrayRef.current) return
          reactiveLevelRef.current = getLevel(analyserRef.current, dataArrayRef.current)
          voiceRafRef.current = window.requestAnimationFrame(loop)
        }
        voiceRafRef.current = window.requestAnimationFrame(loop)
      })
      .catch(() => {
        voiceReactiveOnRef.current = false
        onError('无法启用声音驱动（麦克风无权限）')
      })
  }, [micAvailable, onError])
  const startVoiceReactiveRef = useRef(startVoiceReactive); startVoiceReactiveRef.current = startVoiceReactive

  /** 播报律动：voiceLive 期间向 AiCore 写入模拟音频幅度（音频驱动开启时不覆盖真实麦克风数据）。 */
  const beginSpeakAnim = useCallback(() => {
    if (voiceReactiveOnRef.current || speakAnimRef.current !== null) return
    const startedAt = performance.now()
    const loop = () => {
      const t = (performance.now() - startedAt) / 1000
      const vol = 0.22 + 0.14 * Math.abs(Math.sin(t * 7.3)) + Math.random() * 0.06
      reactiveLevelRef.current = { vol, low: vol * 0.85 }
      speakAnimRef.current = window.requestAnimationFrame(loop)
    }
    speakAnimRef.current = window.requestAnimationFrame(loop)
  }, [])

  const endSpeakAnim = useCallback(() => {
    if (speakAnimRef.current !== null) window.cancelAnimationFrame(speakAnimRef.current)
    speakAnimRef.current = null
    if (!voiceReactiveOnRef.current) reactiveLevelRef.current = { vol: 0, low: 0 }
  }, [])

  useEffect(() => {
    if (getPrefs().audioDrive) startVoiceReactiveRef.current()
    return () => {
      stopVoiceReactive()
      if (speakAnimRef.current !== null) window.cancelAnimationFrame(speakAnimRef.current)
    }
  }, [stopVoiceReactive])

  return { reactiveLevelRef, voiceReactiveOnRef, beginSpeakAnim, endSpeakAnim }
}
