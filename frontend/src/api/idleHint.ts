import { http } from './http'
import type { IdleHint } from './types'

/** 闲置轻推话题：无话可说时返回 {topic: null, text: null}。 */
export async function getIdleHint(): Promise<IdleHint | null> {
  try {
    const resp = await http.get('/idle-hint')
    return resp.data as IdleHint
  } catch {
    return null
  }
}
