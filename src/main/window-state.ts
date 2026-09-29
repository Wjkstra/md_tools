// 窗口位置 / 尺寸 / 最大化状态持久化（debounce 写入 userData/window-state.json）

import { app, BrowserWindow } from 'electron'
import path from 'node:path'
import fsp from 'node:fs/promises'

interface SavedState {
  x?: number
  y?: number
  width: number
  height: number
  maximized?: boolean
}

function stateFile(): string {
  return path.join(app.getPath('userData'), 'window-state.json')
}

export async function loadWindowState(): Promise<Partial<SavedState>> {
  try {
    return JSON.parse(await fsp.readFile(stateFile(), 'utf8')) as Partial<SavedState>
  } catch {
    return {}
  }
}

/** 监听窗口变化并去抖保存；返回清理函数 */
export function persistWindowState(win: BrowserWindow): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  let destroyed = false

  const save = (): void => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(async () => {
      timer = null
      if (destroyed || win.isDestroyed()) return
      const state: SavedState = win.isMaximized()
        ? { ...(win.getNormalBounds() as SavedState), maximized: true }
        : ({ ...(win.getBounds() as SavedState), maximized: false })
      try {
        await fsp.writeFile(stateFile(), JSON.stringify(state), 'utf8')
      } catch {
        // 忽略临时写入失败
      }
    }, 400)
  }

  win.on('resize', save)
  win.on('move', save)
  win.on('maximize', save)
  win.on('unmaximize', save)

  return () => {
    destroyed = true
    if (timer) clearTimeout(timer)
  }
}
