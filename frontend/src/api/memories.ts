import { http, getErrorMessage } from './http'
import type { Memory } from './types'

export async function listMemories(): Promise<Memory[]> {
  try {
    const resp = await http.get('/memories')
    return resp.data as Memory[]
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

export async function deleteMemory(id: number): Promise<void> {
  try {
    await http.delete(`/memories/${id}`)
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

/** 编辑一条记忆（后端会同步重嵌向量，无 embedding 配置时退化为最近度召回）。 */
export async function updateMemory(id: number, content: string): Promise<void> {
  try {
    await http.put(`/memories/${id}`, { content })
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}
