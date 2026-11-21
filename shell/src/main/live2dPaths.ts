/**
 * Live2D 资源路径工具（主进程共用）。
 *
 * 项目里有两种路径形态：
 *   · 渲染层 / 配置里：web 路径 `/live2d/<模型目录>/xxx.model3.json`（可能带 %20）
 *   · 主进程 fs：绝对路径 `D:\...\public\live2d\...`
 * 以前两者在多个文件里各写一份解析逻辑（scan / 体检 / 导入），这次统一到这里，
 * 避免"改一处漏两处"（尤其是含空格的模型目录，例如 `Hotaru Shiomi`）。
 */
import { app } from 'electron'
import { join, relative, sep } from 'node:path'
import { readdirSync, statSync, type Dirent } from 'node:fs'

/** live2d 资源根目录（dev: 源码 public/live2d；打包: out/renderer/live2d）。取不到返回 null。 */
export function live2dRootDir(): string | null {
  const roots = [
    join(app.getAppPath(), 'src', 'renderer', 'public', 'live2d'), // dev（app 根 = shell/）
    join(__dirname, '..', 'renderer', 'live2d'),                   // prod: out/main → out/renderer
  ]
  return roots.find((r) => {
    try { return statSync(r).isDirectory() } catch { return false }
  }) ?? null
}

/**
 * 把 web 路径（可能已编码、可能带前导 `/live2d/`）或普通 fs 路径解析成绝对路径。
 * 解析不出 / 路径非法时返回 null。
 */
export function toFsPath(input: string): string | null {
  let p = String(input ?? '').trim()
  if (!p) return null
  // 渲染层可能传 encodeURI 后的路径（空格 → %20）；decodeURI 对普通路径是幂等的
  try { p = decodeURI(p) } catch { /* 非法转义：按原样处理 */ }
  if (p.startsWith('file:///')) p = p.slice('file:///'.length)
  if (p.startsWith('file://')) p = p.slice('file://'.length)

  if (p.startsWith('/live2d/')) {
    const root = live2dRootDir()
    if (!root) return null
    return join(root, ...p.slice('/live2d/'.length).split('/'))
  }
  return p
}

/** 绝对 fs 路径 → `/live2d/...` 的 web 路径（保留空格，由渲染层 encodeURI）。 */
export function toWebPath(fsPath: string): string {
  const root = live2dRootDir()
  if (!root) return fsPath
  try {
    const rel = relative(root, fsPath)
    if (rel.startsWith('..')) return fsPath
    return `/live2d/${rel.split(sep).join('/')}`
  } catch {
    return fsPath
  }
}

/** 目录里递归找 model3.json（跳过打包垃圾目录）。 */
export function findModel3In(dir: string, depth = 0): string | null {
  if (depth > 3) return null
  let entries: Dirent[]
  try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return null }
  const direct = entries.find((e) => e.isFile() && e.name.toLowerCase().endsWith('.model3.json'))
  if (direct) return join(dir, direct.name)
  for (const e of entries) {
    if (!e.isDirectory() || e.name === '__MACOSX' || e.name.startsWith('.')) continue
    const r = findModel3In(join(dir, e.name), depth + 1)
    if (r) return r
  }
  return null
}
