// 字数 / 字符 / 行数 / 阅读时长统计。针对规范文本（含标记）做轻量清洗。

export interface DocStats {
  chars: number // 总字符（不含换行）
  charsNoSpaces: number
  words: number // 英文单词 + CJK 单字
  lines: number
  readingMinutes: number
}

export function countStats(text: string): DocStats {
  const chars = text.replace(/\s/g, '').length
  const charsNoSpaces = text.replace(/\s/g, '').length

  const lines = text === '' ? 1 : text.split('\n').length

  const cjk = text.match(/[一-鿿㐀-䶿぀-ヿ가-힯]/g)?.length ?? 0
  const latinWords =
    text.match(/[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*/g)?.length ?? 0

  const words = cjk + latinWords
  // 中文约 400 字/分钟，英文约 240 词/分钟
  const readingMinutes = Math.max(1, Math.round(cjk / 400 + latinWords / 240))

  return { chars, charsNoSpaces, words, lines, readingMinutes }
}
