import { http, getErrorMessage } from './http'

export interface MarketSkill {
  id: number
  slug: string
  title: string
  description: string
  author: string
}

export interface InstallResult {
  id: number
  slug: string
  title: string
  description: string
  status: string
  required_keys: Record<string, string>
  message: string
}

/** 技能市场：浏览所有用户已上线（approved）的技能。 */
export async function listMarketSkills(): Promise<MarketSkill[]> {
  try {
    const resp = await http.get('/market/skills')
    return resp.data as MarketSkill[]
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

/** 导出技能 JSON 包（code / tests / description）。 */
export async function exportSkill(id: number): Promise<unknown> {
  try {
    const resp = await http.get(`/market/skills/${id}/export`)
    return resp.data
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

/** 安装他人技能：门禁 + 沙箱重验 → 复制为本用户提案 → 批准上线。 */
export async function installSkill(id: number): Promise<InstallResult> {
  try {
    const resp = await http.post(`/market/skills/${id}/install`)
    return resp.data as InstallResult
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}
