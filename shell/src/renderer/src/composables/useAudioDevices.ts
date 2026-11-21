import { ref } from 'vue'

/**
 * 录音设备（麦克风）的**检测 / 切换 / 容错** —— 所有语音入口共用这一份。
 *
 * 为什么需要它：此前三处采音（桌宠聊天坞 `useVoiceInput`、日记 `useRecorder`、
 * 调试台 `VoiceDebug`）都是 `getUserMedia({ audio: {...} })` —— **不指定设备**，
 * 于是永远只能用系统默认麦克风：插了耳机仍从外放麦收音，用户无从切换，
 * 也无从知道系统里到底有没有麦、选中的是哪一个。
 *
 * 「检测」比看上去难，三个现实问题必须处理：
 *   1. **未授权时 `label` 是空串**（Chromium 的隐私策略）：直接 `enumerateDevices()`
 *      只能拿到一堆无名设备。要拿到"麦克风阵列 (Realtek…)"这种真名，必须先**申请
 *      一次麦克风权限**再枚举 —— 但申请会点亮系统指示灯，所以只在用户**主动打开
 *      设备列表**时才探测（`probe: true`），绝不在页面加载时偷偷开麦。
 *   2. **设备会被拔掉**：选中的 id 可能突然不存在，此时 `deviceId: { exact }` 会直接
 *      抛 `OverconstrainedError`。策略是**自动回退系统默认并告知用户**，
 *      而不是让"开麦"整个失败（这正是"检测"要兜住的情况）。
 *   3. **跨窗口共享**：桌宠 / 日记 / 调试台是三个独立窗口。同一 origin 下
 *      localStorage 共享，所以选择天然全局生效；再用 BroadcastChannel
 *      让"在日记里换了麦，聊天坞立刻跟上"。
 */
const STORE_KEY = 'yuiro.audio.input_device'

export interface AudioDevice {
  id: string
  label: string
  isDefault: boolean
}

function loadStored(): string {
  try {
    return window.localStorage.getItem(STORE_KEY) ?? ''
  } catch {
    return ''
  }
}

/**
 * 把 `getUserMedia` 的错误翻成**用户能照着做的话**。
 *
 * 原来三处都是笼统的"无法访问麦克风（请检查系统权限）"：没插麦、被拒权、
 * 被别的程序占着，这三种的处理方式完全不同，用户却看不出是哪一种。
 */
export function describeMicError(e: unknown): string {
  const name = e instanceof DOMException ? e.name : ((e as { name?: string } | null)?.name ?? '')
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return '麦克风权限被拒绝：请在系统设置里允许本应用使用麦克风'
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return '没有检测到麦克风设备：请插入或启用一个录音设备'
    case 'NotReadableError':
    case 'TrackStartError':
      return '麦克风被占用或不可读：请关掉正在用它的程序（会议 / 录音软件）后重试'
    case 'OverconstrainedError':
      return '所选麦克风已不可用，已回退到系统默认'
    default: {
      const msg = e instanceof Error ? e.message : String(e)
      return msg ? `无法访问麦克风：${msg}` : '无法访问麦克风'
    }
  }
}

/** 模块级单例：三个窗口各有一份，窗口内所有组件共用同一份状态。 */
const devices = ref<AudioDevice[]>([])
const selectedId = ref(loadStored())
/** 是否已经拿到过麦克风权限 —— 没拿到之前，"设备名"本身是读不到的。 */
const ready = ref(false)
const probing = ref(false)
const error = ref('')

let probeStream: MediaStream | null = null
let listening = false
let channel: BroadcastChannel | null = null

function persist(): void {
  try {
    window.localStorage.setItem(STORE_KEY, selectedId.value)
  } catch {
    /* 隐私模式忽略 */
  }
  channel?.postMessage({ type: 'select', id: selectedId.value })
}

/**
 * 枚举录音设备。
 *
 * @param probe 是否先申请一次权限再枚举。**只有用户主动打开设备列表时才传 true** ——
 *              它会让系统麦克风指示灯亮一下，不适合在页面加载时静默调用。
 */
