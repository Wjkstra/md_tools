// 主进程 / 预加载 / 渲染进程共享的类型与 IPC 契约

export interface DirEntry {
  name: string
  path: string
  isDirectory: boolean
}

export type ImagePathType = 'relative' | 'absolute'

export interface AppSettings {
  theme: string
  fontSize: number
  tabSize: number
  codeLineNumbers: boolean
  mermaid: boolean
  smartPunctuation: boolean
  focusMode: boolean
  typewriterMode: boolean
  autoBracket: boolean
  imageFolder: string
  imagePathType: ImagePathType
  highlightMark: boolean
  autoSave: boolean
  sidebarVisible: boolean
  sidebarTab: 'files' | 'outline'
  lastFile: string | null
  lastFolder: string | null
  enabledPlugins: string[]
  recentFiles: string[]
  recentFolders: string[]
}

export const DEFAULT_SETTINGS: AppSettings = {
  theme: 'github-light',
  fontSize: 16,
  tabSize: 2,
  codeLineNumbers: true,
  mermaid: true,
  smartPunctuation: false,
  focusMode: false,
  typewriterMode: false,
  autoBracket: true,
  imageFolder: 'assets',
  imagePathType: 'relative',
  highlightMark: true,
  autoSave: false,
  sidebarVisible: false,
  sidebarTab: 'files',
  lastFile: null,
  lastFolder: null,
  enabledPlugins: [],
  recentFiles: [],
  recentFolders: []
}

export interface WatchChange {
  watchId: number
  path: string
  kind: string
}

export interface ImageImportArgs {
  srcPath: string
  docPath: string | null
  folder: string
  pathType: ImagePathType
}

export interface ImageBufferArgs {
  buffer: ArrayBuffer
  ext: string
  docPath: string | null
  folder: string
  pathType: ImagePathType
}

export interface PdfExportOptions {
  landscape: boolean
  margin: 'default' | 'narrow' | 'none'
  showPageNumbers: boolean
}

export interface ImageExportOptions {
  format: 'png' | 'jpeg'
}

export interface PandocExportArgs {
  markdown: string
  targetPath: string
  withToc: boolean
}

export interface ContextMenuItem {
  id?: string
  label?: string
  enabled?: boolean
  separator?: boolean
}

export type MenuAction =
  | 'new'
  | 'open'
  | 'open-folder'
  | 'save'
  | 'save-as'
  | 'export-html'
  | 'export-pdf'
  | 'export-png'
  | 'export-jpeg'
  | 'export-docx'
  | 'export-epub'
  | 'export-latex'
  | 'export-odt'
  | 'close-folder'
  | 'quit'
  | 'bold'
  | 'italic'
  | 'strikethrough'
  | 'inline-code'
  | 'code-block'
  | 'link'
  | 'image'
  | 'quote'
  | 'table'
  | 'math'
  | 'hr'
  | 'find'
  | 'toggle-source'
  | 'toggle-sidebar'
  | 'toggle-focus'
  | 'toggle-typewriter'
  | 'outline-tab'
  | 'files-tab'
  | 'settings'
  | 'open-custom-css'
  | 'toggle-fullscreen'
  | 'actual-size'
  | 'zoom-in'
  | 'zoom-out'
  | 'reload-file'
  | 'about'

export interface PluginInfo {
  name: string
  dir: string
  main: string
}

/** 通过 contextBridge 暴露给渲染进程的完整 API */
export interface MdNoteAPI {
  // 菜单
  onMenuAction(cb: (action: MenuAction) => void): () => void
  // 文件读写
  readTextFile(path: string): Promise<string>
  writeTextFile(path: string, text: string): Promise<void>
  // 对话框
  showOpenDialog(filters?: { name: string; extensions: string[] }[]): Promise<string | null>
  showSaveDialog(defaultName: string, filters?: { name: string; extensions: string[] }[]): Promise<string | null>
  showFolderDialog(): Promise<string | null>
  // 目录 / 监视
  listDir(path: string): Promise<DirEntry[]>
  watchFolder(path: string): Promise<number>
  unwatchFolder(watchId: number): Promise<void>
  onWatchChange(cb: (e: WatchChange) => void): () => void
  // 设置
  loadSettings(): Promise<AppSettings>
  saveSettings(settings: AppSettings): Promise<void>
  // 图片
  importImage(args: ImageImportArgs): Promise<string>
  saveImageBuffer(args: ImageBufferArgs): Promise<string>
  // Shell
  openPath(path: string): Promise<void>
  showItemInFolder(path: string): void
  openExternal(url: string): Promise<void>
  // 导出
  exportHtml(targetPath: string, html: string): Promise<void>
  exportPdf(targetPath: string, html: string, options: PdfExportOptions): Promise<void>
  exportImage(targetPath: string, html: string, options: ImageExportOptions): Promise<void>
  pandocAvailable(): Promise<boolean>
  pandocExport(args: PandocExportArgs): Promise<{ ok: boolean; error?: string }>
  // 自定义 CSS
  loadCustomCss(): Promise<string>
  openCustomCssFile(): Promise<void>
  // 插件
  listPlugins(): Promise<PluginInfo[]>
  readPluginSource(dir: string, main: string): Promise<string>
  // 页面内查找
  findInPage(text: string, forward: boolean, continueSearch: boolean): Promise<void>
  stopFindInPage(): void
  // 右键菜单
  showContextMenu(items: ContextMenuItem[]): Promise<string | null>
  // 元信息
  getUserDataPath(): string
}
