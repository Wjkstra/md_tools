// 实时（所见即所得）编辑器：
// - 块在未聚焦时显示渲染结果；点击进入该块源码编辑（Typora 模式）
// - 回车拆分 / 行首退格合并 / 列表缩进 / 标记空格触发 / Ctrl+B/I 等包裹
// - 任务复选框、表格、TOC、图片拖放粘贴
// - 结构变更走 splice + EditHistory；渲染全部经 VirtualList 虚拟化

import { Lifetime } from '../core/disposable'
import { getCaretOffset, setCaretOffset, getCaretRect } from '../core/dom'
import {
  buildModel,
  extractHeadings,
  findBlockIndex,
  serialize,
  type Block,
  type DocModel
} from './block-model'
import { VirtualList, type MountedRow } from './virtual-list'
import { BlockViewFactory } from './block-view'
import {
  createMarkdownEngine,
  warmHighlighter,
  type MarkdownEngine
} from '../services/markdown'
import { EditHistory } from './history'
import {
  detectSpaceTrigger,
  indentLine,
  insertAt,
  mergeWith,
  splitAt,
  wrapSelection
} from './transforms'
import type { AppSettings } from '@shared/types'
import { PluginManager } from '../services/plugins'
import type MarkdownIt from 'markdown-it'

export interface LiveEditorCallbacks {
  getDocPath(): string | null
  getSettings(): AppSettings
  onTextChanged(): void
  openLink(href: string): void
  prompt(message: string, defaultValue: string): Promise<string | null>
}

interface EditingState {
  index: number
}

const RAW_NEWLINE_TYPES: Block['type'][] = ['code', 'math', 'frontmatter', 'html']

export class LiveEditor {
  private lt = new Lifetime()
  private engine: MarkdownEngine
  private views: BlockViewFactory
  private vl: VirtualList
  private history = new EditHistory()

  private text = ''
  private model: DocModel
  private editing: EditingState | null = null
  private rowLifetimes = new Map<number, Lifetime>()
  private activeIndex = -1
  private pendingCellEdit: { index: number; flat: number } | null = null

  constructor(
    private container: HTMLElement,
    private cb: LiveEditorCallbacks
  ) {
    this.engine = createMarkdownEngine()
    const pluginManager = new PluginManager()
    pluginManager.applyInternal(this.engine.md)
    void pluginManager.loadExternalPlugins(this.engine.md)
    this.lt.add(() => pluginManager.dispose())

    this.views = new BlockViewFactory(this.engine)
    this.model = buildModel('')
    warmHighlighter() // 后台预热语法高亮

    this.vl = new VirtualList(container, {
      count: () => this.model.blocks.length,
      blockAt: (i) => this.model.blocks[i],
      onMount: (row) => this.onMount(row),
      onUnmount: (row) => this.onUnmount(row)
    })

    this.lt.on(container, 'keydown', (e) => this.onKeyDown(e))
    this.lt.on(document, 'selectionchange', () => this.scheduleActiveUpdate())
    this.bindDragDrop()
  }

  // ---------------- 文本装载 / 读取 ----------------

  setText(text: string): void {
    this.text = text
    this.history.clear()
    this.refreshModel(true)
  }

  getText(): string {
    // 若有正在编辑的块，先提交再返回
    if (this.editing) this.commitEditing()
    return serialize(this.model)
  }

  get offsetInfo(): { blocks: number; active: number } {
    return { blocks: this.model.blocks.length, active: this.activeIndex }
  }

  private refreshModel(resetScroll: boolean): void {
    this.model = buildModel(this.text)
    this.views.invalidate()
    if (resetScroll) {
      this.vl.rebuild()
      this.container.scrollTop = 0
    } else {
      const anchor = this.vl.anchorAt(this.container.scrollTop)
      this.vl.rebuild(anchor)
    }
    this.activeIndex = -1
  }

  // ---------------- 行挂载 / 卸载 ----------------

  private renderCtx() {
    const docPath = this.cb.getDocPath()
    const s = this.cb.getSettings()
    return {
      docBase: docPath ? dirname(docPath) : null,
      mermaidEnabled: s.mermaid,
      codeLineNumbers: s.codeLineNumbers,
      dark: isDarkTheme(s.theme),
      headings: extractHeadings(this.model)
    }
  }

