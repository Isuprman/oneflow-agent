import { http, getErrorMessage } from './http'
import type { Conversation, Message, ToolStep } from './types'

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
