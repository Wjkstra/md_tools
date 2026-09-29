// 轻量 DOM 工具

export type ElChild = Node | string | null | undefined | false

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Partial<HTMLElementTagNameMap[K]> & { class?: string } = {},
  ...children: ElChild[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag)
  for (const [key, value] of Object.entries(props)) {
    if (value == null) continue
    if (key === 'class') el.className = String(value)
    else if (key === 'dataset' && typeof value === 'object') {
      Object.assign(el.dataset, value)
    } else {
      ;(el as unknown as Record<string, unknown>)[key] = value
    }
  }
  appendChildren(el, children)
  return el
}

export function appendChildren(el: HTMLElement, children: ElChild[]): void {
  for (const child of children) {
    if (child == null || child === false) continue
    el.append(child instanceof Node ? child : document.createTextNode(child))
  }
}

export function clear(el: HTMLElement): void {
  el.replaceChildren()
}

/** 将 selection 折叠到元素开头 */
export function collapseSelection(el: HTMLElement, atStart = true): void {
  const range = document.createRange()
  range.selectNodeContents(el)
  range.collapse(atStart)
  const sel = window.getSelection()
  sel?.removeAllRanges()
  sel?.addRange(range)
}

/**
 * 计算 selection 锚点相对 contenteditable 根的字符偏移。
 * 仅遍历文本节点，换行以 \n 计。
 */
export function getCaretOffset(root: HTMLElement): number {
  const sel = window.getSelection()
  if (!sel || sel.rangeCount === 0) return 0
  const range = sel.getRangeAt(0)
  if (!root.contains(range.startContainer)) return 0

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let offset = 0
  let node = walker.nextNode()
  while (node) {
    if (node === range.startContainer) return offset + range.startOffset
    offset += (node.textContent?.length ?? 0)
    node = walker.nextNode()
  }
  return offset
}

/** 按字符偏移在 contenteditable 根内定位光标 */
export function setCaretOffset(root: HTMLElement, offset: number): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let remaining = offset
  let node = walker.nextNode()
  const range = document.createRange()
  while (node) {
    const len = node.textContent?.length ?? 0
    if (remaining <= len) {
      range.setStart(node, Math.max(0, Math.min(remaining, len)))
      range.collapse(true)
      const sel = window.getSelection()
      sel?.removeAllRanges()
      sel?.addRange(range)
      return
    }
    remaining -= len
    node = walker.nextNode()
  }
  range.selectNodeContents(root)
  range.collapse(false)
  const sel = window.getSelection()
  sel?.removeAllRanges()
  sel?.addRange(range)
}

/** 当前光标的视口位置（用于打字机模式） */
export function getCaretRect(): DOMRect | null {
  const sel = window.getSelection()
  if (!sel || sel.rangeCount === 0) return null
  const range = sel.getRangeAt(0).cloneRange()
  let rect = range.getBoundingClientRect()
  if (rect.width === 0 && rect.height === 0) {
    // 部分浏览器对折叠范围返回空矩形，插入临时探针测量
    const probe = document.createElement('span')
    probe.append('​')
    range.insertNode(probe)
    rect = probe.getBoundingClientRect()
    probe.remove()
  }
  return rect
}

export function debounce<A extends unknown[]>(fn: (...args: A) => void, wait: number): (...args: A) => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  return (...args: A) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      fn(...args)
    }, wait)
  }
}
