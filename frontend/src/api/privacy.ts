import { http, getErrorMessage } from './http'

export interface PurgeResult {
  purged_user_id: number
  receipt: Record<string, number>
}

/** 数据主权：导出当前用户全部数据（记忆/画像/会话/提案/任务等单份 JSON）。 */
export async function exportData(): Promise<unknown> {
  try {
    const resp = await http.get('/privacy/export')
    return resp.data
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

/** 数据主权：彻底清除当前用户全部数据，需显式 confirm=DELETE；返回各表行数收据。 */
export async function purgeData(): Promise<PurgeResult> {
  try {
    const resp = await http.delete('/privacy/purge', { data: { confirm: 'DELETE' } })
    return resp.data as PurgeResult
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}
