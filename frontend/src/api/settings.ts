import { http, getErrorMessage } from './http'
import type { HotelConfig, HotelConfigIn, LlmConfig, LlmConfigIn } from './types'

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
