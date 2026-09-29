// 表格可视化编辑：单击选中单元格、再次单击编辑、列边框拖拽调宽、
// 右键增删行列与对齐；变更序列化为 GFM 表格 Markdown 回传。

import type { Lifetime } from '../core/disposable'

export type TableChangeHandler = (markdown: string) => void

type Align = '' | 'left' | 'center' | 'right'

interface EdgeHit {
  col: number
  x: number
}

export class TableController {
  private selected: HTMLTableCellElement | null = null
  private editingCell: HTMLTableCellElement | null = null
  private editAbort: AbortController | null = null
  private edge: EdgeHit | null = null
  private resizer: HTMLDivElement | null = null

  constructor(
    private table: HTMLTableElement,
    lt: Lifetime,
    private onChange: TableChangeHandler,
    private onNavigate: (flatPos: number) => void = () => {}
  ) {
    if (!table.tHead) table.createTHead()
    lt.on(table, 'click', (e) => this.onClick(e))
    lt.on(table, 'mousedown', (e) => this.onMouseDown(e))
    lt.on(table, 'mousemove', (e) => this.onMouseMove(e))
    lt.on(table, 'mouseleave', () => this.clearEdge())
    lt.on(table, 'contextmenu', (e) => this.onContextMenu(e))
    lt.add(() => this.abortEdit())
  }

  private cellFromEvent(e: MouseEvent): HTMLTableCellElement | null {
    return (e.target as HTMLElement).closest('td,th') as HTMLTableCellElement | null
  }

  // ---------------- 选择 / 编辑 ----------------

  private onClick(e: MouseEvent): void {
    const cell = this.cellFromEvent(e)
    if (!cell || this.editingCell) return
    if (this.selected === cell) this.startEdit(cell)
    else this.select(cell)
  }

  private select(cell: HTMLTableCellElement): void {
    this.abortEdit()
    this.clearSelection()
    this.selected = cell
    cell.classList.add('cell-selected')
  }

  private clearSelection(): void {
    this.selected?.classList.remove('cell-selected')
    this.selected = null
  }

  private startEdit(cell: HTMLTableCellElement): void {
    this.editingCell = cell
    cell.contentEditable = 'true'
    cell.classList.add('cell-editing')
    cell.focus()
    const range = document.createRange()
    range.selectNodeContents(cell)
    range.collapse(false)
    const sel = window.getSelection()
    sel?.removeAllRanges()
    sel?.addRange(range)

    // 编辑会话内的全部监听走独立 AbortController；提交/卸载时一次性移除
    const abort = new AbortController()
    this.editAbort = abort
    const sig: AddEventListenerOptions = { signal: abort.signal }
    cell.addEventListener(
      'keydown',
      (ev) => {
        if (ev.key === 'Enter' || ev.key === 'Escape') {
          ev.preventDefault()
          this.commitEdit()
        } else if (ev.key === 'Tab') {
          ev.preventDefault()
          this.navigateToAdjacent(cell, ev.shiftKey)
        }
      },
      sig
    )
    cell.addEventListener('blur', () => this.commitEdit(), sig)
  }

  private commitEdit(): void {
    const cell = this.editingCell
    if (!cell) return
    this.editingCell = null
    this.abortEdit()
    cell.contentEditable = 'false'
    cell.classList.remove('cell-editing')
    this.emitChange()
  }

  private abortEdit(): void {
    this.editAbort?.abort()
    this.editAbort = null
  }

  // ---------------- Tab 导航 ----------------

  private orderedCells(): HTMLTableCellElement[] {
    const result: HTMLTableCellElement[] = []
    for (const row of this.table.rows) {
      for (const cell of row.cells) result.push(cell)
    }
    return result
  }

