// 图标生成：Offscreen 离屏渲染 build/icon.svg → 多尺寸 PNG，
// 再把 [16,24,32,48,64,128,256] PNG 组装为单个 build/icon.ico（PNG 内嵌，Vista+ 支持）。
// 用法：npx electron scripts/make-icons.mjs

import { app, BrowserWindow, nativeImage } from 'electron'
import fs from 'node:fs'
import path from 'node:path'

const ROOT = process.cwd()
const TMP = path.join(ROOT, '.icongen')
const ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

async function run() {
  fs.mkdirSync(TMP, { recursive: true })
  const svg = fs.readFileSync(path.join(ROOT, 'build/icon.svg'), 'utf8')
  const taggedSvg = svg.replace('<svg ', '<svg id="icon" width="256" height="256" ')

  const win = new BrowserWindow({
    width: 512,
    height: 512,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    webPreferences: { sandbox: true }
  })

  win.setBackgroundColor('#00000000')

  const page = `data:text/html;charset=utf-8,${encodeURIComponent(
    `<!doctype html><style>html,body{margin:0}</style>${taggedSvg}`
  )}`
  await win.loadURL(page)

  /** JS 改变 SVG 尺寸 → capturePage 全窗口 → 裁剪目标区域 */
  async function captureAt(size) {
    await win.webContents.executeJavaScript(
      `var i=document.getElementById('icon');` +
        `i.setAttribute('width','${size}');i.setAttribute('height','${size}');`
    )
    // 等待渐变 / 布局
    await new Promise((r) => setTimeout(r, 120))
    const full = await win.webContents.capturePage()
    return full.crop({ x: 0, y: 0, width: size, height: size }).toPNG()
  }

  const pngs = new Map()
  for (const size of ICO_SIZES) {
    const png = await captureAt(size)
    fs.writeFileSync(path.join(TMP, `${size}.png`), png)
    pngs.set(size, png)
  }

  // 512 主 PNG（通用 / Linux）
  fs.writeFileSync(path.join(ROOT, 'build/icon.png'), await captureAt(512))

  // 验证透明通道：左上角像素 alpha 应为 0（圆角外）
  const corner = nativeImage
    .createFromBuffer(pngs.get(256))
    .crop({ x: 0, y: 0, width: 1, height: 1 })
    .toBitmap()
  const alphaOk = corner[3] === 0
  // 中心像素应为白色（M 或箭头区域）
  console.log(`[icon] corner alpha: ${alphaOk ? '0 ok' : corner[3]}`)

  // 组装 ICO
  const ico = buildIco(ICO_SIZES.map((size) => ({ size, data: pngs.get(size) })))
  fs.writeFileSync(path.join(ROOT, 'build/icon.ico'), ico)
  console.log(`[icon] build/icon.ico (${ICO_SIZES.join(', ')}), build/icon.png (512)`)

  app.quit()
}

/** 将多张 PNG 打包进一个 ICO 容器 */
function buildIco(images) {
  const n = images.length
  const header = Buffer.alloc(6)
  header.writeUInt16LE(0, 0) // reserved
  header.writeUInt16LE(1, 2) // type: icon
  header.writeUInt16LE(n, 4)

  const entries = Buffer.alloc(16 * n)
  let offset = 6 + entries.length
  const parts = [header, entries]

  images.forEach((img, i) => {
    const e = i * 16
    entries.writeUInt8(img.size >= 256 ? 0 : img.size, e) // width
    entries.writeUInt8(img.size >= 256 ? 0 : img.size, e + 1) // height
    entries.writeUInt8(0, e + 2) // palette
    entries.writeUInt8(0, e + 3) // reserved
    entries.writeUInt16LE(1, e + 4) // color planes
    entries.writeUInt16LE(32, e + 6) // bit depth
    entries.writeUInt32LE(img.data.length, e + 8)
    entries.writeUInt32LE(offset, e + 12)
    offset += img.data.length
    parts.push(img.data)
  })

  return Buffer.concat(parts)
}

app.whenReady().then(run).catch((err) => {
  console.error(err)
  app.quit(1)
})
