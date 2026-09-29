// Mermaid 图表：首次使用时动态加载，securityLevel=strict 隔离，主题随明暗切换。

import { escapeHtml, sanitizeSvg } from '../services/markdown'

/** 仅声明我们使用到的 Mermaid 接口，避免与库类型耦合 */
export interface MermaidApi {
  initialize(config: unknown): void
  render(id: string, text: string): Promise<{ svg: string }>
}

let cached: MermaidApi | null = null
let initializedTheme = ''
let seq = 0

async function getMermaid(theme: 'light' | 'dark'): Promise<MermaidApi> {
  if (!cached) {
    const mod = await import('mermaid')
    cached = mod.default as unknown as MermaidApi
  }
  if (initializedTheme !== theme) {
    cached.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: theme === 'dark' ? 'dark' : 'neutral',
      fontFamily: 'inherit',
      flowchart: { useMaxWidth: true },
      sequence: { useMaxWidth: true }
    })
    initializedTheme = theme
  }
  return cached
}

export function invalidateMermaidTheme(): void {
  initializedTheme = ''
}

/** 渲染到目标元素；signal 取消（块卸载）后结果被丢弃 */
export async function renderMermaid(
  host: HTMLElement,
  code: string,
  theme: 'light' | 'dark',
  signal?: AbortSignal
): Promise<void> {
  const body = host.querySelector<HTMLElement>('.diagram-body') ?? host
  body.textContent = '图表渲染中…'
  try {
    const mermaid = await getMermaid(theme)
    if (signal?.aborted) return
    const id = `mmd-${Date.now().toString(36)}-${seq++}`
    const { svg } = await mermaid.render(id, code)
    // mermaid 可能遗留临时容器，显式清理
    document.getElementById(`d-${id}`)?.remove()
    if (signal?.aborted) return
    body.innerHTML = sanitizeSvg(svg)
  } catch (err) {
    if (signal?.aborted) return
    const msg = err instanceof Error ? err.message : String(err)
    body.innerHTML = `<div class="diagram-error">图表语法错误：${escapeHtml(msg)}</div>`
  }
}
