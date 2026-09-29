// 模态对话框：alert / confirm / prompt / 设置面板 / PDF 选项。
// 全部为 DOM 实现；打开期间登记监听，关闭即移除。

import { Lifetime } from '../core/disposable'
import { h } from '../core/dom'
import { settingsService } from '../services/settings'
import { BUILTIN_THEMES } from '../services/themes'
import type { PdfExportOptions } from '@shared/types'

interface ModalHandle {
  close: () => void
}

function openModal(title: string, body: HTMLElement, footer?: HTMLElement): ModalHandle {
  const lt = new Lifetime()
  const overlay = h('div', { class: 'modal-overlay' })
  const box = h('div', { class: 'modal-box' })
  const titleEl = h('div', { class: 'modal-title' }, title)
  box.append(titleEl, h('div', { class: 'modal-body' }, body))
  if (footer) box.append(footer)
  overlay.append(box)
  document.body.append(overlay)

  const close = (): void => {
    lt.dispose()
    overlay.remove()
  }
  lt.on(overlay, 'mousedown', (e) => {
    if (e.target === overlay) close()
  })
  lt.on(document, 'keydown', (e) => {
    if (e.key === 'Escape') close()
  })
  return { close }
}

export async function alert(message: string): Promise<void> {
  const body = h('div', { class: 'modal-message' }, message)
  const footer = h('div', { class: 'modal-footer' })
  return new Promise((resolve) => {
    const handle = openModal('提示', body, footer)
    const ok = h('button', { class: 'btn btn-primary', type: 'button' }, '确定')
    footer.append(ok)
    ok.addEventListener('click', () => {
      handle.close()
      resolve()
    })
  })
}

export async function confirm(message: string): Promise<boolean> {
  const body = h('div', { class: 'modal-message' }, message)
  const footer = h('div', { class: 'modal-footer' })
  return new Promise((resolve) => {
    const handle = openModal('请确认', body, footer)
    const cancel = h('button', { class: 'btn', type: 'button' }, '取消')
    const ok = h('button', { class: 'btn btn-primary', type: 'button' }, '确定')
    footer.append(cancel, ok)
    cancel.addEventListener('click', () => {
      handle.close()
      resolve(false)
    })
    ok.addEventListener('click', () => {
      handle.close()
      resolve(true)
    })
  })
}

export async function prompt(message: string, defaultValue: string): Promise<string | null> {
  const input = h('input', { class: 'input', value: defaultValue }) as HTMLInputElement
  const body = h('div', {}, h('div', { class: 'modal-message' }, message), input)
  const footer = h('div', { class: 'modal-footer' })
  setTimeout(() => input.focus(), 0)
  return new Promise((resolve) => {
    const handle = openModal('输入', body, footer)
    const cancel = h('button', { class: 'btn', type: 'button' }, '取消')
    const ok = h('button', { class: 'btn btn-primary', type: 'button' }, '确定')
    footer.append(cancel, ok)
    const submit = (): void => {
      handle.close()
      resolve(input.value)
    }
    ok.addEventListener('click', submit)
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submit()
    })
    cancel.addEventListener('click', () => {
      handle.close()
      resolve(null)
    })
  })
}

// ---------------- 设置面板 ----------------

function toggleRow(label: string, checked: boolean, onChange: (v: boolean) => void): HTMLElement {
  const input = document.createElement('input')
  input.type = 'checkbox'
  input.checked = checked
  input.addEventListener('change', () => onChange(input.checked))
  return h('label', { class: 'settings-row' }, h('span', {}, label), input)
}

