import { onBeforeUnmount, onMounted, watch, type Ref } from 'vue'
import { useElectronRelativeMouse } from './useElectronRelativeMouse'

/** 唯一穿透决策者：UI > 拖动 > 渐隐 > Alpha；不依赖按下后补发。 */
export function useMousePassthrough(options: {
  chatOpen: Ref<boolean>; menuOpen: Ref<boolean>
  hitModel: (x:number,y:number)=>boolean
  fadeActive?: Ref<boolean>
}) {
  let last: boolean | null = null
  const { x, y } = useElectronRelativeMouse()
  function updateFromPointer(px:number,py:number):void {
    const elements = document.elementsFromPoint(px,py)
    const ui = elements.some(e => e.closest('.bm-icon,.panel,.chat-dock,input,button'))
    const dragging = !!(window as any).__yuiroDragging
    const interactive = ui || dragging || (!options.fadeActive?.value && options.hitModel(px,py))
    const next = !interactive
    ;(window as any).__yuiroContourInput = { x:px,y:py,ui,dragging,fade:!!options.fadeActive?.value,model:options.hitModel(px,py),passthrough:next }
    if(last!==next){last=next;window.yuiro?.setMousePassthrough(next)}
  }
  function syncForcedInteractive():void {
    window.yuiro?.setFocusable(options.chatOpen.value)
    updateFromPointer(x.value,y.value)
  }
  function forceInteractive(on:boolean):void { if(on){last=false;window.yuiro?.setMousePassthrough(false)}else updateFromPointer(x.value,y.value) }
  function pointer(e:MouseEvent):void {updateFromPointer(e.clientX,e.clientY)}
  function refreshContour():void {updateFromPointer(x.value,y.value)}
  watch([x,y,options.fadeActive ?? (()=>false),options.menuOpen],()=>updateFromPointer(x.value,y.value),{flush:'sync'})
  watch(options.chatOpen,syncForcedInteractive)
  onMounted(()=>{
    window.addEventListener('mousemove',pointer,true)
    window.addEventListener('mouseup',syncForcedInteractive)
    window.addEventListener('yuiro-contour-updated',refreshContour)
    syncForcedInteractive()
  })
  onBeforeUnmount(()=>{
    window.removeEventListener('mousemove',pointer,true)
    window.removeEventListener('mouseup',syncForcedInteractive)
    window.removeEventListener('yuiro-contour-updated',refreshContour)
  })
  return {syncForcedInteractive,forceInteractive,updateFromPointer}
}
