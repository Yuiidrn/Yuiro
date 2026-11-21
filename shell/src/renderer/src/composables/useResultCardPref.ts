import type { Ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'

/**
 * 桌宠「结果卡」（歌单雷达 / 搜索候选 / 歌曲列表）外观偏好。
 *
 * 与「回复气泡」完全同一套机制（useSpeechBubblePref）：调试台在「UI」页调，
 * 桌宠窗口即时生效；两个窗口同源共享 localStorage，vueuse 的 useLocalStorage
 * 默认监听 storage 事件，因此跨窗口改动会自动同步。
 *
 * 默认摆在模型**左侧**：与头部右上侧的回复气泡左右镜像、同一高度带，
 * 两者都贴在模型躯干之外 —— 这是「不遮挡模型」这条硬约束的落点。
 *
 * 只暴露真正值得用户自己调的项：
 *   side     —— 贴模型左侧还是右侧（默认左侧，与回复气泡对称）
 *   offsetX  —— 左右微调（px）
 *   offsetY  —— 上下微调（px）
 *   maxWidth —— 卡片最大宽度（px）
 *   alpha    —— 底色不透明度（越低越透、越不挡模型）
 */

export type ResultCardSide = 'left' | 'right'

/** 结果卡条目（歌单 / 歌曲候选 / 联网来源）—— 引擎 agent:result 消息里的元素。 */
export interface ResultCardItem {
  source?: string
  name?: string
  artist?: string
  track_count?: number
  // S51：联网检索的来源卡字段（kind === 'source' 时使用）。
  // 来源卡的价值就在"能点开核验"，所以 url 是必给的；snippet 只作参考。
  title?: string
  url?: string
  snippet?: string
  published_at?: string
  // S45：点选时必须带上 ID —— 只传歌名会让引擎**重新搜索**，
  // 于是"点的是这首、放的是另一首"（实测：点《LIFE》放成 Life-Tobu）。
  song_id?: string | number
  encrypted_id?: string
  playlist_id?: string
  playable?: boolean | null
  availability?: 'unknown' | 'api_available' | 'api_unavailable' | 'api_preview'
  availability_note?: string
  playback_backend?: 'builtin'
  rights_flags?: Record<string, unknown>
}

export const RESULT_CARD_DEFAULTS = {
  side: 'left' as ResultCardSide,
  offsetX: 0,
  offsetY: 0,
  /** 最大宽度（px），对应 ResultCard 的 --rc-max-w */
  maxWidth: 224,
  /** 底色不透明度 0.3~1，对应 ResultCard 的 --rc-bg */
  alpha: 0.92,
}

const KEY_SIDE = 'yuiro-result-card-side'
const KEY_OX = 'yuiro-result-card-offset-x'
const KEY_OY = 'yuiro-result-card-offset-y'
const KEY_MAX_W = 'yuiro-result-card-max-w'
const KEY_ALPHA = 'yuiro-result-card-alpha'

/** 模块级单例：两个窗口内各只有一份，避免多处调用产生多份状态。 */
let cached: {
  side: Ref<ResultCardSide>
  offsetX: Ref<number>
  offsetY: Ref<number>
  maxWidth: Ref<number>
  alpha: Ref<number>
  reset: () => void
} | null = null

function clamp(v: unknown, lo: number, hi: number, fallback: number): number {
  const n = Number(v)
  if (!Number.isFinite(n)) return fallback
  return Math.min(Math.max(n, lo), hi)
}

export function useResultCardPref() {
  if (cached) return cached

  const side = useLocalStorage<ResultCardSide>(KEY_SIDE, RESULT_CARD_DEFAULTS.side)
  const offsetX = useLocalStorage<number>(KEY_OX, RESULT_CARD_DEFAULTS.offsetX)
  const offsetY = useLocalStorage<number>(KEY_OY, RESULT_CARD_DEFAULTS.offsetY)
  const maxWidth = useLocalStorage<number>(KEY_MAX_W, RESULT_CARD_DEFAULTS.maxWidth)
  const alpha = useLocalStorage<number>(KEY_ALPHA, RESULT_CARD_DEFAULTS.alpha)

  // 防御历史脏值（例如手改过 localStorage）
  if (side.value !== 'left' && side.value !== 'right') side.value = RESULT_CARD_DEFAULTS.side
  if (offsetX.value !== clamp(offsetX.value, -400, 400, RESULT_CARD_DEFAULTS.offsetX)) {
    offsetX.value = clamp(offsetX.value, -400, 400, RESULT_CARD_DEFAULTS.offsetX)
  }
  if (offsetY.value !== clamp(offsetY.value, -400, 400, RESULT_CARD_DEFAULTS.offsetY)) {
    offsetY.value = clamp(offsetY.value, -400, 400, RESULT_CARD_DEFAULTS.offsetY)
  }
  if (maxWidth.value !== clamp(maxWidth.value, 120, 420, RESULT_CARD_DEFAULTS.maxWidth)) {
    maxWidth.value = clamp(maxWidth.value, 120, 420, RESULT_CARD_DEFAULTS.maxWidth)
  }
  if (alpha.value !== clamp(alpha.value, 0.3, 1, RESULT_CARD_DEFAULTS.alpha)) {
    alpha.value = clamp(alpha.value, 0.3, 1, RESULT_CARD_DEFAULTS.alpha)
  }

  function reset(): void {
    side.value = RESULT_CARD_DEFAULTS.side
    offsetX.value = RESULT_CARD_DEFAULTS.offsetX
    offsetY.value = RESULT_CARD_DEFAULTS.offsetY
    maxWidth.value = RESULT_CARD_DEFAULTS.maxWidth
    alpha.value = RESULT_CARD_DEFAULTS.alpha
  }

  cached = { side, offsetX, offsetY, maxWidth, alpha, reset }
  return cached
}

/** 把当前值组装成 CSS 变量（供 ResultCard 绑到包装元素上）。 */
export function resultCardCssVars(maxWidth: number, alpha: number): Record<string, string> {
  return {
    '--rc-max-w': `${Math.round(maxWidth)}px`,
    '--rc-bg': `rgba(255, 255, 255, ${alpha})`,
  }
}
