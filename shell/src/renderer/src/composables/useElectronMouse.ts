import { computed, ref, type Ref } from 'vue'

/**
 * 订阅主进程 ~60fps 推来的鼠标 screen 坐标（DIP），返回响应式 {x,y}。
 * 模块级单例：首次调用时启动主进程坐标流，多个消费者共享同一数据流。
 */
const mouseX = ref(0)
const mouseY = ref(0)
const fraction = ref<{u:number;v:number}|null>(null)
const fractionX = computed(()=>fraction.value?.u??null)
const fractionY = computed(()=>fraction.value?.v??null)
let listening = false
let stop: (() => void) | null = null

export interface ElectronMouse {
  x: Ref<number>
  y: Ref<number>
  u: Ref<number|null>
  v: Ref<number|null>
}

export function useElectronMouse(): ElectronMouse {
  if (!listening) {
    listening = true
    window.yuiro.startOverlayTracking()
    stop = window.yuiro.onCursorPoint((p) => {
      mouseX.value = p.x
      mouseY.value = p.y
      fraction.value=Number.isFinite(p.u)&&Number.isFinite(p.v)?{u:p.u!,v:p.v!}:null
    })
  }
  return { x: mouseX, y: mouseY, u:fractionX, v:fractionY }
}
