// App：组装主界面，管理文件生命周期、模式切换、菜单动作、
// 外部变更监视、状态栏/大纲联动与全部导出通道。

import { Lifetime } from './core/disposable'
import { debounce, h } from './core/dom'
import { settingsService } from './services/settings'
import { applyTheme, loadCustomCss } from './services/themes'
import { countStats, type DocStats } from './services/word-count'
import { LiveEditor } from './editor/live-editor'
import { SourceEditor } from './editor/source-editor'
import { buildModel, extractHeadings } from './editor/block-model'
import { invalidateMermaidTheme } from './editor/mermaid-diagram'
import { Sidebar } from './ui/sidebar'
import { StatusBar } from './ui/statusbar'
import { FindBar } from './ui/findbar'
import * as Dialogs from './ui/dialogs'
import {
  exportHtmlFile,
  exportImageFile,
  exportPdfFile,
  PANDOC_FORMATS,
  pandocExport
} from './services/exporter'
import type { MenuAction, WatchChange } from '@shared/types'
import welcomeDoc from '../welcome.md?raw'

type Mode = 'live' | 'source'

export class App {
  private lt = new Lifetime()
  private live!: LiveEditor
  private source!: SourceEditor
  private sidebar!: Sidebar
  private statusbar!: StatusBar
  private findbar!: FindBar

  private scroll!: HTMLElement
  private sourceHost!: HTMLElement

  private filePath: string | null = null
  private mode: Mode = 'live'
  private dirty = false
  private stats: DocStats = countStats('')

  async init(): Promise<void> {
    const settings = await settingsService.load()
    applyTheme(settings.theme, settings.fontSize)
    await loadCustomCss()
    document.body.classList.toggle('focus-mode', settings.focusMode)

    // 构建界面骨架
    this.scroll = h('div', { class: 'editor-scroll', tabIndex: -1 })
    this.sourceHost = h('div', { class: 'source-host' })
    this.sourceHost.hidden = true
    const editorArea = h('div', { class: 'editor-area' }, this.scroll, this.sourceHost)

    this.sidebar = new Sidebar(this.lt, {
      openFile: (p) => this.openFile(p),
      getCurrentFile: () => this.filePath,
      jumpHeading: (i) => this.jumpHeading(i),
      closeFolder: () => {}
    })

    const workspace = h('div', { class: 'workspace' }, this.sidebar.el, editorArea)

    this.statusbar = new StatusBar()
    this.findbar = new FindBar()
    const appEl = h(
      'div',
      { class: 'app' },
      workspace,
      this.findbar.el,
      this.statusbar.el
    )
    document.body.append(appEl)

    // 编辑器（容器已入文档）
    this.live = new LiveEditor(this.scroll, {
      getDocPath: () => this.filePath,
      getSettings: () => settingsService.current,
      onTextChanged: () => this.onContentChanged(),
      openLink: (href) => this.openLink(href),
      prompt: (msg, def) => Dialogs.prompt(msg, def)
    })
    this.source = new SourceEditor(
      this.sourceHost,
      settings.theme,
      settings.fontSize,
      () => this.onContentChanged(),
      () => this.filePath
    )

    // 会话恢复：侧边栏状态 → 上次文件夹 → 上次文件；无则欢迎文档
    const startSettings = settingsService.current
    this.sidebar.restoreState(startSettings.sidebarVisible, startSettings.sidebarTab)
    if (startSettings.lastFolder) {
      await this.sidebar.openFolder(startSettings.lastFolder).catch(() => {})
    }
    if (startSettings.lastFile) {
      await this.openFile(startSettings.lastFile)
    } else {
      this.loadWelcome()
    }

    // 关闭窗口时若有未保存修改，弹出原生确认
    this.lt.on(window, 'beforeunload', (e) => {
      if (this.dirty) {
        e.preventDefault()
        e.returnValue = false
      }
    })

    this.lt.add(() => this.findbar.dispose())
    this.lt.add(() => this.live.dispose())
    this.lt.add(() => this.source.dispose())

    // 菜单动作
    window.mdnote.onMenuAction((action: MenuAction) => {
      this.handleAction(action).catch((err) => console.error(err))
    })

    // 设置变更：仅在外观/渲染相关字段变化时做重量刷新，避免保存等操作引发重建
    let prev = settingsService.current
    settingsService.onChange((s) => {
      const looksChanged =
        prev.theme !== s.theme ||
        prev.fontSize !== s.fontSize ||
        prev.mermaid !== s.mermaid ||
        prev.codeLineNumbers !== s.codeLineNumbers ||
        prev.highlightMark !== s.highlightMark
      const focusChanged = prev.focusMode !== s.focusMode
      prev = s

      applyTheme(s.theme, s.fontSize)
      if (focusChanged) document.body.classList.toggle('focus-mode', s.focusMode)
      if (looksChanged) {
        invalidateMermaidTheme()
        this.live.reloadView()
        this.source.applyTheme(s.theme, s.fontSize)
      }
      void loadCustomCss()
      this.refreshStatus()
    }, this.lt)

    // 外部文件改动
    window.mdnote.onWatchChange((e: WatchChange) => this.handleExternalChange(e.path, e.kind))

    // 滚动 → 大纲高亮
    const onScroll = debounce(() => this.updateActiveHeading(), 120)
    this.lt.on(this.scroll, 'scroll', onScroll)

    this.refreshStatus()
  }

