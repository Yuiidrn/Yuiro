import { computed, type ComputedRef } from 'vue'
import { useElectronMouse } from './useElectronMouse'
import { useElectronWindowBounds } from './useElectronWindowBounds'
import { useWindowSize } from '@vueuse/core'

/**
 * 鼠标相对桌宠窗口左上角的坐标（窗口内坐标系，与 getBoundingClientRect 的 CSS 尺寸一致）。
 * 坐标流全部由主进程算好（DIP），渲染层绝不用 window.screenX 反推（防漂移，坑 B）。
 */
export interface RelativeMouse {
  x: ComputedRef<number>
  y: ComputedRef<number>
}

export function relativeCss(point: number, origin: number, dipSize: number, cssSize: number): number {
  return (point-origin)*cssSize/(dipSize || cssSize)
}

export function useElectronRelativeMouse(): RelativeMouse {
  const { x: mx, y: my, u, v } = useElectronMouse()
  const { x: bx, y: by, width: bw, height: bh } = useElectronWindowBounds()
  const { width, height } = useWindowSize()
  // Prefer physical normalized fractions, retaining old-preload fallback during migration.
  const x = computed(() => u.value!==null ? u.value*width.value : relativeCss(mx.value,bx.value,bw.value,width.value))
  const y = computed(() => v.value!==null ? v.value*height.value : relativeCss(my.value,by.value,bh.value,height.value))
  return { x, y }
}
