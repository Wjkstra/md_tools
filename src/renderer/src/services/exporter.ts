// 导出器：构建独立 HTML（内联全部 CSS），并替换 Mermaid 围栏为渲染结果；
// PDF / 图片交主进程离屏窗口；Pandoc 通道支持 docx/ePub/LaTeX/odt。

import {
  createMarkdownEngine,
  sanitizeHtml,
  type MarkdownEngine
} from './markdown'
import { buildModel, extractHeadings } from '../editor/block-model'
import { renderMermaid } from '../editor/mermaid-diagram'
import { isDarkTheme } from '../editor/live-editor'
import type { PdfExportOptions, ImageExportOptions } from '@shared/types'

export interface StandaloneOptions {
  includeToc: boolean
}

/** 收集当前页面的全部 CSS 文本（同源样式表） */
function collectPageCss(): string {
  const parts: string[] = []
  for (const sheet of document.styleSheets) {
    try {
      const rules = sheet.cssRules
      if (!rules) continue
      for (const rule of rules) parts.push(rule.cssText)
    } catch {
      // 跨域样式表跳过
    }
  }
  return parts.join('\n')
}

function tocHtml(markdown: string): string {
  const headings = extractHeadings(buildModel(markdown))
  if (headings.length === 0) return ''
  const items = headings
    .map(
      (h) =>
        `<li class="toc-item toc-l${h.level}" style="padding-left:${(h.level - 1) * 14}px">` +
        `<a href="#${h.id}">${h.text}</a></li>`
    )
    .join('')
  return `<nav class="export-toc"><div class="toc-title">目录</div><ul class="toc-list">${items}</ul></nav>`
}

/** 将 HTML 中 Mermaid 围栏替换为已渲染图表 */
async function replaceMermaidFences(container: HTMLElement, dark: boolean): Promise<void> {
  const nodes = container.querySelectorAll('code.language-mermaid')
  for (const codeEl of nodes) {
    const pre = codeEl.closest('pre')
    if (!pre) continue
    const wrapper = document.createElement('div')
    wrapper.className = 'diagram'
    pre.insertAdjacentElement('beforebegin', wrapper)
    pre.remove()
    wrapper.innerHTML = '<div class="diagram-body">渲染中…</div>'
    await renderMermaid(wrapper, codeEl.textContent ?? '', dark ? 'dark' : 'light')
  }
}

export async function buildStandaloneHtml(
  markdown: string,
  opts: StandaloneOptions,
  engine?: MarkdownEngine
): Promise<string> {
  const eng = engine ?? createMarkdownEngine()
  const rendered = eng.md.render(markdown, { docBase: null })

  const tpl = document.createElement('template')
  tpl.innerHTML = rendered
  const theme = document.documentElement.dataset.theme ?? 'github-light'
  await replaceMermaidFences(tpl.content as unknown as HTMLElement, isDarkTheme(theme))

  const bodyHtml = sanitizeHtml(tpl.innerHTML)
  const css = collectPageCss()
  const toc = opts.includeToc ? tocHtml(markdown) : ''

  return `<!doctype html>
<html lang="zh-CN" data-theme="${theme}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>导出文档</title>
<style>
${css}
body { max-width: 900px; margin: 40px auto; padding: 0 24px; }
.export-toc { margin: 24px 0 40px; padding: 16px 20px; background: var(--bg-secondary, #f6f8fa); border-radius: 8px; }
.export-toc .toc-list { list-style: none; margin: 0; padding: 0; }
@page { margin: 2cm; }
</style>
</head>
<body>
${toc}
<div class="export-content">${bodyHtml}</div>
</body>
</html>`
}

// ---------------- 通道封装 ----------------

export async function exportHtmlFile(markdown: string, includeToc = false): Promise<boolean> {
  const target = await window.mdnote.showSaveDialog('export.html', [
    { name: 'HTML', extensions: ['html'] }
  ])
  if (!target) return false
  const html = await buildStandaloneHtml(markdown, { includeToc })
  await window.mdnote.exportHtml(target, html)
  return true
}

export async function exportPdfFile(
  markdown: string,
  options: PdfExportOptions,
  includeToc = false
): Promise<boolean> {
  const target = await window.mdnote.showSaveDialog('export.pdf', [
    { name: 'PDF', extensions: ['pdf'] }
  ])
  if (!target) return false
  const html = await buildStandaloneHtml(markdown, { includeToc })
  await window.mdnote.exportPdf(target, html, options)
  return true
}

export async function exportImageFile(
  markdown: string,
  options: ImageExportOptions
): Promise<boolean> {
  const target = await window.mdnote.showSaveDialog(
    options.format === 'jpeg' ? 'export.jpg' : 'export.png',
    [{ name: options.format.toUpperCase(), extensions: [options.format === 'jpeg' ? 'jpg' : 'png'] }]
  )
  if (!target) return false
  const html = await buildStandaloneHtml(markdown, { includeToc: false })
  await window.mdnote.exportImage(target, html, options)
  return true
}

export const PANDOC_FORMATS: { action: string; ext: string; name: string }[] = [
  { action: 'export-docx', ext: 'docx', name: 'Word 文档' },
  { action: 'export-epub', ext: 'epub', name: 'ePub 电子书' },
  { action: 'export-latex', ext: 'tex', name: 'LaTeX' },
  { action: 'export-odt', ext: 'odt', name: 'OpenDocument' }
]

export async function pandocExport(
  markdown: string,
  ext: string,
  withToc: boolean
): Promise<{ ok: boolean; error?: string }> {
  const target = await window.mdnote.showSaveDialog(`export.${ext}`, [
    { name: ext.toUpperCase(), extensions: [ext] }
  ])
  if (!target) return { ok: true } // 用户取消，视为非错误
  return window.mdnote.pandocExport({ markdown, targetPath: target, withToc })
}