  // ---------------- 内容变更 ----------------

  private loadWelcome(): void {
    this.live.setText(welcomeDoc)
    this.stats = countStats(welcomeDoc)
    this.scheduleOutline()
    this.dirty = false
    this.refreshStatus()
  }

  // ---------------- 内容变更 ----------------

  private onContentChanged(): void {
    this.dirty = true
    this.scheduleStats()
    this.scheduleOutline()
    this.scheduleAutoSave()
    this.refreshStatus()
  }

  private scheduleStats = debounce(() => {
    this.stats = countStats(this.currentText())
    this.refreshStatus()
  }, 200)

  private scheduleOutline = debounce(() => {
    const model = buildModel(this.currentText())
    this.sidebar.setHeadings(extractHeadings(model))
    if (this.mode === 'source') this.updateSourceHeading()
  }, 300)

  /** 自动保存：开启且已有文件路径时，停顿 1 秒静默落盘 */
  private scheduleAutoSave = debounce(() => {
    if (!settingsService.current.autoSave || !this.filePath) return
    const target = this.filePath
    this.writeToDisk(target, this.currentText())
      .then(() => {
        if (this.filePath === target) {
          this.dirty = false
          this.refreshStatus()
        }
      })
      .catch((err) => console.error('[autosave]', err))
  }, 1000)

  private currentText(): string {
    if (this.mode === 'live') return this.live.getText()
    return this.source.getText()
  }

  private updateActiveHeading(): void {
    if (this.mode !== 'live') {
      this.updateSourceHeading()
      return
    }
    const id = this.live.activeHeadingAtScroll()
    if (id) this.sidebar.setActiveHeading(id)
  }

  /** 源码模式下根据光标位置定位大纲章节 */
  private updateSourceHeading(): void {
    const model = buildModel(this.currentText())
    const off = this.source.getOffset()
    const headings = extractHeadings(model)
    let current = ''
    for (const h of headings) {
      if (model.blocks[h.blockIndex].start <= off) current = h.id
      else break
    }
    if (current) this.sidebar.setActiveHeading(current)
  }

  private refreshStatus(): void {
    this.statusbar.update({
      dirty: this.dirty,
      mode: this.mode,
      stats: this.stats,
      fileName: this.filePath ? baseName(this.filePath) : '无标题.md'
    })
    document.title = `${this.dirty ? '* ' : ''}${this.filePath ? baseName(this.filePath) : '无标题'}`
  }

