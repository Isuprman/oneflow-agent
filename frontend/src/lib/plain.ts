// 文本净化：把 Markdown 回复转成适合 TTS 朗读与右上角回显的纯文本。
// 去掉 Markdown 语法符号、emoji 与多余空白，保留中文/字母/数字/常用标点。
// 不依赖任何第三方库。

/**
 * 常见 emoji / 符号 / 象形 / 装饰类 Unicode 区段：
 * - U+1F000–U+1FAFF：表情、象形、交通、旗帜等主要 emoji 区段
 * - U+2600–U+27BF：杂项符号 + 装饰符号（☀★♠♥✦✂ 等）
 * - U+2B00–U+2BFF：杂项符号与箭头（⭐⭕ 等）
 * - U+2300–U+23FF：杂项技术符号（⌚⌛⏰ 等）
 * - U+25A0–U+25FF：几何图形（▪▸▶● 等常见列表圆点）
 * - U+2190–U+21FF：箭头（←↑→ 等）
 * - U+FE00–U+FE0F：变体选择符
 * - U+20E3 / U+200D：组合键帽符 / 零宽连接符
 */
const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2300}-\u{23FF}\u{25A0}-\u{25FF}\u{2190}-\u{21FF}\u{FE00}-\u{FE0F}\u{20E3}\u{200D}]/gu

/** 剔除文本中的常见 emoji 与符号（可复用）。 */
export function stripEmoji(text: string): string {
  return text.replace(EMOJI_RE, '')
}

/** 把 Markdown 回复转成纯文本：去标题符/强调符/代码符/列表符/链接/emoji，供朗读与回显。 */
export function toPlainText(text: string): string {
  return (
    stripEmoji(text)
      // [文字](链接) → 只留「文字」
      .replace(/\[([^\]]*)\]\([^)\s]*\)/g, '$1')
      // 裸链接：去掉 http(s):// 与 www. 前缀，避免朗读出一串 http://
      .replace(/https?:\/\/(?:www\.)?/gi, '')
      // 强调与代码符：** * _ ` 全部清掉（单个/成对滥用都不留星号）
      .replace(/[*_`]+/g, '')
      // 行首列表符：- / + / • / ◦ / · / 1. / 1)（去列表符、保留内容文本）
      .replace(/^\s*(?:[-+•◦·]\s+|\d+[.)]\s*)/gm, '')
      // 行首标题符：# / ## …（最多 6 级，带不带空格都清）
      .replace(/^\s*#{1,6}\s*/gm, '')
      // 行尾闭合的标题符（如 `标题 ###`）
      .replace(/\s*#{1,6}\s*$/gm, '')
      // 分隔线 `---`（`***`/`___` 已被强调符规则清掉）
      .replace(/^\s*-{3,}\s*$/gm, '')
      // 行尾多余空白
      .replace(/[ \t]+$/gm, '')
      // 行首多余空白（`* 项目` 的 `*` 已被强调符规则清掉，清掉残留缩进）
      .replace(/^[ \t]+/gm, '')
      // 常见不可见字符：不间断空格/零宽空格/BOM
      .replace(/[\u00A0\u200B\uFEFF]/g, '')
      // 连续空白合并为单个空格，再首尾去空白
      .replace(/[ \t]{2,}/g, ' ')
      .trim()
  )
}
