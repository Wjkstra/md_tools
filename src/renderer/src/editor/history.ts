// 文档级编辑历史：每次结构/块提交记一条 splice，支持撤销重做，栈顶限量。

export interface EditEntry {
  start: number
  before: string
  after: string
  caret: number // 操作完成后的光标偏移
}

export class EditHistory {
  private undoStack: EditEntry[] = []
  private redoStack: EditEntry[] = []
  private readonly capacity = 300

  record(entry: EditEntry): void {
    if (entry.before === entry.after) return
    this.undoStack.push(entry)
    if (this.undoStack.length > this.capacity) this.undoStack.shift()
    this.redoStack.length = 0
  }

  /** 返回撤销所需的反向 splice；caret 为撤销后应定位的位置 */
  undo(): { start: number; remove: string; insert: string; caret: number } | null {
    const entry = this.undoStack.pop()
    if (!entry) return null
    this.redoStack.push(entry)
    return {
      start: entry.start,
      remove: entry.after,
      insert: entry.before,
      caret: entry.start + entry.before.length
    }
  }

  redo(): { start: number; remove: string; insert: string; caret: number } | null {
    const entry = this.redoStack.pop()
    if (!entry) return null
    this.undoStack.push(entry)
    return {
      start: entry.start,
      remove: entry.before,
      insert: entry.after,
      caret: entry.caret
    }
  }

  clear(): void {
    this.undoStack.length = 0
    this.redoStack.length = 0
  }
}
