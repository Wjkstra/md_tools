// 源码模式：CodeMirror 6，Markdown 语法、行内搜索、换行、明暗主题随设置。

import { EditorView, keymap, highlightSpecialChars } from '@codemirror/view'
import { EditorState, Compartment, type Extension } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { openSearchPanel } from '@codemirror/search'
import { markdown, markdownLanguage } from '@codemirror/lang-markdown'
import {
  bracketMatching,
  indentOnInput,
  syntaxHighlighting
} from '@codemirror/language'
import { oneDark } from '@codemirror/theme-one-dark'
import { gfmHighlightStyle, gfmDarkHighlightStyle } from './cm-highlight'
import { isDarkTheme } from './live-editor'
import { settingsService } from '../services/settings'

export class SourceEditor {
  view: EditorView
  private themeCompartment = new Compartment()

  constructor(
    parent: HTMLElement,
    private theme: string,
    private fontSize: number,
    private onChanged: () => void,
    private getDocPath: () => string | null
  ) {
    this.view = new EditorView({
      parent,
      state: EditorState.create({
        doc: '',
        extensions: this.extensions()
      })
    })
    this.bindMediaEvents()
  }

  // ---------------- 图片拖放 / 粘贴 ----------------

  private bindMediaEvents(): void {
    const dom = this.view.dom
    dom.addEventListener('dragover', this.onDragOver)
    dom.addEventListener('drop', this.onDrop)
    dom.addEventListener('paste', this.onPaste)
  }

  private onDragOver = (e: DragEvent): void => {
    if (e.dataTransfer?.types.includes('Files')) e.preventDefault()
  }

  private onDrop = (e: DragEvent): void => {
    const files = e.dataTransfer?.files
    if (!files || files.length === 0) return
    e.preventDefault()
    const pos = this.view.posAtCoords({ x: e.clientX, y: e.clientY })
    void this.insertFiles([...files], pos ?? this.view.state.selection.main.head)
  }

  private onPaste = (e: ClipboardEvent): void => {
    const files = e.clipboardData?.files
    if (!files || files.length === 0) return
    e.preventDefault()
    void this.insertFiles([...files], this.view.state.selection.main.head)
  }

  private async insertFiles(files: File[], pos: number): Promise<void> {
    const paths: string[] = []
    for (const file of files) {
      const p = await this.persistImage(file)
      if (p) paths.push(p)
    }
    if (paths.length === 0) return
    const md = paths.map((p) => `![](${p})`).join('\n')
    this.view.dispatch({
      changes: { from: pos, insert: md },
      selection: { anchor: pos + md.length }
    })
    this.onChanged()
  }

  private async persistImage(file: File): Promise<string | null> {
    const s = settingsService.current
    const docPath = this.getDocPath()
    const localPath = (file as File & { path?: string }).path
    if (localPath) {
      return window.mdnote.importImage({
        srcPath: localPath,
        docPath,
        folder: s.imageFolder,
        pathType: s.imagePathType
      })
    }
    const buffer = await file.arrayBuffer()
    const ext = `.${(file.type.split('/')[1] ?? 'png').replace('jpeg', 'jpg')}`
    return window.mdnote.saveImageBuffer({
      buffer,
      ext,
      docPath,
      folder: s.imageFolder,
      pathType: s.imagePathType
    })
  }

  showSearch(): void {
    openSearchPanel(this.view)
  }

  private extensions(): Extension[] {
    return [
      history(),
      bracketMatching(),
      indentOnInput(),
      highlightSpecialChars(),
      keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
      markdown({ base: markdownLanguage }),
      syntaxHighlighting(isDarkTheme(this.theme) ? gfmDarkHighlightStyle : gfmHighlightStyle, {
        fallback: true
      }),
      this.themeCompartment.of(this.themeExtension()),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) this.onChanged()
      }),
      EditorView.lineWrapping
    ]
  }

  private themeExtension() {
    const dark = isDarkTheme(this.theme)
    const base = EditorView.theme({
      '&': {
        height: '100%',
        fontSize: `${this.fontSize}px`,
        backgroundColor: dark ? '#0d1117' : '#ffffff',
        color: dark ? '#c9d1d9' : '#24292f'
      },
      '.cm-content': {
        padding: '24px 8px 200px 48px',
        maxWidth: '900px',
        margin: '0 auto',
        fontFamily: "'JetBrains Mono','Consolas','Courier New',monospace",
        lineHeight: '1.7'
      },
      '.cm-scroller': { overflow: 'auto' },
      '.cm-gutters': {
        backgroundColor: dark ? '#0d1117' : '#f6f8fa',
        color: '#8b949e',
        border: 'none'
      },
      '.cm-cursor': { borderLeftColor: dark ? '#c9d1d9' : '#24292f' },
      '&.cm-focused': { outline: 'none' },
      '.cm-activeLine': { backgroundColor: dark ? '#161b22' : '#f6f8fa' }
    })
    return dark ? [base, oneDark] : [base]
  }

  setText(text: string, offset?: number): void {
    this.view.dispatch({
      changes: { from: 0, to: this.view.state.doc.length, insert: text }
    })
    if (offset !== undefined) {
      const pos = Math.max(0, Math.min(offset, text.length))
      this.view.dispatch({ selection: { anchor: pos } })
      this.view.requestMeasure()
    }
  }

  getText(): string {
    return this.view.state.doc.toString()
  }

  getOffset(): number {
    return this.view.state.selection.main.head
  }

  setOffset(offset: number): void {
    this.view.dispatch({ selection: { anchor: offset }, scrollIntoView: true })
    this.view.focus()
  }

  /** 跳转到指定行（1 基） */
  gotoLine(line: number): void {
    const doc = this.view.state.doc
    const safe = Math.max(1, Math.min(line, doc.lines))
    const pos = doc.line(safe).from
    this.view.dispatch({ selection: { anchor: pos }, scrollIntoView: true })
    this.view.focus()
  }

  focus(): void {
    this.view.focus()
  }

  /** 设置变更（主题/字号） */
  applyTheme(theme: string, fontSize: number): void {
    this.theme = theme
    this.fontSize = fontSize
    this.view.dispatch({
      effects: this.themeCompartment.reconfigure(this.themeExtension())
    })
  }

  dispose(): void {
    const dom = this.view.dom
    dom.removeEventListener('dragover', this.onDragOver)
    dom.removeEventListener('drop', this.onDrop)
    dom.removeEventListener('paste', this.onPaste)
    this.view.destroy()
  }
}
