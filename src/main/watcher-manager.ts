import fs from 'node:fs'
import type { BrowserWindow } from 'electron'
import type { WatchChange } from '@shared/types'

/**
 * 文件夹监视器管理：
 * - 每个打开的文件夹仅持有一个递归 FSWatcher（Windows 原生支持 recursive）
 * - 事件做 150ms 合并，避免大批量保存时风暴
 * - 切换/关闭文件夹必须 close，防止句柄泄漏
 */
export class WatcherManager {
  private watchers = new Map<number, fs.FSWatcher>()
  private timers = new Map<number, NodeJS.Timeout>()
  private pending = new Map<number, WatchChange[]>()
  private seq = 0

  watch(win: BrowserWindow, folder: string): number {
    const id = ++this.seq
    const watcher = fs.watch(
      folder,
      { recursive: true, encoding: 'utf8' },
      (event, filename) => {
        if (!filename) return
        const change: WatchChange = { watchId: id, path: filename, kind: event }
        const list = this.pending.get(id) ?? []
        list.push(change)
        this.pending.set(id, list)
        if (!this.timers.has(id)) {
          const timer = setTimeout(() => this.flush(win, id), 150)
          this.timers.set(id, timer)
        }
      }
    )
    watcher.on('error', () => this.unwatch(id))
    this.watchers.set(id, watcher)
    return id
  }

  private flush(win: BrowserWindow, id: number): void {
    this.timers.delete(id)
    const list = this.pending.get(id) ?? []
    this.pending.delete(id)
    if (list.length === 0 || win.isDestroyed()) return
    // 同一路径仅保留最后一个事件
    const merged = new Map<string, WatchChange>()
    for (const c of list) merged.set(c.path.toLowerCase(), c)
    for (const change of merged.values()) {
      win.webContents.send('watch:change', change)
    }
  }

  unwatch(id: number): void {
    const timer = this.timers.get(id)
    if (timer) {
      clearTimeout(timer)
      this.timers.delete(id)
    }
    this.pending.delete(id)
    const watcher = this.watchers.get(id)
    if (watcher) {
      watcher.close()
      this.watchers.delete(id)
    }
  }

  dispose(): void {
    for (const id of [...this.watchers.keys()]) this.unwatch(id)
  }
}
