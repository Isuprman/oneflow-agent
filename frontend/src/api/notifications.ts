import { http } from './http'
import type { AppNotification } from './types'

/** 拉取主动通知（默认仅未读；unreadOnly=false 拉全部历史），最新在前。 */
export async function listNotifications(unreadOnly = true): Promise<AppNotification[]> {
  try {
    const resp = await http.get('/notifications', { params: { unread: unreadOnly } })
    return resp.data as AppNotification[]
  } catch {
    // 轮询场景：网络抖动静默返回空，下一轮重试
    return []
  }
}

export async function markNotificationRead(id: number): Promise<void> {
  try {
    await http.post(`/notifications/${id}/read`)
  } catch {
    // 标记失败不影响展示，忽略
  }
}

export async function deleteNotification(id: number): Promise<void> {
  try {
    await http.delete(`/notifications/${id}`)
  } catch {
    // 删除失败静默，下一轮刷新自然对齐
  }
}
