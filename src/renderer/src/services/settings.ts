// 设置服务：主进程 JSON 持久化 + 内存缓存 + 变更订阅

import { DEFAULT_SETTINGS, type AppSettings } from '@shared/types'
import type { Lifetime } from '../core/disposable'

class SettingsService {
  current: AppSettings = { ...DEFAULT_SETTINGS }

  async load(): Promise<AppSettings> {
    const raw = await window.mdnote.loadSettings()
    this.current = { ...DEFAULT_SETTINGS, ...(raw as Partial<AppSettings>) }
    return this.current
  }

  async save(): Promise<void> {
    await window.mdnote.saveSettings(this.current)
  }

  /** 局部更新并持久化 */
  async patch(p: Partial<AppSettings>): Promise<AppSettings> {
    this.current = { ...this.current, ...p }
    await this.save()
    for (const cb of this.listeners) cb(this.current)
    return this.current
  }

  private listeners = new Set<(s: AppSettings) => void>()

  onChange(cb: (s: AppSettings) => void, lt?: Lifetime): void {
    this.listeners.add(cb)
    lt?.add(() => this.listeners.delete(cb))
  }
}

export const settingsService = new SettingsService()