  /**
   * Tab 流程：先登记「待编辑位置」，再提交当前单元格；
   * 提交会让外部重建表格，重建后由 editCellAt 恢复编辑。
   */
  private navigateToAdjacent(current: HTMLTableCellElement, backward: boolean): void {
    const cells = this.orderedCells()
    const flat = cells.indexOf(current)
    if (backward) {
      if (flat <= 0) return
      this.onNavigate(flat - 1)
      this.commitEdit()
      return
    }
    if (flat < cells.length - 1) {
      this.onNavigate(flat + 1)
      this.commitEdit()
      return
    }
    // 末单元格 Tab：在最后一行后追加一行，再进入新行首格
    const lastRow = this.table.rows[this.table.rows.length - 1]
    if (lastRow) this.insertRow(lastRow, false)
    const newCells = this.orderedCells()
    this.onNavigate(newCells.length - (lastRow ? lastRow.cells.length : 1))
    this.commitEdit()
  }

  /** 重建后按文档序位置恢复编辑；位置非法返回 false */
  editCellAt(flatPos: number): boolean {
    const cells = this.orderedCells()
    const cell = cells[flatPos]
    if (!cell) return false
    this.select(cell)
    this.startEdit(cell)
    return true
  }

  // ---------------- 列宽拖拽 ----------------

  private hitEdge(cell: HTMLTableCellElement, x: number): EdgeHit | null {
    const rect = cell.getBoundingClientRect()
    if (rect.right - x < 6) return { col: cell.cellIndex, x: rect.right }
    if (x - rect.left < 6 && cell.cellIndex > 0) return { col: cell.cellIndex - 1, x: rect.left }
    return null
  }

  private onMouseMove(e: MouseEvent): void {
    if (e.buttons !== 0) return
    const cell = this.cellFromEvent(e)
    if (!cell || this.editingCell) {
      this.clearEdge()
      return
    }
    this.edge = this.hitEdge(cell, e.clientX)
    this.table.style.cursor = this.edge ? 'col-resize' : ''
    if (this.edge) this.showResizer(this.edge.x)
    else this.hideResizer()
  }

  private onMouseDown(e: MouseEvent): void {
    if (!this.edge) return
    e.preventDefault()
    e.stopPropagation()
    this.beginDrag(this.edge)
  }

  private clearEdge(): void {
    this.edge = null
    this.table.style.cursor = ''
    this.hideResizer()
  }

  private showResizer(x: number): void {
    if (!this.resizer) {
      this.resizer = document.createElement('div')
      this.resizer.className = 'col-resizer'
      this.table.style.position = this.table.style.position || 'relative'
      this.table.append(this.resizer)
    }
    const tableRect = this.table.getBoundingClientRect()
    this.resizer.style.left = `${x - tableRect.left}px`
    this.resizer.style.top = '0'
    this.resizer.style.height = `${tableRect.height}px`
  }

  private hideResizer(): void {
    this.resizer?.remove()
    this.resizer = null
  }

  private beginDrag(edge: EdgeHit): void {
    const tableRect = this.table.getBoundingClientRect()
    let colgroup = this.table.querySelector('colgroup')
    if (!colgroup) {
      colgroup = document.createElement('colgroup')
      const cols = this.table.tHead?.rows[0]?.cells.length ?? 0
      for (let i = 0; i < cols; i++) colgroup.append(document.createElement('col'))
      this.table.prepend(colgroup)
    }
    const colEl = colgroup.children[edge.col] as HTMLElement
    const headCell = this.table.tHead?.rows[0]?.cells[edge.col]
    const startWidth = headCell?.getBoundingClientRect().width ?? 80
    const startX = edge.x

    const onMove = (ev: MouseEvent): void => {
      const w = Math.max(36, startWidth + ev.clientX - startX)
      colEl.style.width = `${w}px`
      this.showResizer(ev.clientX)
    }
    const onUp = (): void => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      this.table.style.cursor = ''
      this.hideResizer()
      this.emitChange()
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    void tableRect
  }

  // ---------------- 右键菜单 ----------------

