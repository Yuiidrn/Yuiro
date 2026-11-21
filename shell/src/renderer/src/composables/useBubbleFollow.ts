import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/**
 * 60fps LERP 平滑跟随系统。
 * 用于浮动气泡跟随桌宠位置时插值平滑，消除僵硬抖动。
 *
 * 用法：传入目标位置 ref，返回当前插值后位置。每帧自动 lerp。
 */
export function useBubbleFollow(targetX: Ref<number>, targetY: Ref<number>, lerpFactor = 0.10) {
  const currentX = ref(targetX.value)
  const currentY = ref(targetY.value)
  const isActive = ref(false)
  let rafId = 0

  function lerp(current: number, target: number, factor: number): number {
    const diff = target - current
    if (Math.abs(diff) < 0.05) return target
    return current + diff * factor
  }

  function tick(): void {
    currentX.value = lerp(currentX.value, targetX.value, lerpFactor)
    currentY.value = lerp(currentY.value, targetY.value, lerpFactor)
    rafId = requestAnimationFrame(tick)
  }

  function start(): void {
    if (isActive.value) return
    isActive.value = true
    // 首次启动直接跳转，避免从 (0,0) 飞入
    currentX.value = targetX.value
    currentY.value = targetY.value
    rafId = requestAnimationFrame(tick)
  }

  function stop(): void {
    isActive.value = false
    cancelAnimationFrame(rafId)
  }

  /**
   * 设置绝对位置（用户拖拽字幕时用，不插值）
   */
  function setAbsolute(x: number, y: number): void {
    currentX.value = x
    currentY.value = y
  }

  onBeforeUnmount(stop)

  return { currentX, currentY, start, stop, setAbsolute, isActive }
}
