import { http, getErrorMessage } from './http'
import type { ChatResponse } from './types'

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
