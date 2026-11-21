import { computed, type ComputedRef } from 'vue'
import { useElectronRelativeMouse } from './useElectronRelativeMouse'
import { useWindowSize } from '@vueuse/core'

/**
 * 鼠标是否贴近窗口任一边缘（用于保留边缘拖动/缩放，不触发穿透/渐隐）。
 * @param threshold 距边缘的判定阈值（px）。
 * @param overshoot 允许略越界（鼠标在窗口外但离边 ≤threshold 仍算"贴边"）。
 */
export function useMouseAroundWindowBorder(
  threshold = 10,
  overshoot = true,
): { isNearAnyBorder: ComputedRef<boolean> } {
  const { x, y } = useElectronRelativeMouse()
  const { width, height } = useWindowSize()

  const isNearAnyBorder = computed(() => {
    const left = x.value
    const right = width.value - x.value
    const top = y.value
    const bottom = height.value - y.value
    const tol = overshoot ? threshold : 0
    // 贴"任一"边即算（OR），用于保留边缘拖动/缩放
    return (
      left <= threshold + tol
      || right <= threshold + tol
      || top <= threshold + tol
      || bottom <= threshold + tol
    )
  })
  return { isNearAnyBorder }
}
