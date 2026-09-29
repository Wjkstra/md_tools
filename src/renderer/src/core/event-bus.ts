import type { Lifetime } from './disposable'

/** 微型类型安全事件总线，可与 Lifetime 绑定自动退订 */
export class EventBus<Events extends Record<string, unknown>> {
  private listeners = new Map<keyof Events, Set<(payload: unknown) => void>>()

  on<K extends keyof Events>(
    key: K,
    handler: (payload: Events[K]) => void,
    lifetime?: Lifetime
  ): void {
    let set = this.listeners.get(key)
    if (!set) {
      set = new Set()
      this.listeners.set(key, set)
    }
    const wrapped = handler as (payload: unknown) => void
    set.add(wrapped)
    lifetime?.add(() => set?.delete(wrapped))
  }

  emit<K extends keyof Events>(key: K, payload: Events[K]): void {
    const set = this.listeners.get(key)
    if (!set) return
    for (const handler of [...set]) {
      try {
        handler(payload)
      } catch (err) {
        console.error('[EventBus]', key, err)
      }
    }
  }

  clear(): void {
    this.listeners.clear()
  }
}
