// 设置页各区块共用的小工具（纯函数，无状态）

export function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}

export function truncateText(text: string, max = 60) {
  return text.length > max ? `${text.slice(0, max)}…` : text
}
