import { http, getErrorMessage } from './http'
import type { BriefingConfig } from './types'

export async function getBriefing(): Promise<BriefingConfig> {
  try {
    const resp = await http.get('/briefing')
    return resp.data as BriefingConfig
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

export async function saveBriefing(data: BriefingConfig): Promise<BriefingConfig> {
  try {
    const resp = await http.put('/briefing', data)
    return resp.data as BriefingConfig
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}
