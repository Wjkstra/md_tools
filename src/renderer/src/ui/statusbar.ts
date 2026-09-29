// 状态栏：保存状态、字数 / 字符 / 行数、阅读时长、当前模式。

import { h } from '../core/dom'
import type { DocStats } from '../services/word-count'

export interface StatusState {
  dirty: boolean
  mode: 'live' | 'source'
  stats: DocStats
  fileName: string
}

export class StatusBar {
  el: HTMLElement
  private stateEl: HTMLElement
  private modeEl: HTMLElement
  private statsEl: HTMLElement

  constructor() {
    this.stateEl = h('span', { class: 'status-save' }, '● 已保存')
    this.modeEl = h('span', { class: 'status-mode' }, '实时视图')
    this.statsEl = h('span', { class: 'status-stats' }, '')
    const left = h('div', { class: 'status-left' }, this.stateEl)
    const right = h('div', { class: 'status-right' }, this.statsEl, this.modeEl)
    this.el = h('footer', { class: 'statusbar' }, left, right)
  }

  update(state: StatusState): void {
    this.stateEl.textContent = state.dirty ? '○ 未保存' : '● 已保存'
    this.stateEl.classList.toggle('is-dirty', state.dirty)
    this.modeEl.textContent = state.mode === 'live' ? '实时视图' : '源码视图'
    const { stats } = state
    this.statsEl.textContent =
      `${stats.words} 字 · ${stats.chars} 字符 · ${stats.lines} 行 · 约 ${stats.readingMinutes} 分钟`
    this.stateEl.title = state.fileName
  }
}
