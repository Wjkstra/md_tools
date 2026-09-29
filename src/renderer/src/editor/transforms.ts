// 编辑期结构变换：回车拆分、退格合并、列表缩进、标记符号空格触发、选区包裹。
// 全部为纯函数，返回 {text, caret}，由 LiveEditor 统一落到规范文本。

import type { BlockType } from './block-model'

export interface TransformResult {
  text: string
  caret: number
}

interface LineInfo {
  lines: string[]
  lineIndex: number
  col: number
}

function locate(raw: string, offset: number): LineInfo {
  const lines = raw.split('\n')
  let lineIndex = 0
  let acc = 0
  for (let i = 0; i < lines.length; i++) {
    const end = acc + lines[i].length
    if (offset <= end) {
      lineIndex = i
      break
    }
    acc = end + 1
    lineIndex = i
  }
  const lineStart = lines.slice(0, lineIndex).reduce((s, l) => s + l.length + 1, 0)
  return { lines, lineIndex, col: Math.max(0, offset - lineStart) }
}

// ---------------- 回车拆分 ----------------

export function splitAt(raw: string, type: BlockType, offset: number): TransformResult {
  const info = locate(raw, offset)
  const { lines, lineIndex } = info
  const line = lines[lineIndex]

  if (type === 'list') {
    const m = /^(\s*)([-+*]|\d{1,9}[.)])(\s+)(.*)$/.exec(line)
    // 空项：回车将该项转为普通段落（移除标记）
    if (m && m[4] === '') {
      lines[lineIndex] = ''
      const text = lines.join('\n')
      return { text, caret: text.split('\n').slice(0, lineIndex).reduce((s, l) => s + l.length + 1, 0) }
    }
    if (m) {
      const indent = m[1]
      let marker = m[2]
      const num = /^\d+/.exec(marker)
      if (num) marker = `${parseInt(num[0], 10) + 1}${marker.includes('.') ? '.' : ')'}`
      lines[lineIndex] = line
      lines.splice(lineIndex + 1, 0, `${indent}${marker} `)
      const text = lines.join('\n')
      const caret =
        lines.slice(0, lineIndex + 1).reduce((s, l) => s + l.length + 1, 0)
      return { text, caret }
    }
  }

  if (type === 'blockquote') {
    const m = /^(\s*)>\s?/.exec(line)
    const prefix = m ? `${m[1]}> ` : '> '
    lines.splice(lineIndex + 1, 0, prefix)
    const text = lines.join('\n')
    return { text, caret: lines.slice(0, lineIndex + 1).reduce((s, l) => s + l.length + 1, 0) }
  }

  if (type === 'heading') {
    // 标题后新建普通段落
    lines.splice(lineIndex + 1, 0, '')
    const text = lines.join('\n')
    return { text, caret: lines.slice(0, lineIndex + 1).reduce((s, l) => s + l.length + 1, 0) }
  }

  // 段落及其余类型：朴素换行
  const before = raw.slice(0, offset)
  const after = raw.slice(offset)
  return { text: `${before}\n${after}`, caret: offset + 1 }
}

// ---------------- 行首退格：合并到上一块 ----------------

export function mergeWith(prevRaw: string, raw: string): TransformResult {
  const text = `${prevRaw}\n${raw}`
  return { text, caret: prevRaw.length + 1 }
}

// ---------------- 列表缩进 / 取消缩进 ----------------

export function indentLine(raw: string, offset: number, tabSize: number, outdent: boolean): TransformResult {
  const info = locate(raw, offset)
  const { lines, lineIndex } = info
  const line = lines[lineIndex]

  if (outdent) {
    lines[lineIndex] = line.replace(/^ {1,4}|\t/, '')
  } else {
    lines[lineIndex] = `${' '.repeat(tabSize)}${line}`
  }
  const text = lines.join('\n')
  const lineStart = lines.slice(0, lineIndex).reduce((s, l) => s + l.length + 1, 0)
  return { text, caret: lineStart + lines[lineIndex].length }
}

// ---------------- 空格触发 Markdown 标记 ----------------

const TRIGGERS: { re: RegExp; build: (line: string) => { text: string; caret: number } | null }[] = [
  {
    re: /^\s{0,3}#{1,6} $/,
    build: (line) => ({ text: line, caret: line.length })
  },
  {
    re: /^\s{0,3}>\s$/,
    build: (line) => ({ text: line, caret: line.length })
  },
  {
    re: /^\s{0,3}[-+*] $/,
    build: (line) => ({ text: line, caret: line.length })
  },
  {
    re: /^\s{0,3}\d{1,9}[.)] $/,
    build: (line) => ({ text: line, caret: line.length })
  },
  {
    re: /^\s{0,3}[-+*]\s\[[ xX]\] $/,
    build: (line) => ({ text: line, caret: line.length })
  },
  {
    re: /^(\s{0,3})```\s*([\w+-]*)$/,
    build: (line) => {
      const m = /^(\s{0,3})```\s*([\w+-]*)$/.exec(line)!
      const text = `${line}\n\n${m[1]}\`\`\``
      return { text, caret: line.length + 1 }
    }
  },
  {
    re: /^\s{0,3}~~\s*$/,
    build: () => ({ text: `$$\n\n$$`, caret: 3 })
  }
]

/** 在 offset 处刚输入空格时检测；返回整块新文本与光标 */
export function detectSpaceTrigger(raw: string, offset: number): TransformResult | null {
  const info = locate(raw, offset)
  const { lines, lineIndex } = info
  const line = lines[lineIndex]
  for (const t of TRIGGERS) {
    if (t.re.test(line)) {
      const r = t.build(line)
      if (!r) continue
      lines[lineIndex] = r.text
      const prefixText = lines.slice(0, lineIndex).join('\n')
      const prefixLen = lineIndex === 0 ? 0 : prefixText.length + 1
      return { text: lines.join('\n'), caret: prefixLen + r.caret }
    }
  }
  return null
}

// ---------------- 行内标记包裹 ----------------

export function wrapSelection(
  raw: string,
  selStart: number,
  selEnd: number,
  marker: string,
  placeholder = ''
): TransformResult & { selStart: number; selEnd: number } {
  const selected = raw.slice(selStart, selEnd)
  if (selected) {
    const text = `${raw.slice(0, selStart)}${marker}${selected}${marker}${raw.slice(selEnd)}`
    return {
      text,
      caret: selEnd + marker.length * 2,
      selStart: selStart + marker.length,
      selEnd: selEnd + marker.length
    }
  }
  const inner = placeholder || ''
  const text = `${raw.slice(0, selStart)}${marker}${inner}${marker}${raw.slice(selEnd)}`
  return {
    text,
    caret: selStart + marker.length + inner.length,
    selStart: selStart + marker.length,
    selEnd: selStart + marker.length + inner.length
  }
}

/** 在指定偏移插入文本（图片/链接插入等） */
export function insertAt(raw: string, offset: number, insertion: string): TransformResult {
  return {
    text: `${raw.slice(0, offset)}${insertion}${raw.slice(offset)}`,
    caret: offset + insertion.length
  }
}
