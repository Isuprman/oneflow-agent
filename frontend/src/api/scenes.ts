import { http, getErrorMessage } from './http'

// 情境剧本（/api/scenes）：与后端路由一一对应的轻量客户端

export interface SceneInfo {
  id: number
  name: string
  steps: string[]
  step_count: number
  enabled: boolean
  created_at: string | null
}

export interface SceneRunResult {
  step: string
  reply: string
  success: boolean
}

export async function listScenes(): Promise<SceneInfo[]> {
  try {
    const resp = await http.get('/scenes')
    return resp.data as SceneInfo[]
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

export async function createScene(name: string, steps: string[]): Promise<SceneInfo> {
  try {
    const resp = await http.post('/scenes', { name, steps })
    return resp.data as SceneInfo
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

export async function toggleScene(id: number, enabled: boolean): Promise<SceneInfo> {
  try {
    const resp = await http.put(`/scenes/${id}`, { enabled })
    return resp.data as SceneInfo
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

export async function deleteScene(id: number): Promise<void> {
  try {
    await http.delete(`/scenes/${id}`)
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

export async function runScene(id: number): Promise<SceneRunResult[]> {
  try {
    const resp = await http.post(`/scenes/${id}/run`)
    return resp.data as SceneRunResult[]
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}
