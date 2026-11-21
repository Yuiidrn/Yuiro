import { ref } from 'vue'
import type { ShellEvent } from '@shared'

/**
 * 桌宠窗口外观（窗口尺寸 / 模型缩放 / 模型水平·垂直偏移）。
 * 默认值；可被调试窗口经 main → pet webContents 的 `appearance:update` 事件更新，
 * 并持久化到 localStorage。
 */

const STORAGE_KEY = 'yuiro-appearance'

interface Appearance {
  width: number
  height: number
  fillRatio: number
  /** 模型水平偏移（px，正值向右） */
  xOffset: number
  yOffset: number
}

const DEFAULT: Appearance = { width: 420, height: 560, fillRatio: 0.55, xOffset: 0, yOffset: 0.45 }

function loadStored(): Appearance {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Appearance>
      return { ...DEFAULT, ...parsed }
    }
  } catch { /* ignore */ }
  return { ...DEFAULT }
}

const state = ref<Appearance>(loadStored())

function persist(): void {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state.value)) } catch { /* ignore */ }
}

let listening = false

export function useAppearance() {
  if (!listening) {
    listening = true
    window.yuiro?.on((event: ShellEvent) => {
      if (event.type !== 'appearance:update') return
      state.value = {
        width: event.width,
        height: event.height,
        fillRatio: event.fillRatio,
        xOffset: event.xOffset,
        yOffset: event.yOffset,
      }
      persist()
    })
  }

  return { appearance: state }
}
