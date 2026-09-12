import axios from 'axios'

// 全局唯一 axios 实例：各域文件（auth/chat/learn…）共用，统一挂 /api 前缀与鉴权头
export const http = axios.create({
  baseURL: '/api',
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('oneflow_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 后端错误响应统一是 {detail: "..."}；转成可 throw 的 Error 文案
export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data?.detail ?? error.message
  }
  return '网络请求失败，请稍后重试'
}
