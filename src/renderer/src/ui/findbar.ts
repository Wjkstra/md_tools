// 查找条：实时模式下调用主进程 findInPage。

import { Lifetime } from '../core/disposable'
import { h } from '../core/dom'

export class FindBar {
  el: HTMLElement
  private input: HTMLInputElement
  private lt = new Lifetime()

  constructor() {
    this.input = document.createElement('input')
    this.input.type = 'text'
    this.input.className = 'find-input'
    this.input.placeholder = '查找…'
    const close = h('button', { class: 'find-close', type: 'button' }, '×')
    this.el = h('div', { class: 'findbar' }, this.input, close)
    this.el.hidden = true

    this.lt.on(this.input, 'input', () => {
      if (this.input.value) {
        window.mdnote.findInPage(this.input.value, true, false)
      } else {
        window.mdnote.stopFindInPage()
      }
    })
    this.lt.on(this.input, 'keydown', (e) => {
      if (e.key === 'Enter') {
        window.mdnote.findInPage(this.input.value, !e.shiftKey, false)
      } else if (e.key === 'Escape') {
        this.close()
      }
    })
    this.lt.on(close, 'click', () => this.close())
  }

  open(): void {
    this.el.hidden = false
    this.input.focus()
  }

  close(): void {
    this.el.hidden = true
    window.mdnote.stopFindInPage()
  }

  dispose(): void {
    this.lt.dispose()
  }
}
