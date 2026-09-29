// 块视图工厂：为每种块生成展示 HTML（结果 LRU 缓存），
// 并在块挂载后绑定交互（复制按钮、Mermaid 异步渲染、TOC、表格控制器）。

import katex from 'katex'
import { parse as parseYaml } from 'yaml'
import { LRU } from '../core/lru'
import {
  escapeHtml,
  highlight,
  sanitizeHtml,
  type MarkdownEngine
} from '../services/markdown'
import { extractHeadings, type Block } from './block-model'
import { TableController } from './table-editor'
import { renderMermaid } from './mermaid-diagram'
import type { Lifetime } from '../core/disposable'

export interface BlockRenderCtx {
  docBase: string | null
  mermaidEnabled: boolean
  codeLineNumbers: boolean
  dark: boolean
  headings: ReturnType<typeof extractHeadings>
}

export interface BlockViewCallbacks {
  onTocJump(id: string): void
  onTableChange(index: number, markdown: string): void
  onCellNavigate(index: number, flatPos: number): void
  consumePendingCellEdit(index: number): number | null
}

export class BlockViewFactory {
  private cache = new LRU<string, string>(300)

  constructor(private engine: MarkdownEngine) {}

  invalidate(): void {
    this.cache.clear()
  }

  produce(index: number, b: Block, ctx: BlockRenderCtx): string {
    const key = `${b.id}|${ctx.mermaidEnabled ? 1 : 0}|${ctx.codeLineNumbers ? 1 : 0}|${ctx.docBase ?? ''}`
    const cached = this.cache.get(key)
    if (cached !== undefined) return cached
    const html = this.build(index, b, ctx)
    this.cache.set(key, html)
    return html
  }

  private build(index: number, b: Block, ctx: BlockRenderCtx): string {
    switch (b.type) {
      case 'heading':
        return this.buildHeading(index, b, ctx)
      case 'code':
        return this.buildCode(b, ctx)
      case 'math':
        return this.buildMath(b)
      case 'toc':
        return this.buildToc(ctx)
      case 'frontmatter':
        return this.buildFrontmatter(b)
      case 'hr':
        return '<hr class="md-hr"/>'
      case 'table':
      case 'blockquote':
      case 'list':
      case 'html':
      case 'paragraph':
        return sanitizeHtml(this.engine.md.render(b.raw, { docBase: ctx.docBase }))
    }
  }

