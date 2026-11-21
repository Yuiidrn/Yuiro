/**
 * 语义槽位 → 具体 Live2D 资源（纯函数，无副作用）。
 *
 * 分工：引擎只下发"要什么语义"（expression_slot / motion_slot）与可能的具体名；
 * 本模块结合当前模型的清单（manifest）决定**实际调用哪个表情 / 哪个组第几个动作**。
 * 解析不到就返回空 → 调用方"只演表情 / 什么都不做"，绝不随机凑一个动作。
 */
import type { Live2DManifest, MotionSlot } from '@shared'
import { EMOTION_TO_SLOT } from '@shared'

/** 表情解析结果。`from: 'none'` = 本次意图不涉及表情（不要重置）。 */
export interface ResolvedExpression {
  /** 具体表情名；'' = 回落默认（reset） */
  name: string
  from: 'concrete' | 'slot' | 'reset' | 'none'
}

/** 动作解析结果。null = 没有可用动作（只演表情）。 */
export interface ResolvedMotion {
  group: string
  index: number
  /** 清单里的真实时长（0 = 未知，调用方回落到运行时探测/引擎时长） */
  durationMs: number
  from: 'concrete' | 'slot'
}

export interface AvatarIntentLike {
  expression?: string | null
  expression_slot?: string | null
  motion?: string | null
  motion_index?: number | null
  motion_slot?: string | null
  emotion?: string | null
}

/** 模型清单里是否真有这个表情名（没有清单时不做校验）。 */
function hasExpression(manifest: Live2DManifest | null, name: string): boolean {
  if (!manifest) return true
  return manifest.expressions.some((e) => e.name === name)
}

/** 取某槽位的第一个表情候选（模型清单里的声明顺序，通常是最"标准"的那个）。 */
function expressionBySlot(manifest: Live2DManifest | null, slot: string): string {
  if (!manifest || !slot) return ''
  return manifest.index.expression[slot]?.[0] ?? ''
}

/**
 * 解析表情：
 *   1. 意图里有具体名且当前模型存在 → 用它；
 *   2. 否则用 expression_slot（缺省时由 emotion 推导）；
 *   3. 都没有 → 不改（`from: 'none'`）；意图显式给空串 → reset。
 */
export function resolveExpression(
  manifest: Live2DManifest | null,
  intent: AvatarIntentLike,
): ResolvedExpression {
  const hasKey = intent.expression !== undefined && intent.expression !== null
  const concrete = String(intent.expression ?? '').trim()

  if (hasKey && !concrete) return { name: '', from: 'reset' }

  if (concrete) {
    if (hasExpression(manifest, concrete)) return { name: concrete, from: 'concrete' }
    // 具体名在当前模型不存在（例如全局表还留着别的模型的名字）→ 降级到槽位
  }

  const slot = String(intent.expression_slot || '') || EMOTION_TO_SLOT[String(intent.emotion ?? '')] || ''
  const bySlot = expressionBySlot(manifest, slot)
  if (bySlot) return { name: bySlot, from: 'slot' }

  // 有具体名但模型里没有、又没有槽位候选 → 回落默认（比挂着旧表情好）
  return concrete ? { name: '', from: 'reset' } : { name: '', from: 'none' }
}

/** 校验 `组#索引` 是否存在于当前模型。 */
function hasMotion(manifest: Live2DManifest | null, group: string, index: number | null): boolean {
  if (!manifest) return true
  return manifest.motions.some(
    (m) => m.group === group && (index === null || m.index === index),
  )
}

/**
 * 解析动作：
 *   1. 意图里有具体 `组#索引` 且当前模型存在 → 用它；
 *   2. 否则按 motion_slot 从清单里挑（同名多候选时优先方向 `_C`）；
 *   3. 都没有 → null（只演表情）。
 */
export function resolveMotion(
  manifest: Live2DManifest | null,
  intent: AvatarIntentLike,
): ResolvedMotion | null {
  const group = String(intent.motion ?? '').trim()
  const rawIndex = intent.motion_index
  const index = typeof rawIndex === 'number' && Number.isInteger(rawIndex) ? rawIndex : null

  if (group) {
    if (hasMotion(manifest, group, index) && index !== null) {
      return { group, index, durationMs: durationOf(manifest, group, index), from: 'concrete' }
    }
    // 具体名不可用（或没给索引 = 该组随机，S34 起不再鼓励）→ 尝试槽位
  }

  const slot = String(intent.motion_slot || '') as MotionSlot | ''
  if (!slot) return null
  const candidates = manifest?.index.motion[slot] ?? []
  if (!candidates.length) return null

  const withMeta = candidates.map((c) => ({
    ...c,
    direction: manifest?.motions.find((m) => m.group === c.group && m.index === c.index)?.direction ?? '',
    durationMs: durationOf(manifest, c.group, c.index),
  }))
  // 方向偏好：_C（正面）优先 —— 桌宠居中显示，侧面变体是给多机位/舞台用的
  const pick = withMeta.find((c) => c.direction === 'C') ?? withMeta[0]
  return { group: pick.group, index: pick.index, durationMs: pick.durationMs, from: 'slot' }
}

function durationOf(manifest: Live2DManifest | null, group: string, index: number): number {
  if (!manifest) return 0
  return manifest.motions.find((m) => m.group === group && m.index === index)?.durationMs ?? 0
}

/**
 * idle 候选池：只取 idle 槽位的动作，并按**时长上限**过滤。
 *
 * 为什么要时长上限：Hiyori 的 Idle 组里有 8.6s 的全身大幅动作，
 * 作为待机反复播会显得"乱动"（用户实际反馈）。上限默认 4.5s，可在调试台调。
 * 池子为空时退化为"最短的一个"，避免模型完全不动。
 */
export function idleCandidates(
  manifest: Live2DManifest | null,
  maxDurationMs: number,
  fixedMotion = '',
): { group: string; index: number; durationMs: number }[] {
  const all = manifest?.index.idle ?? []
  if(fixedMotion)return all.filter(m=>`${m.group}#${m.index}`===fixedMotion)
  if (!all.length) return []
  const pool = all.filter((m) => m.durationMs > 0 && m.durationMs <= maxDurationMs)
  if (pool.length) return pool
  return [all[0]] // all 已按时长升序
}
