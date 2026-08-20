export interface UserOut {
  id: number
  username: string
}

export interface TokenOut {
  access_token: string
  token_type: string
}

export interface Conversation {
  id: number
  title: string | null
  created_at: string
}

export interface Message {
  id: number
  role: string
  content: string | null
}

export interface ToolStep {
  tool: string
  arguments: Record<string, unknown>
  result: Record<string, unknown>
  success: boolean
}

export interface ChatResponse {
  conversation_id: number
  reply: string
  steps: number
  trace: ToolStep[]
}

export interface Health {
  status: string
  llm_provider: string
  llm_model: string
}

export interface LlmConfig {
  provider: string
  model: string
  api_key_set: boolean
  base_url: string
  configured: boolean
}

export interface LlmConfigIn {
  provider: string
  model: string
  api_key: string
  base_url: string
}

export interface HotelConfig {
  base_url: string
  api_key_set: boolean
  configured: boolean
}

export interface HotelConfigIn {
  base_url: string
  api_key: string
}

export interface Memory {
  id: number
  content: string
  created_at: string
}

export interface AppNotification {
  id: number
  title: string
  content: string
  kind: string
  created_at: string
}

export interface BriefingConfig {
  enabled: boolean
  hour: number
  minute: number
}
