import type { BrowserWindow, Screen } from 'electron'

/** DIP is not a uniform metric across mixed-DPI Windows displays. Normalize in
 * physical pixels first, then let the renderer multiply by its CSS viewport. */
export function overlayCursor(desktop: Screen, win: BrowserWindow, windows=process.platform==='win32') {
  const point=desktop.getCursorScreenPoint(),bounds=win.getBounds()
  const p=windows?desktop.dipToScreenPoint(point):point
  const b=windows?desktop.dipToScreenRect(win,bounds):bounds
  return {x:point.x,y:point.y,u:(p.x-b.x)/Math.max(1,b.width),v:(p.y-b.y)/Math.max(1,b.height)}
}
