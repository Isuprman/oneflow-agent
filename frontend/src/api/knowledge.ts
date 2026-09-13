import { http, getErrorMessage } from './http'

export interface KnowledgeDocOut {
  id: number
  filename: string
  status: 'pending' | 'ready' | 'failed'
  error: string | null
  size: number
  chunk_count: number
  created_at: string | null
}

/** 上传文档建知识（后端 BackgroundTasks 异步切块 embedding，前端轮询状态）。 */
export async function uploadKnowledge(file: File): Promise<KnowledgeDocOut> {
  try {
    const form = new FormData()
    form.append('file', file)
    const resp = await http.post('/knowledge', form)
    return resp.data as KnowledgeDocOut
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

export async function listKnowledge(): Promise<KnowledgeDocOut[]> {
  try {
    const resp = await http.get('/knowledge')
    return resp.data as KnowledgeDocOut[]
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

export async function deleteKnowledge(id: number): Promise<void> {
  try {
    await http.delete(`/knowledge/${id}`)
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}
