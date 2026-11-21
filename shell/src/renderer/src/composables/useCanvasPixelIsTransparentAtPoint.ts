import { ref, watch, type Ref, onScopeDispose } from 'vue'
import { useElectronRelativeMouse } from './useElectronRelativeMouse'

export interface PixelSampleOptions {
  /** alpha 阈值：>= 该值视为不透明。 */
  threshold?: number
  /** 采样圆形半径（px），用圆形区域而非单像素，防边缘抖动。 */
  regionRadius?: number
}

/**
 * 判定"窗口相对坐标 (x,y) 处 canvas 是否透明（即光标下方非模型不透明像素）"。
 *
 * 算法参考 AIRI canvas-alpha.ts：直接从 Pixi 持有的同一 WebGL 上下文 readPixels，
 * 对光标周围 radius 圆形区域采样，任一像素 alpha >= threshold 即不透明(false)。
 *
 * 快路径：光标落在 Live2DCanvas 模型包围盒之外时直接返回 true（透明），不做 GPU 读取。
 * 越界/无上下文/异常一律返回 true（透明），保证安全。
 *
 * @param canvasRef Pixi 画布（含 preserveDrawingBuffer，readPixels 前已 bind 原 framebuffer）。
 * @param cursorX 窗口相对 x（CSS px）
 * @param cursorY 窗口相对 y（CSS px）
 * @param getModelRect 返回模型 client 包围盒（用于快路径），无模型时返回 null
 */
export function useCanvasPixelIsTransparentAtPoint(
  canvasRef: Ref<HTMLCanvasElement | null | undefined>,
  cursorX: Ref<number>,
  cursorY: Ref<number>,
  getModelRect: () => { left: number, top: number, width: number, height: number } | null,
  options: PixelSampleOptions = {},
) {
  const { threshold = 10, regionRadius = 25 } = options
  const isTransparent = ref(true)
  let raf = 0
  let paused = true

  const sample = () => {
    raf = 0
    if (paused) return
    const canvas = canvasRef.value
    const x = cursorX.value
    const y = cursorY.value

    // 快路径：光标在模型包围盒之外 → 透明（不读 GPU）
    const rect = getModelRect()
    if (rect) {
      const cx = rect.left
      const cy = rect.top
      const cw = rect.width
      const ch = rect.height
      if (x < cx - regionRadius || x > cx + cw + regionRadius || y < cy - regionRadius || y > cy + ch + regionRadius) {
        isTransparent.value = true
        return
      }
    }

    if (!canvas) { isTransparent.value = true; return }
    const gl = (canvas.getContext('webgl2') || canvas.getContext('webgl')) as WebGLRenderingContext | null
    if (!gl) { isTransparent.value = true; return }

    const rect2 = canvas.getBoundingClientRect()
    const scaleX = gl.drawingBufferWidth / rect2.width
    const scaleY = gl.drawingBufferHeight / rect2.height
    // WebGL 原点在左下，需 Y 翻转；autoDensity/resolution 通过 scale 处理
    const xIn = Math.round(x * scaleX)
    const yIn = Math.round(y * scaleY)
    const xCenter = xIn
    const yCenter = gl.drawingBufferHeight - 1 - yIn

    const r = Math.round(regionRadius * scaleX)
    const x0 = Math.max(0, xCenter - r)
    const x1 = Math.min(gl.drawingBufferWidth - 1, xCenter + r)
    const y0 = Math.max(0, yCenter - r)
    const y1 = Math.min(gl.drawingBufferHeight - 1, yCenter + r)
    const w = x1 - x0 + 1
    const h = y1 - y0 + 1
    if (w <= 0 || h <= 0) { isTransparent.value = true; return }

    const pixels = new Uint8Array(w * h * 4)
    try {
      gl.readPixels(x0, y0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
    } catch {
      isTransparent.value = true
      return
    }

    const r2 = r * r
    let found = false
    for (let i = 0; i < w * h; i++) {
      const px = (i % w) - r
      const py = Math.floor(i / w) - r
      if (px * px + py * py > r2) continue // 圆形过滤（去方角）
      if (pixels[i * 4 + 3] >= threshold) { found = true; break }
    }
    isTransparent.value = !found
    // console.debug('[fade] sample ' + JSON.stringify({ x, y, r, found, transparent: !found }))
  }

  const schedule = () => {
    if (raf) return
    raf = requestAnimationFrame(sample)
  }

  const stopWatch = watch([cursorX, cursorY], () => { if (!paused) schedule() })

  const pause = () => { paused = true; if (raf) { cancelAnimationFrame(raf); raf = 0 } }
  const resume = () => { if (paused) { paused = false; schedule() } }

  onScopeDispose(() => { stopWatch(); if (raf) cancelAnimationFrame(raf) })

  return { isTransparent, pause, resume }
}
