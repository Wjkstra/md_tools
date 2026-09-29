import { app, BrowserWindow } from 'electron'
import path from 'node:path'
import fsp from 'node:fs/promises'
import { spawn } from 'node:child_process'
import type { ImageExportOptions, PdfExportOptions, PandocExportArgs } from '@shared/types'

// ---------------- HTML ----------------

export async function exportHtml(targetPath: string, html: string): Promise<void> {
  await fsp.writeFile(targetPath, html, 'utf8')
}

// ---------------- PDF / 图片：通过隐藏窗口离屏渲染 ----------------

async function withExportWindow(
  html: string,
  run: (win: BrowserWindow) => Promise<void>
): Promise<void> {
  const tmpDir = path.join(app.getPath('temp'), 'mdnote-export')
  await fsp.mkdir(tmpDir, { recursive: true })
  const tmpFile = path.join(tmpDir, `doc-${process.pid}-${Date.now()}.html`)
  await fsp.writeFile(tmpFile, html, 'utf8')

  const win = new BrowserWindow({
    show: false,
    webPreferences: { sandbox: true, contextIsolation: true }
  })

  try {
    await win.loadFile(tmpFile)
    await run(win)
  } finally {
    if (!win.isDestroyed()) win.destroy()
    fsp.rm(tmpFile, { force: true }).catch(() => {})
  }
}

const PDF_MARGINS: Record<PdfExportOptions['margin'], { top: number; bottom: number; left: number; right: number }> = {
  default: { top: 2.0, bottom: 2.0, left: 1.8, right: 1.8 },
  narrow: { top: 1.0, bottom: 1.0, left: 1.0, right: 1.0 },
  none: { top: 0.2, bottom: 0.2, left: 0.2, right: 0.2 }
}

export async function exportPdf(
  targetPath: string,
  html: string,
  options: PdfExportOptions
): Promise<void> {
  await withExportWindow(html, async (win) => {
    const margin = PDF_MARGINS[options.margin]
    const data = await win.webContents.printToPDF({
      landscape: options.landscape,
      printBackground: true,
      margins: {
        marginType: 'custom',
        top: margin.top,
        bottom: margin.bottom,
        left: margin.left,
        right: margin.right
      },
      displayHeaderFooter: options.showPageNumbers,
      headerTemplate: '<div></div>',
      footerTemplate:
        '<div style="width:100%;text-align:center;font-size:9px;color:#888;"><span class="pageNumber"></span> / <span class="totalPages"></span></div>'
    })
    await fsp.writeFile(targetPath, data)
  })
}

export async function exportImage(
  targetPath: string,
  html: string,
  options: ImageExportOptions
): Promise<void> {
  await withExportWindow(html, async (win) => {
    const { width, height } = await win.webContents.executeJavaScript(
      `(function(){
        var b=document.body, d=document.documentElement;
        return {
          width: Math.max(b.scrollWidth, d.scrollWidth),
          height: Math.max(b.scrollHeight, d.scrollHeight)
        };
      })()`
    )
    // 限制超长图高度，防止异常分配
    const w = Math.min(Math.ceil(width) + 24, 16384)
    const h = Math.min(Math.ceil(height) + 24, 16384)
    win.setContentSize(w, h)
    // 等待 resize 后布局完成
    await new Promise((r) => setTimeout(r, 120))
    const image = await win.webContents.capturePage()
    const buffer =
      options.format === 'jpeg' ? image.toJPEG(92) : image.toPNG()
    await fsp.writeFile(targetPath, buffer)
  })
}

// ---------------- Pandoc ----------------

export function pandocAvailable(): Promise<boolean> {
  return new Promise((resolve) => {
    const child = spawn('pandoc', ['--version'], { windowsHide: true })
    child.on('error', () => resolve(false))
    child.on('exit', (code) => resolve(code === 0))
  })
}

export async function pandocExport(args: PandocExportArgs): Promise<{ ok: boolean; error?: string }> {
  const tmpDir = path.join(app.getPath('temp'), 'mdnote-export')
  await fsp.mkdir(tmpDir, { recursive: true })
  const input = path.join(tmpDir, `doc-${Date.now()}.md`)
  await fsp.writeFile(input, args.markdown, 'utf8')

  const pandocArgs = [input, '-o', args.targetPath, '--standalone']
  if (args.withToc) pandocArgs.push('--toc')

  return new Promise((resolve) => {
    const child = spawn('pandoc', pandocArgs, { windowsHide: true })
    let stderr = ''
    child.stderr.on('data', (d) => (stderr += d.toString()))
    child.on('error', (err) => {
      fsp.rm(input, { force: true }).catch(() => {})
      resolve({ ok: false, error: err.message })
    })
    child.on('exit', (code) => {
      fsp.rm(input, { force: true }).catch(() => {})
      resolve(code === 0 ? { ok: true } : { ok: false, error: stderr || `exit code ${code}` })
    })
  })
}
