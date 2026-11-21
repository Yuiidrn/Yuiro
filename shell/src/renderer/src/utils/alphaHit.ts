/** CSS 坐标查询低分辨率 Alpha 遮罩，保留身体间隙；不读取 DOM 渐隐透明度。 */
export interface AlphaMask { width: number; height: number; alpha: Uint8Array; left: number; top: number; cssWidth: number; cssHeight: number }
export function alphaHit(mask: AlphaMask | null, x: number, y: number, threshold: number, radius: number): boolean {
  if (!mask) return false
  const { width: w, height: h, cssWidth, cssHeight } = mask
  const px = (x - mask.left) * w / cssWidth, py = (y - mask.top) * h / cssHeight
  const rx = Math.ceil(radius * w / cssWidth), ry = Math.ceil(radius * h / cssHeight)
  for (let j = Math.max(0, Math.floor(py)-ry); j <= Math.min(h-1, Math.floor(py)+ry); j++) {
    for (let i = Math.max(0, Math.floor(px)-rx); i <= Math.min(w-1, Math.floor(px)+rx); i++) {
      const dx = Math.max(0, Math.abs(i-px)-1)*cssWidth/w
      const dy = Math.max(0, Math.abs(j-py)-1)*cssHeight/h
      if (Math.hypot(dx,dy) <= radius && mask.alpha[j*w+i] >= threshold) return true
    }
  }
  return false
}
