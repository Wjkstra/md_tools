// 文档块模型：将整篇 Markdown 切分为独立块，供虚拟化与按块编辑使用。
// 规范文本（gaps 保留块间换行）= 各块 raw 按 gaps 拼接，保证编辑可逆。

export type BlockType =
  | 'frontmatter'
  | 'code'
  | 'math'
  | 'heading'
  | 'blockquote'
  | 'list'
  | 'table'
  | 'hr'
  | 'toc'
  | 'html'
  | 'paragraph'

export interface Block {
  id: string
  type: BlockType
  start: number // 内容起始偏移（含）
  end: number // 内容结束偏移（不含换行）
  raw: string
  lang?: string
  level?: number
}

export interface DocModel {
  text: string
  blocks: Block[]
  gaps: number[]
}

interface HeadingInfo {
  level: number
  text: string
  id: string
  blockIndex: number
}

const FENCE_RE = /^(\s{0,3})(`{3,}|~{3,})\s*([^\n]*)$/
const MATH_LINE_RE = /^\s*\$\$\s*$/
const MATH_INLINE_LINE_RE = /^\$\$\s*.+\s*\$\$\s*$/
const HR_RE = /^\s{0,3}(?:(?:-\s+){2,}-|(?:\*\s+){2,}\*|(?:_\s+){2,}_)[ \t]*$/
const HR_SINGLE_RE = /^\s{0,3}(-{3,}|\*{3,}|_{3,})[ \t]*$/
const TOC_RE = /^\s*\[toc\]\s*$/i
const HEADING_RE = /^\s{0,3}(#{1,6})(?:[ \t]+(.*))?$/
const QUOTE_RE = /^\s{0,3}>/
const LIST_RE = /^(\s{0,3})([-+*]|\d{1,9}[.)])([ \t]+|$)/
const TABLE_DELIM_RE = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/
const HTML_START_RE = /^\s*<(?:!--|!DOCTYPE|\?|\/?[A-Za-z][\w:-]*(?:\s|\/?>))/i

function fnv1a(s: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(36)
}

export function blockHash(type: BlockType, raw: string, lang?: string): string {
  return fnv1a(`${type}|${lang ?? ''}|${raw}`)
}

export function buildModel(text: string): DocModel {
  // 切行：记录每行起始偏移；去掉行尾 \r
  const lineStarts: number[] = []
  const lineTexts: string[] = []
  let pos = 0
  while (pos <= text.length) {
    lineStarts.push(pos)
    let nl = text.indexOf('\n', pos)
    if (nl === -1) nl = text.length
    let line = text.slice(pos, nl)
    if (line.endsWith('\r')) line = line.slice(0, -1)
    lineTexts.push(line)
    if (nl === text.length) break
    pos = nl + 1
  }
  const n = lineTexts.length

  const ranges: { a: number; b: number; type: BlockType; lang?: string; level?: number }[] = []

  const first = 0
  // 1. YAML front matter：文档起始的 --- 围栏
  let cursor = 0
  if (lineTexts[0] === '---') {
    let close = -1
    for (let j = 1; j < n; j++) {
      if (lineTexts[j] === '---' || lineTexts[j] === '...') {
        close = j
        break
      }
      if (lineTexts[j] === '') break
    }
    if (close > 0) {
      ranges.push({ a: 0, b: close + 1, type: 'frontmatter' })
      cursor = close + 1
    }
  }
  void first

  const isBlank = (i: number): boolean => lineTexts[i] === '' || /^\s+$/.test(lineTexts[i])

  const nextNonBlank = (i: number): number => {
    let k = i
    while (k < n && isBlank(k)) k++
    return k
  }

  while (cursor < n) {
    if (isBlank(cursor)) {
      cursor++
      continue
    }
    const line = lineTexts[cursor]

    // 围栏代码块
    const fence = FENCE_RE.exec(line)
    if (fence) {
      const marker = fence[2][0]
      const len = fence[2].length
      let close = cursor + 1
      while (close < n) {
        const m = /^(\s{0,3})(`{3,}|~{3,})\s*$/.exec(lineTexts[close])
        if (m && m[2][0] === marker && m[2].length >= len) {
          close++
          break
        }
        close++
      }
      const lang = (fence[3] ?? '').trim().split(/\s+/)[0] ?? ''
      ranges.push({ a: cursor, b: close, type: 'code', lang: lang || undefined })
      cursor = close
      continue
    }

    // 数学块
    if (MATH_INLINE_LINE_RE.test(line)) {
      ranges.push({ a: cursor, b: cursor + 1, type: 'math' })
      cursor++
      continue
    }
    if (MATH_LINE_RE.test(line)) {
      let close = cursor + 1
      while (close < n && !/^\s*\$\$\s*$/.test(lineTexts[close])) close++
      close = Math.min(close + 1, n) // 含闭合行；未闭合则吃到文末
      ranges.push({ a: cursor, b: close, type: 'math' })
      cursor = close
      continue
    }

    // 分隔线
    if (HR_RE.test(line) || HR_SINGLE_RE.test(line)) {
      ranges.push({ a: cursor, b: cursor + 1, type: 'hr' })
      cursor++
      continue
    }

    // TOC
    if (TOC_RE.test(line)) {
      ranges.push({ a: cursor, b: cursor + 1, type: 'toc' })
      cursor++
      continue
    }

    // ATX 标题
    const heading = HEADING_RE.exec(line)
    if (heading) {
      ranges.push({ a: cursor, b: cursor + 1, type: 'heading', level: heading[1].length })
      cursor++
      continue
    }

    // 引用块（允许中间夹空行后继续）
    if (QUOTE_RE.test(line)) {
      let j = cursor + 1
      while (j < n) {
        if (QUOTE_RE.test(lineTexts[j])) {
          j++
        } else if (isBlank(j)) {
          const k = nextNonBlank(j)
          if (k < n && QUOTE_RE.test(lineTexts[k])) j++
          else break
        } else break
      }
      ranges.push({ a: cursor, b: j, type: 'blockquote' })
      cursor = j
      continue
    }

    // 列表（含任务列表）
    if (LIST_RE.test(line)) {
      let j = cursor + 1
      while (j < n) {
        if (LIST_RE.test(lineTexts[j])) {
          j++
          continue
        }
        if (/^\s+\S/.test(lineTexts[j])) {
          j++ // 缩进续行（懒续行 / 嵌套）
          continue
        }
        if (isBlank(j)) {
          const k = nextNonBlank(j)
          if (k < n && (LIST_RE.test(lineTexts[k]) || /^\s+\S/.test(lineTexts[k]))) {
            j++ // 松散列表：保留空行
            continue
          }
          break
        }
        break
      }
      ranges.push({ a: cursor, b: j, type: 'list' })
      cursor = j
      continue
    }

    // 表格
    if (line.includes('|') && cursor + 1 < n && TABLE_DELIM_RE.test(lineTexts[cursor + 1])) {
      let j = cursor + 2
      while (j < n && !isBlank(j) && lineTexts[j].includes('|')) j++
      ranges.push({ a: cursor, b: j, type: 'table' })
      cursor = j
      continue
    }

    // HTML 块：吃到空行
    if (HTML_START_RE.test(line)) {
      let j = cursor + 1
      while (j < n && !isBlank(j)) j++
      ranges.push({ a: cursor, b: j, type: 'html' })
      cursor = j
      continue
    }

    // 段落：吃到空行或新块起点
    let j = cursor + 1
    while (j < n && !isBlank(j)) {
      const l = lineTexts[j]
      if (
        FENCE_RE.test(l) ||
        MATH_LINE_RE.test(l) ||
        MATH_INLINE_LINE_RE.test(l) ||
        HR_RE.test(l) ||
        HR_SINGLE_RE.test(l) ||
        TOC_RE.test(l) ||
        HEADING_RE.test(l) ||
        QUOTE_RE.test(l) ||
        LIST_RE.test(l) ||
        HTML_START_RE.test(l)
      )
        break
      // 表格起点
      if (l.includes('|') && j + 1 < n && TABLE_DELIM_RE.test(lineTexts[j + 1])) break
      j++
    }
    ranges.push({ a: cursor, b: j, type: 'paragraph' })
    cursor = j
  }

  // 转换范围 → Block（含偏移、raw、id）
  const blocks: Block[] = []
  if (ranges.length === 0) {
    const empty: Block = {
      id: blockHash('paragraph', ''),
      type: 'paragraph',
      start: 0,
      end: 0,
      raw: ''
    }
    return { text, blocks: [empty], gaps: [0] }
  }

  for (const r of ranges) {
    const start = lineStarts[r.a]
    const lastLine = lineTexts[r.b - 1]
    const end = lineStarts[r.b - 1] + lastLine.length
    const raw = text.slice(start, end)
    blocks.push({
      id: blockHash(r.type, raw, r.lang),
      type: r.type,
      start,
      end,
      raw,
      lang: r.lang,
      level: r.level
    })
  }

  // gaps：相邻块内容之间的换行数
  const gaps: number[] = []
  for (let i = 0; i < blocks.length; i++) {
    const from = blocks[i].end
    const to = i + 1 < blocks.length ? blocks[i + 1].start : text.length
    let count = 0
    for (let k = from; k < to; k++) if (text[k] === '\n') count++
    gaps.push(count)
  }

  return { text, blocks, gaps }
}

