import { isPetClick } from '../avatar/clickFeedback'
import { onBeforeUnmount, onMounted } from 'vue'

interface Rect {
  left: number
  top: number
  width: number
  height: number
}

/**
 * JS 拖动：鼠标在模型矩形内按下 → 三阶段拖动窗口。
 *
 * 实现要点（见 debug-log 第 28 篇坑 B/C）：
 * - 渲染层只负责「判定 mousedown 是否命中模型矩形」，**不参与坐标换算**；
 *   实际移动由主进程读 OS 光标绝对坐标 + setBounds 钉死尺寸完成。
 * - 拖动期间置 `window.__yuiroDragging = true`，让 Live2DCanvas 走"拖动分支"：
 *   只更新 modelRect（功能泡/悬停区跟随窗口），不重算 scale、不触发 fit，
 *   从而不产生反馈放大（膨胀）。
 */
export function usePetDrag(getModelRect: () => Rect | null, hitContour?: (x:number,y:number)=>boolean, onClick?:()=>void) {
  let dragging = false
  let pressed:{x:number;y:number;at:number}|null=null

  function hitModel(x: number, y: number): boolean {
    if (hitContour) return hitContour(x,y)
    const r = getModelRect()
    if (!r) return false
    const pad = 10
    return (
      x >= r.left - pad
      && x <= r.left + r.width + pad
      && y >= r.top - pad
      && y <= r.top + r.height + pad
    )
  }

  function onMouseDown(e: MouseEvent): void {
    if(e.button!==0)return
    // 忽略 UI 元素上的按下（聊天面板/图标等）：只有模型本体可拖动
    const t = e.target as HTMLElement | null
    if (t?.closest?.('.panel, .bm-icon, .result-card, .chat-dock, input, button')) return
    if (!hitModel(e.clientX, e.clientY)) return
    pressed={x:e.screenX,y:e.screenY,at:performance.now()}
    e.preventDefault()
  }

  function onMouseMove(e:MouseEvent): void {
    if(!pressed)return
    if(!dragging){
      if(Math.hypot(e.screenX-pressed.x,e.screenY-pressed.y)<=5)return
      dragging=true;(window as any).__yuiroDragging=true;window.yuiro?.dragPetStart()
    }
    window.yuiro?.dragPetMove()
  }

  function onMouseUp(e:MouseEvent): void {
    if(e.button!==0)return
    const start=pressed;pressed=null
    if(!dragging){if(start&&isPetClick(e.screenX-start.x,e.screenY-start.y,performance.now()-start.at)&&hitModel(e.clientX,e.clientY))onClick?.();return}
    dragging = false
    ;(window as any).__yuiroDragging = false
    console.debug('[drag] end')
    window.yuiro?.dragPetEnd()
  }

  function cancel(){pressed=null;if(dragging)window.yuiro?.dragPetEnd();dragging=false;(window as any).__yuiroDragging=false}
  onMounted(() => {
    window.addEventListener('blur',cancel)
    window.addEventListener('mousedown', onMouseDown, { passive: false })
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  })

  onBeforeUnmount(() => {
    cancel();window.removeEventListener('blur',cancel)
    window.removeEventListener('mousedown', onMouseDown)
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
    ;(window as any).__yuiroDragging = false
  })
}