  private buildHeading(index: number, b: Block, ctx: BlockRenderCtx): string {
    const level = b.level ?? 1
    const stripped = b.raw.replace(/^\s*#{1,6}\s+/, '').replace(/\s+#+\s*$/, '')
    const info = ctx.headings.find((h) => h.blockIndex === index)
    const id = info?.id ?? stripped
    const inline = this.engine.renderInline(stripped)
    return sanitizeHtml(
      `<h${level} id="${escapeHtml(id)}" class="md-heading md-h${level}">${inline}</h${level}>`
    )
  }

  private buildCode(b: Block, ctx: BlockRenderCtx): string {
    const rawLines = b.raw.split('\n')
    const code = rawLines.slice(1, -1).join('\n')
    const lang = b.lang ?? ''

    if (lang === 'mermaid' && ctx.mermaidEnabled) {
      return '<div class="diagram mermaid-host"><div class="diagram-body">图表渲染中…</div></div>'
    }

    const codeHtml = highlight(code, lang)
    const lineCount = code === '' ? 1 : code.split('\n').length
    const linenos = ctx.codeLineNumbers
      ? `<pre class="code-linenos" aria-hidden="true">${Array.from(
          { length: lineCount },
          (_v, i) => `<span>${i + 1}</span>`
        ).join('\n')}</pre>`
      : ''

    return sanitizeHtml(
      `<div class="code-block" data-linecount="${lineCount}">
        <div class="code-header">
          <span class="code-lang">${escapeHtml(lang || 'text')}</span>
          <button type="button" class="code-copy">复制</button>
        </div>
        <div class="code-main">${linenos}<pre class="code-result"><code>${codeHtml}</code></pre></div>
      </div>`
    )
  }

  private buildMath(b: Block): string {
    let latex: string
    const single = /^\$\$\s*(.+?)\s*\$\$$/.exec(b.raw)
    if (single) {
      latex = single[1]
    } else {
      const lines = b.raw.split('\n')
      if (lines[0]?.trim() === '$$') lines.shift()
      if (lines[lines.length - 1]?.trim() === '$$') lines.pop()
      latex = lines.join('\n')
    }
    try {
      const rendered = katex.renderToString(latex, {
        displayMode: true,
        throwOnError: false,
        strict: false
      })
      return `<div class="math-block">${rendered}</div>`
    } catch (err) {
      return `<div class="math-block math-error">公式错误：${escapeHtml(String(err))}</div>`
    }
  }

  private buildToc(ctx: BlockRenderCtx): string {
    const items = ctx.headings
      .map(
        (h) =>
          `<li class="toc-item toc-l${h.level}" style="padding-left:${(h.level - 1) * 14}px">` +
          `<a class="toc-link" data-toc-id="${escapeHtml(h.id)}">${escapeHtml(h.text)}</a></li>`
      )
      .join('')
    return sanitizeHtml(
      `<nav class="toc-block"><div class="toc-title">目录</div><ul class="toc-list">${items}</ul></nav>`
    )
  }

  private buildFrontmatter(b: Block): string {
    const inner = b.raw.split('\n').slice(1, -1).join('\n')
    let body: string
    try {
      const obj = parseYaml(inner)
      if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
        body = Object.entries(obj)
          .map(
            ([k, v]) =>
              `<div class="fm-row"><dt>${escapeHtml(k)}</dt>` +
              `<dd>${escapeHtml(formatYamlValue(v))}</dd></div>`
          )
          .join('')
      } else {
        body = `<dd>${escapeHtml(inner)}</dd>`
      }
    } catch (err) {
      body = `<div class="fm-error">YAML 解析错误：${escapeHtml(
        err instanceof Error ? err.message : String(err)
      )}</div>`
    }
    return sanitizeHtml(
      `<div class="fm-block"><div class="fm-header">YAML Front Matter</div><dl class="fm-body">${body}</dl></div>`
    )
  }

  /** 挂载后绑定交互；所有监听登记到行级 Lifetime，卸载即清 */
  postProcess(
    root: HTMLElement,
    b: Block,
    index: number,
    rowLt: Lifetime,
    signal: AbortSignal,
    cb: BlockViewCallbacks,
    docBase: string | null,
    dark: boolean
  ): void {
    // 复制按钮
    for (const btn of root.querySelectorAll<HTMLButtonElement>('.code-copy')) {
      rowLt.on(btn, 'click', () => {
        const codeText = btn.closest('.code-block')?.querySelector('code')?.textContent ?? ''
        navigator.clipboard.writeText(codeText).then(() => {
          btn.textContent = '已复制'
          setTimeout(() => (btn.textContent = '复制'), 1500)
        })
      })
    }

    // Mermaid 异步渲染（signal 取消后丢弃结果）
    const host = root.querySelector<HTMLElement>('.mermaid-host')
    if (host) {
      const code = b.raw.split('\n').slice(1, -1).join('\n')
      void renderMermaid(host, code, dark ? 'dark' : 'light', signal)
    }

    // TOC 跳转
    for (const link of root.querySelectorAll<HTMLElement>('.toc-link')) {
      rowLt.on(link, 'click', () => {
        const id = link.dataset.tocId
        if (id) cb.onTocJump(id)
      })
    }

    // 表格可视化控制器
    for (const table of root.querySelectorAll<HTMLTableElement>('table')) {
      const controller = new TableController(
        table,
        rowLt,
        (md) => cb.onTableChange(index, md),
        (flatPos) => cb.onCellNavigate(index, flatPos)
      )
      // 表格重建后恢复 Tab 导航的目标单元格编辑
      const pending = cb.consumePendingCellEdit(index)
      if (pending !== null) controller.editCellAt(pending)
    }

    void docBase
  }
}

function formatYamlValue(v: unknown): string {
  if (v === null) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
