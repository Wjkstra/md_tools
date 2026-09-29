import { app } from 'electron'
import path from 'node:path'
import fs from 'node:fs'
import fsp from 'node:fs/promises'

const MAX_TEXT_BYTES = 50 * 1024 * 1024 // 50MB 读取上限，防止异常巨型文件拖垮渲染进程

export async function readTextFile(filePath: string): Promise<string> {
  const abs = path.resolve(filePath)
  const stat = await fsp.stat(abs)
  if (!stat.isFile()) throw new Error('Not a file')
  if (stat.size > MAX_TEXT_BYTES) throw new Error('File too large (limit 50MB)')
  return fsp.readFile(abs, 'utf8')
}

export async function writeTextFile(filePath: string, text: string): Promise<void> {
  const abs = path.resolve(filePath)
  await fsp.mkdir(path.dirname(abs), { recursive: true })
  await fsp.writeFile(abs, text, 'utf8')
}

/** 惰性列出单层目录，目录在前、文件在后 */
export async function listDir(dirPath: string): Promise<import('@shared/types').DirEntry[]> {
  const abs = path.resolve(dirPath)
  const dirents = await fsp.readdir(abs, { withFileTypes: true })
  const entries = dirents
    .filter((d) => !d.name.startsWith('.'))
    .map((d) => ({
      name: d.name,
      path: path.join(abs, d.name),
      isDirectory: d.isDirectory()
    }))
  entries.sort((a, b) => {
    if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1
    return a.name.localeCompare(b.name, 'zh-CN', { numeric: true })
  })
  return entries
}

/** 将拖入 / 粘贴的图片拷贝到文档旁的图片目录，返回嵌入路径 */
export async function importImage(
  srcPath: string,
  docPath: string | null,
  folder: string,
  pathType: 'relative' | 'absolute'
): Promise<string> {
  const baseDir = docPath ? path.dirname(path.resolve(docPath)) : app.getPath('documents')
  const targetDir = path.join(baseDir, folder || 'assets')
  await fsp.mkdir(targetDir, { recursive: true })

  const src = path.resolve(srcPath)
  const ext = path.extname(src) || '.png'
  const stem = path.basename(src, ext).replace(/[\\/:*?"<>|]/g, '_')
  const target = await uniquePath(targetDir, `${stem}${ext}`)
  await fsp.copyFile(src, target)
  return formatImagePath(target, baseDir, pathType)
}

export async function saveImageBuffer(
  buffer: Buffer,
  ext: string,
  docPath: string | null,
  folder: string,
  pathType: 'relative' | 'absolute'
): Promise<string> {
  const baseDir = docPath ? path.dirname(path.resolve(docPath)) : app.getPath('documents')
  const targetDir = path.join(baseDir, folder || 'assets')
  await fsp.mkdir(targetDir, { recursive: true })

  const safeExt = /^\.[a-zA-Z0-9]{2,5}$/.test(ext) ? ext.toLowerCase() : '.png'
  const target = await uniquePath(targetDir, `image-${Date.now()}${safeExt}`)
  await fsp.writeFile(target, Buffer.from(buffer))
  return formatImagePath(target, baseDir, pathType)
}

async function uniquePath(dir: string, filename: string): Promise<string> {
  let candidate = path.join(dir, filename)
  if (!fs.existsSync(candidate)) return candidate
  const ext = path.extname(filename)
  const stem = path.basename(filename, ext)
  for (let i = 1; i < 10000; i++) {
    candidate = path.join(dir, `${stem}-${i}${ext}`)
    if (!fs.existsSync(candidate)) return candidate
  }
  throw new Error('Cannot find unique filename')
}

function formatImagePath(target: string, baseDir: string, pathType: 'relative' | 'absolute'): string {
  if (pathType === 'absolute') return target.replace(/\\/g, '/')
  const rel = path.relative(baseDir, target).replace(/\\/g, '/')
  return rel.startsWith('..') ? rel : `./${rel}`
}
