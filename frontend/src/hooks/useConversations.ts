import { useCallback, useEffect, useState } from 'react'
import { createConversation, getMessages, listConversations } from '../api/conversations'
import type { Conversation, Message, ToolStep } from '../api/types'

export interface ChatMessage { id: string; role: 'user' | 'assistant'; content: string; trace?: ToolStep[]; isStreaming?: boolean }

function isRenderable(message: Message): message is Message & { role: 'user' | 'assistant'; content: string } { return (message.role === 'user' || message.role === 'assistant') && message.content !== null }

// 会话列表 / 当前会话消息 / 轨迹展开：聊天页左侧栏与时间线的数据源
export function useConversations(onError: (message: string) => void, onConversationCreated?: () => void) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [expandedTraces, setExpandedTraces] = useState<Set<string>>(new Set())

  const loadMessages = useCallback(async (id: number) => {
    setLoadingMessages(true); onError('')
    try { const loaded = await getMessages(id); setMessages(loaded.filter(isRenderable).map((message) => ({ id: `history-${message.id}`, role: message.role, content: message.content }))); setExpandedTraces(new Set()) }
    catch (reason) { onError(reason instanceof Error ? reason.message : String(reason)); setMessages([]) }
    finally { setLoadingMessages(false) }
  }, [onError])

  useEffect(() => { listConversations().then((list) => { setConversations(list); if (list[0]) { setActiveId(list[0].id); void loadMessages(list[0].id) } }).catch((reason: unknown) => onError(reason instanceof Error ? reason.message : String(reason))) }, [loadMessages, onError])

  const newChat = async () => {
    onError('')
    try {
      const conversation = await createConversation()
      setConversations((previous) => [conversation, ...previous.filter((item) => item.id !== conversation.id)])
      setActiveId(conversation.id); setMessages([]); setExpandedTraces(new Set())
      onConversationCreated?.()
    } catch (reason) { onError(reason instanceof Error ? reason.message : String(reason)) }
  }

  const selectConversation = (id: number) => { setActiveId(id); void loadMessages(id) }

  return { conversations, setConversations, activeId, setActiveId, messages, setMessages, loadingMessages, expandedTraces, setExpandedTraces, loadMessages, newChat, selectConversation }
}
