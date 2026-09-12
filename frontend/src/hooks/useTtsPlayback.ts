import { useCallback, useEffect, useRef, useState } from 'react'
import { tts } from '../api/tts'
import { getPrefs } from '../prefs'
import { enterFollowUpWindow } from '../lib/speech/wake'
import { playBlob, speak as speakFallback, splitSentences } from '../lib/speech/playback'

interface UseTtsPlaybackOpts {
  standbyOnRef: { current: boolean }
  // 播报前暂停/播完恢复待命的桥接（归 useStandby 所有，经 ref 共享）
  resumeStandbyRef: { current: boolean }
  standbyActionsRef: { current: { pause: () => void; resume: () => void } }
  holdJarvisEcho: () => void
  fadeJarvisEcho: (ms: number) => void
  beginSpeakAnim: () => void
  endSpeakAnim: () => void
}

// 语音播报：分句预取流水线（首句合成完即开播，合成与播放交错）+ 暂停待命防回声。
// followUp=true 时（仅对话回复）播完进免唤醒跟随窗口；显示与声音对齐：播报期间文字不淡出。
export function useTtsPlayback(opts: UseTtsPlaybackOpts) {
  const { standbyOnRef, resumeStandbyRef, standbyActionsRef, holdJarvisEcho, fadeJarvisEcho, beginSpeakAnim, endSpeakAnim } = opts
  const [voiceLive, setVoiceLive] = useState(false)
  const voiceLiveRef = useRef(false)
  // 播报链 id：每次 speakReply 自增，被打断的旧链自动作废
  const speakChainRef = useRef(0)
  // 播报安全网定时器：音频 ended 事件异常不触发时兜底恢复监听
  const voiceSafetyRef = useRef<number | null>(null)
  // 上次播报结束时刻（俏皮话情境感知用）
  const lastSpeakEndRef = useRef(0)
  const voiceOnRef = useRef(false)

  useEffect(() => { voiceOnRef.current = getPrefs().voice }, [])

  const speakReply = useCallback((plain: string, followUp = false) => {
    if (!voiceOnRef.current || !plain) return
    setVoiceLive(true); voiceLiveRef.current = true
    // 播报开始前暂停待命监听，避免扬声器声音被识别成指令（回声/循环）
    if (standbyOnRef.current && !resumeStandbyRef.current) {
      resumeStandbyRef.current = true
      standbyActionsRef.current.pause()
    }
    // 播报期间回显文字保持展示，播完才淡出（消除“字先消失声音才来”的错位）
    holdJarvisEcho()
    // 全息核心随播报律动（音频驱动开启时不覆盖真实麦克风数据）
    beginSpeakAnim()
    const chainId = ++speakChainRef.current
    // 全部句子播完后收尾；被新链取代的旧链不做收尾（新链接管待命恢复）
    const finish = () => {
      if (speakChainRef.current !== chainId) return
      speakChainRef.current = 0
      setVoiceLive(false); voiceLiveRef.current = false
      endSpeakAnim()
      lastSpeakEndRef.current = Date.now()
      if (resumeStandbyRef.current) {
        resumeStandbyRef.current = false
        if (!standbyOnRef.current) standbyActionsRef.current.resume()
        if (followUp && standbyOnRef.current) enterFollowUpWindow()
      }
      fadeJarvisEcho(3500)
    }
    // 分句预取流水线：合成器持续预取后续句子，与播放重叠——消除句间空白。
    // 单句合成失败标记 failed，由播放循环回退浏览器语音读该句；被打断则整链作废。
    const sentences = splitSentences(plain)
    void (async () => {
      const blobs: (Blob | 'failed' | undefined)[] = new Array(sentences.length)
      let produced = 0

      const produce = async () => {
        while (produced < sentences.length && speakChainRef.current === chainId) {
          const i = produced
          try {
            const blob = await tts(sentences[i], getPrefs().ttsVoice)
            if (speakChainRef.current !== chainId) return
            blobs[i] = blob
          } catch {
            if (speakChainRef.current !== chainId) return
            blobs[i] = 'failed'
          }
          produced++
        }
      }
      const producer = produce()

      for (let i = 0; i < sentences.length; i++) {
        if (speakChainRef.current !== chainId) return
        while (blobs[i] === undefined && speakChainRef.current === chainId) {
          await new Promise((resolve) => setTimeout(resolve, 50))
        }
        if (speakChainRef.current !== chainId) return
        const item = blobs[i]
        if (item === 'failed' || item === undefined) {
          // 该句合成失败：回退浏览器语音兜底
          try { await speakFallback(sentences[i]) } catch { /* 被打断 */ }
          if (speakChainRef.current !== chainId) return
          continue
        }
        try {
          await playBlob(item)
        } catch (err) {
          if (err instanceof Error && err.message === 'interrupted') {
            if (speakChainRef.current === chainId) speakChainRef.current = 0
            return
          }
        }
        if (speakChainRef.current !== chainId) return
      }
      finish()
      void producer
    })()
    // 安全网：链条异常卡死时按全文估算强制收尾
    if (voiceSafetyRef.current) window.clearTimeout(voiceSafetyRef.current)
    voiceSafetyRef.current = window.setTimeout(() => {
      voiceSafetyRef.current = null
      finish()
    }, Math.min(8000 + plain.length * 320, 120000))
  }, [standbyOnRef, resumeStandbyRef, standbyActionsRef, holdJarvisEcho, fadeJarvisEcho, beginSpeakAnim, endSpeakAnim])

  useEffect(() => () => { if (voiceSafetyRef.current) window.clearTimeout(voiceSafetyRef.current) }, [])

  return { voiceLive, voiceLiveRef, speakReply, speakChainRef, lastSpeakEndRef, voiceOnRef }
}
