// Markdown 渲染引擎：markdown-it + 行内 KaTeX + GFM 任务列表。
// 所有产物必须经 DOMPurify 净化后才能进入 DOM。

import MarkdownIt from 'markdown-it'
import DOMPurify, { type Config } from 'dompurify'
import katex from 'katex'
import { slugify } from '../editor/block-model'

// ---------------- 语法高亮：全量 highlight.js 按需动态加载（190+ 语言） ----------------

import type { HLJSApi } from 'highlight.js'
let hljsPromise: Promise<unknown> | null = null
let hljs: HLJSApi | null = null

export function warmHighlighter(): void {
  if (!hljsPromise) {
    hljsPromise = import('highlight.js').then((m) => {
      hljs = m.default as HLJSApi
    })
    hljsPromise.catch(() => {
      hljsPromise = null
    })
  }
}

function highlightCode(str: string, lang: string): string {
  return highlight(str, lang)
}

export function highlight(str: string, lang: string): string {
  if (hljs) {
    try {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(str, { language: lang, ignoreIllegals: true }).value
      }
      return hljs.highlightAuto(str).value
    } catch {
      // 落到转义
    }
  }
  return escapeHtml(str)
}

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// ---------------- 引擎构造 ----------------

export interface HeadingAllocator {
  allocate(text: string): string
}

export function createHeadingAllocator(): HeadingAllocator {
  const used = new Set<string>()
  return {
    allocate(text: string) {
      let id = slugify(text)
      let n = 1
      while (used.has(id)) id = `${slugify(text)}-${++n}`
      used.add(id)
      return id
    }
  }
}

export interface MarkdownEngine {
  md: MarkdownIt
  render(raw: string): string
  renderInline(raw: string): string
}

export function createMarkdownEngine(): MarkdownEngine {
  const md = MarkdownIt({
    html: true, // 允许内嵌 HTML，但渲染后由 DOMPurify 强过滤
    linkify: true,
    typographer: false,
    breaks: false,
    highlight: (str, lang) => highlightCode(str, lang || '')
  })

  // 图片：相对路径改走 mdasset 自定义协议（带文档目录），懒加载
  const defaultImageRender =
    md.renderer.rules.image ??
    ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
  md.renderer.rules.image = (tokens, idx, options, env, self) => {
    const src = tokens[idx].attrGet('src') ?? ''
    const docBase = (env as { docBase?: string }).docBase
    if (docBase && !/^(https?:|data:|mdasset:)/i.test(src)) {
      tokens[idx].attrSet(
        'src',
        `mdasset://asset/?base=${encodeURIComponent(docBase)}&src=${encodeURIComponent(src)}`
      )
    }
    tokens[idx].attrSet('loading', 'lazy')
    tokens[idx].attrSet('decoding', 'async')
    return defaultImageRender(tokens, idx, options, env, self)
  }

  // 外链安全属性
  const defaultLinkRender =
    md.renderer.rules.link_open ??
    ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
  md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
    const href = tokens[idx].attrGet('href') ?? ''
    if (/^https?:\/\//i.test(href)) {
      tokens[idx].attrSet('target', '_blank')
      tokens[idx].attrSet('rel', 'noopener noreferrer')
    }
    return defaultLinkRender(tokens, idx, options, env, self)
  }

  // 标题 id（env.allocator 可选，供块级渲染与大纲对齐）
  md.renderer.rules.heading_open = (tokens, idx, options, env, self) => {
    const inline = tokens[idx + 1]
    const allocator = (env as { headingAllocator?: HeadingAllocator }).headingAllocator
    if (inline && allocator) {
      tokens[idx].attrSet('id', allocator.allocate(inline.content))
    }
    return self.renderToken(tokens, idx, options)
  }

  // GFM 任务列表：core 阶段识别 [x]/[ ]，列表项打标
  md.core.ruler.after('inline', 'gfm-task', (state) => {
    const tokens = state.tokens
    for (let i = 1; i < tokens.length - 2; i++) {
      if (
        tokens[i].type === 'paragraph_open' &&
        tokens[i + 1].type === 'inline' &&
        tokens[i - 1].type === 'list_item_open'
      ) {
        const inline = tokens[i + 1]
        const m = /^\[([ xX])\][ \t]*/.exec(inline.content)
        if (m) {
          tokens[i - 1].meta = { taskChecked: m[1].toLowerCase() === 'x' }
          // 从首个文本子节点剥掉标记
          const firstText = inline.children?.find((c) => c.type === 'text')
          if (firstText && firstText.content.startsWith(m[0])) {
            firstText.content = firstText.content.slice(m[0].length)
          }
        }
      }
    }
  })

  md.renderer.rules.list_item_open = (tokens, idx, options, _env, self) => {
    const meta = tokens[idx].meta as { taskChecked?: boolean } | null
    if (meta && typeof meta.taskChecked === 'boolean') {
      tokens[idx].attrJoin('class', 'task-list-item')
      const checked = meta.taskChecked ? 'checked' : ''
      return (
        self.renderToken(tokens, idx, options) +
        `<input class="task-checkbox" type="checkbox" disabled ${checked}/>`
      )
    }
    return self.renderToken(tokens, idx, options)
  }

  // 行内公式 $...$（在 escape 之后，\$ 已被消费；代码块由 backticks 规则整体消费）
  md.inline.ruler.after('escape', 'math_inline', (state, silent) => {
    if (state.src.charCodeAt(state.pos) !== 0x24 /* $ */) return false
    const prevChar = state.src[state.pos - 1]
    if (prevChar && /[\w$]/.test(prevChar)) return false

    let p = state.pos + 1
    let close = -1
    while (p < state.posMax) {
      const code = state.src.charCodeAt(p)
      if (code === 0x5c /* \ */) {
        p += 2
        continue
      }
      if (code === 0x24) {
        close = p
        break
      }
      p++
    }
    if (close === -1) return false
    const content = state.src.slice(state.pos + 1, close)
    if (!content || /^\s|\s$/.test(content)) return false
    const after = state.src[close + 1]
    if (after && /\d/.test(after)) return false // 规避货币场景

    if (!silent) {
      const token = state.push('math_inline', 'span', 0)
      token.markup = '$'
      token.content = content
    }
    state.pos = close + 1
    return true
  })

  md.renderer.rules.math_inline = (tokens, idx) => {
    try {
      return katex.renderToString(tokens[idx].content, {
        displayMode: false,
        throwOnError: false,
        strict: false
      })
    } catch (err) {
      return `<span class="math-error">${escapeHtml(String(err))}</span>`
    }
  }

  return {
    md,
    render(raw: string) {
      return md.render(raw, { headingAllocator: createHeadingAllocator() })
    },
    renderInline(raw: string) {
      return md.renderInline(raw, {})
    }
  }
}