  // ---------------- 文件操作 ----------------

  private async discardGuard(): Promise<boolean> {
    if (!this.dirty) return true
    return Dialogs.confirm('当前文档尚未保存，确定放弃修改？')
  }

  private async newFile(): Promise<void> {
    if (!(await this.discardGuard())) return
    this.filePath = null
    this.live.setText('')
    this.source.setText('')
    this.dirty = false
    this.stats = countStats('')
    this.scrollTop0()
    this.scheduleOutline()
    this.refreshStatus()
  }

  private async openFile(path: string): Promise<void> {
    if (path !== this.filePath && !(await this.discardGuard())) return
    try {
      const content = await window.mdnote.readTextFile(path)
      this.filePath = path
      if (this.mode === 'live') this.live.setText(content)
      else this.source.setText(content)
      this.dirty = false
      this.stats = countStats(content)
      this.scrollTop0()
      this.scheduleOutline()
      this.refreshStatus()
      this.pushRecentFile(path)
    } catch (err) {
      await Dialogs.alert(`无法打开文件：${err instanceof Error ? err.message : err}`)
    }
  }

  private scrollTop0(): void {
    this.scroll.scrollTop = 0
  }

  private async save(saveAs: boolean): Promise<void> {
    let target = this.filePath
    if (!target || saveAs) {
      const chosen = await window.mdnote.showSaveDialog(
        this.filePath ? baseName(this.filePath) : '无标题.md'
      )
      if (!chosen) return
      target = chosen
    }
    const text = this.currentText()
    if (!target) return
    await this.writeToDisk(target, text)
    this.dirty = false
    this.refreshStatus()
  }

  /** 将指定文本写入目标路径并更新统计 / 最近文件 / 会话记录 */
  private async writeToDisk(target: string, text: string): Promise<void> {
    await window.mdnote.writeTextFile(target, text)
    this.filePath = target
    this.stats = countStats(text)
    this.pushRecentFile(target)
    await settingsService.patch({ lastFile: target })
  }

  private async pushRecentFile(path: string): Promise<void> {
    const recent = [path, ...settingsService.current.recentFiles.filter((p) => p !== path)].slice(0, 10)
    await settingsService.patch({ recentFiles: recent })
  }

  // ---------------- 模式切换 ----------------

  private toggleSourceView(): void {
    if (this.mode === 'live') {
      const text = this.live.getText()
      this.source.setText(text)
      this.mode = 'source'
      this.scroll.hidden = true
      this.sourceHost.hidden = false
      this.source.focus()
    } else {
      const text = this.source.getText()
      this.live.setText(text)
      this.mode = 'live'
      this.sourceHost.hidden = true
      this.scroll.hidden = false
    }
    this.scheduleOutline()
    this.refreshStatus()
  }

  private jumpHeading(blockIndex: number): void {
    const model = buildModel(this.currentText())
    const b = model.blocks[blockIndex]
    if (!b) return
    if (this.mode === 'live') {
      this.live.jumpToBlock(blockIndex)
    } else {
      const line = model.text.slice(0, b.start).split('\n').length
      this.source.gotoLine(line)
    }
  }

  // ---------------- 链接 ----------------