  private onMount(row: MountedRow): void {
    const index = row.index
    const b = this.model.blocks[index]
    const lifetime = new Lifetime()
    this.rowLifetimes.set(index, lifetime)

    row.root.dataset.idx = String(index)
    row.inner.className = `block block-${b.type}`
    const ctx = this.renderCtx()
    row.inner.innerHTML = this.views.produce(index, b, ctx)
    this.views.postProcess(
      row.inner,
      b,
      index,
      lifetime,
      lifetime.signal,
      {
        onTocJump: (id) => this.jumpToHeadingId(id),
        onTableChange: (i, md) => this.onTableChange(i, md),
        onCellNavigate: (i, flat) => {
          this.pendingCellEdit = { index: i, flat }
        },
        consumePendingCellEdit: (i) => {
          if (this.pendingCellEdit?.index !== i) return null
          const flat = this.pendingCellEdit.flat
          this.pendingCellEdit = null
          return flat
        }
      },
      ctx.docBase,
      ctx.dark
    )

    lifetime.on(row.inner, 'mousedown', (e) => this.onBlockMouseDown(e, index))
  }

  private onUnmount(row: MountedRow): void {
    const index = row.index
    if (this.editing?.index === index) this.commitEditing()
    const lifetime = this.rowLifetimes.get(index)
    lifetime?.dispose()
    this.rowLifetimes.delete(index)
    delete row.root.dataset.idx
  }

  // ---------------- 点击进入编辑 ----------------

  private onBlockMouseDown(e: MouseEvent, index: number): void {
    const target = e.target as HTMLElement

    // 复选框切换
    if (target.matches('input.task-checkbox')) {
      e.preventDefault()
      this.toggleTask(index, target as HTMLInputElement)
      return
    }
    if (target.closest('button, .diagram, table, .toc-block')) return

    // Ctrl/Cmd+点击链接：打开
    const link = target.closest('a')
    if (link && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      const href = link.getAttribute('href')
      if (href) this.cb.openLink(href)
      return
    }

    if (this.editing?.index === index) return // 已在编辑，原生定位

    e.preventDefault()
    this.enterEditing(index, null)
    const inner = this.vl.mountedRow(index)?.inner
    if (inner) {
      const local = caretPointOffset(inner, e.clientX, e.clientY)
      if (local !== null) setCaretOffset(inner, local)
    }
  }

  private enterEditing(index: number, offset: number | null): void {
    if (this.editing) this.commitEditing()
    const b = this.model.blocks[index]
    const inner = this.vl.mountedRow(index)?.inner
    if (!b || !inner) return
    inner.contentEditable = 'true'
    inner.classList.add('is-editing')
    inner.textContent = b.raw
    inner.focus({ preventScroll: true })
    this.editing = { index }
    const caret = offset ?? b.raw.length
    setCaretOffset(inner, Math.max(0, Math.min(caret, b.raw.length)))
    this.setActive(index)
  }

  private commitEditing(): void {
    if (!this.editing) return
    const index = this.editing.index
    this.editing = null
    const inner = this.vl.mountedRow(index)?.inner
    if (!inner) return
    const rawNow = inner.textContent ?? ''
    inner.contentEditable = 'false'
    inner.classList.remove('is-editing')
    const b = this.model.blocks[index]
    if (!b) return
    if (rawNow !== b.raw) {
      this.applySplice(b.start, b.end, rawNow, b.start + rawNow.length)
    } else {
      this.rerenderRow(index)
    }
  }

  private rerenderRow(index: number): void {
    const row = this.vl.mountedRow(index)
    if (!row) return
    this.rowLifetimes.get(index)?.dispose()
    const lifetime = new Lifetime()
    this.rowLifetimes.set(index, lifetime)
    const b = this.model.blocks[index]
    const ctx = this.renderCtx()
    row.inner.innerHTML = this.views.produce(index, b, ctx)
    this.views.postProcess(
      row.inner,
      b,
      index,
      lifetime,
      lifetime.signal,
      {
        onTocJump: (id) => this.jumpToHeadingId(id),
        onTableChange: (i, md) => this.onTableChange(i, md),
        onCellNavigate: (i, flat) => {
          this.pendingCellEdit = { index: i, flat }
        },
        consumePendingCellEdit: (i) => {
          if (this.pendingCellEdit?.index !== i) return null
          const flat = this.pendingCellEdit.flat
          this.pendingCellEdit = null
          return flat
        }
      },
      ctx.docBase,
      ctx.dark
    )
    lifetime.on(row.inner, 'mousedown', (e) => this.onBlockMouseDown(e, index))
  }

