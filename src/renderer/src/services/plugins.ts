// 插件系统（可扩展性核心）：
// - 内部插件：==文字高亮==（GFM 扩展），随设置启停
// - 外部插件：userData/plugins/<name>/，用户在设置中显式启用；
//   源码经主进程读取 → Blob 模块导入，activate(PluginAPI) 接管。
//   沙箱内插件没有 Node 能力，仅可使用窗口 API 与下述扩展点。

import type MarkdownIt from 'markdown-it'
import type { AppSettings } from '@shared/types'
import { settingsService } from './settings'

export interface PluginAPI {
  settings: AppSettings
  addMarkdownItPlugin(plugin: (md: MarkdownIt, ...params: unknown[]) => void, ...params: unknown[]): void
}

interface LoadedExternal {
  id: string
  deactivate?: () => void
}

// ---------------- ==高亮== 内联规则 ----------------

export function installMark(md: MarkdownIt): void {
  md.inline.ruler.after('escape', 'mark_inline', (state, silent) => {
    if (state.src.charCodeAt(state.pos) !== 0x3d /* = */) return false
    if (state.src.charCodeAt(state.pos + 1) !== 0x3d) return false
    let p = state.pos + 2
    let close = -1
    while (p < state.posMax - 1) {
      if (
        state.src.charCodeAt(p) === 0x3d &&
        state.src.charCodeAt(p + 1) === 0x3d &&
        state.src[p - 1] !== '\\'
      ) {
        close = p
        break
      }
      p++
    }
    if (close === -1) return false
    const content = state.src.slice(state.pos + 2, close)
    if (!content) return false
    if (!silent) {
      const token = state.push('mark_inline', 'mark', 0)
      token.content = content
    }
    state.pos = close + 2
    return true
  })

  md.renderer.rules.mark_inline = (tokens, idx) =>
    `<mark>${tokens[idx].content}</mark>`
}

// ---------------- 插件管理器 ----------------

export class PluginManager {
  private externals: LoadedExternal[] = []

  /** 应用内置扩展点 */
  applyInternal(md: MarkdownIt): void {
    if (settingsService.current.highlightMark) installMark(md)
  }

  async loadExternalPlugins(md: MarkdownIt): Promise<void> {
    const enabled = new Set(settingsService.current.enabledPlugins)
    if (enabled.size === 0) return

    const infos = await window.mdnote.listPlugins()
    for (const info of infos) {
      if (!enabled.has(info.name) || this.externals.some((e) => e.id === info.name)) continue
      try {
        const source = await window.mdnote.readPluginSource(info.dir, info.main)
        const blob = new Blob([source], { type: 'text/javascript' })
        const url = URL.createObjectURL(blob)
        try {
          const mod = (await import(/* @vite-ignore */ url)) as {
            default?: { activate?: (api: PluginAPI) => void; deactivate?: () => void }
          }
          const plugin = mod.default
          if (plugin?.activate) {
            const api: PluginAPI = {
              settings: settingsService.current,
              addMarkdownItPlugin: (p, ...params) => p(md, ...params)
            }
            plugin.activate(api)
            this.externals.push({ id: info.name, deactivate: plugin.deactivate })
          }
        } finally {
          URL.revokeObjectURL(url)
        }
      } catch (err) {
        console.error(`[PluginManager] failed to load ${info.name}`, err)
      }
    }
  }

  dispose(): void {
    for (const p of this.externals) {
      try {
        p.deactivate?.()
      } catch {
        // ignore
      }
    }
    this.externals = []
  }
}
