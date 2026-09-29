import { app, BrowserWindow, shell, protocol, Menu, session } from 'electron'
import path from 'node:path'
import { registerIpc } from './ipc'
import { WatcherManager } from './watcher-manager'
import { buildAppMenu } from './menu'
import { registerAssetProtocol } from './asset-protocol'
import { loadWindowState, persistWindowState } from './window-state'

// 必须在 app ready 前声明自定义协议的特权（与 https 同等安全策略）
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'mdasset',
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true }
  }
])

const watchers = new WatcherManager()

/**
 * CSP 由主进程按环境下发：
 * - 生产：脚本仅同源（无 unsafe-eval）
 * - 开发：允许 Vite 的 eval/HMR
 */
function installCsp(): void {
  const isDev = !!process.env['ELECTRON_RENDERER_URL']
  const scriptSrc = isDev ? "'self' 'unsafe-eval'" : "'self'"
  const csp =
    `default-src 'self'; ` +
    `script-src ${scriptSrc}; ` +
    `style-src 'self' 'unsafe-inline'; ` +
    `img-src 'self' data: blob: mdasset:; ` +
    `font-src 'self' data:; ` +
    `connect-src 'self' ws:; ` +
    `worker-src 'self' blob:; ` +
    `media-src 'self' mdasset:; ` +
    `object-src 'none'; base-uri 'none'`
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [csp]
      }
    })
  })
}

async function createWindow(): Promise<BrowserWindow> {
  const saved = await loadWindowState()
  const win = new BrowserWindow({
    width: saved.width ?? 1280,
    height: saved.height ?? 860,
    x: saved.x,
    y: saved.y,
    minWidth: 680,
    minHeight: 480,
    show: false,
    backgroundColor: '#ffffff',
    icon: path.resolve(__dirname, '../../build/icon.ico'),
    autoHideMenuBar: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false
    }
  })

  win.once('ready-to-show', () => {
    if (saved.maximized) win.maximize()
    win.show()
  })
  persistWindowState(win)

  // 渲染进程诊断日志（预加载错误、控制台、进程崩溃）
  win.webContents.on('console-message', (_e, level, message, line, sourceId) => {
    console.log(`[renderer:${level}] ${message} (${sourceId}:${line})`)
  })
  win.webContents.on('render-process-gone', (_e, details) => {
    console.error('[renderer gone]', JSON.stringify(details))
  })
  win.webContents.on('preload-error', (_e, preloadPath, err) => {
    console.error(`[preload error] ${preloadPath}`, err)
  })

  // 所有 window.open 交给系统浏览器，应用内不建第二个渲染器
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url).catch(() => {})
    return { action: 'deny' }
  })

  // 禁止渲染文档触发的页面级导航（编辑内容里的 <a> 由渲染进程自己接管）
  win.webContents.on('will-navigate', (e, url) => {
    const isDevUrl = process.env['ELECTRON_RENDERER_URL'] && url.startsWith(process.env['ELECTRON_RENDERER_URL'])
    if (!isDevUrl && !url.endsWith('/out/renderer/index.html')) e.preventDefault()
  })

  Menu.setApplicationMenu(buildAppMenu(win))
  registerIpc(watchers)
  registerAssetProtocol()

  if (process.env['ELECTRON_RENDERER_URL']) {
    const url = process.env['ELECTRON_RENDERER_URL']
    win.loadURL(process.env['SMOKE'] === '1' ? `${url}?smoke=1` : url)
  } else {
    const file = path.join(__dirname, '../renderer/index.html')
    if (process.env['SMOKE'] === '1') win.loadFile(file, { query: { smoke: '1' } })
    else win.loadFile(file)
  }

  return win
}

// 单实例：避免多个窗口重复持有文件监视器
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const wins = BrowserWindow.getAllWindows()
    if (wins.length > 0) {
      if (wins[0].isMinimized()) wins[0].restore()
      wins[0].focus()
    }
  })

  app.whenReady().then(async () => {
    installCsp()
    const win = await createWindow()

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow().catch((err) => console.error(err))
      }
    })

    // 冒烟测试：打开功能夹具，等待异步图表渲染，输出探测结果
    if (process.env['SMOKE'] === '1') {
      setTimeout(async () => {
        try {
          const fixture = path.resolve(process.env['SMOKE_FILE'] || 'test/fixture.md')
          await win.webContents.executeJavaScript(
            `window.__app.__open(${JSON.stringify(fixture)})`
          )
          await new Promise((r) => setTimeout(r, 1200))
          const result = await win.webContents.executeJavaScript(
            `JSON.stringify(window.__app.__probe())`
          )
          console.log(`[SMOKE] render: ${result}`)


          // ---- 交互 + 虚拟化 + 长文档性能 ----
          const interaction = await win.webContents.executeJavaScript(
            `(async () => {
              const toggled = await window.__app.__toggleFirstTask()

              const scroller = document.querySelector('.editor-scroll')
              scroller.scrollTop = scroller.scrollHeight
              await new Promise(r => setTimeout(r, 300))
              const mountedAtBottom = document.querySelectorAll('.vl-row').length

              // 6 万个块（30000 标题 + 30000 段落）
              const big = Array.from({ length: 30000 }, (_v, i) =>
                \`# 标题 \${i}\\n\\n这是第 \${i} 段，包含 **加粗** 与 \\\`code\\\` 内容。\`).join('\\n\\n')
              const t0 = performance.now()
              window.__app.__loadText(big)
              const t1 = performance.now()
              await new Promise(r => setTimeout(r, 200))
              const mountedTop = document.querySelectorAll('.vl-row').length
              scroller.scrollTop = scroller.scrollHeight / 2
              await new Promise(r => setTimeout(r, 300))
              const mountedMid = document.querySelectorAll('.vl-row').length
              scroller.scrollTop = scroller.scrollHeight
              await new Promise(r => setTimeout(r, 300))
              const mountedBottom2 = document.querySelectorAll('.vl-row').length

              return JSON.stringify({
                toggled, mountedAtBottom,
                loadMs: Math.round(t1 - t0),
                blocks: window.__app.__probe().blocks,
                mountedTop, mountedMid, mountedBottom2,
                totalHeight: Math.round(scroller.scrollHeight)
              })
            })()`
          )
          console.log(`[SMOKE] perf: ${interaction}`)

          // ---- 真实编辑流程（需重新打开夹具，perf 阶段换成了长文档）----
          await win.webContents.executeJavaScript(
            `window.__app.__open(${JSON.stringify(fixture)})`
          )
          await new Promise((r) => setTimeout(r, 500))
          const editResult = await win.webContents.executeJavaScript(
            `window.__app.__editTest().then(r => JSON.stringify(r))`
          )
          console.log(`[SMOKE] edit: ${editResult}`)
        } catch (err) {
          console.error('[SMOKE] probe failed', err)
        }
        watchers.dispose()
        app.quit()
      }, 1800)
    }
  })

  app.on('window-all-closed', () => {
    watchers.dispose()
    if (process.platform !== 'darwin') app.quit()
  })

  app.on('before-quit', () => watchers.dispose())
}