  // ---------------- 规范文本 splice ----------------

  private applySplice(start: number, end: number, insert: string, caret: number, record = true): void {
    const before = this.text.slice(start, end)
    if (record) this.history.record({ start, before, after: insert, caret })
    this.text = this.text.slice(0, start) + insert + this.text.slice(end)
    this.refreshModel(false)
    this.cb.onTextChanged()

    // 编辑状态延续：定位到 caret 所在块并重新进入编辑
    const idx = findBlockIndex(this.model, caret)
    this.enterEditing(idx, caret - this.model.blocks[idx].start)
  }

  private applyUndoRedo(
    start: number,
    remove: string,
    insert: string,
    caret: number,
    inverse: { start: number; before: string; after: string; caret: number } | null
  ): void {
    void inverse
    this.text = this.text.slice(0, start) + insert + this.text.slice(start + remove.length)
    this.refreshModel(false)
    this.cb.onTextChanged()
    const idx = findBlockIndex(this.model, caret)
    this.enterEditing(idx, caret - this.model.blocks[idx].start)
  }

  // ---------------- 键盘 ----------------

  private onKeyDown(e: KeyboardEvent): void {
    if (!this.editing) return
    const index = this.editing.index
    const inner = this.vl.mountedRow(index)?.inner
    if (!inner) return
    const b = this.model.blocks[index]
    const settings = this.cb.getSettings()

    const ctrl = e.ctrlKey || e.metaKey

    if (ctrl) {
      this.handleCtrlKey(e, inner, b, index)
      return
    }

    switch (e.key) {
      case 'Enter': {
        if (RAW_NEWLINE_TYPES.includes(b.type)) return // 块内正常换行
        e.preventDefault()
        const r = splitAt(inner.textContent ?? '', b.type, getCaretOffset(inner))
        this.applySplice(b.start, b.end, r.text, b.start + r.caret)
        break
      }
      case 'Backspace': {
        if (getCaretOffset(inner) !== 0) return
        const prev = this.model.blocks[index - 1]
        if (!prev) return
        e.preventDefault()
        const r = mergeWith(prev.raw, inner.textContent ?? '')
        // 合并跨度：上一块起点 → 当前块终点
        this.applySplice(prev.start, b.end, r.text, prev.start + r.caret)
        break
      }
      case 'Tab': {
        e.preventDefault()
        if (b.type === 'list') {
          const r = indentLine(
            inner.textContent ?? '',
            getCaretOffset(inner),
            settings.tabSize,
            e.shiftKey
          )
          this.applySplice(b.start, b.end, r.text, b.start + r.caret)
        } else {
          document.execCommand('insertText', false, ' '.repeat(settings.tabSize))
        }
        break
      }
      case ' ': {
        const off = getCaretOffset(inner)
        const rawNow = inner.textContent ?? ''
        const probe = `${rawNow.slice(0, off)} ${rawNow.slice(off)}`
        const r = detectSpaceTrigger(probe, off + 1)
        if (r) {
          e.preventDefault()
          this.applySplice(b.start, b.end, r.text, b.start + r.caret)
        }
        break
      }
      case 'Escape':
        e.preventDefault()
        this.commitEditing()
        break
      case '"':
        if (settings.smartPunctuation) {
          e.preventDefault()
          this.insertPaired(inner, '“', '”')
        }
        break
      case '*':
      case '~':
      case '`':
        if (settings.autoBracket && getCaretOffset(inner) > 0) {
          e.preventDefault()
          const marker = e.key === '~' ? '~~' : e.key
          this.insertPaired(inner, marker, marker)
        }
        break
      case '[':
        if (settings.autoBracket) {
          e.preventDefault()
          this.insertPaired(inner, '[', ']')
        }
        break
    }
  }

