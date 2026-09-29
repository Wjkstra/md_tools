// 虚拟化列表：整篇文档中仅挂载视口附近（含 overscan）的块。
// 高度 = 初始估算 → ResizeObserver 实测校正；变化时增量平移后续行，
// 视口上方的变化反向补偿滚动，保证长文档滚动条稳定、DOM 节点数恒定。

import { Lifetime } from '../core/disposable'
import { estimateHeight, type Block } from './block-model'

export interface MountedRow {
  index: number
  root: HTMLDivElement
  inner: HTMLDivElement
}

export interface VirtualListHandlers {
  count(): number
  blockAt(i: number): Block
  onMount(row: MountedRow): void
  onUnmount(row: MountedRow): void
}

export interface ScrollAnchor {
  blockId?: string
  index?: number
  offset: number
}

export class VirtualList {
  private lt = new Lifetime()
  private spacer: HTMLDivElement
  private ro: ResizeObserver
  private heights: number[] = []
  private pos: Float64Array = new Float64Array(0)
  private total = 0
  private rows = new Map<number, MountedRow>()
  private measured = new Map<string, number>()
  private rangeStart = 0
  private rafQueued = false
  private readonly overscan = 400

  constructor(
    private container: HTMLElement,
    private handlers: VirtualListHandlers
  ) {
    this.spacer = document.createElement('div')
    this.spacer.className = 'vl-spacer'
    container.append(this.spacer)

    this.ro = new ResizeObserver((entries) => this.onMeasure(entries))
    this.lt.on(container, 'scroll', () => this.scheduleUpdate())
    this.lt.on(window, 'resize', () => this.scheduleUpdate())

    this.rebuild()
  }

  /** 结构变化后重建高度索引；保留按内容哈希的实测高度与滚动锚点 */
  rebuild(anchor?: ScrollAnchor): void {
    const n = this.handlers.count()
    this.heights = new Array(n)
    this.pos = new Float64Array(n + 1)
    for (let i = 0; i < n; i++) {
      const b = this.handlers.blockAt(i)
      const h = this.measured.get(b.id) ?? estimateHeight(b)
      this.heights[i] = h
      this.pos[i + 1] = this.pos[i] + h
    }
    this.total = this.pos[n]
    this.pruneMeasured()
    this.spacer.style.height = `${this.total}px`

    // 恢复滚动锚点
    if (anchor) {
      let idx = anchor.index ?? 0
      if (anchor.blockId) {
        for (let i = 0; i < n; i++) {
          if (this.handlers.blockAt(i).id === anchor.blockId) {
            idx = i
            break
          }
        }
      }
      this.container.scrollTop = this.pos[idx] + anchor.offset
    }

    // 简化处理：全部卸载后重挂当前窗口（窗口内行数很少）
    this.unmountAll()
    this.update()
  }

  get scrollTop(): number {
    return this.container.scrollTop
  }

  /** 供大纲 / TOC 跳转 */
  scrollToIndex(i: number, offset = 0): void {
    if (i < 0 || i >= this.heights.length) return
    this.container.scrollTop = this.pos[i] + offset
    this.update()
  }

  indexAtViewportY(y: number): number {
    // drop / 定位使用：将视口 y 换算为块索引
    const target = this.container.scrollTop + y
    return this.bisectLeft(target) - 1
  }

  positionOf(i: number): number {
    return this.pos[i] ?? 0
  }

  /** 给定文档 y，返回锚点块索引与块内偏移（结构重建前保存滚动位置） */
  anchorAt(y: number): { index: number; offset: number } {
    let lo = 0
    let hi = this.heights.length - 1
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1
      if (this.pos[mid] <= y) lo = mid
      else hi = mid - 1
    }
    return { index: lo, offset: y - this.pos[lo] }
  }

  /** 清理已不存在的旧块实测高度，防止长会话中 Map 无限增长 */
  private pruneMeasured(): void {
    if (this.measured.size <= 2000) return
    const alive = new Set<string>()
    for (let i = 0; i < this.handlers.count(); i++) alive.add(this.handlers.blockAt(i).id)
    for (const key of [...this.measured.keys()]) {
      if (!alive.has(key)) this.measured.delete(key)
    }
  }

  private scheduleUpdate(): void {
    if (this.rafQueued) return
    this.rafQueued = true
    requestAnimationFrame(() => {
      this.rafQueued = false
      this.update()
    })
  }

  private update(): void {
    const n = this.handlers.count()
    if (n === 0) {
      this.unmountAll()
      return
    }
    const top = this.container.scrollTop
    const bottom = top + this.container.clientHeight

    const s = Math.max(0, this.bisectLeft(top - this.overscan) - 1)
    let e = this.bisectLeft(bottom + this.overscan)
    e = Math.min(n, e + 1)

    this.rangeStart = s

    // 卸载离开窗口的行
    for (const [i, row] of this.rows) {
      if (i < s || i >= e) this.unmount(i, row)
    }
    // 挂载进入窗口的行
    for (let i = s; i < e; i++) {
      if (!this.rows.has(i)) this.mount(i)
    }
  }

  private bisectLeft(target: number): number {
    let lo = 0
    let hi = this.pos.length - 1
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (this.pos[mid] < target) lo = mid + 1
      else hi = mid
    }
    return lo
  }

  private mount(i: number): void {
    const root = document.createElement('div')
    root.className = 'vl-row'
    root.style.transform = `translate3d(0,${this.pos[i]}px,0)`
    const inner = document.createElement('div')
    inner.className = 'vl-row-inner'
    root.append(inner)
    this.spacer.append(root)
    const row: MountedRow = { index: i, root, inner }
    this.rows.set(i, row)
    this.handlers.onMount(row)
    // observe 在内容填充之后也能立即拿到首帧尺寸
    this.ro.observe(inner)
  }

  private unmount(i: number, row: MountedRow): void {
    this.ro.unobserve(row.inner)
    this.handlers.onUnmount(row)
    row.root.remove()
    this.rows.delete(i)
  }

  private unmountAll(): void {
    for (const [i, row] of [...this.rows]) this.unmount(i, row)
    this.rangeStart = 0
  }

  private onMeasure(entries: ResizeObserverEntry[]): void {
    for (const entry of entries) {
      let row: MountedRow | undefined
      for (const r of this.rows.values()) {
        if (r.inner === entry.target) {
          row = r
          break
        }
      }
      if (!row) continue
      const h = Math.max(8, Math.ceil(entry.contentRect.height))
      const index = row.index
      if (this.heights[index] === undefined || this.heights[index] === h) continue
      this.applyHeight(index, h)
    }
  }

  private applyHeight(index: number, h: number): void {
    const delta = h - this.heights[index]
    this.heights[index] = h
    this.measured.set(this.handlers.blockAt(index).id, h)

    for (let k = index + 1; k < this.pos.length; k++) this.pos[k] += delta
    this.total += delta
    this.spacer.style.height = `${this.total}px`

    // 视口上方的行高度变化 → 补偿滚动，避免内容跳动
    if (index < this.rangeStart) {
      this.container.scrollTop = this.container.scrollTop + delta
    }
    // 平移后续已挂载行
    for (const [i, row] of this.rows) {
      if (i > index) row.root.style.transform = `translate3d(0,${this.pos[i]}px,0)`
    }
  }

  /** 让某个块保持挂载（外部需要临时定位时） */
  mountedRow(i: number): MountedRow | undefined {
    return this.rows.get(i)
  }

  dispose(): void {
    this.unmountAll()
    this.ro.disconnect()
    this.spacer.remove()
    this.measured.clear()
    this.lt.dispose()
  }
}
