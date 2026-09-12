import { http, getErrorMessage } from './http'
import type { TaskInfo, TaskUpdateIn } from './types'

export async function listTasks(): Promise<TaskInfo[]> {
  try {
    const resp = await http.get('/tasks')
    return resp.data as TaskInfo[]
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function updateTask(id: number, data: TaskUpdateIn): Promise<TaskInfo> {
  try {
    const resp = await http.put(`/tasks/${id}`, data)
    return resp.data as TaskInfo
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function deleteTask(id: number): Promise<void> {
  try {
    await http.delete(`/tasks/${id}`)
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}