  private handleCtrlKey(
    e: KeyboardEvent,
    inner: HTMLElement,
    b: Block,
    index: number
  ): void {
    const key = e.key.toLowerCase()
    const wrap = (marker: string): void => {
      e.preventDefault()
      const raw = inner.textContent ?? ''
      const sel = window.getSelection()
      let s = 0
      let en = 0
      if (sel && sel.rangeCount > 0 && inner.contains(sel.anchorNode)) {
        s = getCaretOffset(inner)
        en = s
        // 取选区首尾
        const range = sel.getRangeAt(0)
        const startOff = selectionOffset(inner, range.startContainer, range.startOffset)
        const endOff = selectionOffset(inner, range.endContainer, range.endOffset)
        s = Math.min(startOff, endOff)
        en = Math.max(startOff, endOff)
      }
      const r = wrapSelection(raw, s, en, marker)
      inner.textContent = r.text
      setCaretOffset(inner, r.caret)
    }

    if (key === 'b') return wrap('**')
    if (key === 'i') return wrap('*')
    if (key === 'z') {
      e.preventDefault()
      this.undo()
      return
    }
    if (key === 'y') {
      e.preventDefault()
      this.redo()
      return
    }
    if (e.shiftKey && key === 'x') return wrap('~~')
    if (e.shiftKey && key === '`') return wrap('`')
    void b
    void index
  }

  private undo(): void {
    if (this.editing) {
      // 丢弃未提交内容，不额外记录
      this.editing = null
      const row = this.vl.mountedRow(this.activeIndex)
      if (row) {
        row.inner.contentEditable = 'false'
        row.inner.classList.remove('is-editing')
      }
    }
    const r = this.history.undo()
    if (!r) return
    this.applyUndoRedo(r.start, r.remove, r.insert, r.caret, null)
  }

  private redo(): void {
    const r = this.history.redo()
    if (!r) return
    this.applyUndoRedo(r.start, r.remove, r.insert, r.caret, null)
  }

  private insertPaired(inner: HTMLElement, open: string, close: string): void {
    const off = getCaretOffset(inner)
    const raw = inner.textContent ?? ''
    const insert = `${open}${close}`
    const r = insertAt(raw, off, insert)
    inner.textContent = r.text
    setCaretOffset(inner, off + open.length)
  }

  // ---------------- 任务列表复选 ----------------

  private toggleTask(index: number, checkbox: HTMLInputElement): void {
    const b = this.model.blocks[index]
    const inner = this.vl.mountedRow(index)?.inner
    if (!inner) return
    const all = [...inner.querySelectorAll('input.task-checkbox')]
    const taskIndex = all.indexOf(checkbox)
    const lines = b.raw.split('\n')
    let seen = -1
    for (let i = 0; i < lines.length; i++) {
      const m = /^(\s*[-+*]\s+)\[([ xX])\](.*)$/.exec(lines[i])
      if (!m) continue
      seen++
      if (seen !== taskIndex) continue
      const next = m[2] === 'x' ? ' ' : 'x'
      lines[i] = `${m[1]}[${next}]${m[3]}`
      break
    }
    const newRaw = lines.join('\n')
    // [x]/[ ] 等长：直接替换文本并静默重建，再仅刷新该行
    this.text = this.text.slice(0, b.start) + newRaw + this.text.slice(b.end)
    this.history.record({ start: b.start, before: b.raw, after: newRaw, caret: b.start })
    this.model = buildModel(this.text)
    this.cb.onTextChanged()
    this.rerenderRow(index)
  }

  // ---------------- 表格回写 ----------------

  private onTableChange(index: number, markdown: string): void {
    const b = this.model.blocks[index]
    if (!b || markdown === b.raw) return
    this.text = this.text.slice(0, b.start) + markdown + this.text.slice(b.end)
    this.history.record({ start: b.start, before: b.raw, after: markdown, caret: b.start })
    this.model = buildModel(this.text)
    this.views.invalidate()
    const anchor = this.vl.anchorAt(this.container.scrollTop)
    this.vl.rebuild(anchor)
    this.cb.onTextChanged()
  }

  // ---------------- TOC / 大纲跳转 ----------------

  jumpToHeadingId(id: string): void {
    const headings = extractHeadings(this.model)
    const h = headings.find((x) => x.id === id)
    if (h) this.vl.scrollToIndex(h.blockIndex, -8)
  }

  jumpToBlock(index: number): void {
    this.vl.scrollToIndex(index, -8)
  }

  get markdownIt(): MarkdownIt {
    return this.engine.md
  }

  /** 滚动位置对应的当前章节 id，供大纲高亮 */
  activeHeadingAtScroll(): string | null {
    const anchor = this.vl.anchorAt(this.container.scrollTop + 40)
    let current: { id: string } | null = null
    for (const h of extractHeadings(this.model)) {
      if (h.blockIndex <= anchor.index) current = h
      else break
    }
    return current?.id ?? null
  }

  /** 主题 / 字号等外观变化：废弃缓存并用锚点重建 */
  reloadView(): void {
    this.views.invalidate()
    const anchor = this.vl.anchorAt(this.container.scrollTop)
    this.vl.rebuild(anchor)
  }

