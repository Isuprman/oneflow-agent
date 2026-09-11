import { http, getErrorMessage } from './http'
import type { Memory } from './types'

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