  private async onContextMenu(e: MouseEvent): Promise<void> {
    const cell = this.cellFromEvent(e)
    if (!cell) return
    e.preventDefault()
    if (this.selected !== cell) this.select(cell)
    const colCount = this.table.tHead?.rows[0]?.cells.length ?? 1
    const result = await window.mdnote.showContextMenu([
      { id: 'row-above', label: '上方插入行' },
      { id: 'row-below', label: '下方插入行' },
      { id: 'col-left', label: '左侧插入列' },
      { id: 'col-right', label: '右侧插入列' },
      { separator: true },
      { id: 'align-left', label: '左对齐' },
      { id: 'align-center', label: '居中对齐' },
      { id: 'align-right', label: '右对齐' },
      { id: 'align-clear', label: '清除对齐' },
      { separator: true },
      { id: 'delete-row', label: '删除行' },
      { id: 'delete-col', label: '删除列', enabled: colCount > 1 }
    ])
    if (result) this.applyMenu(result, cell)
  }

  private applyMenu(action: string, cell: HTMLTableCellElement): void {
    const row = cell.parentElement as HTMLTableRowElement
    const col = cell.cellIndex
    switch (action) {
      case 'row-above':
        this.insertRow(row, true)
        break
      case 'row-below':
        this.insertRow(row, false)
        break
      case 'col-left':
        this.insertColumn(col, true)
        break
      case 'col-right':
        this.insertColumn(col, false)
        break
      case 'delete-row':
        if (this.table.rows.length > 1) row.remove()
        break
      case 'delete-col':
        for (const r of this.table.rows) r.deleteCell(col)
        this.table.querySelector('colgroup')?.children[col]?.remove()
        break
      case 'align-left':
      case 'align-center':
      case 'align-right':
      case 'align-clear': {
        const align = action === 'align-clear' ? '' : (action.replace('align-', '') as Align)
        this.setColumnAlign(col, align)
        break
      }
    }
    this.clearSelection()
    this.emitChange()
  }

  private insertRow(row: HTMLTableRowElement, above: boolean): void {
    const cols = this.table.tHead?.rows[0]?.cells.length ?? row.cells.length
    const newRow = document.createElement('tr')
    for (let i = 0; i < cols; i++) newRow.append(document.createElement('td'))
    row.insertAdjacentElement(above ? 'beforebegin' : 'afterend', newRow)
  }

  private insertColumn(col: number, left: boolean): void {
    const insertPos = left ? col : col + 1
    for (const r of this.table.rows) {
      const tag = r.parentElement?.tagName === 'THEAD' ? 'th' : 'td'
      r.insertBefore(document.createElement(tag), r.children[insertPos] ?? null)
    }
    const colgroup = this.table.querySelector('colgroup')
    if (colgroup) {
      colgroup.insertBefore(document.createElement('col'), colgroup.children[insertPos] ?? null)
    }
  }

  private setColumnAlign(col: number, align: Align): void {
    for (const r of this.table.rows) {
      const c = r.cells[col]
      if (c) c.style.textAlign = align
    }
  }

  // ---------------- 序列化 ----------------

  private currentAligns(): Align[] {
    const headCells = this.table.tHead?.rows[0]?.cells
    const result: Align[] = []
    if (!headCells) return result
    for (const c of headCells) {
      const a = c.style.textAlign
      result.push(a === 'left' || a === 'center' || a === 'right' ? a : '')
    }
    return result
  }

  private emitChange(): void {
    const colCount = this.table.tHead?.rows[0]?.cells.length ?? 0
    if (colCount === 0) return

    const escape = (s: string): string => s.replace(/\|/g, '\\|').trim()
    const lines: string[] = []

    const headerRow = this.table.tHead!.rows[0]!
    lines.push(`| ${[...headerRow.cells].map((c) => escape(c.textContent ?? '')).join(' | ')} |`)
    const aligns = this.currentAligns()
    lines.push(
      `| ${aligns
        .map((a) => (a === 'left' ? ':--' : a === 'right' ? '--:' : a === 'center' ? ':--:' : '---'))
        .join(' | ')} |`
    )
    if (this.table.tBodies[0]) {
      for (const r of this.table.tBodies[0].rows) {
        const cells = [...r.cells].map((c) => escape(c.textContent ?? ''))
        while (cells.length < colCount) cells.push('')
        lines.push(`| ${cells.join(' | ')} |`)
      }
    }
    this.onChange(lines.join('\n'))
  }
}
