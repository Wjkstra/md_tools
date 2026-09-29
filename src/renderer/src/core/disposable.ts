/**
 * 统一的资源生命周期管理。
 * 所有组件通过 Lifetime 收集释放函数；dispose 时逆序执行且只执行一次。
 * 约定：事件监听、Observer、定时器、订阅、DOM 引用必须登记。
 */
export type Disposable = () => void

export class Lifetime {
  private items: Disposable[] = []
  private _disposed = false

  get disposed(): boolean {
    return this._disposed
  }

  add<T extends Disposable>(d: T): T {
    if (this._disposed) {
      d()
      return d
    }
    this.items.push(d)
    return d
  }

  /** 登记 addEventListener，dispose 时通过 AbortSignal 一次性全部移除 */
  on<K extends keyof WindowEventMap>(
    target: Window,
    type: K,
    handler: (e: WindowEventMap[K]) => void,
    options?: AddEventListenerOptions
  ): void
  on<K extends keyof HTMLElementEventMap>(
    target: HTMLElement,
    type: K,
    handler: (e: HTMLElementEventMap[K]) => void,
    options?: AddEventListenerOptions
  ): void
  on<K extends keyof DocumentEventMap>(
    target: Document,
    type: K,
    handler: (e: DocumentEventMap[K]) => void,
    options?: AddEventListenerOptions
  ): void
  on(target: EventTarget, type: string, handler: EventListener, options?: AddEventListenerOptions): void
  on(target: EventTarget, type: string, handler: EventListener, options?: AddEventListenerOptions): void {
    if (this._disposed) return
    target.addEventListener(type, handler, { ...options, signal: this.signal })
  }

  /** 供 fetch / 自定义异步流程使用的取消信号 */
  get signal(): AbortSignal {
    if (!this._signal) {
      this._signal = new AbortController()
      this.items.push(() => this._signal?.abort())
    }
    return this._signal.signal
  }
  private _signal: AbortController | null = null

  interval(ms: number, cb: () => void): void {
    const t = setInterval(cb, ms)
    this.items.push(() => clearInterval(t))
  }

  timeout(ms: number, cb: () => void): void {
    const t = setTimeout(cb, ms)
    this.items.push(() => clearTimeout(t))
  }

  dispose(): void {
    if (this._disposed) return
    this._disposed = true
    // 逆序释放：后创建的依赖先销毁
    for (let i = this.items.length - 1; i >= 0; i--) {
      try {
        this.items[i]()
      } catch (err) {
        console.error('[Lifetime] dispose error', err)
      }
    }
    this.items.length = 0
    this._signal = null
  }
}
