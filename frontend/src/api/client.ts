import axios from 'axios'
import type {
  AppNotification,
  BriefingConfig,
  ChatResponse,
  Conversation,
  HotelConfig,
  HotelConfigIn,
  IdleHint,
  LlmConfig,
  LlmConfigIn,
  Memory,
  Message,
  TaskInfo,
  TaskUpdateIn,
  ToolStep,
  TokenOut,
  UserOut,
} from './types'

const http = axios.create({
  baseURL: '/api',
})

// ─── 自学习（技能工厂）──────────────────────────────

export interface LearnProposalOut {
  id: number
  slug: string
  title: string
  description: string
  status: string
  required_keys: Record<string, string>
  branch: string
  log: string
  created_at: string | null
}

export async function acquireSkill(request: string): Promise<LearnProposalOut> {
  const resp = await http.post('/learn/acquire', { request })
  return resp.data
}

export async function listLearnProposals(): Promise<LearnProposalOut[]> {
  const resp = await http.get('/learn/proposals')
  return resp.data
}

export async function approveLearnProposal(
  id: number,
  keys: Record<string, string>,
): Promise<{ ok: boolean; message?: string; tool_name?: string; live?: boolean; missing_keys?: Record<string, string> }> {
  const resp = await http.post(`/learn/proposals/${id}/approve`, { keys })
  return resp.data
}

export async function rejectLearnProposal(id: number): Promise<{ ok: boolean; message: string }> {
  const resp = await http.post(`/learn/proposals/${id}/reject`)
  return resp.data
}

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('oneflow_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data?.detail ?? error.message
  }
  return '网络请求失败，请稍后重试'
}