// ---------------- DOMPurify 净化 ----------------

let hooksInstalled = false

function installHooks(): void {
  if (hooksInstalled) return
  hooksInstalled = true

  DOMPurify.addHook('uponSanitizeElement', (node, data) => {
    if (data.tagName === 'input') {
      const type = (node as Element).getAttribute('type')?.toLowerCase()
      if (type !== 'checkbox') (node as ChildNode).remove()
    }
    // 禁止 <script> 以外一切可执行载体：object/embed/iframe 直接移除
    if (['object', 'embed', 'iframe', 'form'].includes(data.tagName)) (node as ChildNode).remove()
  })

  DOMPurify.addHook('uponSanitizeAttribute', (_node, data) => {
    if (data.attrName === 'style') {
      const cleaned = cleanStyle(data.attrValue, false)
      if (cleaned === '') data.keepAttr = false
      else data.attrValue = cleaned
    }
    // 剥掉任何形式的内联事件
    if (/^on/i.test(data.attrName)) data.keepAttr = false
  })
}

function cleanStyle(css: string, allowLocalRef: boolean): string {
  const decls = css.split(';')
  const kept: string[] = []
  for (const decl of decls) {
    const d = decl.trim()
    if (!d) continue
    if (/expression|javascript:|vbscript:|@import|<\/?style/i.test(d)) continue
    const urlMatch = /url\s*\(/i.exec(d)
    if (urlMatch) {
      const refOnly = /url\(\s*#[\w-]+\s*\)/i.test(d)
      if (!(allowLocalRef && refOnly)) continue
    }
    kept.push(d)
  }
  return kept.join('; ')
}

const BASE_CONFIG: Config = {
  ADD_TAGS: ['input', 'details', 'summary', 'abbr', 'mark', 'sub', 'sup', 'ins', 'del'],
  ADD_ATTR: [
    'target',
    'rel',
    'align',
    'id',
    'class',
    'style',
    'checked',
    'disabled',
    'type',
    'colspan',
    'rowspan',
    'col',
    'span',
    'loading',
    'decoding'
  ],
  ALLOW_DATA_ATTR: true,
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel|mdasset|data):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i
}

export function sanitizeHtml(html: string): string {
  installHooks()
  return DOMPurify.sanitize(html, BASE_CONFIG) as string
}

/** Mermaid 生成的 SVG：USE_PROFILES svg；Mermaid 自身 securityLevel=strict 已隔离 */
export function sanitizeSvg(html: string): string {
  installHooks()
  const config: Config = {
    USE_PROFILES: { svg: true, svgFilters: true, html: true }
  }
  return DOMPurify.sanitize(html, config) as string
}
