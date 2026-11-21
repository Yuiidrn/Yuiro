/**
 * Shared type contract for the Yuiro event bus (eventa-style).
 * Used by main process, preload bridge, and renderer.
 */

/** An approval request originating from the C++ SystemDaemon. */
export interface ApprovalRequest {
  approvalRequestId: string
  tool: string
  summary: string
  args: Record<string, unknown>
  preview?: string
}

/** Result emitted for speech/audio segments driving lipsync. */
export interface LipSyncPayload {
  mouthOpen: number
  visemes: number[]
  segmentId: string
}

/**
 * 桌宠窗口外观（主进程 petLayout 的形状，调试台 ⇄ 桌宠窗口之间传递）。
 *
 * 单位是 **DIP / 逻辑像素**（Electron 的 setSize 与渲染层 CSS px 都用它），
 * 与"截屏里量到的物理像素"相差一个显示器缩放比例（125% / 150% …）：
 * 703 DIP 在 150% 缩放的屏幕上会占用约 1055 物理像素 —— 这不是错位，是两套坐标系。
 */
export interface PetLayout {
  width: number
  height: number
  fillRatio: number
  /** 模型水平偏移（px，正值向右） */
  xOffset: number
  yOffset: number
}

/* ── 模型体检 / 导入（S49）──────────────────────────────────────────────── */

export interface ModelIssue {
  level: 'error' | 'warn'
  text: string
}

export interface ModelReport {
  /** 无 error 级问题才算通过（warn 只提示，不拦） */
  ok: boolean
  dir: string
  model3: string
  issues: ModelIssue[]
  info: {
    moc: string
    mocVersion: number
    textures: { file: string; mb: number }[]
    expressions: string[]
    motionGroups: { group: string; count: number }[]
    params: number
    physics: boolean
    pose: boolean
    /** 含中文/空格的文件名（URL 未编码就 404 的高发原因） */
    nonAscii: string[]
  }
}

export interface ModelImportResult {
  ok: boolean
  dest?: string
  modelPath?: string
  report: ModelReport
  message: string
}

/** Typed events flowing between renderer ⇄ main ⇄ engine. */
export type ShellEvent =
  | { type: 'voice-input:start' }
  | { type: 'voice-input:stop' }
  | { type: 'tts:start'; segmentId: string }
  | { type: 'tts:interrupted' }
  | { type: 'lip-sync:param'; payload: LipSyncPayload }
  | { type: 'action:tool-call'; tool: string; args: unknown }
  | { type: 'approval:required'; request: ApprovalRequest }
  | { type: 'approval:resolve'; approved: boolean; requestId: string }
  | { type: 'chat:user'; text: string }
  | { type: 'chat:assistant'; text: string }
  // --- 综合其它项目的新增事件 ---
  // OpenDesktop: 主动互动 / 摄像头 / 截图随附
  | { type: 'proactive:greet'; message: string }
  | { type: 'vision:capture'; kind: 'screenshot' | 'camera'; dataUrl: string }
  | { type: 'attachment:add'; kind: 'image' | 'screen' | 'camera'; dataUrl: string }
  // my-neuro / Agentic: 情绪驱动表情
  | { type: 'emotion:set'; emotion: string }
  // 调试窗口 → 桌宠窗口：外观（窗口尺寸 / 模型缩放 / 模型水平·垂直偏移）调整
  | {
    type: 'appearance:update'
    width: number
    height: number
    fillRatio: number
    /** 模型水平偏移（px，正值向右） */
    xOffset: number
    yOffset: number
  }
  // 调试窗口 → 桌宠窗口：更换 Live2D 模型（path 为 public 下的 model3.json 路径）
  | { type: 'avatar:model'; path: string; characterId?: string }
  // 调试窗口 → 桌宠窗口：试播一个动作（index 省略 = 该组内随机）
  | { type: 'avatar:motion'; group: string; index?: number; characterId?: string; modelPath?: string }
  // 调试窗口 → 桌宠窗口：预览某个表情
  | { type: 'avatar:expression'; name: string; characterId?: string; modelPath?: string }
  // 调试窗口 → 桌宠窗口：**试演一次成套表演**（S49）
  // 表情 + 动作 + 时长一次原子下发，与引擎的 avatar:intent 走同一条应用路径。
  // 为什么要这条直连：以前"试演"只能调引擎 HTTP，引擎没起就完全点不动，
  // 也分不清"表演配错了"还是"引擎不在"。现在调试台自己解析表演并直推桌宠。
  | {
    type: 'avatar:perform'
    characterId?: string
    modelPath?: string
    /** 表演名（仅用于日志显示） */
    name?: string
    /** 表情名；缺省 = 不动当前表情，空串 = 回落默认 */
    expression?: string
    motion?: string
    motionIndex?: number | null
    durationMs?: number
  }