export function serialize(model: DocModel): string {
  let out = ''
  for (let i = 0; i < model.blocks.length; i++) {
    out += model.blocks[i].raw
    out += '\n'.repeat(model.gaps[i] ?? 0)
  }
  return out
}

/** 根据偏移定位块索引（offset 落在块内容或其后的间隙时归属该块） */
export function findBlockIndex(model: DocModel, offset: number): number {
  let lo = 0
  let hi = model.blocks.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (model.blocks[mid].start <= offset) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** 粗略行高估算，用于首屏前的占位高度，渲染后以实测为准 */
export function estimateHeight(b: Block): number {
  const lines = b.raw === '' ? 1 : b.raw.split('\n').length
  switch (b.type) {
    case 'heading':
      return b.level && b.level <= 3 ? 52 : 44
    case 'hr':
      return 34
    case 'toc':
      return 180
    case 'code':
    case 'frontmatter':
      return lines * 22 + 34
    case 'math':
      return lines * 26 + 24
    case 'html':
      return lines * 22 + 16
    case 'blockquote':
      return lines * 30 + 18
    case 'list':
      return lines * 32 + 14
    case 'table':
      return lines * 34 + 18
    case 'paragraph': {
      const approxLines = Math.max(1, Math.ceil(b.raw.length / 46))
      return approxLines * 28 + 16
    }
  }
}

/** 提取标题（去内联标记），供大纲与 TOC 使用 */
export function extractHeadings(model: DocModel): HeadingInfo[] {
  const result: HeadingInfo[] = []
  const used = new Set<string>()
  model.blocks.forEach((b, blockIndex) => {
    if (b.type !== 'heading' || !b.level) return
    const text = b.raw
      .replace(/^\s*#{1,6}\s+/, '')
      .replace(/\s+#+\s*$/, '')
      .replace(/[*_`~]/g, '')
      .trim()
    let id = slugify(text)
    let n = 1
    while (used.has(id)) id = `${slugify(text)}-${++n}`
    used.add(id)
    result.push({ level: b.level, text, id, blockIndex })
  })
  return result
}

export function slugify(text: string): string {
  return (
    text
      .trim()
      .toLowerCase()
      .replace(/[&<>"'`=\/\\|!?.,:;()[\]{}]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '') || 'section'
  )
}
