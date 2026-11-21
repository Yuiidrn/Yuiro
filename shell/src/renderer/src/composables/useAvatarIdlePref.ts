import { useLocalStorage } from '@vueuse/core'
import { computed } from 'vue'

/**
 * 桌宠「待机行为」偏好（S53）。
 *
 * 为什么单独做成偏好：待机是最常被看到的状态，也最容易"过"——
 * 之前是全组随机 + 播完立刻续播，Hiyori 会把 8.6s 的全身动作当待机反复播。
 * 现在只播 idle 语义动作，并且**播完停顿一段时间**再播下一个。
 *
 * 调试台窗口与桌宠窗口同源、共用 localStorage，`useLocalStorage` 会自动监听
 * storage 事件 —— 调完两边即时一致，无需重启。
 */
export const AVATAR_IDLE_DEFAULTS = {
  /** 是否播放待机动作（关闭 = 只呼吸/眨眼，表情保持 neutral） */
  enabled: true,
  /** 两个 idle 动作之间最短停顿 */
  intervalMinMs: 6000,
  /** 最长停顿（区间内随机，避免机械感） */
  intervalMaxMs: 12000,
  /** 只选时长不超过该值的 idle 动作（过滤掉大幅/超长动作） */
  maxDurationMs: 4500,
}

const KEY_ENABLED = 'yuiro-avatar-idle-enabled'
const KEY_MIN = 'yuiro-avatar-idle-min-ms'
const KEY_MAX = 'yuiro-avatar-idle-max-ms'
const KEY_DUR = 'yuiro-avatar-idle-max-duration-ms'

function clamp(v: number, lo: number, hi: number, fallback: number): number {
  const n = Number(v)
  if (!Number.isFinite(n)) return fallback
  return Math.min(Math.max(Math.round(n), lo), hi)
}

export function useAvatarIdlePref() {
  const role = useLocalStorage('yuiro-active-character', 'hiyori')
  function scoped<T extends boolean | number | string>(base: string, initial: T, hotaruInitial: T = initial) {
    // Hiyori 保留旧偏好键；当前 VueUse 版本不支持动态 storage key。
    const hiyori = useLocalStorage<T>(base, initial)
    const hotaru = useLocalStorage<T>(`${base}:hotaru`, hotaruInitial)
    return computed<T>({
      get: () => role.value === 'hotaru' ? hotaru.value : hiyori.value,
      set: (value) => { if (role.value === 'hotaru') hotaru.value = value; else hiyori.value = value },
    })
  }
  const fixedMotion=scoped<string>('yuiro-avatar-idle-fixed-motion','Idle#0','')
  const gazeHoldMs=scoped<number>('yuiro-avatar-gaze-hold-ms',2200,2800)
  gazeHoldMs.value=clamp(gazeHoldMs.value,500,10000,2200)
  const gazeEnabled=scoped<boolean>('yuiro-avatar-gaze-enabled',true)
  const gazeStrength=scoped<number>('yuiro-avatar-gaze-strength',.18,.10)
  const gestureCooldownMs=scoped<number>('yuiro-avatar-gesture-cooldown',12000,18000)
  const gestureMaxMs=scoped<number>('yuiro-avatar-gesture-max-ms',2500,2000)
  gazeStrength.value=Math.max(0,Math.min(.4,Number.isFinite(gazeStrength.value)?gazeStrength.value:.18))
  gestureCooldownMs.value=clamp(gestureCooldownMs.value,5000,60000,12000)
  gestureMaxMs.value=clamp(gestureMaxMs.value,500,4000,2500)
  const reactiveEnabled = scoped<boolean>('yuiro-avatar-reactive-enabled', true)
  const agentReactionsEnabled=scoped<boolean>('yuiro-avatar-agent-reactions-enabled',true)
  const agentCooldownMs=scoped<number>('yuiro-avatar-agent-cooldown-ms',10000,14000)
  const agentMaxMs=scoped<number>('yuiro-avatar-agent-max-ms',4000)
  agentCooldownMs.value=clamp(agentCooldownMs.value,3000,60000,10000)
  agentMaxMs.value=clamp(agentMaxMs.value,500,6000,4000)
  const enabled = scoped<boolean>(KEY_ENABLED, AVATAR_IDLE_DEFAULTS.enabled)
  const intervalMinMs = scoped<number>(KEY_MIN, AVATAR_IDLE_DEFAULTS.intervalMinMs)
  const intervalMaxMs = scoped<number>(KEY_MAX, AVATAR_IDLE_DEFAULTS.intervalMaxMs)
  const maxDurationMs = scoped<number>(KEY_DUR, AVATAR_IDLE_DEFAULTS.maxDurationMs)

  // 防御历史脏值 / 手改 localStorage
  intervalMinMs.value = clamp(intervalMinMs.value, 2000, 60000, AVATAR_IDLE_DEFAULTS.intervalMinMs)
  intervalMaxMs.value = clamp(intervalMaxMs.value, 2000, 120000, AVATAR_IDLE_DEFAULTS.intervalMaxMs)
  if (intervalMaxMs.value < intervalMinMs.value) intervalMaxMs.value = intervalMinMs.value
  maxDurationMs.value = clamp(maxDurationMs.value, 1000, 15000, AVATAR_IDLE_DEFAULTS.maxDurationMs)

  function reset(): void {
    gazeHoldMs.value=role.value==='hotaru'?2800:2200
    gazeEnabled.value=true;gazeStrength.value=role.value==='hotaru'?.10:.18
    gestureCooldownMs.value=role.value==='hotaru'?18000:12000;gestureMaxMs.value=role.value==='hotaru'?2000:2500
    fixedMotion.value=role.value==='hotaru'?'':'Idle#0'
    reactiveEnabled.value=true
    agentReactionsEnabled.value=true;agentCooldownMs.value=role.value==='hotaru'?14000:10000;agentMaxMs.value=4000
    enabled.value = AVATAR_IDLE_DEFAULTS.enabled
    intervalMinMs.value = AVATAR_IDLE_DEFAULTS.intervalMinMs
    intervalMaxMs.value = AVATAR_IDLE_DEFAULTS.intervalMaxMs
    maxDurationMs.value = AVATAR_IDLE_DEFAULTS.maxDurationMs
  }

  return { agentReactionsEnabled,agentCooldownMs,agentMaxMs,fixedMotion,gazeHoldMs,gazeEnabled,gazeStrength,gestureCooldownMs,gestureMaxMs,reactiveEnabled, enabled, intervalMinMs, intervalMaxMs, maxDurationMs, reset }
}

/** 区间内随机停顿（min > max 时按 min 处理）。 */
export function randomIdleDelay(minMs: number, maxMs: number): number {
  const lo = Math.max(0, Math.min(minMs, maxMs))
  const hi = Math.max(lo, maxMs)
  return lo + Math.round(Math.random() * (hi - lo))
}
