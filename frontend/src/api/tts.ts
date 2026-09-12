import { http } from './http'

export async function tts(text: string, voice?: string): Promise<Blob> {
  try {
    const resp = await http.post(
      '/tts',
      { text, voice: voice ?? 'zh-CN-XiaoxiaoNeural' },
      // 8 秒超时：edge-tts 走微软服务器国内偶发慢请求，超时即回退浏览器语音，
      // 绝不让播报链路挂住几十秒
      { responseType: 'blob', timeout: 8000 },
    )
    return resp.data as Blob
  } catch {
    // blob 错误响应时 error.response.data 可能是 Blob 而非对象，无法读取 detail，统一抛固定文案
    throw new Error('语音合成失败')
  }
}
