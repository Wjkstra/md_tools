// 侧边栏：文件树（惰性展开 / 监视刷新）与大纲（标题跳转 / 当前章节高亮）。

import { Lifetime } from '../core/disposable'
import { debounce, h } from '../core/dom'
import type { DirEntry, WatchChange } from '@shared/types'

export interface SidebarCallbacks {
  openFile(path: string): void
  getCurrentFile(): string | null
  jumpHeading(blockIndex: number): void
  closeFolder(): void
}

interface TreeState {
  path: string
  expanded: Set<string>
  loaded: Map<string, DirEntry[]>
}

const MARKDOWN_RE = /\.(md|markdown|txt)$/i

export class Sidebar {
  el: HTMLElement
  private filesPanel: HTMLElement
  private outlinePanel: HTMLElement
  private tabsEl: HTMLElement
  private tree: TreeState | null = null
  private watchId: number | null = null
  private renderLt: Lifetime | null = null
  private outlineLt: Lifetime | null = null
  private headings: { level: number; text: string; id: string; blockIndex: number }[] = []
  private activeHeadingId = ''

  constructor(lt: Lifetime, private cb: SidebarCallbacks) {
    this.el = h('aside', { class: 'sidebar' })

    this.tabsEl = h('div', { class: 'sidebar-tabs' })
    const filesTab = h('button', { class: 'sidebar-tab is-active', type: 'button' }, '文件')
    const outlineTab = h('button', { class: 'sidebar-tab', type: 'button' }, '大纲')
    this.tabsEl.append(filesTab, outlineTab)

    this.filesPanel = h('div', { class: 'sidebar-panel is-active' })
    this.outlinePanel = h('div', { class: 'sidebar-panel' })
    this.el.append(this.tabsEl, this.filesPanel, this.outlinePanel)

    lt.on(filesTab, 'click', () => this.switchTab('files'))
    lt.on(outlineTab, 'click', () => this.switchTab('outline'))

    // 文件变更：合并刷新（展开状态保留）
    const scheduleRefresh = debounce(() => this.renderFiles(), 250)
    window.mdnote.onWatchChange((e: WatchChange) => {
      if (this.tree && e.watchId === this.watchId) scheduleRefresh()
    })
  }

  private switchTab(tab: 'files' | 'outline'): void {
    this.tabsEl.children[0].classList.toggle('is-active', tab === 'files')
    this.tabsEl.children[1].classList.toggle('is-active', tab === 'outline')
    this.filesPanel.classList.toggle('is-active', tab === 'files')
    this.outlinePanel.classList.toggle('is-active', tab === 'outline')
  }

  showTab(tab: 'files' | 'outline'): void {
    this.switchTab(tab)
    this.el.classList.add('is-visible')
  }

  /** 启动恢复：只改 UI，不触发设置写入 */
  restoreState(visible: boolean, tab: 'files' | 'outline'): void {
    this.switchTab(tab)
    this.el.classList.toggle('is-visible', visible)
  }

  get visible(): boolean {
    return this.el.classList.contains('is-visible')
  }

  toggle(): void {
    this.el.classList.toggle('is-visible')
  }

  // ---------------- 文件树 ----------------

  async openFolder(folder: string): Promise<void> {
    await this.closeFolder()
    this.tree = { path: folder, expanded: new Set([folder]), loaded: new Map() }
    this.watchId = await window.mdnote.watchFolder(folder)
    await this.renderFiles()
  }

  async closeFolder(): Promise<void> {
    if (this.watchId !== null) {
      await window.mdnote.unwatchFolder(this.watchId)
      this.watchId = null
    }
    this.renderLt?.dispose()
    this.renderLt = null
    this.tree = null
    this.filesPanel.replaceChildren()
    this.cb.closeFolder()
  }

  get hasFolder(): boolean {
    return this.tree !== null
  }

  private async renderFiles(): Promise<void> {
    // 上一轮渲染的行监听全部释放，防止刷新累积泄漏
    this.renderLt?.dispose()
    this.renderLt = new Lifetime()

    if (!this.tree) {
      this.filesPanel.replaceChildren(
        h('div', { class: 'sidebar-empty' }, '尚未打开文件夹'),
        h('div', { class: 'sidebar-empty-hint' }, '文件 → 打开文件夹 (Ctrl+Shift+O)')
      )
      return
    }
    const tree = this.tree
    this.filesPanel.replaceChildren()

    const header = h('div', { class: 'tree-header' }, shorten(tree.path))
    this.filesPanel.append(header)
    await this.renderDir(this.filesPanel, tree.path, 0)
  }

  private async renderDir(parent: HTMLElement, dir: string, depth: number): Promise<void> {
    if (!this.tree) return
    const cached = this.tree.loaded.get(dir)
    const entries: DirEntry[] = cached ?? (await window.mdnote.listDir(dir))
    if (!cached && this.tree) this.tree.loaded.set(dir, entries)
    const current = this.cb.getCurrentFile()

    for (const entry of entries) {
      if (entry.isDirectory) {
        const expanded = this.tree.expanded.has(entry.path)
        const row = h(
          'div',
          { class: 'tree-row tree-dir' },
          h('span', { class: `tree-chevron ${expanded ? 'is-open' : ''}` }, expanded ? '▾' : '▸'),
          h('span', { class: 'tree-label' }, entry.name)
        )
        row.style.paddingLeft = `${8 + depth * 14}px`
        parent.append(row)
        if (expanded) {
          await this.renderDir(parent, entry.path, depth + 1)
        }
        this.renderLt?.on(row, 'click', async () => {
          if (!this.tree) return
          if (this.tree.expanded.has(entry.path)) {
            this.tree.expanded.delete(entry.path)
          } else {
            this.tree.expanded.add(entry.path)
          }
          await this.renderFiles()
        })
      } else if (MARKDOWN_RE.test(entry.name)) {
        const isActive = current === entry.path
        const row = h(
          'div',
          { class: `tree-row tree-file ${isActive ? 'is-active' : ''}` },
          h('span', { class: 'tree-icon' }, '📄'),
          h('span', { class: 'tree-label' }, entry.name)
        )
        row.style.paddingLeft = `${8 + depth * 14 + 14}px`
        parent.append(row)
        this.renderLt?.on(row, 'click', () => this.cb.openFile(entry.path))
      }
    }
  }

  refreshCurrentFile(): void {
    void this.renderFiles()
  }

  // ---------------- 大纲 ----------------

  setHeadings(headings: Sidebar['headings']): void {
    this.headings = headings
    this.outlineLt?.dispose()
    this.outlineLt = new Lifetime()
    this.outlinePanel.replaceChildren()
    if (headings.length === 0) {
      this.outlinePanel.append(h('div', { class: 'sidebar-empty' }, '文档中暂无标题'))
      return
    }
    for (const heading of headings) {
      const row = h(
        'div',
        { class: `outline-row outline-l${heading.level} ${this.activeHeadingId === heading.id ? 'is-active' : ''}` },
        h('span', { class: 'outline-label' }, heading.text || '(空标题)')
      )
      row.style.paddingLeft = `${8 + (heading.level - 1) * 14}px`
      this.outlinePanel.append(row)
      this.outlineLt?.on(row, 'click', () => this.cb.jumpHeading(heading.blockIndex))
    }
  }

  setActiveHeading(id: string): void {
    if (id === this.activeHeadingId) return
    this.activeHeadingId = id
    this.outlinePanel.querySelectorAll('.outline-row').forEach((row, i) => {
      row.classList.toggle('is-active', this.headings[i]?.id === id)
    })
  }
}

function shorten(p: string): string {
  const parts = p.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || p
}
