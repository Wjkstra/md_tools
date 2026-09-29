import { contextBridge, ipcRenderer } from 'electron'
import type {
  AppSettings,
  ContextMenuItem,
  ImageExportOptions,
  ImageBufferArgs,
  ImageImportArgs,
  MdNoteAPI,
  MenuAction,
  PandocExportArgs,
  PdfExportOptions,
  WatchChange
} from '../shared/types'

const api: MdNoteAPI = {
  onMenuAction(cb: (action: MenuAction) => void): (() => void) {
    const handler = (_e: unknown, action: MenuAction): void => cb(action)
    ipcRenderer.on('menu:action', handler)
    return () => ipcRenderer.removeListener('menu:action', handler)
  },

  readTextFile: (p) => ipcRenderer.invoke('file:read', p),
  writeTextFile: (p, text) => ipcRenderer.invoke('file:write', p, text),

  showOpenDialog: (filters) => ipcRenderer.invoke('dialog:open', filters ?? null),
  showSaveDialog: (defaultName, filters) =>
    ipcRenderer.invoke('dialog:save', defaultName, filters ?? null),
  showFolderDialog: () => ipcRenderer.invoke('dialog:folder'),

  listDir: (p) => ipcRenderer.invoke('dir:list', p),
  watchFolder: (p) => ipcRenderer.invoke('dir:watch', p),
  unwatchFolder: (id) => ipcRenderer.invoke('dir:unwatch', id),

  onWatchChange(cb: (e: WatchChange) => void): () => void {
    const handler = (_e: unknown, change: WatchChange): void => cb(change)
    ipcRenderer.on('watch:change', handler)
    return () => ipcRenderer.removeListener('watch:change', handler)
  },

  loadSettings: (): Promise<AppSettings> => ipcRenderer.invoke('settings:load'),
  saveSettings: (settings: AppSettings) => ipcRenderer.invoke('settings:save', settings),

  importImage: (args: ImageImportArgs) => ipcRenderer.invoke('image:import', args),
  saveImageBuffer: (args: ImageBufferArgs) =>
    ipcRenderer.invoke('image:save-buffer', args),

  openPath: (p) => ipcRenderer.invoke('shell:open-path', p).then(() => {}),
  showItemInFolder: (p) => ipcRenderer.send('shell:show-item', p),
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),

  exportHtml: (target, html) => ipcRenderer.invoke('export:html', target, html),
  exportPdf: (target, html, options: PdfExportOptions) =>
    ipcRenderer.invoke('export:pdf', target, html, options),
  exportImage: (target, html, options: ImageExportOptions) =>
    ipcRenderer.invoke('export:image', target, html, options),

  pandocAvailable: () => ipcRenderer.invoke('pandoc:available'),
  pandocExport: (args: PandocExportArgs) => ipcRenderer.invoke('pandoc:export', args),

  loadCustomCss: () => ipcRenderer.invoke('custom-css:load'),
  openCustomCssFile: () => ipcRenderer.invoke('custom-css:open'),

  listPlugins: () => ipcRenderer.invoke('plugins:list'),
  readPluginSource: (dir, main) => ipcRenderer.invoke('plugins:source', dir, main),

  findInPage: (text, forward, continueSearch) => {
    ipcRenderer.send('find:in-page', text, forward, continueSearch)
    return Promise.resolve()
  },
  stopFindInPage: () => ipcRenderer.send('find:stop'),

  showContextMenu: (items: ContextMenuItem[]) => ipcRenderer.invoke('context-menu', items),

  getUserDataPath: () => ipcRenderer.sendSync('path:user-data')
}

contextBridge.exposeInMainWorld('mdnote', api)
