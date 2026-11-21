/**
 * 悬停渐隐（Fade on Hover）决策纯函数。
 *
 * 语义（免打扰模式）：开启后，光标**靠近模型**到设定范围即整窗 UI（模型 + 功能泡 +
 * 括号菜单）淡出，同时点击穿透让出下层桌面；离开范围或贴边拖动时恢复可交互。
 *
 * 优先级短路：
 *   - uiOpen（面板打开）→ 可交互、不渐隐（面板是要操作的内容）
 *   - nearBorder（贴窗口边缘）→ 可交互、不渐隐（保留边缘拖动/缩放）
 *   - 其余：interactive = !fadeEnabled；shouldFade = fadeEnabled && 光标在靠近范围内
 *
 * 「靠近范围」由 useFadeOnHover 用模型包围盒 + 用户可调的 nearRange 算出（见 useFadeOnHoverPref）：
 * 0 = 贴到模型才渐隐，越大越"早"渐隐（可超出窗口边界，因为相对鼠标坐标在窗外同样有效）。
 *
 * 注意：
 *   - 不依赖"光标下像素透明度"——早期实现要求光标悬在透明像素才渐隐，
 *     导致"在模型本体上反而更不渐隐"，与免打扰直觉相反，已废弃。
 *   - interactive 只看 fadeEnabled（与"是否已渐隐"无关）：所以即使光标在窗口的透明边距里、
 *     未进入靠近范围，窗口依然是穿透的 —— 不会挡住下层的桌面点击。
 */
export interface FadeOnHoverInput {
  fadeEnabled: boolean
  /** 光标是否已进入「靠近模型」的触发范围 */
  mouseNearModel: boolean
  nearBorder: boolean
  uiOpen: boolean
}

export interface FadeOnHoverDecision {
  interactive: boolean
  shouldFade: boolean
}

export function fadeOnHoverDecision(input: FadeOnHoverInput): FadeOnHoverDecision {
  const { fadeEnabled, mouseNearModel, nearBorder, uiOpen } = input
  if (uiOpen) return { interactive: true, shouldFade: false }
  if (nearBorder) return { interactive: true, shouldFade: false }
  const interactive = !fadeEnabled
  const shouldFade = fadeEnabled && mouseNearModel
  return { interactive, shouldFade }
}
