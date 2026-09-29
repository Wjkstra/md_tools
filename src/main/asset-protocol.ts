import { protocol } from 'electron'
import path from 'node:path'
import fsp from 'node:fs/promises'

// 仅允许图片类扩展名，防止通过 Markdown 图片语法读取任意本地文件
const MIME_MAP: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.bmp': 'image/bmp',
  '.avif': 'image/avif',
  '.ico': 'image/x-icon',
  '.svg': 'image/svg+xml'
}

// URL 形如: mdasset://asset/?base=<文档目录>&src=<相对或绝对路径>
export function registerAssetProtocol(): void {
  protocol.handle('mdasset', async (request) => {
    try {
      const url = new URL(request.url)
      const base = url.searchParams.get('base') ?? ''
      let src = url.searchParams.get('src') ?? ''
      if (!src) return new Response('Bad request', { status: 400 })

      let resolved: string
      if (path.isAbsolute(src) || /^[A-Za-z]:[\\/]/.test(src)) {
        resolved = path.resolve(src)
      } else {
        // 规范化并去掉前导 ./
        resolved = path.resolve(base, src.replace(/^\.\//, ''))
      }

      const ext = path.extname(resolved).toLowerCase()
      const mime = MIME_MAP[ext]
      if (!mime) return new Response('Forbidden file type', { status: 403 })

      const data = await fsp.readFile(resolved)
      return new Response(new Uint8Array(data), {
        headers: { 'Content-Type': mime, 'Cache-Control': 'no-cache' }
      })
    } catch {
      return new Response('Not found', { status: 404 })
    }
  })
}
