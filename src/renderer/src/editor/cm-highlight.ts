// CodeMirror 语法高亮配色（GitHub 明暗风格）

import { HighlightStyle } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

export const gfmHighlightStyle = HighlightStyle.define([
  { tag: t.heading, color: '#1f2328', fontWeight: 'bold' },
  { tag: t.heading1, fontSize: '1.5em' },
  { tag: t.heading2, fontSize: '1.3em' },
  { tag: t.heading3, fontSize: '1.15em' },
  { tag: t.emphasis, fontStyle: 'italic' },
  { tag: t.strong, fontWeight: 'bold' },
  { tag: t.strikethrough, textDecoration: 'line-through' },
  { tag: t.keyword, color: '#cf222e' },
  { tag: t.atom, color: '#0550ae' },
  { tag: t.bool, color: '#0550ae' },
  { tag: t.url, color: '#0969da' },
  { tag: t.link, color: '#0969da' },
  { tag: t.string, color: '#0a3069' },
  { tag: t.comment, color: '#6e7781', fontStyle: 'italic' },
  { tag: t.meta, color: '#6e7781' },
  { tag: t.processingInstruction, color: '#cf222e' },
  { tag: t.list, color: '#24292f' },
  { tag: t.quote, color: '#57606a', fontStyle: 'italic' },
  { tag: t.monospace, color: '#953800' },
  { tag: t.invalid, color: '#cf222e' }
])

export const gfmDarkHighlightStyle = HighlightStyle.define([
  { tag: t.heading, color: '#e6edf3', fontWeight: 'bold' },
  { tag: t.heading1, fontSize: '1.5em' },
  { tag: t.heading2, fontSize: '1.3em' },
  { tag: t.heading3, fontSize: '1.15em' },
  { tag: t.emphasis, fontStyle: 'italic' },
  { tag: t.strong, fontWeight: 'bold' },
  { tag: t.strikethrough, textDecoration: 'line-through' },
  { tag: t.keyword, color: '#ff7b72' },
  { tag: t.atom, color: '#79c0ff' },
  { tag: t.bool, color: '#79c0ff' },
  { tag: t.url, color: '#79c0ff' },
  { tag: t.link, color: '#79c0ff' },
  { tag: t.string, color: '#a5d6ff' },
  { tag: t.comment, color: '#8b949e', fontStyle: 'italic' },
  { tag: t.meta, color: '#8b949e' },
  { tag: t.processingInstruction, color: '#ff7b72' },
  { tag: t.list, color: '#c9d1d9' },
  { tag: t.quote, color: '#8b949e', fontStyle: 'italic' },
  { tag: t.monospace, color: '#ffa657' },
  { tag: t.invalid, color: '#ff7b72' }
])
