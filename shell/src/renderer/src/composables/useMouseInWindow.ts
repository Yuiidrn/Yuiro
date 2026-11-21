import { computed, ref, type Ref, onScopeDispose, watch } from 'vue'
import { refDebounced } from '@vueuse/core'
import { useElectronRelativeMouse } from './useElectronRelativeMouse'
import { useWindowSize } from '@vueuse/core'

/**
 * 鼠标是否在桌宠窗口内（相对坐标 0..width / 0..height）。
 * isOutside 经 250ms 防抖，避免边缘抖动导致反复切换。
 */
export function useMouseInWindow(debounceMs = 250) {
  const { x, y } = useElectronRelativeMouse()
  const { width, height } = useWindowSize()

  const isInside = computed(() =>
    x.value >= 0 && y.value >= 0 && x.value <= width.value && y.value <= height.value,
  )
  const isOutsideRaw = computed(() => !isInside.value)
  const isOutside = refDebounced(isOutsideRaw, debounceMs)

  return { x, y, isInside, isOutside }
}

/**
 * 鼠标是否在某 DOM 元素内（基于 getBoundingClientRect 的 CSS 坐标 + 窗口相对鼠标）。
 * 用于判定"悬停在功能泡/面板等可交互 UI 上"。
 */
export function useMouseInElement(target: Ref<HTMLElement | null | undefined>, debounceMs = 250) {
  const { x, y } = useElectronRelativeMouse()
  const isOutside = ref(true)
  const rawOutside = ref(true)
  const debounced = refDebounced(rawOutside, debounceMs)
  let ro: ResizeObserver | null = null

  const recompute = () => {
    const el = target.value
    if (!el) { rawOutside.value = true; return }
    const r = el.getBoundingClientRect()
    rawOutside.value =
      x.value < r.left || x.value > r.right || y.value < r.top || y.value > r.bottom
  }

  watch([x, y, target], recompute, { immediate: true, flush: 'post' })
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(recompute)
    if (target.value) ro.observe(target.value)
  }
  watch(target, (el, _old, onCleanup) => {
    ro?.disconnect()
    if (el && ro) ro.observe(el)
    onCleanup(() => ro?.disconnect())
  })
  onScopeDispose(() => ro?.disconnect())

  // isOutside = 鼠标在元素外（经防抖）
  watch(debounced, (v) => { isOutside.value = v }, { immediate: true })
  return { isOutside }
}
