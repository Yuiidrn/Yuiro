/**
 * Live2D 模型清单（manifest）+ **语义槽位推断**（主进程）。
 *
 * 为什么放在主进程：要读 model3.json 以及每个 motion3.json 的 `Meta`
 * （Loop / Duration）——渲染层逐个 fetch 几十个动作文件既慢又浪费。
 * 一次 fs 扫描 + 按 mtime 缓存，渲染层只拿最终索引。
 *
 * 推断原则：**能从名字看出来的才推断，看不出来就留空**（绝不猜）。
 *   · Hotaru：`mtn_bye01_C` / `exp_smile03` → 语义清晰，可零配置接入；
 *   · Hiyori：`Hiyori_m01` / `happy` → 动作名无语义，靠档案覆盖；
 *   · 肥牛：`expression2..7` → 表情名无语义，靠档案覆盖。
 */
import { readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import type {
  Live2DManifest,
  ManifestExpression,
  ManifestMotion,
  SlotCoverage,
} from '../shared/live2d'
import { inferExpressionSlot, inferMotionSlot, parseMotionName } from '../shared/live2dInfer'
import { findModel3In, toFsPath, toWebPath } from './live2dPaths'

/* ── 缓存 ──────────────────────────────────────────────────────────────── */

interface CacheEntry { mtimeMs: number; manifest: Live2DManifest }
const cache = new Map<string, CacheEntry>()

/** 导入/删除模型后调用，丢弃全部缓存（mtime 相同但内容被替换的极端情况也能兜住）。 */
export function clearManifestCache(): void {
  cache.clear()
}

function emptyManifest(path: string, model3: string, warning: string): Live2DManifest {
  return {
    path,
    model3,
    mocVersion: 0,
    expressions: [],
    motions: [],
    index: { expression: {}, motion: {}, idle: [] },
    coverage: {
      expression: {}, motion: {}, unmappedExpressions: [], unmappedMotions: [],
      unmappedExpressionCount: 0, unmappedMotionCount: 0, hasLipSync: false, hasEyeBlink: false,
    },
    warnings: [warning],
  }
}

/* ── 主入口 ────────────────────────────────────────────────────────────── */

/** 检查一个模型（目录或 model3.json 路径），返回带槽位索引的清单。不抛错。 */
export function inspectModel(input: string): Live2DManifest {
  const raw = String(input ?? '').trim()
  const fsPath = toFsPath(raw)
  if (!fsPath) return emptyManifest(raw, '', '路径为空或无法解析（拿不到 live2d 资源根目录？）')

  let model3: string | null = null
  try {
    const st = statSync(fsPath)
    model3 = st.isDirectory() ? findModel3In(fsPath) : fsPath
  } catch {
    return emptyManifest(raw, fsPath, `路径不存在或不可读：${raw}`)
  }
  if (!model3) return emptyManifest(raw, fsPath, '没有找到 *.model3.json')

  let mtime = 0
  try { mtime = statSync(model3).mtimeMs } catch { /* 读取失败就走重建 */ }
  const hit = cache.get(model3)
  if (hit && hit.mtimeMs === mtime) return hit.manifest

  const manifest = buildManifest(model3)
  cache.set(model3, { mtimeMs: mtime, manifest })
  return manifest
}

function buildManifest(model3: string): Live2DManifest {
  const webPath = toWebPath(model3)
  let json: Record<string, any>
  try {
    json = JSON.parse(readFileSync(model3, 'utf8')) as Record<string, any>
  } catch (e) {
    return emptyManifest(webPath, model3, `model3.json 解析失败：${e instanceof Error ? e.message : String(e)}`)
  }
  const base = model3.replace(/[\\/][^\\/]+$/, '')
  const refs = (json.FileReferences ?? {}) as Record<string, any>
  const warnings: string[] = []

  // ── moc3 版本（>=6 = Cubism 5.3 导出，Core 5.1 读不了）──
  let mocVersion = 0
  try {
    const moc = readFileSync(join(base, String(refs.Moc ?? '')))
    mocVersion = moc[4] ?? 0
    if (mocVersion >= 6) {
      warnings.push(`moc3 版本 ${mocVersion}（Cubism 5.3+）超出当前 Core 5.1 支持范围，加载会失败`)
    }
  } catch { warnings.push('Moc 无法读取') }

  // ── 参数组：口型 / 眨眼 ──
  const groups: { Name?: string }[] = Array.isArray(json.Groups) ? json.Groups : []
  const groupNames = new Set(groups.map((g) => String(g?.Name ?? '')))
  const hasLipSync = groupNames.has('LipSync')
  const hasEyeBlink = groupNames.has('EyeBlink')
  if (!hasLipSync) warnings.push('缺少 LipSync 参数组：口型同步不会生效（模型需在 Groups 登记 ParamMouthOpenY）')
  if (!hasEyeBlink) warnings.push('缺少 EyeBlink 参数组：自动眨眼不会生效')

  // ── 表情 ──
  const expressions: ManifestExpression[] = []
  for (const item of (Array.isArray(refs.Expressions) ? refs.Expressions : [])) {
    const name = String((item as Record<string, unknown>)?.Name ?? '').trim()
    if (!name) continue
    expressions.push({ name, slot: inferExpressionSlot(name) })
  }

  // ── 动作 ──
  const motions: ManifestMotion[] = []
  const rawMotions = (refs.Motions ?? {}) as Record<string, unknown[]>
  for (const [group, list] of Object.entries(rawMotions)) {
    if (!Array.isArray(list)) continue
    list.forEach((item, index) => {
      const obj = (item ?? {}) as Record<string, unknown>
      const file = String(obj.File ?? '')
      if (!file) return
      const { direction } = parseMotionName(file)
      // 组名启发（Idle 组 → 待机）与文件名推断都在纯函数里，主进程不再重复一套规则
      const slot = inferMotionSlot(group, file)

      let loop = false
      let durationMs = 0
      try {
        const meta = (JSON.parse(readFileSync(join(base, file), 'utf8')) as Record<string, any>)?.Meta ?? {}
        loop = meta.Loop === true
        const d = Number(meta.Duration ?? 0)
        if (Number.isFinite(d) && d > 0) durationMs = Math.round(d * 1000)
      } catch { /* 动作文件读不到：时长 0，槽位推断不受影响 */ }

      motions.push({ group, index, file, loop, durationMs, slot, direction })
    })
  }

  // ── 预索引 ──
  const exprIndex: Record<string, string[]> = {}
  for (const e of expressions) {
    if (!e.slot) continue
    ;(exprIndex[e.slot] ??= []).push(e.name)
  }
  const motionIndex: Record<string, { group: string; index: number }[]> = {}
  for (const m of motions) {
    if (!m.slot) continue
    ;(motionIndex[m.slot] ??= []).push({ group: m.group, index: m.index })
  }
  const idle = motions
    .filter((m) => m.slot === 'idle')
    .map((m) => ({ group: m.group, index: m.index, durationMs: m.durationMs }))
    .sort((a, b) => a.durationMs - b.durationMs)

  // ── 覆盖统计 ──
  const unmappedExpressions = expressions.filter((e) => !e.slot).map((e) => e.name)
  const unmappedMotions = motions.filter((m) => !m.slot).map((m) => `${m.group}#${m.index} (${m.file})`)
  const coverage: SlotCoverage = {
    expression: Object.fromEntries(Object.entries(exprIndex).map(([k, v]) => [k, v.length])),
    motion: Object.fromEntries(Object.entries(motionIndex).map(([k, v]) => [k, v.length])),
    unmappedExpressions: unmappedExpressions.slice(0, 20),
    unmappedMotions: unmappedMotions.slice(0, 20),
    unmappedExpressionCount: unmappedExpressions.length,
    unmappedMotionCount: unmappedMotions.length,
    hasLipSync,
    hasEyeBlink,
  }

  if (idle.length === 0) {
    warnings.push('没有 idle 语义动作：待机将保持静止（仅呼吸/眨眼）')
  }
  if (unmappedMotions.length) {
    warnings.push(`${unmappedMotions.length} 个动作无法从文件名推断语义（可在档案里用 motion_slots 指定）`)
  }
  if (unmappedExpressions.length) {
    warnings.push(`${unmappedExpressions.length} 个表情无法从名字推断语义（可在档案里用 expression_map 指定）`)
  }

  return {
    path: webPath,
    model3,
    mocVersion,
    expressions,
    motions,
    index: { expression: exprIndex, motion: motionIndex, idle },
    coverage,
    warnings,
  }
}