  private async openLink(href: string): Promise<void> {
    if (/^https?:\/\//i.test(href) || /^mailto:/i.test(href)) {
      await window.mdnote.openExternal(href)
      return
    }
    if (this.filePath && /\.md(#|$)/i.test(href)) {
      const dir = this.filePath.replace(/\\/g, '/').slice(0, this.filePath.replace(/\\/g, '/').lastIndexOf('/'))
      const resolved = `${dir}/${href.split('#')[0]}`.replace(/\//g, '\\')
      this.openFile(resolved).catch(() => {})
      return
    }
    // 其他本地文件交给系统
    window.mdnote.openPath(href).catch(() => {})
  }

  // ---------------- 外部变更 ----------------

  private async handleExternalChange(relPath: string, kind: string): Promise<void> {
    void kind
    if (!this.filePath) return
    const normalized = this.filePath.replace(/\\/g, '/').toLowerCase()
    if (!normalized.endsWith(`/${relPath.replace(/\\/g, '/').toLowerCase()}`)) return
    let disk: string
    try {
      disk = await window.mdnote.readTextFile(this.filePath)
    } catch {
      return
    }
    if (disk === this.currentText()) return
    const reload = this.dirty
      ? await Dialogs.confirm('文件已被其他程序修改，是否重新载入？（未保存的修改将丢失）')
      : true
    if (reload) {
      if (this.mode === 'live') this.live.setText(disk)
      else this.source.setText(disk)
      this.dirty = false
      this.refreshStatus()
    }
  }

  // ---------------- 导出 ----------------

  private async exportByAction(action: MenuAction): Promise<void> {
    const text = this.currentText()
    switch (action) {
      case 'export-html':
        await exportHtmlFile(text)
        break
      case 'export-pdf': {
        const result = await Dialogs.pdfOptionsDialog()
        if (result) await exportPdfFile(text, result.options, result.includeToc)
        break
      }
      case 'export-png':
        await exportImageFile(text, { format: 'png' })
        break
      case 'export-jpeg':
        await exportImageFile(text, { format: 'jpeg' })
        break
      case 'export-docx':
      case 'export-epub':
      case 'export-latex':
      case 'export-odt':
        await this.pandoc(action, text)
        break
    }
  }

  private async pandoc(action: MenuAction, text: string): Promise<void> {
    const fmt = PANDOC_FORMATS.find((f) => f.action === action)
    if (!fmt) return
    const available = await window.mdnote.pandocAvailable()
    if (!available) {
      await Dialogs.alert('未检测到 Pandoc。请安装后重试：https://pandoc.org/installing.html')
      return
    }
    const result = await pandocExport(text, fmt.ext, false)
    if (!result.ok && result.error) await Dialogs.alert(`导出失败：${result.error}`)
  }

  // ---------------- 菜单总入口 ----------------

  private async handleAction(action: MenuAction): Promise<void> {
    switch (action) {
      case 'new':
        await this.newFile()
        return
      case 'open': {
        const path = await window.mdnote.showOpenDialog()
        if (path) await this.openFile(path)
        return
      }
      case 'open-folder': {
        const folder = await window.mdnote.showFolderDialog()
        if (folder) {
          await this.sidebar.openFolder(folder)
          this.sidebar.el.classList.add('is-visible')
          await settingsService.patch({
            lastFolder: folder,
            sidebarVisible: true,
            sidebarTab: 'files'
          })
        }
        return
      }
      case 'close-folder':
        await this.sidebar.closeFolder()
        await settingsService.patch({ lastFolder: null })
        return
      case 'save':
        await this.save(false)
        return
      case 'save-as':
        await this.save(true)
        return
      case 'toggle-source':
        this.toggleSourceView()
        return
      case 'toggle-sidebar':
        this.sidebar.toggle()
        await settingsService.patch({ sidebarVisible: this.sidebar.visible })
        return
      case 'files-tab':
        this.sidebar.showTab('files')
        await settingsService.patch({ sidebarVisible: true, sidebarTab: 'files' })
        return
      case 'outline-tab':
        this.sidebar.showTab('outline')
        await settingsService.patch({ sidebarVisible: true, sidebarTab: 'outline' })
        return
      case 'toggle-focus':
        await settingsService.patch({ focusMode: !settingsService.current.focusMode })
        return
      case 'toggle-typewriter':
        await settingsService.patch({ typewriterMode: !settingsService.current.typewriterMode })
        return
      case 'find':
        if (this.mode === 'source') this.source.showSearch()
        else this.findbar.open()
        return
      case 'bold':
        if (this.mode === 'live') this.live.wrapInline('**')
        return
      case 'italic':
        if (this.mode === 'live') this.live.wrapInline('*')
        return
      case 'strikethrough':
        if (this.mode === 'live') this.live.wrapInline('~~')
        return
      case 'inline-code':
        if (this.mode === 'live') this.live.wrapInline('`')
        return
      case 'code-block':
      case 'math':
      case 'table':
      case 'quote':
      case 'hr':
      case 'image':
      case 'link':
        if (this.mode === 'live') await this.live.insertBlock(action)
        return
      case 'settings':
        await Dialogs.showSettings(() => {})
        return
      case 'open-custom-css':
        await window.mdnote.openCustomCssFile()
        return
      case 'export-html':
      case 'export-pdf':
      case 'export-png':
      case 'export-jpeg':
      case 'export-docx':
      case 'export-epub':
      case 'export-latex':
      case 'export-odt':
        await this.exportByAction(action)
        return
      case 'reload-file':
        if (this.filePath) await this.openFile(this.filePath)
        return
      case 'about':
        await Dialogs.alert('MdNote v0.1.0\n一款注重性能、安全与可扩展性的 Markdown 编辑器')
        return
      case 'actual-size':
        await settingsService.patch({ fontSize: 16 })
        return
      case 'zoom-in':
        await settingsService.patch({ fontSize: Math.min(28, settingsService.current.fontSize + 1) })
        return
      case 'zoom-out':
        await settingsService.patch({ fontSize: Math.max(12, settingsService.current.fontSize - 1) })
        return
      case 'toggle-fullscreen':
        return
    }
  }

  dispose(): void {
    this.lt.dispose()
  }

  /** @internal 仅供冒烟测试（仅在 ?smoke=1 时挂到 window） */
  async __open(path: string): Promise<void> {
    await this.openFile(path)
  }

  /** @internal 直接装载文本（长文档性能测试） */
  __loadText(text: string): void {
    if (this.mode === 'live') this.live.setText(text)
    else this.source.setText(text)
  }

  /** @internal 编辑流程测试：点击段落 → 输入 → 失焦提交 */
  async __editTest(): Promise<{ entered: boolean; persisted: boolean }> {
    const p = document.querySelector<HTMLElement>('.block-paragraph')
    if (!p) return { entered: false, persisted: false }
    const rect = p.getBoundingClientRect()
    p.dispatchEvent(
      new MouseEvent('mousedown', {
        bubbles: true,
        cancelable: true,
        clientX: rect.left + 24,
        clientY: rect.top + rect.height / 2
      })
    )
    await new Promise((r) => setTimeout(r, 80))
    const entered = p.isContentEditable
    document.execCommand('insertText', false, '[编辑测试标记]')
    p.dispatchEvent(new FocusEvent('blur'))
    await new Promise((r) => setTimeout(r, 250))
    const persisted = document.body.innerHTML.includes('[编辑测试标记]')
    return { entered, persisted }
  }
  async __toggleFirstTask(): Promise<number> {
    const boxes = [...document.querySelectorAll<HTMLInputElement>('.task-checkbox')]
    const first = boxes.find((b) => !b.checked)
    first?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    await new Promise((r) => setTimeout(r, 150))
    return document.querySelectorAll('.task-checkbox[checked]').length
  }

  /** @internal 探测当前渲染状态 */
  __probe(): Record<string, number> {
    return {
      rows: document.querySelectorAll('.vl-row').length,
      blocks: document.querySelectorAll('.block').length,
      headings: document.querySelectorAll('.md-heading').length,
      codeBlocks: document.querySelectorAll('.code-block').length,
      tasks: document.querySelectorAll('.task-checkbox').length,
      tables: document.querySelectorAll('table').length,
      mermaidHosts: document.querySelectorAll('.mermaid-host').length,
      tocBlocks: document.querySelectorAll('.toc-block').length,
      mathInline: document.querySelectorAll('.katex').length,
      quotes: document.querySelectorAll('blockquote').length
    }
  }
}

function baseName(p: string): string {
  const parts = p.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1]
}
