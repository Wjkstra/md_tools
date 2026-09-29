// 主题服务：data-theme 切换 CSS 变量集；字号 CSS 变量；自定义 CSS 注入。

export const BUILTIN_THEMES = [
  { id: 'github-light', name: 'GitHub 亮色' },
  { id: 'github-dark', name: 'GitHub 暗色' },
  { id: 'sepia', name: '护眼米色' },
  { id: 'midnight', name: '午夜蓝' }
]

let customStyleEl: HTMLStyleElement | null = null

export function applyTheme(theme: string, fontSize: number): void {
  document.documentElement.dataset.theme = theme
  document.documentElement.style.setProperty('--font-size', `${fontSize}px`)
}

export async function loadCustomCss(): Promise<void> {
  const css = await window.mdnote.loadCustomCss()
  if (!customStyleEl) {
    customStyleEl = document.createElement('style')
    customStyleEl.id = 'custom-css-style'
    document.head.append(customStyleEl)
  }
  customStyleEl.textContent = css
}

export async function reloadCustomCss(): Promise<void> {
  await loadCustomCss()
}
