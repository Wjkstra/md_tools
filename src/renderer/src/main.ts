// 渲染进程入口

import './styles/base.css'
import './styles/layout.css'
import './styles/editor.css'
import './styles/components.css'
import 'katex/dist/katex.min.css'

import { App } from './app'

const app = new App()
app.init().catch((err) => console.error('[boot failed]', err))

// 冒烟模式：暴露 app 供主进程自动化驱动
if (new URLSearchParams(location.search).get('smoke') === '1') {
  ;(window as unknown as { __app: App }).__app = app
}

// 兜底：记录未捕获错误，避免静默失败
window.addEventListener('error', (e) => {
  console.error('[window error]', e.error ?? e.message)
})
window.addEventListener('unhandledrejection', (e) => {
  console.error('[unhandled rejection]', e.reason)
})