export async function register(username: string, password: string): Promise<UserOut> {
  try {
    const resp = await http.post('/auth/register', { username, password })
    return resp.data as UserOut
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function login(username: string, password: string): Promise<TokenOut> {
  try {
    const resp = await http.post('/auth/login', { username, password })
    return resp.data as TokenOut
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function me(): Promise<UserOut> {
  try {
    const resp = await http.get('/auth/me')
    return resp.data as UserOut
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function listConversations(): Promise<Conversation[]> {
  try {
    const resp = await http.get('/conversations')
    return resp.data as Conversation[]
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function createConversation(title?: string): Promise<Conversation> {
  try {
    const resp = await http.post('/conversations', { title: title ?? null })
    return resp.data as Conversation
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function getMessages(id: number): Promise<Message[]> {
  try {
    const resp = await http.get(`/conversations/${id}/messages`)
    return resp.data as Message[]
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function getTrace(id: number): Promise<ToolStep[]> {
  try {
    const resp = await http.get(`/conversations/${id}/trace`)
    return resp.data as ToolStep[]
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function sendChat(
  conversation_id: number | null,
  message: string,
): Promise<ChatResponse> {
  try {
    const resp = await http.post('/chat', { conversation_id, message })
    return resp.data as ChatResponse
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

/** SSE step 事件：工具调用进度（calling=开始调用，done=拿到结果）。 */
export interface StreamStep {
  tool: string
  status: 'calling' | 'done'
  success?: boolean
  result?: unknown
}

/** SSE confirm 事件：高危操作待用户确认。 */
export interface StreamConfirm {
  tool: string
  summary: string
}

export async function streamChat(
  conversationId: number | null,
  message: string,
  onDelta: (text: string) => void,
  onDone: (resp: ChatResponse) => void,
  onError: (e: Error) => void,
  onStep?: (step: StreamStep) => void,
  onConfirm?: (pending: StreamConfirm) => void,
): Promise<void> {
  try {
    const token = localStorage.getItem('oneflow_token')
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ conversation_id: conversationId, message }),
    })
    if (!res.ok || !res.body) {
      let detail = ''
      try {
        const data = (await res.json()) as { detail?: string }
        detail = data.detail ?? ''
      } catch {
        detail = await res.text()
      }
      throw new Error(detail || `请求失败（HTTP ${res.status}）`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const parseEvent = (block: string): void => {
      if (!block.trim()) return
      let event = ''
      const dataLines: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) {
          event = line.slice('event:'.length).trim()
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice('data:'.length).trim())
        }
      }
      if (!event || dataLines.length === 0) return
      const data = dataLines.join('\n')
      if (event === 'delta') {
        const parsed = JSON.parse(data) as { text?: string }
        if (parsed.text) onDelta(parsed.text)
      } else if (event === 'step') {
        onStep?.(JSON.parse(data) as StreamStep)
      } else if (event === 'confirm') {
        onConfirm?.(JSON.parse(data) as StreamConfirm)
      } else if (event === 'error') {
        const parsed = JSON.parse(data) as { message?: string }
        onError(new Error(parsed.message ?? '服务异常'))
      } else if (event === 'done') {
        onDone(JSON.parse(data) as ChatResponse)
      }
    }

    let streaming = true
    while (streaming) {
      const { done, value } = await reader.read()
      if (done) {
        streaming = false
      } else {
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() ?? ''
        for (const block of blocks) parseEvent(block)
      }
    }
    if (buffer.trim()) parseEvent(buffer)
  } catch (e: unknown) {
    onError(e instanceof Error ? e : new Error(String(e)))
  }
}

export async function getLlmConfig(): Promise<LlmConfig> {
  try {
    const resp = await http.get('/settings/llm')
    return resp.data as LlmConfig
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function saveLlmConfig(data: LlmConfigIn): Promise<LlmConfig> {
  try {
    const resp = await http.put('/settings/llm', data)
    return resp.data as LlmConfig
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function getHotelConfig(): Promise<HotelConfig> {
  try {
    const resp = await http.get('/settings/hotel')
    return resp.data as HotelConfig
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function saveHotelConfig(data: HotelConfigIn): Promise<HotelConfig> {
  try {
    const resp = await http.put('/settings/hotel', data)
    return resp.data as HotelConfig
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function listMemories(): Promise<Memory[]> {
  try {
    const resp = await http.get('/memories')
    return resp.data as Memory[]
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function deleteMemory(id: number): Promise<void> {
  try {
    await http.delete(`/memories/${id}`)
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

/** 拉取主动通知（默认仅未读；unreadOnly=false 拉全部历史），最新在前。 */
export async function listNotifications(unreadOnly = true): Promise<AppNotification[]> {
  try {
    const resp = await http.get('/notifications', { params: { unread: unreadOnly } })
    return resp.data as AppNotification[]
  } catch {
    // 轮询场景：网络抖动静默返回空，下一轮重试
    return []
  }
}

export async function markNotificationRead(id: number): Promise<void> {
  try {
    await http.post(`/notifications/${id}/read`)
  } catch {
    // 标记失败不影响展示，忽略
  }
}

export async function getBriefing(): Promise<BriefingConfig> {
  try {
    const resp = await http.get('/briefing')
    return resp.data as BriefingConfig
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function saveBriefing(data: BriefingConfig): Promise<BriefingConfig> {
  try {
    const resp = await http.put('/briefing', data)
    return resp.data as BriefingConfig
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function deleteNotification(id: number): Promise<void> {
  try {
    await http.delete(`/notifications/${id}`)
  } catch {
    // 删除失败静默，下一轮刷新自然对齐
  }
}

export async function listTasks(): Promise<TaskInfo[]> {
  try {
    const resp = await http.get('/tasks')
    return resp.data as TaskInfo[]
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function updateTask(id: number, data: TaskUpdateIn): Promise<TaskInfo> {
  try {
    const resp = await http.put(`/tasks/${id}`, data)
    return resp.data as TaskInfo
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function deleteTask(id: number): Promise<void> {
  try {
    await http.delete(`/tasks/${id}`)
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

/** 闲置轻推话题：无话可说时返回 {topic: null, text: null}。 */
export async function getIdleHint(): Promise<IdleHint | null> {
  try {
    const resp = await http.get('/idle-hint')
    return resp.data as IdleHint
  } catch {
    return null
  }
}

export async function tts(text: string, voice?: string): Promise<Blob> {
  try {
    const resp = await http.post(
      '/tts',
      { text, voice: voice ?? 'zh-CN-XiaoxiaoNeural' },
      // 8 秒超时：edge-tts 走微软服务器国内偶发慢请求，超时即回退浏览器语音，
      // 绝不让播报链路挂住几十秒
      { responseType: 'blob', timeout: 8000 },
    )
    return resp.data as Blob
  } catch {
    // blob 错误响应时 error.response.data 可能是 Blob 而非对象，无法读取 detail，统一抛固定文案
    throw new Error('语音合成失败')
  }
}