  // ---------------- 活动块 / 专注 / 打字机 ----------------

  private setActive(index: number): void {
    if (this.activeIndex === index) return
    this.activeIndex = index
    const oldRow = this.container.querySelector('.block-active')
    oldRow?.classList.remove('block-active')
    this.vl.mountedRow(index)?.inner.classList.add('block-active')
  }

  private rafActive = 0
  private scheduleActiveUpdate(): void {
    if (this.rafActive) return
    this.rafActive = requestAnimationFrame(() => {
      this.rafActive = 0
      this.updateActiveState()
    })
  }

  private updateActiveState(): void {
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0) return
    const node = sel.getRangeAt(0).startContainer
    const rowEl =
      node instanceof Element
        ? node.closest<HTMLElement>('.vl-row')
        : (node.parentElement?.closest<HTMLElement>('.vl-row') ?? null)
    if (rowEl) {
      const idx = Number(rowEl.dataset.idx)
      if (!Number.isNaN(idx)) this.setActive(idx)
    }

    const settings = this.cb.getSettings()
    if (settings.typewriterMode && this.editing) {
      const rect = getCaretRect()
      if (rect && (rect.top !== 0 || rect.height !== 0)) {
        const target = rect.top + rect.height / 2 - this.container.clientHeight / 2
        if (Math.abs(target) > 4) this.container.scrollTop += target
      }
    }
  }

  // ---------------- 图片拖放 / 粘贴 ----------------

  private bindDragDrop(): void {
    this.lt.on(this.container, 'dragover', (e) => {
      if (e.dataTransfer?.types.includes('Files')) e.preventDefault()
    })
    this.lt.on(this.container, 'drop', (e) => this.onDrop(e))
    this.lt.on(this.container, 'paste', (e) => this.onPaste(e))
  }

  private async onDrop(e: DragEvent): Promise<void> {
    const files = e.dataTransfer?.files
    if (!files || files.length === 0) return
    e.preventDefault()
    const paths: string[] = []
    for (const f of [...files]) {
      const p = await this.persistImage(f)
      if (p) paths.push(p)
    }
    if (paths.length === 0) return

    if (this.editing) {
      this.insertIntoEditing(paths.map(imageMd).join('\n'))
    } else {
      const rect = this.container.getBoundingClientRect()
      let idx = this.vl.indexAtViewportY(e.clientY - rect.top)
      idx = Math.max(0, Math.min(idx, this.model.blocks.length - 1))
      const start = this.model.blocks[idx].start
      this.applySplice(start, start, `${paths.map(imageMd).join('\n')}\n\n`, start)
    }
  }

  private async onPaste(e: ClipboardEvent): Promise<void> {
    const files = e.clipboardData?.files
    if (!files || files.length === 0) return
    e.preventDefault()
    const paths: string[] = []
    for (const f of [...files]) {
      const p = await this.persistImage(f)
      if (p) paths.push(p)
    }
    if (paths.length === 0) return
    if (this.editing) this.insertIntoEditing(paths.map(imageMd).join('\n'))
    else {
      const end = this.text.length
      this.applySplice(end, end, `${paths.map(imageMd).join('\n')}\n`, end)
    }
  }

  private async persistImage(file: File): Promise<string | null> {
    const settings = this.cb.getSettings()
    const electronFile = file as File & { path?: string }
    const docPath = this.cb.getDocPath()
    if (electronFile.path) {
      return window.mdnote.importImage({
        srcPath: electronFile.path,
        docPath,
        folder: settings.imageFolder,
        pathType: settings.imagePathType
      })
    }
    const buffer = await file.arrayBuffer()
    const ext = `.${(file.type.split('/')[1] ?? 'png').replace('jpeg', 'jpg')}`
    return window.mdnote.saveImageBuffer({
      buffer,
      ext,
      docPath,
      folder: settings.imageFolder,
      pathType: settings.imagePathType
    })
  }

  private insertIntoEditing(markdown: string): void {
    if (!this.editing) return
    const index = this.editing.index
    const inner = this.vl.mountedRow(index)?.inner
    const b = this.model.blocks[index]
    if (!inner || !b) return
    const off = getCaretOffset(inner)
    const r = insertAt(inner.textContent ?? '', off, markdown)
    this.applySplice(b.start, b.end, r.text, b.start + r.caret)
  }

  // ---------------- 菜单驱动的格式操作 ----------------

  /** Ctrl+B / I / 删除线 / 行内代码 */
  wrapInline(marker: string): void {
    if (!this.editing) {
      // 在最后一个块末尾开始编辑后包裹
      const last = this.model.blocks.length - 1
      const b = this.model.blocks[last]
      this.enterEditing(last, b.raw.length)
    }
    const index = this.editing?.index
    const inner = index !== undefined ? this.vl.mountedRow(index)?.inner : undefined
    if (!inner) return
    const raw = inner.textContent ?? ''
    const r = wrapSelection(raw, getCaretOffset(inner), getCaretOffset(inner), marker)
    inner.textContent = r.text
    // 选中占位区间
    selectOffsets(inner, r.selStart, r.selEnd)
  }

  /** 插入代码块 / 公式 / 表格 / 引用等新块 */
  async insertBlock(kind: string): Promise<void> {
    const snippets: Record<string, string> = {
      code: '```\n\n```',
      math: '$$\n\n$$',
      table: '| 列1 | 列2 |\n| --- | --- |\n|  |  |',
      quote: '> 引用内容',
      hr: '---'
    }
    if (kind === 'image') {
      const path = await this.pickImage()
      if (path) this.insertIntoEditingOrEnd(imageMd(path))
      return
    }
    if (kind === 'link') {
      const url = await this.cb.prompt('输入链接地址', 'https://')
      if (url) this.insertIntoEditingOrEnd(`[链接文本](${url})`)
      return
    }
    const snippet = snippets[kind]
    if (!snippet) return
    const last = this.model.blocks.length - 1
    const end = this.model.blocks[last].end
    this.applySplice(end, end, `\n\n${snippet}`, end + 2)
  }

  private async pickImage(): Promise<string | null> {
    const src = await window.mdnote.showOpenDialog([
      { name: '图片', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'] }
    ])
    if (!src) return null
    const settings = this.cb.getSettings()
    return window.mdnote.importImage({
      srcPath: src,
      docPath: this.cb.getDocPath(),
      folder: settings.imageFolder,
      pathType: settings.imagePathType
    })
  }

  private insertIntoEditingOrEnd(markdown: string): void {
    if (this.editing) this.insertIntoEditing(markdown)
    else {
      const end = this.text.length
      this.applySplice(end, end, markdown, end)
    }
  }

  dispose(): void {
    for (const lt of this.rowLifetimes.values()) lt.dispose()
    this.rowLifetimes.clear()
    this.vl.dispose()
    this.lt.dispose()
  }
}

