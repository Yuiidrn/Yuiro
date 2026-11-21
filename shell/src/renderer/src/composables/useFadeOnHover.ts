import { computed, watch, type Ref } from 'vue'
import { refDebounced } from '@vueuse/core'
import { useMouseInWindow } from './useMouseInWindow'
import { useMouseAroundWindowBorder } from './useMouseAroundWindowBorder'
import { fadeOnHoverDecision } from '../utils/fadeOnHoverDecision'

/**
 * 悬停渐隐（Fade on Hover）实际生效 composable：决策 → 切换窗口穿透 + 经 shouldFade 驱动 UI 淡出。
 *
 * "是否开启"由外部 fadeEnabled 传入，"靠近触发范围"由 nearRange 传入
 * （两者都经 localStorage 跨窗口共享，见 useFadeOnHoverPref）。
 *
 * 免打扰语义：开启后光标**靠近模型**到设定范围即整窗 UI 淡出并穿透；
 * 离开范围或贴边拖动时恢复。范围以模型包围盒为基准往外扩 nearRange px。
 *
 * 坐标铁律：相对鼠标坐标与模型矩形都用窗口相对坐标（与 bounds 同系；
 * 坐标由主进程算好 DIP，渲染层绝不用 window.screenX 反推）。
 *
 * 取舍（重要）：开启后整窗点击穿透，模型本体不可按住拖动（forward 只转发 move，
 * mousedown 不送达）。移动桌宠靠窗口边缘拖动/托盘。不为"既要穿透又要可拖"引入闪烁。
 */
export interface Rect {
  left: number
  top: number
  width: number
  height: number
}

export function useFadeOnHover(
  uiOpen: Ref<boolean>,
  fadeEnabled: Ref<boolean>,
  nearRange: Ref<number>,
  getModelRect: () => Rect | null,
  hitContour?: (x:number,y:number,radius:number)=>boolean,
) {
  // 窗口相对坐标：用于"是否靠近模型" / "是否贴边"判定（与 bounds 同系）
  const { x, y, isInside } = useMouseInWindow(250)
  const { isNearAnyBorder } = useMouseAroundWindowBorder(10, true)

  /**
   * 光标是否进入「靠近模型」的触发范围。
   *
   * 距离 = 光标到模型包围盒最近边的欧氏距离（在盒内即 0）：
   * 盒内必然命中，盒外到 nearRange px 内也算"靠近" —— 这个范围**可以超出窗口边界**，
   * 因为相对鼠标坐标在窗外同样有值（主进程持续计算，不依赖窗口内的鼠标事件）。
   */
  const nearModelRaw = computed(() => {
    if (hitContour) return hitContour(x.value,y.value,nearRange.value)
    const r = getModelRect()
    // 模型还没量出来（首帧 / 换模型途中）→ 退回"在窗口内"判定。
    // 否则会出现"渐隐开着却怎么都不淡"，用户会以为坏了。
    if (!r) return isInside.value
    const dx = Math.max(r.left - x.value, 0, x.value - (r.left + r.width))
    const dy = Math.max(r.top - y.value, 0, y.value - (r.top + r.height))
    return Math.hypot(dx, dy) <= nearRange.value
  })

  // 与"是否在窗口内"同样防抖：边缘来回抖动不该导致反复淡入淡出
  const mouseNearModel = refDebounced(nearModelRaw, 250)

  const decision = computed(() => fadeOnHoverDecision({
    fadeEnabled: fadeEnabled.value,
    mouseNearModel: mouseNearModel.value,
    nearBorder: isNearAnyBorder.value,
    uiOpen: uiOpen.value,
  }))

  const interactive = computed(() => decision.value.interactive)
  const shouldFade = computed(() => decision.value.shouldFade)

  // 决策 → 穿透状态。interactive 即可交互（关穿透）；否则开穿透（forward 由主进程保证）。
  watch(interactive, (v) => {
    console.log('[fade] decision ' + JSON.stringify({
      interactive: v,
      shouldFade: shouldFade.value,
      nearModel: mouseNearModel.value,
      range: nearRange.value,
      enabled: fadeEnabled.value,
    }))
    // 窗口穿透由 useMousePassthrough 统一决策。
  }, { immediate: true })

  watch(shouldFade, (v) => {
    console.log('[fade] shouldFade ' + JSON.stringify({ v, enabled: fadeEnabled.value }))
  })

  return {
    shouldFade,
    interactive,
  }
}
