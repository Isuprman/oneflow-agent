import { useCallback, useEffect, useRef, useState } from 'react'

// HUD 显示通道：全局错误条 / 顶部 Toast / OPERATOR 回显 / JARVIS 回显。
// 各业务域（发送、播报、唤醒、轮询）只调这里的 show/hold/fade 原语，定时器细节集中在本 hook。
export function useHud() {
  const [error, setError] = useState('')
  // 发消息错误 → 单个右上 Toast
  const [toast, setToast] = useState<string | null>(null)
  const toastTimerRef = useRef<number | null>(null)
  // 右上角「OPERATOR 刚说的话」：只在此显示一次，~2s 自动消失（时间线不重复显示用户消息）
  const [echo, setEcho] = useState<string | null>(null)
  const echoTimerRef = useRef<number | null>(null)
  // 右上角「JARVIS 回复」：完成后 ~3s 自动消失（时间线仍保留回复记录）
  const [jarvisEcho, setJarvisEcho] = useState<string | null>(null)
  const jarvisEchoTimerRef = useRef<number | null>(null)

  const clearToast = useCallback(() => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current)
    toastTimerRef.current = null
    setToast(null)
  }, [])

  /** 弹一个 ~2.5s 自动消失的顶部居中 Toast（重复错误会重置计时器）。 */
  const showToast = useCallback((message: string) => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current)
    setToast(message)
    toastTimerRef.current = window.setTimeout(() => {
      toastTimerRef.current = null
      setToast(null)
    }, 2500)
  }, [])

  /** OPERATOR 回显：~2s 自动消失。 */
  const showEcho = useCallback((text: string) => {
    setEcho(text)
    if (echoTimerRef.current) window.clearTimeout(echoTimerRef.current)
    echoTimerRef.current = window.setTimeout(() => setEcho(null), 2000)
  }, [])

  /** JARVIS 回显：只更新文本，不动淡出计时器（持有展示权的一方决定何时淡出）。 */
  const showJarvisEcho = useCallback((text: string | null) => { setJarvisEcho(text) }, [])

  /** 取消 JARVIS 回显的待发淡出（播报/流式期间文字保持，播完才淡出）。 */
  const holdJarvisEcho = useCallback(() => {
    if (jarvisEchoTimerRef.current) { window.clearTimeout(jarvisEchoTimerRef.current); jarvisEchoTimerRef.current = null }
  }, [])

  /** 安排 JARVIS 回显在 ms 后淡出（重复调用会重置计时器）。 */
  const fadeJarvisEcho = useCallback((ms: number) => {
    if (jarvisEchoTimerRef.current) window.clearTimeout(jarvisEchoTimerRef.current)
    jarvisEchoTimerRef.current = window.setTimeout(() => setJarvisEcho(null), ms)
  }, [])

  useEffect(() => () => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current)
    if (echoTimerRef.current !== null) window.clearTimeout(echoTimerRef.current)
    if (jarvisEchoTimerRef.current !== null) window.clearTimeout(jarvisEchoTimerRef.current)
  }, [])

  return { error, setError, toast, showToast, clearToast, echo, showEcho, jarvisEcho, showJarvisEcho, holdJarvisEcho, fadeJarvisEcho }
}