export async function showSettings(onApplied: () => void): Promise<void> {
  const body = h('div', { class: 'settings-body' })

  // 主题
  const themeSelect = document.createElement('select')
  themeSelect.className = 'input'
  for (const t of BUILTIN_THEMES) {
    const opt = document.createElement('option')
    opt.value = t.id
    opt.textContent = t.name
    opt.selected = settingsService.current.theme === t.id
    themeSelect.append(opt)
  }
  body.append(h('label', { class: 'settings-row' }, h('span', {}, '主题'), themeSelect))

  // 字号
  const fontRange = document.createElement('input')
  fontRange.type = 'range'
  fontRange.min = '12'
  fontRange.max = '28'
  fontRange.value = String(settingsService.current.fontSize)
  const fontVal = h('span', { class: 'settings-range-val' }, `${fontRange.value}px`)
  body.append(h('label', { class: 'settings-row' }, h('span', {}, '字号'), h('span', { class: 'settings-range' }, fontRange, fontVal)))
  fontRange.addEventListener('input', () => (fontVal.textContent = `${fontRange.value}px`))

  // 图片目录
  const folderInput = document.createElement('input')
  folderInput.className = 'input'
  folderInput.value = settingsService.current.imageFolder
  body.append(h('label', { class: 'settings-row' }, h('span', {}, '图片目录'), folderInput))

  const pathSelect = document.createElement('select')
  pathSelect.className = 'input'
  for (const [v, label] of [['relative', '相对路径'], ['absolute', '绝对路径']] as const) {
    const opt = document.createElement('option')
    opt.value = v
    opt.textContent = label
    opt.selected = settingsService.current.imagePathType === v
    pathSelect.append(opt)
  }
  body.append(h('label', { class: 'settings-row' }, h('span', {}, '图片路径'), pathSelect))

  body.append(h('div', { class: 'settings-divider' }, '编辑选项'))
  body.append(
    toggleRow('Mermaid 图表', settingsService.current.mermaid, (v) =>
      settingsService.patch({ mermaid: v })
    )
  )
  body.append(
    toggleRow('代码行号', settingsService.current.codeLineNumbers, (v) =>
      settingsService.patch({ codeLineNumbers: v })
    )
  )
  body.append(
    toggleRow('输入符号自动配对', settingsService.current.autoBracket, (v) =>
      settingsService.patch({ autoBracket: v })
    )
  )
  body.append(
    toggleRow('智能标点（弯引号）', settingsService.current.smartPunctuation, (v) =>
      settingsService.patch({ smartPunctuation: v })
    )
  )
  body.append(
    toggleRow('==文字高亮== 扩展', settingsService.current.highlightMark, (v) =>
      settingsService.patch({ highlightMark: v })
    )
  )
  body.append(
    toggleRow('自动保存（停顿 1 秒后落盘）', settingsService.current.autoSave, (v) =>
      settingsService.patch({ autoSave: v })
    )
  )

  // ---------------- 插件管理 ----------------
  body.append(h('div', { class: 'settings-divider' }, '插件（变更后需重启应用）'))
  const pluginInfos = await window.mdnote.listPlugins()
  const pluginSelection = new Set(settingsService.current.enabledPlugins)
  if (pluginInfos.length === 0) {
    body.append(
      h(
        'div',
        { class: 'settings-hint' },
        '未发现插件。将插件放入用户数据目录的 plugins/ 文件夹后重启设置。'
      )
    )
  }
  for (const info of pluginInfos) {
    body.append(
      toggleRow(info.name, pluginSelection.has(info.name), (checked) => {
        if (checked) pluginSelection.add(info.name)
        else pluginSelection.delete(info.name)
      })
    )
  }

  const footer = h('div', { class: 'modal-footer' })
  await new Promise<void>((resolve) => {
    const handle = openModal('设置', body, footer)
    const cancel = h('button', { class: 'btn', type: 'button' }, '关闭')
    const ok = h('button', { class: 'btn btn-primary', type: 'button' }, '应用')
    footer.append(cancel, ok)
    cancel.addEventListener('click', () => {
      handle.close()
      resolve()
    })
    ok.addEventListener('click', async () => {
      const pluginsChanged =
        pluginSelection.size !== settingsService.current.enabledPlugins.length ||
        [...pluginSelection].some(
          (name) => !settingsService.current.enabledPlugins.includes(name)
        )
      await settingsService.patch({
        theme: themeSelect.value,
        fontSize: Number(fontRange.value),
        imageFolder: folderInput.value || 'assets',
        imagePathType: pathSelect.value === 'absolute' ? 'absolute' : 'relative',
        enabledPlugins: [...pluginSelection]
      })
      onApplied()
      handle.close()
      resolve()
      if (pluginsChanged) {
        const restart = await confirm('插件设置已变更，是否立即重启应用？')
        if (restart) location.reload()
      }
    })
  })
}

// ---------------- PDF 选项 ----------------

export async function pdfOptionsDialog(): Promise<{
  options: PdfExportOptions
  includeToc: boolean
} | null> {
  const body = h('div', { class: 'settings-body' })
  const margin = document.createElement('select')
  margin.className = 'input'
  for (const [v, label] of [
    ['default', '默认页边距'],
    ['narrow', '窄页边距'],
    ['none', '最小页边距']
  ] as const) {
    const opt = document.createElement('option')
    opt.value = v
    opt.textContent = label
    margin.append(opt)
  }
  body.append(h('label', { class: 'settings-row' }, h('span', {}, '页边距'), margin))

  const landscape = document.createElement('input')
  landscape.type = 'checkbox'
  body.append(h('label', { class: 'settings-row' }, h('span', {}, '横向'), landscape))

  const pageNumbers = document.createElement('input')
  pageNumbers.type = 'checkbox'
  pageNumbers.checked = true
  body.append(h('label', { class: 'settings-row' }, h('span', {}, '页码'), pageNumbers))

  const toc = document.createElement('input')
  toc.type = 'checkbox'
  body.append(h('label', { class: 'settings-row' }, h('span', {}, '包含自动目录'), toc))

  const footer = h('div', { class: 'modal-footer' })
  return new Promise((resolve) => {
    const handle = openModal('PDF 导出', body, footer)
    const cancel = h('button', { class: 'btn', type: 'button' }, '取消')
    const ok = h('button', { class: 'btn btn-primary', type: 'button' }, '导出')
    footer.append(cancel, ok)
    cancel.addEventListener('click', () => {
      handle.close()
      resolve(null)
    })
    ok.addEventListener('click', () => {
      handle.close()
      resolve({
        options: {
          landscape: landscape.checked,
          margin: margin.value as PdfExportOptions['margin'],
          showPageNumbers: pageNumbers.checked
        },
        includeToc: toc.checked
      })
    })
  })
}
