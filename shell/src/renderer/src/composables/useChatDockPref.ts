import type { Ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'

/**
 * 桌宠「聊天坞」（脚底居中的输入胶囊）外观偏好。
 *
 * 与回复气泡 / 歌单卡同一套机制：调试台「UI」页调，桌宠窗口即时生效；
 * 两个窗口同源共享 localStorage，vueuse 的 useLocalStorage 默认监听 storage 事件，
 * 因此跨窗口改动会自动同步（storage 事件只在「别的窗口」触发）。
 *
 * 保留影响观感与操作习惯的配置：
 *   width    —— 输入胶囊最大宽度（越窄越不挡模型）
 *   height   —— 输入条高度（36–80px）
 *   offsetX / offsetY —— 相对位置（受窗口边界约束）
 *   radius / fontSize —— 圆角与输入字号
 *   alpha    —— 底色不透明度（越低越透）
 *   showMic  —— 是否显示麦克风按钮（不用语音的人可以收掉；括号菜单里仍有语音入口）
 *   showSend —— 是否显示发送按钮（回车即可发送，也可以收掉）
 */

export const CHAT_DOCK_DEFAULTS = {
  /** 最大宽度（px），对应输入胶囊的 --dock-w */
  width: 330,
  height:44,
  offsetX:0,offsetY:0,radius:28,fontSize:14,
  /** 底色不透明度 0.3~1，对应 --dock-alpha */
  alpha: 0.93,
  showMic: true,
  showSend: true,
}

const KEY_WIDTH = 'yuiro-chat-dock-width'
const KEY_ALPHA = 'yuiro-chat-dock-alpha'
const KEY_SHOW_MIC = 'yuiro-chat-dock-show-mic'
const KEY_SHOW_SEND = 'yuiro-chat-dock-show-send'

/** 模块级单例：两个窗口内各只有一份，避免多处调用产生多份状态。 */
let cached: {
  width: Ref<number>
  height:Ref<number>
  offsetX:Ref<number>;offsetY:Ref<number>;radius:Ref<number>;fontSize:Ref<number>
  alpha: Ref<number>
  showMic: Ref<boolean>
  showSend: Ref<boolean>
  reset: () => void
} | null = null

function clamp(v: unknown, lo: number, hi: number, fallback: number): number {
  const n = Number(v)
  if (!Number.isFinite(n)) return fallback
  return Math.min(Math.max(n, lo), hi)
}

export function useChatDockPref() {
  if (cached) return cached

  const width = useLocalStorage<number>(KEY_WIDTH, CHAT_DOCK_DEFAULTS.width)
  const height=useLocalStorage<number>('yuiro-chat-dock-height',CHAT_DOCK_DEFAULTS.height)
  if(height.value!==clamp(height.value,36,80,44))height.value=clamp(height.value,36,80,44)
  const offsetX=useLocalStorage('yuiro-chat-dock-offset-x',0),offsetY=useLocalStorage('yuiro-chat-dock-offset-y',0),radius=useLocalStorage('yuiro-chat-dock-radius',28),fontSize=useLocalStorage('yuiro-chat-dock-font-size',14)
  for(const [value,min,max,fallback] of [[offsetX,-1000,1000,0],[offsetY,-50,400,0],[radius,0,40,28],[fontSize,11,24,14]] as const)value.value=clamp(value.value,min,max,fallback)
  const alpha = useLocalStorage<number>(KEY_ALPHA, CHAT_DOCK_DEFAULTS.alpha)
  const showMic = useLocalStorage<boolean>(KEY_SHOW_MIC, CHAT_DOCK_DEFAULTS.showMic)
  const showSend = useLocalStorage<boolean>(KEY_SHOW_SEND, CHAT_DOCK_DEFAULTS.showSend)

  // 防御历史脏值（例如手改过 localStorage）
  if (width.value !== clamp(width.value, 180, 640, CHAT_DOCK_DEFAULTS.width)) {
    width.value = clamp(width.value, 180, 640, CHAT_DOCK_DEFAULTS.width)
  }
  if (alpha.value !== clamp(alpha.value, 0.3, 1, CHAT_DOCK_DEFAULTS.alpha)) {
    alpha.value = clamp(alpha.value, 0.3, 1, CHAT_DOCK_DEFAULTS.alpha)
  }

  function reset(): void {
    width.value = CHAT_DOCK_DEFAULTS.width
    height.value=CHAT_DOCK_DEFAULTS.height
    offsetX.value=0;offsetY.value=0;radius.value=28;fontSize.value=14
    alpha.value = CHAT_DOCK_DEFAULTS.alpha
    showMic.value = CHAT_DOCK_DEFAULTS.showMic
    showSend.value = CHAT_DOCK_DEFAULTS.showSend
  }

  cached = { width, height, offsetX,offsetY,radius,fontSize,alpha, showMic, showSend, reset }
  return cached
}

/**
 * 组装成 CSS 变量，**绑到 `.shell-root`** 上。
 *
 * 必须绑在根元素：tokens.css 里的 `--chat-surface-solid` 是用 `var(--dock-alpha)`
 * 拼出来的，而自定义属性是在「声明它的元素」上完成替换的 —— 绑在子元素上不会生效。
 */
export function chatDockCssVars(width: number, alpha: number,height=44,offsetX=0,offsetY=0,radius=28,fontSize=14): Record<string, string> {
  return {
    '--dock-x':`${clamp(offsetX,-1000,1000,0)}px`,'--dock-y':`${clamp(offsetY,-50,400,0)}px`,'--dock-radius':`${clamp(radius,0,40,28)}px`,'--dock-font':`${clamp(fontSize,11,24,14)}px`,
    '--dock-h':`${Math.round(clamp(height,36,80,44))}px`,
    '--dock-w': `${Math.round(width)}px`,
    '--dock-alpha': String(alpha),
  }
}
