import { useCallback, useRef, useState } from 'react'
import { streamChat, type StreamStep } from '../api/chat'
import { listConversations } from '../api/conversations'
import { toPlainText } from '../lib/plain'

interface UseChatStreamOpts {
  activeId: number | null
  setActiveId: (id: number) => void
  setConversations: (value: import('../api/types').Conversation[] | ((previous: import('../api/types').Conversation[]) => import('../api/types').Conversation[])) => void
  // 忙闲镜像（轮询方读最新值）
  sendingRef: { current: boolean }
  voiceOnRef: { current: boolean }
  // 播报前暂停/播完恢复待命的桥接（归 useStandby 所有）
  resumeStandbyRef: { current: boolean }
  standbyOnRef: { current: boolean }
  standbyActionsRef: { current: { pause: () => void; resume: () => void } }
  showToast: (message: string) => void
  clearToast: () => void
  showEcho: (text: string) => void
  showJarvisEcho: (text: string | null) => void
  holdJarvisEcho: () => void
  fadeJarvisEcho: (ms: number) => void
  setError: (message: string) => void
  bumpInteraction: () => void
  speakReply: (plain: string, followUp?: boolean) => void
}

// 发送链路：输入框 + 真流式发送（工具遥测/高危确认/错误 Toast）+ 发送脉冲。
// 流式增量实时进 JARVIS 回显；忙时明确提示不静默丢弃。
export function useChatStream(opts: UseChatStreamOpts) {
  const {
    activeId, setActiveId, setConversations, sendingRef, voiceOnRef,
    resumeStandbyRef, standbyOnRef, standbyActionsRef,
    showToast, clearToast, showEcho, showJarvisEcho, holdJarvisEcho, fadeJarvisEcho, setError,
    bumpInteraction, speakReply,
  } = opts
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [corePulse, setCorePulse] = useState(0)
  // 真流式：当前正在调用的工具名（执行完清空，驱动遥测状态）
  const [liveTool, setLiveTool] = useState('')
  // 高危操作待确认（engine 暂存，等用户确认/取消）
  const [pendingConfirm, setPendingConfirm] = useState<{ tool: string; summary: string } | null>(null)
  // 真流式：累积 delta 增量，实时刷新 JARVIS 回显；出错标记防播报错误文本
  const liveTextRef = useRef('')
  const hadErrorRef = useRef(false)

  const doSend = useCallback((rawText: string) => {
    const text = rawText.trim()
    if (!text) return
    // 忙时不再静默丢弃：明确告知用户上一件事还在处理
    if (sending) { showToast('正在处理上一件事，请稍候'); return }
    clearToast()
    bumpInteraction()
    setInput(''); setSending(true); sendingRef.current = true; setError('')
    // 右上角「OPERATOR + 内容」只显示一次，~2s 自动消失；不再进左侧时间线
    showEcho(text)
    setCorePulse((value) => value + 1)
    liveTextRef.current = ''
    hadErrorRef.current = false
    setLiveTool('')
    setPendingConfirm(null)
    void streamChat(activeId, text, (piece) => {
      // 真流式打字机：delta 增量实时进右上角 JARVIS 回显
      if (hadErrorRef.current) return
      liveTextRef.current += piece
      showJarvisEcho(liveTextRef.current)
      holdJarvisEcho()
    }, (response) => {
      setLiveTool('')
      if (activeId === null) { setActiveId(response.conversation_id); listConversations().then(setConversations).catch(() => {}) }
      // 本轮出过错：不重复展示/播报错误文本（Toast 已提示）；若播报暂停过则恢复待命
      if (hadErrorRef.current) {
        if (resumeStandbyRef.current) {
          resumeStandbyRef.current = false
          if (!standbyOnRef.current) standbyActionsRef.current.resume()
        }
        return
      }
      // 右上角 JARVIS 回复回显：语音开启时文字保持到播完才淡出（显示与声音对齐）
      showJarvisEcho(toPlainText(response.reply))
      holdJarvisEcho()
      if (!voiceOnRef.current) fadeJarvisEcho(3500)
      speakReply(toPlainText(response.reply), true)
    }, (reason) => {
      // 发送失败/服务端 error 事件：顶部 Toast；标记出错防播报错误文本
      hadErrorRef.current = true
      setLiveTool('')
      showJarvisEcho(null)
      showToast(reason.message)
    }, (step: StreamStep) => {
      // 工具步骤实时上遥测：calling 显示工具名，done 回落思考态
      setLiveTool(step.status === 'calling' ? step.tool : '')
    }, (pending) => {
      // 高危操作待确认：弹确认条，点按钮或语音说“确认/取消”均可
      setPendingConfirm(pending)
    }).finally(() => { setSending(false); sendingRef.current = false })
  }, [activeId, sending, setActiveId, setConversations, sendingRef, voiceOnRef, resumeStandbyRef, standbyOnRef, standbyActionsRef, showToast, clearToast, showEcho, showJarvisEcho, holdJarvisEcho, fadeJarvisEcho, setError, bumpInteraction, speakReply])

  return { input, setInput, sending, liveTool, pendingConfirm, corePulse, doSend }
}