/** Window options for the transparent desktop-pet overlay (AIRI window-contract). */
export interface OverlayWindowOptions {
  frame: false
  transparent: true
  alwaysOnTop: true
  skipTaskbar: true
  focusable: false
  hasShadow: false
  roundedCorners: false
}

/** Runtime constant replicating {@link OverlayWindowOptions}. */
export const OVERLAY_WINDOW_OPTIONS: OverlayWindowOptions = {
  frame: false,
  transparent: true,
  alwaysOnTop: true,
  skipTaskbar: true,
  focusable: false,
  hasShadow: false,
  roundedCorners: false,
}

/** Event type string constants. */
export const EVENT_TYPES = {
  VOICE_INPUT_START: 'voice-input:start',
  VOICE_INPUT_STOP: 'voice-input:stop',
  TTS_START: 'tts:start',
  TTS_INTERRUPTED: 'tts:interrupted',
  LIP_SYNC_PARAM: 'lip-sync:param',
  ACTION_TOOL_CALL: 'action:tool-call',
  APPROVAL_REQUIRED: 'approval:required',
  APPROVAL_RESOLVE: 'approval:resolve',
  CHAT_USER: 'chat:user',
  CHAT_ASSISTANT: 'chat:assistant',
  PROACTIVE_GREET: 'proactive:greet',
  VISION_CAPTURE: 'vision:capture',
  ATTACHMENT_ADD: 'attachment:add',
  EMOTION_SET: 'emotion:set',
  APPEARANCE_UPDATE: 'appearance:update',
} as const

/**
 * /ws/audio 语音链路事件（引擎 → 壳，独立于上述 IPC ShellEvent 总线）。
 * 由 `engine/yuiro/audio/__init__.py` 的 VoicePipeline 经 main.py 转发。
 * 阶段链：pipeline:state（loading/ready/error）→ vad:state → asr:start → asr:text
 *        → llm:start → llm:text → tts:start → tts:synthesize → tts:audio
 *        → tts:ready → tts:end
 * 载荷：
 *   pipeline:state {state: 'loading'|'ready'|'error'|'init', stage?, progress?}
 *                  冷启动加载进度；前端应在 state!=='ready' 时暂缓采音/显示启动态
 *   vad:state      {state: 'active'|'inactive', prob?, db?}
 *   vad:error      {message}
 *   asr:start      {state: 'transcribing'}
 *   asr:text       {text, duration_ms}
 *   asr:error      {message, duration_ms}
 *   llm:start      {state: 'requesting', input}
 *   llm:text       {text, source_text?, duration_ms}
 *                  S52：`text` 是**展示语言**文本（气泡用），`source_text` 是内部中文原文；
 *                  展示语言为中文时两者相同
 *   tts:start      {text, display_text?}
 *   tts:synthesize {text, segments, display_text?}
 *                  S52：`text` 在"整段转换"模式下是整段译文；在"逐句转换"模式
 *                  （默认）下仍是内部中文原文（译文在合成时逐段产生）。
 *                  `display_text` 仅在它与内部原文不同时出现（调试台对照用）
 *   tts:audio      {wav(base64), sample_rate, slice_ms, volumes[]}
 *   tts:ready      {duration_ms, wav_bytes, volumes_count}
 *   tts:end        {}
 *                  ⚠ S53：`tts:end` 只代表**音频段已全部下发给前端**，不代表已播完。
 *                  渲染层另有一个**本地合成**事件 `tts:playback_end`（由播放队列在
 *                  最后一段 onended 时发出，见 useVoiceInput）——UI 要"真的播完"
 *                  这个时刻请用它，不要用 tts:end。
 * 上行：二进制帧 = int16 单声道 16kHz PCM；JSON 帧 {type:'interrupt'} = barge-in。
 */

/**
 * /ws/control 文字回复 TTS 事件（引擎 → 壳，随「语音回复 TTS」统一开关开启时下发）。
 * 由 `engine/yuiro/main.py` 的 `_speak_reply` 在 `chat:assistant` 之后补发——
 * 文字链路的"说出回复"是附加步骤，音频走 control 通道（文字聊天可能没有 /ws/audio 连接）。
 * 载荷：
 *   tts:reply_audio {wav(base64), sample_rate, slice_ms, volumes[]}  —— 一段合成音频
 *   tts:reply_end   {}                                               —— 全部下完/被新回合打断
 * 前端消费：App.vue 的控制通道 onmessage 收到后转进 useVoiceInput 的同一条播放队列，
 * 复用口型（volumes）、`tts:playback_end`（真的播完才收气泡）与 stopPlayback（改口停播）。
 */