// ---------------- 辅助函数 ----------------

function imageMd(p: string): string {
  return `![](${p})`
}

function dirname(p: string): string {
  const normalized = p.replace(/\\/g, '/')
  const idx = normalized.lastIndexOf('/')
  return idx === -1 ? '' : p.slice(0, idx)
}

export function isDarkTheme(theme: string): boolean {
  return /dark|night|monokai|dracula/i.test(theme)
}

function selectionOffset(root: HTMLElement, node: Node, offset: number): number {
  if (!root.contains(node)) return 0
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let total = 0
  let cur = walker.nextNode()
  while (cur) {
    if (cur === node) return total + offset
    total += cur.textContent?.length ?? 0
    cur = walker.nextNode()
  }
  return total
}

function selectOffsets(root: HTMLElement, start: number, end: number): void {
  const s = findTextPosition(root, start)
  const en = findTextPosition(root, end)
  if (!s || !en) return
  const range = document.createRange()
  range.setStart(s.node, s.offset)
  range.setEnd(en.node, en.offset)
  const sel = window.getSelection()
  sel?.removeAllRanges()
  sel?.addRange(range)
}

function findTextPosition(root: HTMLElement, target: number): { node: Text; offset: number } | null {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let remaining = target
  let node = walker.nextNode()
  while (node) {
    const len = node.textContent?.length ?? 0
    if (remaining <= len) return { node: node as Text, offset: remaining }
    remaining -= len
    node = walker.nextNode()
  }
  return null
}

function caretPointOffset(root: HTMLElement, x: number, y: number): number | null {
  const doc = root.ownerDocument
  const range =
    (doc as unknown as { caretRangeFromPoint?: (x: number, y: number) => Range }).caretRangeFromPoint?.(
      x,
      y
    ) ?? null
  if (!range || !root.contains(range.startContainer)) return null
  return selectionOffset(root, range.startContainer, range.startOffset)
}
