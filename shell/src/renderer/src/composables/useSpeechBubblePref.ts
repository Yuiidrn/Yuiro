import type { Ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'

/**
 * 桌宠「回复气泡」（漫画说话云）外观偏好。
 *
 * 调试台窗口与桌宠窗口同源，共用 localStorage，所以在这里调完两边一致。
 * vueuse 的 useLocalStorage 默认监听 storage 事件，
 * 因此跨窗口改动会自动同步（storage 事件只在「别的窗口」触发）。
 *
 * 只暴露真正影响观感、且值得让用户自己调的参数：
 *   maxWidth —— 气泡最大宽度（越小越窄，但文字换行会变高）
 *   alpha    —— 底色不透明度（越低越透、越不挡模型）
 *   offsetX / offsetY —— 整体微调（换个地方冒出来，避开脸或让位给别的卡片）
 */

export const SPEECH_BUBBLE_DEFAULTS = {
  /** 最大宽度（px），对应 SpeechCloud 的 --cloud-max-w */
  maxWidth: 190,
  /** 底色不透明度 0.3~1，对应 SpeechCloud 的 --cloud-bg */
  alpha: 0.92,
  /** 整体左右微调（px，正数向右） */
  offsetX: 0,
  /** 整体上下微调（px，正数向下） */
  offsetY: 0,
}

const KEY_MAX_W = 'yuiro-speech-bubble-max-w'
const KEY_ALPHA = 'yuiro-speech-bubble-alpha'
const KEY_OX = 'yuiro-speech-bubble-offset-x'
const KEY_OY = 'yuiro-speech-bubble-offset-y'

/** 模块级单例：两个窗口内各只有一份，避免多处调用产生多份状态。 */
let cached: {
  maxWidth: Ref<number>
  alpha: Ref<number>
  offsetX: Ref<number>
  offsetY: Ref<number>
  reset: () => void
} | null = null

function clamp(v: number, lo: number, hi: number, fallback: number): number {
  const n = Number(v)
  if (!Number.isFinite(n)) return fallback
  return Math.min(Math.max(n, lo), hi)
}

export function useSpeechBubblePref() {
  if (cached) return cached

  const maxWidth = useLocalStorage<number>(KEY_MAX_W, SPEECH_BUBBLE_DEFAULTS.maxWidth)
  const alpha = useLocalStorage<number>(KEY_ALPHA, SPEECH_BUBBLE_DEFAULTS.alpha)
  const offsetX = useLocalStorage<number>(KEY_OX, SPEECH_BUBBLE_DEFAULTS.offsetX)
  const offsetY = useLocalStorage<number>(KEY_OY, SPEECH_BUBBLE_DEFAULTS.offsetY)

  // 防御历史脏值（例如手改过 localStorage）
  if (maxWidth.value !== clamp(maxWidth.value, 100, 720, SPEECH_BUBBLE_DEFAULTS.maxWidth)) {
    maxWidth.value = clamp(maxWidth.value, 100, 720, SPEECH_BUBBLE_DEFAULTS.maxWidth)
  }
  if (alpha.value !== clamp(alpha.value, 0.05, 1, SPEECH_BUBBLE_DEFAULTS.alpha)) {
    alpha.value = clamp(alpha.value, 0.05, 1, SPEECH_BUBBLE_DEFAULTS.alpha)
  }
  if (offsetX.value !== clamp(offsetX.value, -1000, 1000, SPEECH_BUBBLE_DEFAULTS.offsetX)) {
    offsetX.value = clamp(offsetX.value, -1000, 1000, SPEECH_BUBBLE_DEFAULTS.offsetX)
  }
  if (offsetY.value !== clamp(offsetY.value, -1000, 1000, SPEECH_BUBBLE_DEFAULTS.offsetY)) {
    offsetY.value = clamp(offsetY.value, -1000, 1000, SPEECH_BUBBLE_DEFAULTS.offsetY)
  }

  function reset(): void {
    maxWidth.value = SPEECH_BUBBLE_DEFAULTS.maxWidth
    alpha.value = SPEECH_BUBBLE_DEFAULTS.alpha
    offsetX.value = SPEECH_BUBBLE_DEFAULTS.offsetX
    offsetY.value = SPEECH_BUBBLE_DEFAULTS.offsetY
  }

  cached = { maxWidth, alpha, offsetX, offsetY, reset }
  return cached
}

/** 把当前值组装成 CSS 变量（供 SpeechCloud 绑到包装元素上）。 */
export function speechBubbleCssVars(maxWidth: number, alpha: number): Record<string, string> {
  return {
    '--cloud-max-w': `${Math.round(maxWidth)}px`,
    '--cloud-bg': `rgba(255, 255, 255, ${alpha})`,
  }
}
