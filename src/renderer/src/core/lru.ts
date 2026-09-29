/**
 * 定容 LRU 缓存，用于块渲染结果、Mermaid SVG 等。
 * 超过容量时淘汰最久未使用项；若值持有重资源，可注册 dispose 回调。
 */
export class LRU<K, V> {
  private map = new Map<K, V>()

  constructor(
    private capacity: number,
    private onEvict: ((value: V) => void) | null = null
  ) {}

  get(key: K): V | undefined {
    const value = this.map.get(key)
    if (value === undefined) return undefined
    // 触达即刷新为最新
    this.map.delete(key)
    this.map.set(key, value)
    return value
  }

  has(key: K): boolean {
    return this.map.has(key)
  }

  set(key: K, value: V): void {
    if (this.map.has(key)) this.map.delete(key)
    this.map.set(key, value)
    while (this.map.size > this.capacity) {
      const oldest = this.map.keys().next().value as K | undefined
      if (oldest === undefined) break
      const evicted = this.map.get(oldest)
      this.map.delete(oldest)
      if (evicted !== undefined && this.onEvict) this.onEvict(evicted)
    }
  }

  get size(): number {
    return this.map.size
  }

  clear(): void {
    if (this.onEvict) {
      for (const v of this.map.values()) this.onEvict(v)
    }
    this.map.clear()
  }
}
