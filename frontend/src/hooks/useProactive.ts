import { useCallback, useEffect, useRef } from 'react'
import { listNotifications, markNotificationRead } from '../api/notifications'
import { getIdleHint } from '../api/idleHint'
import { getPrefs } from '../prefs'
import { toPlainText } from '../lib/plain'

interface UseProactiveOpts {
  // 忙闲镜像 ref：轮询读最新值，避免 interval 闭包过期
  sendingRef: { current: boolean }
  voiceLiveRef: { current: boolean }
  standbyOnRef: { current: boolean }
  voiceOnRef: { current: boolean }
  speakReply: (plain: string, followUp?: boolean) => void
  showJarvisEcho: (text: string | null) => void
  holdJarvisEcho: () => void
  fadeJarvisEcho: (ms: number) => void
}

// 主动服务：通知轮询（15s）+ 闲置轻推（60s，每会话最多 2 次）。
// 忙时（发送中/播报中）顺延不打断，避免播报撞车。
export function useProactive(opts: UseProactiveOpts) {
  const { sendingRef, voiceLiveRef, standbyOnRef, voiceOnRef, speakReply, showJarvisEcho, holdJarvisEcho, fadeJarvisEcho } = opts
  // 最近一次交互时间 + 本会话搭话次数（频控上限 2）；发送与唤醒也会刷新交互时间
  const lastInteractionRef = useRef(Date.now())
  const chatterCountRef = useRef(0)

  const bumpInteraction = useCallback(() => { lastInteractionRef.current = Date.now() }, [])

  // 主动通知轮询：定时任务播报/日程提醒 → 右上角展示 + 语音播报 + 标记已读
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      // 忙时顺延：对话进行中或正在播报时不打断，下一轮再拉
      if (cancelled || sendingRef.current || voiceLiveRef.current) return
      const list = await listNotifications()
      if (cancelled || list.length === 0) return
      const latest = list[0]
      // 页面隐藏时升级成系统通知（需用户授权，拒绝则静默）
      if (document.hidden && typeof Notification !== 'undefined') {
        if (Notification.permission === 'default') {
          Notification.requestPermission().catch(() => {})
        }
        if (Notification.permission === 'granted') {
          try {
            new Notification(latest.title, { body: toPlainText(latest.content).slice(0, 120), icon: '/icon.svg' })
          } catch {
            // 部分浏览器要求走 ServiceWorker 注册，失败则退回页内展示
          }
        }
      }
      lastInteractionRef.current = Date.now()
      // 多条合并成一段播报；system_error 类只展示不播报（避免 TTS 读报错详情）
      const speakable = list.filter((note) => note.kind !== 'system_error')
      const display = list.length === 1
        ? `【${latest.title}】${toPlainText(latest.content)}`
        : `【${latest.title}】等 ${list.length} 条新通知`
      showJarvisEcho(display)
      holdJarvisEcho()
      if (speakable.length > 0) {
        const speakText = speakable
          .map((note) => `${note.title}：${toPlainText(note.content)}`)
          .join('。')
          .slice(0, 500)
        // followUp=true：播报期间麦克风本就暂停，播完后用户接话无回声风险，直接免唤醒派发；
        // 文字由 speakReply 接管（播完才淡出）
        speakReply(speakText, true)
      } else {
        fadeJarvisEcho(6000)
      }
      for (const note of list) void markNotificationRead(note.id)
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 15000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [sendingRef, voiceLiveRef, speakReply, showJarvisEcho, holdJarvisEcho, fadeJarvisEcho])

  // 闲置轻推：长时间无交互时贾维斯主动说一句（每会话最多 2 次，宁缺毋滥）
  useEffect(() => {
    const IDLE_MS = 20 * 60 * 1000
    const timer = window.setInterval(async () => {
      if (!getPrefs().chitchat) return
      if (sendingRef.current || voiceLiveRef.current || !standbyOnRef.current) return
      if (chatterCountRef.current >= 2) return
      if (Date.now() - lastInteractionRef.current < IDLE_MS) return
      const hint = await getIdleHint()
      if (!hint || !hint.text || chatterCountRef.current >= 2) return
      chatterCountRef.current += 1
      lastInteractionRef.current = Date.now()
      showJarvisEcho(hint.text)
      holdJarvisEcho()
      if (!voiceOnRef.current) fadeJarvisEcho(6000)
      speakReply(hint.text, true)
    }, 60000)
    return () => window.clearInterval(timer)
  }, [sendingRef, voiceLiveRef, standbyOnRef, voiceOnRef, speakReply, showJarvisEcho, holdJarvisEcho, fadeJarvisEcho])

  return { bumpInteraction }
}
