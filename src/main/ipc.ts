import { app, dialog, ipcMain, Menu, shell, BrowserWindow } from 'electron'
import path from 'node:path'
import fsp from 'node:fs/promises'
import { listDir, readTextFile, writeTextFile, importImage, saveImageBuffer } from './fs-service'
import { WatcherManager } from './watcher-manager'
import {
  exportHtml,
  exportImage,
  exportPdf,
  pandocAvailable,
  pandocExport
} from './export-service'
import type { ContextMenuItem } from '@shared/types'

function settingsFile(): string {
  return path.join(app.getPath('userData'), 'settings.json')
}

function customCssFile(): string {
  return path.join(app.getPath('userData'), 'custom.css')
}

async function loadSettingsRaw(): Promise<unknown> {
  try {
    const text = await fsp.readFile(settingsFile(), 'utf8')
    return JSON.parse(text)
  } catch {
    return {}
  }
}

/** 集中注册全部 IPC 处理器；频道面保持最小，参数在调用处校验 */
export function registerIpc(watchers: WatcherManager): void {
  ipcMain.handle('file:read', (_e, p: string) => readTextFile(p))
  ipcMain.handle('file:write', (_e, p: string, text: string) => writeTextFile(p, text))

  ipcMain.handle('dialog:open', async (_e, filters) => {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
      filters: filters ?? [{ name: 'Markdown', extensions: ['md', 'markdown', 'txt'] }]
    })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('dialog:save', async (_e, defaultName: string, filters) => {
    const result = await dialog.showSaveDialog({
      defaultPath: defaultName,
      filters: filters ?? [{ name: 'Markdown', extensions: ['md'] }]
    })
    return result.canceled ? null : result.filePath
  })

  ipcMain.handle('dialog:folder', async () => {
    const result = await dialog.showOpenDialog({ properties: ['openDirectory'] })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('dir:list', (_e, p: string) => listDir(p))

  ipcMain.handle('dir:watch', (e, p: string) => {
    const win = BrowserWindow.fromWebContents(e.sender)
    if (!win) throw new Error('no window')
    return watchers.watch(win, p)
  })
  ipcMain.handle('dir:unwatch', (_e, id: number) => watchers.unwatch(id))

  ipcMain.handle('settings:load', () => loadSettingsRaw())
  ipcMain.handle('settings:save', (_e, data: unknown) =>
    fsp.writeFile(settingsFile(), JSON.stringify(data, null, 2), 'utf8')
  )

  ipcMain.handle('image:import', (_e, args) =>
    importImage(args.srcPath, args.docPath, args.folder, args.pathType)
  )
  ipcMain.handle('image:save-buffer', (_e, args) =>
    saveImageBuffer(Buffer.from(args.buffer), args.ext, args.docPath, args.folder, args.pathType)
  )

  ipcMain.handle('shell:open-path', (_e, p: string) => shell.openPath(p))
  ipcMain.on('shell:show-item', (_e, p: string) => shell.showItemInFolder(p))
  ipcMain.handle('shell:open-external', (_e, url: string) => {
    if (/^https?:\/\//i.test(url) || /^mailto:/i.test(url)) return shell.openExternal(url)
    throw new Error('Disallowed URL scheme')
  })

  ipcMain.handle('export:html', (_e, target: string, html: string) => exportHtml(target, html))
  ipcMain.handle('export:pdf', (_e, target: string, html: string, options) =>
    exportPdf(target, html, options)
  )
  ipcMain.handle('export:image', (_e, target: string, html: string, options) =>
    exportImage(target, html, options)
  )
  ipcMain.handle('pandoc:available', () => pandocAvailable())
  ipcMain.handle('pandoc:export', (_e, args) => pandocExport(args))

  ipcMain.handle('custom-css:load', async () => {
    try {
      return await fsp.readFile(customCssFile(), 'utf8')
    } catch {
      return ''
    }
  })

  ipcMain.handle('custom-css:open', async () => {
    await fsp.writeFile(customCssFile(), '/* 自定义样式将覆盖内置主题 */\n', { flag: 'a' })
    return shell.openPath(customCssFile())
  })

  ipcMain.handle('plugins:list', async () => {
    const dir = path.join(app.getPath('userData'), 'plugins')
    let names: string[] = []
    try {
      names = await fsp.readdir(dir)
    } catch {
      return []
    }
    const result = []
    for (const name of names) {
      const pj = path.join(dir, name, 'package.json')
      try {
        const text = await fsp.readFile(pj, 'utf8')
        const json = JSON.parse(text)
        if (json.main) result.push({ name: json.name ?? name, dir: path.join(dir, name), main: json.main })
      } catch {
        // 跳过无效插件目录
      }
    }
    return result
  })

  ipcMain.on('find:in-page', (e, text: string, forward: boolean, continueSearch: boolean) => {
    e.sender.findInPage(text, { forward, findNext: !continueSearch })
  })
  ipcMain.on('find:stop', (e) => e.sender.stopFindInPage('clearSelection'))

  ipcMain.handle('context-menu', async (e, items: ContextMenuItem[]) => {
    const win = BrowserWindow.fromWebContents(e.sender)
    return await new Promise<string | null>((resolve) => {
      const template = items.map((item) => {
        if (item.separator) return { type: 'separator' as const }
        return {
          label: item.label,
          enabled: item.enabled ?? true,
          click: () => resolve(item.id ?? null)
        }
      })
      const menu = Menu.buildFromTemplate(template)
      menu.once('menu-will-close', () => setTimeout(() => resolve(null), 0))
      menu.popup({ window: win ?? undefined })
    })
  })

  ipcMain.handle('path:user-data', () => app.getPath('userData'))

  ipcMain.handle('plugins:source', async (_e, dir: string, main: string) => {
    const resolved = path.resolve(dir, main)
    // 限定插件入口必须位于该插件目录内，防目录穿越
    if (!resolved.startsWith(path.resolve(dir))) throw new Error('Invalid plugin path')
    return fsp.readFile(resolved, 'utf8')
  })
}
