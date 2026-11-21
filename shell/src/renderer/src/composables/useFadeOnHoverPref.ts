import { ref, watch, type Ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'

/**
 * 悬停渐隐（Fade on Hover）偏好与确认状态。
 *
 * 管"是否开启"与"靠近触发范围"的持久化（localStorage，跨 pet 窗口与 dev 调试台
 * 共享同一 origin），以及"首次开启确认层"的状态机。
 * 实际的靠近判定 / 穿透决策由 useFadeOnHover 负责。
 *
 * 逃生通道：渐隐开启后窗口 click-through、渲染层自身点不动，
 * 这里订阅主进程（托盘"关闭悬停渐隐"）的强制关闭指令，确保用户总能恢复可交互。
 */

/**
 * 「靠近触发范围」默认值（px）。
 *
 * 语义：以**模型包围盒**为基准往外扩 N px，光标进入这个范围即触发渐隐。
 * 取 90 大致等于窗口为模型预留的边距（左右各 64 + 底部 100），
 * 所以默认观感与"鼠标进窗口就渐隐"接近；调小则要更贴近模型才渐隐。
 */
export const FADE_NEAR_RANGE_DEFAULT = 90

/** 数值归一：非数字/NaN 回退默认值，并夹紧到合法区间。 */
function clampNum(v: unknown, lo: number, hi: number, fallback: number): number {
  const n = Number(v)
  if (!Number.isFinite(n)) return fallback
  return Math.min(Math.max(n, lo), hi)
}

export function useFadeOnHoverPref() {
  const bridge = window.yuiro
  const fadeEnabled = useLocalStorage<boolean>('yuiro-fade-on-hover-enabled', false)
  const dontShowAgain = useLocalStorage<boolean>('yuiro-fade-on-hover-dont-show-again', false)
  /** 靠近触发范围（px）：0 = 贴到模型才渐隐；越大越"早"渐隐。 */
  const nearRange = useLocalStorage<number>('yuiro-fade-on-hover-near-range', FADE_NEAR_RANGE_DEFAULT)
  if (nearRange.value !== clampNum(nearRange.value, 0, 600, FADE_NEAR_RANGE_DEFAULT)) {
    nearRange.value = clampNum(nearRange.value, 0, 600, FADE_NEAR_RANGE_DEFAULT)
  }
  const showNotice = ref(false)

  /** 用户点击开关：dont-show-again 已勾选则直接启用；否则弹确认层。 */
  function requestEnable(): void {
    if (dontShowAgain.value) {
      fadeEnabled.value = true
    } else {
      showNotice.value = true
    }
  }
  function confirmNotice(dontShow: boolean): void {
    if (dontShow) dontShowAgain.value = true
    fadeEnabled.value = true
    showNotice.value = false
  }
  function cancelNotice(): void {
    showNotice.value = false
  }
  /** 强制设置开关（托盘菜单调用）：直接置位，不经过确认层，也不改动"不再提示"记忆。 */
  function setEnabled(on: boolean): void {
    fadeEnabled.value = on
    if (!on) showNotice.value = false
  }

  // 上报开启状态给主进程 → 驱动托盘菜单项文案（开启/关闭）。
  watch(fadeEnabled, (v) => bridge.reportFadeState(v), { immediate: true })
  // 主进程（托盘）请求切换开关时执行。
  bridge.onFadeSet(setEnabled)

  return {
    fadeEnabled: fadeEnabled as Ref<boolean>,
    dontShowAgain: dontShowAgain as Ref<boolean>,
    nearRange: nearRange as Ref<number>,
    showNotice,
    requestEnable,
    confirmNotice,
    cancelNotice,
    setEnabled,
  }
}