async function refresh(probe = false): Promise<void> {
  error.value = ''
  const md = navigator.mediaDevices
  if (!md?.enumerateDevices) {
    error.value = '当前环境不支持录音设备检测'
    devices.value = []
    return
  }

  if (probe && !ready.value) {
    probing.value = true
    try {
      // 只为"拿权限 → 解锁设备名"，拿到后立刻释放，不在这里开始录音
      probeStream = await md.getUserMedia({ audio: true })
      ready.value = true
    } catch (e) {
      error.value = describeMicError(e)
    } finally {
      probing.value = false
      probeStream?.getTracks().forEach((t) => t.stop())
      probeStream = null
    }
  }

  try {
    const all = await md.enumerateDevices()
    const inputs = all.filter((d) => d.kind === 'audioinput')
    devices.value = inputs.map((d, i) => ({
      id: d.deviceId,
      // 未授权时 label 为空 —— 明确写成"麦克风 N"，别留空白让人以为坏了
      label: d.label?.trim() || `麦克风 ${i + 1}`,
      isDefault: d.deviceId === 'default' || d.deviceId === '',
    }))
    if (inputs.some((d) => Boolean(d.label?.trim()))) ready.value = true

    // ★ 选中的设备被拔掉 → 回退系统默认并告知（否则开麦时直接 OverconstrainedError）
    if (selectedId.value && !devices.value.some((d) => d.id === selectedId.value)) {
      selectedId.value = ''
      persist()
      error.value = '之前选择的麦克风已断开，已回退到系统默认'
    }
    if (!devices.value.length && !error.value) {
      error.value = '没有检测到麦克风设备'
    }
  } catch (e) {
    error.value = describeMicError(e)
  }
}

function select(id: string): void {
  selectedId.value = id
  persist()
}

/** 当前设备名（给 UI 显示；未选 = 系统默认）。 */
function currentLabel(): string {
  if (!selectedId.value) return '系统默认'
  return devices.value.find((d) => d.id === selectedId.value)?.label ?? '系统默认'
}

/**
 * 打开麦克风流 —— **三处采音都必须走这里**，不要各自写 `getUserMedia`。
 *
 * 只有这里做了两件关键的兜底：① 选中设备失效时**自动回退默认**（不让开麦整个失败）；
 * ② 错误翻译成可操作的话（见 `describeMicError`）。
 */
async function openStream(extra: MediaTrackConstraints = {}): Promise<MediaStream> {
  const base: MediaTrackConstraints = {
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
    ...extra,
  }
  const id = selectedId.value
  if (id) {
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        audio: { ...base, deviceId: { exact: id } },
      })
      ready.value = true
      return s
    } catch (e) {
      const name = e instanceof DOMException ? e.name : ''
      // 只有"设备不在了"才回退；权限等其它错误应当如实抛给调用方
      if (name !== 'OverconstrainedError' && name !== 'NotFoundError') throw e
      selectedId.value = ''
      persist()
      void refresh()
    }
  }
  const s = await navigator.mediaDevices.getUserMedia({ audio: base })
  ready.value = true
  return s
}

/**
 * 挂上 `devicechange` 与跨窗口同步。**每个窗口调用一次即可**（内部有幂等判断）。
 * 组件卸载不需要解绑：这是模块级单例，生命周期与窗口一致。
 */
function listen(): void {
  if (!listening) {
    listening = true
    try {
      navigator.mediaDevices?.addEventListener?.('devicechange', () => void refresh())
    } catch {
      /* 环境不支持就算了，不影响主流程 */
    }
  }
  if (!channel && typeof BroadcastChannel !== 'undefined') {
    channel = new BroadcastChannel('yuiro.audio.device')
    channel.onmessage = (ev: MessageEvent): void => {
      const data = ev.data as { type?: string; id?: string } | null
      if (data?.type === 'select' && typeof data.id === 'string') {
        selectedId.value = data.id
        try {
          window.localStorage.setItem(STORE_KEY, data.id)
        } catch {
          /* 隐私模式 */
        }
      }
    }
  }
}

export function useAudioDevices() {
  return {
    devices,
    selectedId,
    ready,
    probing,
    error,
    refresh,
    select,
    currentLabel,
    openStream,
    listen,
  }
}
