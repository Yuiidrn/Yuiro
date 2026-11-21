import { ref, type Ref } from 'vue'

/**
 * 订阅主进程推来的桌宠窗口 bounds（DIP，与鼠标 screen 坐标同坐标系）。
 * 模块级单例，多个消费者共享。
 */
const boundsX = ref(0)
const boundsY = ref(0)
const boundsW = ref(0)
const boundsH = ref(0)
let listening = false

export interface ElectronWindowBounds {
  x: Ref<number>
  y: Ref<number>
  width: Ref<number>
  height: Ref<number>
}

export function useElectronWindowBounds(): ElectronWindowBounds {
  if (!listening) {
    listening = true
    window.yuiro.startOverlayTracking()
    window.yuiro.onWindowBounds((b) => {
      boundsX.value = b.x
      boundsY.value = b.y
      boundsW.value = b.width
      boundsH.value = b.height
    })
  }
  return { x: boundsX, y: boundsY, width: boundsW, height: boundsH }
}
