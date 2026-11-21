<script setup lang="ts">
import { notifySpeechSettings, watchSpeechSettings } from './utils/speechSettingsSignal'
import { acceptsReplySpeech } from './avatar/replyIdentity'

import { presenceAfter, type Presence } from './avatar/presence'
import { contourBands } from './utils/contourBands'
import { computed, onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue'
import { Icon } from '@iconify/vue'
import Live2DCanvas from './components/Live2DCanvas.vue'
import ChatBubble from './components/ChatBubble.vue'
import { useSpeechBubblePref } from './composables/useSpeechBubblePref'
import { useResultCardPref } from './composables/useResultCardPref'
import { useUiAppearance } from './composables/useUiAppearance'
import type { DetachedState, ClientPlayback } from '../../shared/detachedUi'
import type { ClientSearchRequest,ClientSearchReply,AgentActivityFrame } from '../../shared/engine-protocol'
import { AgentReactions } from './avatar/agentReactions'
import { useAvatarIdlePref } from './composables/useAvatarIdlePref'
import { dialogueAnchor } from '../../shared/dialogueLine'
import BracketMenu from './components/BracketMenu.vue'
import MicDevicePicker from './components/MicDevicePicker.vue'
import type { ResultCardItem } from './composables/useResultCardPref'
import FadeOnHoverNotice from './components/FadeOnHoverNotice.vue'
import { useBracketMenu } from './composables/useBracketMenu'
import { useMousePassthrough } from './composables/useMousePassthrough'
import { usePetDrag } from './composables/usePetDrag'
import { useVoiceInput } from './composables/useVoiceInput'
import { useTheme } from './composables/useTheme'
import { useFadeOnHover } from './composables/useFadeOnHover'
import { useFadeOnHoverPref } from './composables/useFadeOnHoverPref'
import { chatDockCssVars, useChatDockPref } from './composables/useChatDockPref'
import type { ShellEvent } from '@shared'

const ENGINE_WS = 'ws://127.0.0.1:8200/ws/control'

// 引擎 WS 鉴权密钥（来自启动环境的 YUIRO_SHARED_SECRET），以 ?secret= 查询参数携带
async function engineWsUrl(path: string): Promise<string> {
  let secret = ''
  try {
    secret = (await window.yuiro?.getEngineSecret?.()) || ''
  } catch {
    secret = ''
  }
  return secret ? `${path}?secret=${encodeURIComponent(secret)}` : path
}

// ── 状态 ──
const activePanel = ref<'chat' | null>(null)
const input = ref('')
const connClass = ref('off')
const connSymbol = ref('○')
const isRecording = ref(false)
// 日志条目：分级（info/success/error/warning）+ 时间戳，my-neuro 标准件风格
interface LogItem { id: number; text: string; level: 'info' | 'success' | 'error' | 'warning'; ts: number }
const logs = ref<LogItem[]>([{ id: 0, text: '[yuiro] 就绪', level: 'info', ts: Date.now() }])
const logFilter = ref<'all' | 'error'>('all')
const currentEmotion = ref('')
/**
 * S02：会话身份（引擎 session:ready 下发）；audio 通道据此绑定同一 AgentSession。
 *
 * S43：**持久化到 localStorage**。原先它只在内存里，页面刷新 / Vite 热更新一重载
 * 就归零 → 每次连接都新建会话（实测开发态一天攒下好几个），用户侧表现为"上下文全丢"。
 * 现在刷新后会带上旧 id：引擎能进程内 resume，或（引擎重启过时）从事件日志 **revive**。
 */
const SESSION_KEY = 'yuiro.session_id'
const sessionId = ref(
  (() => { try { return window.localStorage.getItem(SESSION_KEY) || '' } catch { return '' } })()
)
let msgIdCounter = 0
let logIdCounter = 1

// ── DOM refs ──
const inputRef = ref<HTMLInputElement>()
const petCanvas = ref<HTMLCanvasElement | null>(null)
const petComponent = ref<InstanceType<typeof Live2DCanvas> | null>(null)

// ── 对话呈现状态 ──
// 桌宠回复 → 漫画说话云框：只显示「当前这一条」，锚定模型头部上方，因此不压腿脚
const speechText = ref('')
const speechVisible = ref(false)
let speechTimer = 0

// S53：气泡生命周期与 TTS 播放对齐 —— 有语音时"播完才消失"，没有语音才退回按字数估算。
// 用户要求："回复气泡应该伴随 tts 的播放完毕才同步消失"。
let speechHeldForPlayback = false   // 本条气泡是否在等语音播完
let speechGraceTimer = 0            // "这轮到底有没有语音"的宽限计时
let speechTtsActive = false         // 本轮是否出现过 TTS 活动（按回合复位，见 asr:start）
const SPEECH_GRACE_MS = 2500        // 宽限期内没有任何音频 → 认定无声，退回估算
const SPEECH_TAIL_MS = 200          // 播完后再留一口气，别让末字刚落文字就消失
const SPEECH_HARD_CAP_MS = 60000    // 兜底上限：等不到"播完"也不能让气泡永久挂着

// S39：工具活动状态行（"正在读取目录…" / "3/7｜在移动文件"）——
// 工具在跑时界面不再静默（"像卡死"的主要来源就是这种静默）。
const activityText = ref('')
let activityTimer = 0

// G7（2026-09-15）：结构化结果卡 —— 工具返回的列表数据（歌单雷达/搜索候选/歌曲列表）
// 此前只躺在工具 JSON 里，界面上什么都不显示，用户侧表现为"推荐了歌单却毫无反应"。
// 现在渲染成一张可看的卡片（视图见 components/ResultCard.vue，默认摆在模型左侧、
// 与头部右上侧的回复气泡左右对称），停留一段时间后自动收起。
// 条目类型 ResultCardItem 定义在 useResultCardPref.ts，供卡片组件复用。
const resultCard = ref<{ title: string; kind: string; items: ResultCardItem[]; note: string } | null>(null)
const sourceCard = ref<typeof resultCard.value>(null)
let sourceTimer=0
function clearSourceCard():void {
  sourceCard.value=null
  if(sourceTimer){clearTimeout(sourceTimer);sourceTimer=0}
}
function scheduleSourceHide():void {
  if(sourceTimer){clearTimeout(sourceTimer);sourceTimer=0}
  const seconds=uiAppearance.settings.value.source.seconds
  if(sourceCard.value&&seconds>0)sourceTimer=window.setTimeout(clearSourceCard,seconds*1000)
}
const uiAppearance=useUiAppearance()
const officialPlayback = ref<ClientPlayback|null>(null)
const officialPending = ref(false)
let mediaRequestId=0, mediaPollTimer=0,clientSearchRequestId=0
let resultCharacterSwitching = false
function clearResultCard(): void {
  clientSearchRequestId++
  clearSourceCard()
  clearMusicCard()
}
function clearMusicCard():void {
  officialPlayback.value=null
  officialPending.value=false
  mediaRequestId++
  resultCard.value = null
  if (resultTimer) { clearTimeout(resultTimer); resultTimer = 0 }
}
let resultTimer = 0
function scheduleResultHide():void {
  if(resultTimer){clearTimeout(resultTimer);resultTimer=0}
  if(!resultCard.value||officialPlayback.value)return
  const seconds=resultCard.value.kind==='source'?uiAppearance.settings.value.source.seconds:uiAppearance.settings.value.results.seconds
  if(seconds>0)resultTimer=window.setTimeout(()=>{resultCard.value=null;resultTimer=0},seconds*1000)
}
// 动作联动节流：读 10 个文件不该手舞足蹈 10 次
const agentReactions=new AgentReactions()
const agentReactionPref=useAvatarIdlePref()
// 自己刚发的消息 → 贴底单条气泡：紧贴输入胶囊上方，仅保留最新一条
const sentMsg = ref<{ id: number; text: string } | null>(null)
const sentIsNew = ref(false)
let sentTimer = 0

// ── Mic animation ──
let micRaf = 0
const micLevel = ref(0)

// ── Composable init ──
const avatarGeneration=ref(0)
function advanceAvatarGeneration(){avatarGeneration.value++;agentReactions.reset();petComponent.value?.cancelPerformance?.()}
const presence = ref<Presence>('idle')
let presenceTimer=0
function presenceEvent(type:string,state?:string){
  const next=presenceAfter(presence.value,type,state)
  if(next===presence.value)return
  presence.value=next;window.clearTimeout(presenceTimer)
  if(next==='thinking'||next==='listening')presenceTimer=window.setTimeout(()=>{presence.value='idle'},60000)
}
const { theme, toggleTheme } = useTheme()
const { inputLevel:micInputLevel, start, stop, sendInterrupt, turnBusy, bargeInEnabled, loadBargeIn:loadVoiceBargeIn, mouthOpen, pipelineState, pipelineLoading, loadingStage, loadingProgress, beginReplyPlayback, enqueueReplyAudio, endReplyAudio, stopPlayback, dispose: disposeVoice } = useVoiceInput((type, payload) => {
  presenceEvent(type,String(payload.state??''))
  // 语音链路事件 → 日志面板，让用户看到识别/LLM/TTS 全过程反馈
  if (type === 'vad:state') log(`[voice] VAD ${payload.state}${payload.prob !== undefined ? ` (${payload.prob})` : ''}`)
  else if (type === 'asr:start') {
    advanceAvatarGeneration()
    clearSourceCard()
    log('[voice] 开始识别…')
    // S53：新一轮开始 → 复位"本轮有 TTS 活动"标记（它决定气泡是等播放还是按字数估算）
    speechTtsActive = false
  }
  else if (type === 'asr:text') log(`[voice] 识别: ${payload.text}`)
  else if (type === 'asr:error') log(`[voice] 识别失败: ${payload.message}`)
  else if (type === 'asr:dropped') log(`[voice] 本句未进入对话：${String(payload.reason ?? '')}`)
  else if (type === 'llm:start') log(`[voice] LLM 请求: ${payload.input}`)
  else if (type === 'llm:text') {
    log(`[voice] LLM 回复: ${payload.text}`)
    // 语音回复也要同步显示在说话云框（气泡）里 —— 否则只有声音没有文字，
    // TTS 一旦出问题（如无声音），用户就完全看不到回复内容了
    clearActivity()
    // S53：语音链路的气泡**等真的播完**再收（不是按字数估算）
    showSpeech(String(payload.text ?? ''), true)
  }
  // S53：本轮只要出现过任何 TTS 活动，就说明"语音正在来的路上"——气泡要一直挂着
  // 等 tts:playback_end（不能因为"还没收到音频"就退回估算，合成慢时会被误判成没语音）。
  else if (type === 'tts:start' || type === 'tts:audio' || type === 'tts:synthesize') {
    speechTtsActive = true
    if (type === 'tts:synthesize') log('[voice] TTS 合成中…')
  }
  else if (type === 'tts:ready') {
    speechTtsActive = true
    log(`[voice] TTS 完成(${(payload.duration_ms as number) ?? 0}ms)，播放中`)
  }
  // S53：本地合成事件（见 useVoiceInput）—— 队列播空 + 引擎已发完 = 她说完了。
  // 此刻收起气泡，做到"文字随语音一起消失"；留 200ms 尾巴避免末字刚落就消失。
  else if (type === 'tts:playback_end') {
    log('[voice] 播放完毕，收起气泡')
    if (speechHeldForPlayback) {
      speechHeldForPlayback = false
      window.setTimeout(() => {
        // 期间若来了新的一条（非 hold），它已接管气泡 → 不要误收
        if (!speechHeldForPlayback) hideSpeech()
      }, SPEECH_TAIL_MS)
    }
  }
  // 打断必须**可观测**（S03 要求"打断原因日志可查"）——
  // 否则用户只会觉得"她没停"，无从判断是引擎没取消、还是前端没停播。
  else if (type === 'tts:interrupted') {
    log(`[voice] 已打断，停止播放（${String(payload.reason ?? 'barge-in')}）`)
    // S53：被打断就没有"播完"了 → 立刻收气泡（她没说完，文字也不该继续挂着）
    hideSpeech()
  }
  else if (type === 'ws:closed') {
    log('[voice] 语音通道断开')
    // S53：通道断了就不会再有音频/播完事件 → 正等播放的气泡直接收掉
    if (speechHeldForPlayback) hideSpeech()
  }
  else if (type === 'mic:start') log('[voice] 麦克风已开启，开始监听')
  else if (type === 'mic:stop') log('[voice] 麦克风已关闭')
  else if (type === 'mic:waiting') log(`[voice] 引擎语音模型加载中（${String(payload.stage ?? '')}），音频将缓存待就绪后识别`)
})

// ── 模型矩形（悬停命中 / 括号菜单中心 / 穿透判定共用） ──
const MODEL_FALLBACK = { left: 0, top: 0, width: 200, height: 200 }
function getModelRect(): { left: number; top: number; width: number; height: number } | null {
  return petComponent.value?.getModelRect?.() ?? null
}
function getFallbackRect(): { left: number; top: number; width: number; height: number } {
  return MODEL_FALLBACK
}
function hitModelContour(x:number,y:number,radius?:number):boolean {
  if (resultCharacterSwitching) return false
  return petComponent.value?.hitContour?.(x,y,radius) ?? false
}

// 聊天面板是否展开（供穿透 / 键盘焦点判断）
const chatOpen = computed(() => activePanel.value === 'chat')
// 括号菜单中心 = 模型中心（client 坐标）
const bracketCenter = computed(() => {
  const r = getModelRect()
  if (r) return { x: r.left + r.width / 2, y: r.top + r.height / 2 }
  return { x: window.innerWidth / 2, y: window.innerHeight / 2 }
})

// ── 悬停渐隐（Fade on Hover）偏好（跨窗口共享，含首次确认状态） ──
const {
  fadeEnabled,
  nearRange,
  showNotice,
  requestEnable,
  confirmNotice,
  cancelNotice,
} = useFadeOnHoverPref()

// ── 聊天坞外观（输入胶囊宽度 / 通透度 / 按钮显隐）│ 调试台「UI」页，即时生效 ──
// 变量绑到 .shell-root：tokens.css 里的 --chat-surface-solid 用它拼透明度，
// 而自定义属性是在"声明它的元素"上完成替换的，绑子元素不生效。
const {
  width: dockWidth,
  height:dockHeight,
  offsetX:dockX,offsetY:dockY,radius:dockRadius,fontSize:dockFontSize,
  alpha: dockAlpha,
  showMic,
  showSend,
} = useChatDockPref()
const dockVars = computed(() => chatDockCssVars(dockWidth.value, dockAlpha.value,dockHeight.value,dockX.value,dockY.value,dockRadius.value,dockFontSize.value))

// ── 悬停唤出括号菜单（BracketMenu 状态机） ──
// 注：渐隐开启期间（fadeEnabled）禁止呼出功能泡，作为免打扰
const { menuOpen, closeMenu } = useBracketMenu({ getModelRect, getFallbackRect, fadeEnabled, hitContour: hitModelContour })

// 面板或菜单展开时暂停渐隐；渐隐开启时可从系统托盘关闭，不保留常驻呼出点。
const uiOpen = computed(() => activePanel.value !== null || menuOpen.value)

// 渐隐按独立 Alpha 轮廓与靠近范围决定；窗口穿透由下面的单一决策者控制。
const { shouldFade } = useFadeOnHover(uiOpen, fadeEnabled, nearRange, getModelRect, hitModelContour)

const { syncForcedInteractive, forceInteractive, updateFromPointer } = useMousePassthrough({
  chatOpen,
  menuOpen,
  hitModel: hitModelContour,
  fadeActive: shouldFade,
})

// 模型拖动：命中 Alpha 轮廓后捕获拖动（主进程 setBounds 钉死尺寸，防膨胀）。
usePetDrag(getModelRect, hitModelContour,()=>{if(!resultCharacterSwitching)petComponent.value?.playClickFeedback?.()})

// ── WebSocket ──
let socket: WebSocket | null = null
// S02：control 通道断线重连定时器（带 session_id 重连 → 引擎进程内 resume）
let reconnectTimer = 0

// petComponent → petCanvas binding
watch(petComponent, (comp) => {
  if (comp?.canvasRef) {
    petCanvas.value = comp.canvasRef
  }
})

function classifyLevel(line: string): LogItem['level'] {
  // 关键词判级（my-neuro 风格）：错误/失败优先，其次成功，再次警告
  if (/错误|失败|error|断开|超时|拒绝|invalid|denied/i.test(line)) return 'error'
  if (/成功|完成|已连接|允许|ok|✓|已打开/i.test(line)) return 'success'
  if (/等待|请求|警告|重试|识别中|合成中|warn/i.test(line)) return 'warning'
  return 'info'
}

function log(line: string): void {
  logs.value.push({ id: logIdCounter++, text: line, level: classifyLevel(line), ts: Date.now() })
  if (logs.value.length > 200) logs.value.splice(0, logs.value.length - 200)
  // 同时转发到主进程终端（[render] 前缀），便于排查"语音自然关闭"等交互问题
  console.log('[render]', line)
}

const filteredLogs = computed(() =>
  logFilter.value === 'error' ? logs.value.filter((l) => l.level === 'error') : logs.value
)

function logTime(ts: number): string {
  const d = new Date(ts)
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

let offSpeechSettings:(()=>void)|null=null
let speechSettingsAlive=true
onMounted(() => {
  offSpeechSettings=watchSpeechSettings(()=>localStorage.getItem('yuiro-active-character')||'',()=>{void loadBargeIn();void loadReplyTts()})
  void connectControl()
  void loadModelPath()
  void loadSearchStatus()  // S51：联网开关可用性（未配置密钥时禁用 + 说明理由）
  void loadBargeIn()       // S03：插话打断开关（读引擎配置；与调试台是同一个开关）
  void loadReplyTts()      // 语音回复 TTS 统一开关（读引擎配置 [tts].reply_tts_enabled）
  window.addEventListener('keydown', onAvatarKeydown)
  document.addEventListener('pointerdown', onDocPointerDown)
  window.addEventListener('keydown', onDockMenuKeydown)
  // 窗口尺寸 / 模型缩放变化时，重新量一次模型矩形供说话云定位
  window.addEventListener('resize', refreshSpeechRect)
  // 调试台「外观」页 → 更换模型 / 试播动作 / 预览表情
  offShellEvent = window.yuiro?.on?.(onShellEvent) ?? null
  // S51：接收日记窗口转来的聊天输入 —— 用**桌宠自己的 session** 发出去，
  // 这样对话 history 连续、回复落在桌宠窗口（气泡 + 口型 + TTS）。
  // 标记"这一轮是日记转来的"→ 回复到达时回传给日记窗口当页边批注
  offRelayChat = window.yuiro?.onRelayChat?.((text) => {
    diaryRelayPending = true
    sendText(text)
  }) ?? null
})

// ── S23：Performance Gallery（Alt+G）──────────────────────────────────────
// spec：Performance Gallery 是"开发工具兼产品能力"——Demo + Debug + Asset Preview。
// 表演库与触发都在引擎侧（配置驱动），前端只做浏览与触发。
// S31 修正：debug router 的前缀是 /api（此前误写成 /debug，导致这些调用 404）。
const ENGINE_API = 'http://127.0.0.1:8200/api'

/* ── 桌宠模型：以引擎配置 persona.model_path 为唯一真相源 ──────────────────
 * 此前 Live2DCanvas 把模型路径写成了常量，导致调试台改 model_path 毫无作用。
 * 现在由这里读取配置并下发给 Live2DCanvas，调试台也就真正能换模型了。 */
const modelPath = ref('')
const activeCharacter = ref('')
const characterRevision = ref(0)
let modelConfigRequest = 0

/**
 * 模型路径就绪标志（拿不到也置 true，只是回退到内置默认模型）。
 *
 * 用它门控 Live2DCanvas 的挂载时机，是为了让**首次加载**就直接用配置里的模型：
 * 首次加载会触发「窗口贴合模型」并由此定格窗口尺寸；若先按默认模型贴合、
 * 随后再切换，窗口尺寸就已固定，切换只在原窗口内缩放（这正是我们要的
 * "在原位置上变化"，而不是被新模型的原始尺寸撑大）。
 */
const modelReady = ref(false)

async function loadModelPath(): Promise<void> {
  const request = ++modelConfigRequest
  try {
    // 加超时：引擎没起时不要拖住桌宠的首屏渲染
    const res = await fetch(`${ENGINE_API}/config`, { signal: AbortSignal.timeout(1500) })
    if (res.ok) {
      const data = await res.json()
      if (request !== modelConfigRequest) return
      const role = String(data?.character?.active_id ?? '')
      if (activeCharacter.value && role !== activeCharacter.value) {
        clearResultCard()
        hideSpeech()
        stopPlayback()
        // 旧身份在 1012 关闭时清理；此时 session:ready 可能已经下发新身份，不能再抹掉。
        sessionItems.value = []
        sentMsg.value = null
        taskPlan.value = null
        clearActivity()
      }
      activeCharacter.value = role
      uiAppearance.setCharacter(role)
      characterRevision.value = Number(data?.character?.revision ?? 0)
      if (role) localStorage.setItem('yuiro-active-character', role)
      const p = data?.sections?.persona?.model_path
      if (typeof p === 'string' && p.trim()) modelPath.value = p.trim()
    }
  } catch {
    // 引擎未就绪 → 交给 Live2DCanvas 用内置默认模型，不阻断启动
  } finally {
    modelReady.value = true
  }
}

/** 调试台 → 桌宠窗口的界面指令（更换模型 / 试播动作 / 预览表情 / 试演表演）。 */
function onShellEvent(e: ShellEvent): void {
  if ((e.type === 'avatar:model' || e.type === 'avatar:motion'
    || e.type === 'avatar:expression' || e.type === 'avatar:perform')
    && e.characterId && e.characterId !== activeCharacter.value) return
  if ((e.type === 'avatar:motion' || e.type === 'avatar:expression')
    && e.modelPath && e.modelPath !== modelPath.value) return
  if (e.type === 'avatar:model') {
    modelPath.value = e.path
    log(`[avatar] 更换模型: ${e.path}`)
  } else if (e.type === 'avatar:motion') {
    petComponent.value?.playMotion?.(e.group, e.index)
  } else if (e.type === 'avatar:expression') {
    petComponent.value?.playExpression?.(e.name)
  } else if (e.type === 'avatar:perform') {
    if ((e.characterId && e.characterId !== activeCharacter.value)
      || (e.modelPath && e.modelPath !== modelPath.value)) return
    // S49：调试台「试演」直连通道。与引擎的 avatar:intent 走同一个应用入口，
    // 因此表现逻辑只有一份；区别只是它不需要引擎在线。
    petComponent.value?.applyAvatarIntent?.({
      expression: e.expression,
      motion: e.motion,
      motion_index: e.motionIndex ?? null,
      duration_ms: e.durationMs,
    })
    const idx = e.motionIndex === undefined || e.motionIndex === null ? '' : `#${e.motionIndex}`
    log(`[avatar] 试演 ${e.name ?? ''} → 表情 ${e.expression || '(默认)'} / 动作 ${e.motion ? e.motion + idx : '(无)'}`)
  }
}

let offShellEvent: (() => void) | null = null
const galleryOpen = ref(false)
const performances = ref<
  Array<{ name: string; note?: string; expression?: string; motion?: string }>
>([])

/** 拉取表演库（GET /debug/avatar/performances）。 */
async function loadPerformances(): Promise<void> {
  try {
    const res = await fetch(`${ENGINE_API}/avatar/performances`)
    const data = await res.json()
    performances.value = Array.isArray(data.performances) ? data.performances : []
    log(`[gallery] 表演库: ${performances.value.length} 个`)
  } catch (e) {
    log(`[gallery] 加载失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

/** 现场触发一次表演（POST /debug/avatar/perform/{name}）。 */
async function runPerformance(name: string): Promise<void> {
  try {
    const res = await fetch(
      `${ENGINE_API}/avatar/perform/${encodeURIComponent(name)}`,
      { method: 'POST' }
    )
    const data = await res.json()
    log(`[gallery] 表演 ${name}: ${String(data.status ?? 'ok')}`)
  } catch (e) {
    log(`[gallery] 触发失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

/** Alt+G：开关 Gallery（打开时刷新列表）。 */
async function toggleGallery(): Promise<void> {
  galleryOpen.value = !galleryOpen.value
  if (galleryOpen.value) await loadPerformances()
}

// ── S43：会话列表（"选择加载页"）───────────────────────────────────────────
// 此前前端只握着自己那一个 session_id：看不到有哪些会话、也无法切换 ——
// 引擎重启或本地 id 丢失后只能新建，用户侧表现为"上下文全丢"且毫无提示。
// 现在给一个列表：可切到历史会话（引擎会进程内 resume 或从事件日志 revive），
// 也可主动开新会话。
const sessionsOpen = ref(false)
const sessionItems = ref<Array<{
  session_id: string
  state: string
  live: boolean
  last_active_at: number
  has_log: boolean
}>>([])

/** 拉取会话一览（GET /api/sessions：内存中的 + 磁盘上有事件日志的）。 */
async function loadSessions(): Promise<void> {
  try {
    const res = await fetch(`${ENGINE_API}/sessions`)
    const data = await res.json()
    sessionItems.value = Array.isArray(data.sessions) ? data.sessions : []
    log(`[session] 会话列表: ${sessionItems.value.length} 个`)
  } catch (e) {
    log(`[session] 列表加载失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

/** 会话时间显示：今天只给时分，更早给月-日。 */
function sessionTime(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const sameDay = d.toDateString() === new Date().toDateString()
  const p = (n: number): string => String(n).padStart(2, '0')
  return sameDay ? `${p(d.getHours())}:${p(d.getMinutes())}` : `${d.getMonth() + 1}-${p(d.getDate())}`
}

/**
 * 切到指定会话：换 id → 关掉当前连接（触发自动重连，重连时带上新 id）。
 * 本地气泡清掉 —— 否则上一个会话的内容会和新会话混在一起显示。
 */
function switchSession(id: string): void {
  if (!id) return
  sessionId.value = id
  try { window.localStorage.setItem(SESSION_KEY, id) } catch { /* 隐私模式等忽略 */ }
  sentMsg.value = null
  sessionItems.value = []
  sessionsOpen.value = false
  log(`[session] 切换到 ${id.slice(0, 8)}（引擎 resume 或从事件日志复活）`)
  try { socket?.close() } catch { /* ignore */ }
}

/** 开新会话：清掉本地 id，重连时由引擎分配新的。 */
function newSession(): void {
  sessionId.value = ''
  try { window.localStorage.removeItem(SESSION_KEY) } catch { /* ignore */ }
  sentMsg.value = null
  sessionItems.value = []
  sessionsOpen.value = false
  log('[session] 新会话')
  try { socket?.close() } catch { /* ignore */ }
}

/** Alt+S：开关会话列表（打开时拉最新）。 */
async function toggleSessions(): Promise<void> {
  sessionsOpen.value = !sessionsOpen.value
  if (sessionsOpen.value) await loadSessions()
}

// ── S29：计划审批（plan approval）────────────────────────────────────────
// 大动作前它先给计划，用户点确认后才执行（对应的引擎 API：/debug/task/{id}/approve|reject）
const taskPlan = ref<{ taskId: string; goal: string; steps: string[] } | null>(null)

/** 批准 / 拒绝当前待确认的计划。 */
async function resolvePlan(approved: boolean): Promise<void> {
  const plan = taskPlan.value
  if (!plan) return
  try {
    const action = approved ? 'approve' : 'reject'
    const res = await fetch(
      `${ENGINE_API}/task/${encodeURIComponent(plan.taskId)}/${action}`,
      { method: 'POST' }
    )
    const data = await res.json()
    log(`[plan] ${approved ? '已批准' : '已拒绝'}: ${String(data.status ?? '')}`)
  } catch (e) {
    log(`[plan] 操作失败: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    taskPlan.value = null
  }
}

/** S05：Alt+E 逐个预览模型表情（确认语义后回填 config.toml [persona.expression_map]）。 */
function onAvatarKeydown(e: KeyboardEvent): void {
  const key = e.key.toLowerCase()
  if (!e.altKey) return
  if (key === 'e') {
    e.preventDefault()
    const name = petComponent.value?.cycleExpressionPreview?.()
    if (name) {
      log(`[avatar] 预览表情: ${name}（Alt+E 循环；确认语义后调整 config.toml expression_map）`)
    }
  } else if (key === 'm') {
    e.preventDefault()
    const name = petComponent.value?.cycleMotionPreview?.()
    if (name) {
      log(`[avatar] 预览动作: ${name}（Alt+M 循环；确认语义后可配置 [persona].motion_map）`)
    }
  } else if (key === 'g') {
    // S23：Performance Gallery（浏览表演库并现场触发）
    e.preventDefault()
    void toggleGallery()
  } else if (key === 's') {
    // S43：会话列表（选择加载页）
    e.preventDefault()
    void toggleSessions()
  }
}

/**
 * S02：建立 / 重建 control 连接。
 * - 首次连接：引擎回发 session:ready 下发会话身份；
 * - 断线重连：带上已知 session_id → 引擎进程内 resume（history 不丢）。
 */
async function connectControl(): Promise<void> {
  const base = await engineWsUrl(ENGINE_WS)
  const url = sessionId.value
    ? `${base}${base.includes('?') ? '&' : '?'}session=${encodeURIComponent(sessionId.value)}`
    : base
  socket = new WebSocket(url)
  const connectionSocket = socket
  socket.onopen = () => {
    if (connectionSocket !== socket) return
    void loadModelPath()
    connClass.value = 'ok'
    connSymbol.value = '●'
    log('[ws] 已连接引擎')
    // S51 修正：引擎**确定在线**之后再查一次联网可用性。
    // 此前只在 onMounted 查一次 —— 若那一刻引擎还没起来（桌宠窗口通常先于
    // 引擎就绪），fetch 失败就落到 catch，`webSearchHint` 被钉死成"引擎未连接"
    // 且**再也不重试**：用户看到的是"点了没反应 + 日志说引擎未连接"，而引擎
    // 其实一直在跑（实测反馈）。这里随每次连接（含断线重连）刷新。
    void loadSearchStatus()
    void loadBargeIn()   // 同理：引擎确定在线后再读打断开关，别把界面钉在默认值上
    void loadReplyTts()  // 同理：语音回复 TTS 开关也随重连刷新
  }
  socket.onclose = (event) => {
    if (connectionSocket !== socket) return
    presenceEvent('control:closed')
    officialPending.value=false
    mediaRequestId++
    if (event.code === 1012) {
      resultCharacterSwitching = true
      clearResultCard()
      hideSpeech()
      modelConfigRequest++
      stopPlayback()
      void stop()
      isRecording.value = false
      sessionId.value = ''
      try { localStorage.removeItem(SESSION_KEY) } catch { /* ignore */ }
    }
    connClass.value = 'off'; connSymbol.value = '○'; log('[ws] 连接断开')
    scheduleReconnect(event.code === 1012 ? 100 : event.code === 1013 ? 250 : 3000)
  }
  socket.onerror = () => { if (connectionSocket !== socket) return; connClass.value = 'err'; connSymbol.value = '!'; log('[ws] 连接错误') }
  socket.onmessage = (ev) => {
    if (connectionSocket !== socket) return
    try {
      const msg = JSON.parse(ev.data as string)
      if (msg.type === 'character:switching') {
        agentReactions.reset()
        presenceEvent('avatar:reset')
        resultCharacterSwitching = true
        clearResultCard()
        hideSpeech()
        stopPlayback()
        void stop()
        isRecording.value = false
        clearActivity()
      } else if (msg.type === 'character:changed') {
        void loadModelPath()
      } else if (msg.type === 'session:ready') {
        resultCharacterSwitching = false
        // S02：引擎下发会话身份 —— 供 audio 通道绑定同一 AgentSession
        sessionId.value = String(msg.session_id ?? '')
        avatarGeneration.value=Number(msg.generation)||0
        // S43：写回本地 —— 刷新 / 热重载后仍带同一个 id 连上来（否则每次都是新会话）
        try { window.localStorage.setItem(SESSION_KEY, sessionId.value) } catch { /* 隐私模式等忽略 */ }
        log(`[ws] 会话已就绪: ${sessionId.value.slice(0, 8)}（gen=${msg.generation ?? 0}）`)
      } else if (msg.type === 'chat:assistant') {
        presenceEvent('chat:assistant')
        // 回复走漫画说话云框（只显示当前一条，不堆叠）
        // S39：回复到了 → 收起活动状态行（它只是"进行中"提示）
        clearActivity()
        // S53：这一轮是日记转来的 → 回传给日记窗口（页边批注）
        if (diaryRelayPending) {
          diaryRelayPending = false
          void window.yuiro?.relayDiaryReply?.(String(msg.text ?? ''))
        }
        // 语音回复 TTS 开关开启 → 这轮文字回复也会出声：气泡等到播完再收
        if (replyTtsEnabled.value) {
          beginReplyPlayback()
          speechTtsActive = true  // 音频即将到来，别让宽限期误判成"没语音"
          showSpeech(String(msg.text ?? ''), true)
        } else {
          showSpeech(String(msg.text ?? ''))
        }
      } else if (msg.type === 'tts:reply_audio') {
        if(!acceptsReplySpeech(msg,sessionId.value,avatarGeneration.value))return
        avatarGeneration.value=msg.generation
        // 文字回复的合成音频段 → 入队播放（复用语音链路的播放队列 + 口型）
        speechTtsActive = true
        enqueueReplyAudio(msg)
      } else if (msg.type === 'tts:reply_end') {
        if(!acceptsReplySpeech(msg,sessionId.value,avatarGeneration.value))return
        avatarGeneration.value=msg.generation
        // 文字回复音频全部下发完；若本轮根本没出过声（合成失败/开关中途关），
        // 退回按字数估算收起气泡（宽限期因 speechTtsActive=true 已失效，需手动兜底）。
        const hadAudio = endReplyAudio()
        if (!hadAudio) {
          log('[speech] 本轮文字回复无音频，气泡退回按字数估算')
          speechHeldForPlayback = false
          scheduleSpeechEstimateHide(speechText.value)
        }
      } else if (msg.type === 'emotion:set') {
        // M5：主情绪变化（语义事件；表情由 S05 的 avatar:intent 通道驱动）
        const emotion = String(msg.emotion ?? '')
        currentEmotion.value = emotion
        log(`[emotion] 当前心情: ${emotion}`)
      } else if (msg.type === 'avatar:intent') {
        if (resultCharacterSwitching || (msg.session_id && msg.session_id !== sessionId.value)) return
        if(msg.session_id&&Number.isInteger(msg.generation)){
          if(msg.generation<avatarGeneration.value)return
          avatarGeneration.value=msg.generation
        }
        // S05：头像意图（表情通道）→ Live2D 应用
        if (msg.emotion) currentEmotion.value = String(msg.emotion)
        petComponent.value?.applyAvatarIntent?.(msg)
        log(`[avatar] 表情: ${String(msg.emotion ?? '')} → ${String(msg.expression || '(默认)')}`)
      } else if (msg.type === 'agent:activity') {
        const frame=msg as AgentActivityFrame
        if(resultCharacterSwitching||frame.session_id!==sessionId.value
          ||frame.character_id!==activeCharacter.value||frame.character_revision!==characterRevision.value
          ||!Number.isInteger(frame.generation)||frame.generation<avatarGeneration.value)return
        avatarGeneration.value=frame.generation
        // S39：它正在干活（工具级反馈）→ 状态行；并按工具类型做**节流**的动作联动。
        // 节流很关键：读 10 个文件不该手舞足蹈 10 次（6 秒内最多一个动作）。
        const prog = String(msg.progress ?? '')
        const act = String(msg.text ?? '')
        showActivity(prog ? `${prog}｜${act}` : act)
        // S53：优先用引擎按档案解析好的具体动作；没解析出来就只给语义槽位，
        // 由渲染层按当前模型清单推断（不再假设 TapBody / 写死数值索引）。
        const reaction=agentReactions.plan(frame,Date.now(),agentReactionPref.agentCooldownMs.value)
        if(reaction)petComponent.value?.playAgentReaction?.(reaction)
      } else if (msg.type === 'media:search-result') {
        const r=msg as ClientSearchReply
        if(resultCharacterSwitching||r.character_id!==activeCharacter.value||r.character_revision!==characterRevision.value||r.session_id!==sessionId.value||r.request_id!==clientSearchRequestId)return
        if(r.status==='ok'){
          resultCard.value={title:r.items.some(it=>it.source==='netease_client_daily')?'客户端日推 · 随机候选':`客户端搜索：${r.keyword}`,kind:'song',items:r.items as ResultCardItem[],note:''};scheduleResultHide()
          showSpeech(`在网易云客户端找到了 ${r.items.length} 首候选，请选择歌曲。`)
        }else showSpeech(r.note||'客户端搜索未完成，未使用其他服务回退。')
      } else if (msg.type === 'media:state') {
        if(resultCharacterSwitching||msg.character_id!==activeCharacter.value||msg.character_revision!==characterRevision.value
          ||msg.session_id!==sessionId.value||msg.request_id!==mediaRequestId)return
        officialPending.value=false
        officialPlayback.value=msg.state??null
        if(msg.note)showSpeech(String(msg.note))
      } else if (msg.type === 'agent:result') {
        if (resultCharacterSwitching || (msg.session_id && msg.session_id !== sessionId.value)) return
        if ((msg.kind === 'source'||msg.character_id) && (msg.character_id !== activeCharacter.value
          || msg.character_revision !== characterRevision.value)) return
        // G7：结构化结果卡（歌单/歌曲列表）—— 让"推荐歌单"这类操作在屏幕上可见，
        // 而不是只在语音里说一句"已经推荐了"。
        const items = Array.isArray(msg.items) ? msg.items : []
        if (items.length) {
          // 卡片锚定模型左侧：先刷新模型矩形，避免用上一次的旧位置定位
          refreshSpeechRect()
          const card = {
            title: String(msg.title ?? '结果'),
            kind: String(msg.kind ?? ''),
            items: items as ResultCardItem[],
            note: String(msg.note ?? ''),
          }
          if(card.kind==='source'){sourceCard.value=card;scheduleSourceHide()}
          else {resultCard.value=card;scheduleResultHide()}
          log(`[result] ${card.title}（${items.length} 项）`)
        }
      } else if (msg.type === 'task:planned') {
        // S29：它提交了计划，等你确认（批准前它不会动手）
        const steps = Array.isArray(msg.steps) ? msg.steps.map((s: unknown) => String(s)) : []
        taskPlan.value = {
          taskId: String(msg.task_id ?? ''),
          goal: String(msg.goal ?? ''),
          steps,
        }
        log(`[plan] 待确认计划: ${taskPlan.value.goal}（${steps.length} 步）`)
      } else if (msg.type === 'proactive:intent') {
        // S20：Presence 的主动表达（已经过注意力策略裁决；低打扰优先气泡）
        const ptext = String(msg.text ?? '')
        const pchannel = String(msg.channel ?? 'bubble')
        // S53：走语音通道的主动表达同样"等播完再收"；纯气泡则按字数估算
        if (ptext) showSpeech(ptext, pchannel === 'voice')
        log(`[presence] ${String(msg.urgency ?? 'low')}/${pchannel}: ${ptext}`)
      } else if (msg.type === 'proactive:greet') {
        // M5：主动互动打招呼 → 同样走说话云框
        const greetText = String(msg.message ?? '在忙吗？需要我陪你聊聊天吗？')
        showSpeech(greetText)
        log(`[proactive] 主动打招呼: ${greetText}`)
      } else if (msg.type === 'approval:required') {        // 系统操作审批：原生对话框 → 回传裁决。
        // try/finally：即使 requestApproval 异常（对话框错误）也回传 resolve（默认拒绝），
        // 绝不让引擎审批永久超时。
        const requestId = String(msg.request_id ?? '')
        const toolName = String(msg.tool ?? '')
        log(`[approval] 等待审批: ${toolName}（${String(msg.summary ?? '')}）`)
        void (async () => {
          let approved = false
          try {
            const res = await window.yuiro?.requestApproval({
              approvalRequestId: requestId,
              tool: toolName,
              summary: String(msg.summary ?? ''),
            })
            approved = res?.approved ?? false
            log(`[approval] ${toolName} → ${approved ? '允许' : '拒绝'}`)
          } catch (err) {
            log(`[approval] 对话框异常，按拒绝处理: ${err instanceof Error ? err.message : String(err)}`)
          } finally {
            if (socket && socket.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({
                type: 'approval:resolve',
                request_id: requestId,
                approved,
              }))
              log(`[approval] 已回传 resolve: ${requestId.slice(0, 8)} approved=${approved}`)
            } else {
              log('[approval] 连接已断开，无法回传 resolve')
            }
          }
        })()
      }
    } catch { /* ignore */ }
  }
}

/** 计划内角色切换快速重连；普通网络故障仍保留 3s 退避。 */
function scheduleReconnect(delayMs = 3000): void {
  if (reconnectTimer) return
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = 0
    void connectControl()
  }, delayMs)
}

onBeforeUnmount(() => {
  speechSettingsAlive=false;offSpeechSettings?.();offSpeechSettings=null
  window.clearTimeout(presenceTimer)
  window.removeEventListener('keydown', onAvatarKeydown)
  document.removeEventListener('pointerdown', onDocPointerDown)
  window.removeEventListener('keydown', onDockMenuKeydown)
  window.removeEventListener('resize', refreshSpeechRect)
  offShellEvent?.()
  offShellEvent = null
  offRelayChat?.()
  offRelayChat = null
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = 0 }
  if (speechTimer) { clearTimeout(speechTimer); speechTimer = 0 }
  if (speechGraceTimer) { clearTimeout(speechGraceTimer); speechGraceTimer = 0 }
  if (sentTimer) { clearTimeout(sentTimer); sentTimer = 0 }
  socket?.close()
  if (micRaf) cancelAnimationFrame(micRaf)
  disposeVoice()
  window.yuiro?.setFocusable(false)
})

// ── 括号菜单动作 → 面板切换 / 快捷操作 ──
function onBracketAction(id: string): void {
  switch (id) {
    case 'chat':
      toggle('chat')
      break
    case 'voice':
      void toggleVoice()
      break
    case 'diary':
      // S51：日记走**独立窗口**（与对话物理分离 —— 日记输入不走 AgentLoop）
      window.yuiro?.openDiary()
      break
    case 'settings':
      openDev('settings')
      break
    case 'theme':
      toggleTheme()
      break
  }
}

// ── 面板切换 ──
function toggle(panel: 'chat'): void {
  activePanel.value = activePanel.value === panel ? null : panel
  syncForcedInteractive()
  closeMenu()
  if (panel === 'chat' && activePanel.value === 'chat') {
    nextTick(focusChatInput)
  }
}

// ── 开发者调试窗口 ──
function openDev(section: 'settings' | 'logs' | 'status'): void {
  window.yuiro?.openDev(section)
}

// ── 消息 ──
function sendText(text: string): void {
  const t = text.trim()
  if (!t) return
  clearSourceCard()
  const music=/^\/(?:搜歌|music)\s+(.+)$/i.exec(t)
  const daily=/^\/(?:推荐|日推|recommend)$/i.test(t)
  if(music||daily){
    if(!socket||socket.readyState!==WebSocket.OPEN){showSpeech('引擎未连接');return}
    const payload:ClientSearchRequest={type:'media:search',backend:'netease_client',keyword:daily?'每日推荐':music![1].trim(),daily,request_id:++clientSearchRequestId,character_id:activeCharacter.value,character_revision:characterRevision.value,session_id:sessionId.value}
    socket.send(JSON.stringify(payload));showSpeech('正在网易云客户端内搜索…');return
  }
  // ★ S03 补口：**新请求更替旧回合**（改口）。
  //   语音链路的"插话打断"由引擎 VAD 负责（见 audio._spawn_speech_end）；
  //   而文字链路此前**完全没有取消** —— 她正在念一段错话时你打字纠正，旧回复会
  //   继续念完、新消息只能干等（S03 里明确列为遗留项："chat 队列保持串行"）。
  //   这里显式打断，让新一轮真正接替。
  if (turnBusy.value) {
    log('[voice] 发送新消息 → 打断当前回合（改口）')
    sendInterrupt()
  }
  // 文字回复音频正在播时发新消息 → 本地立即停播（改口；引擎侧新回合会取消旧朗读任务）
  stopPlayback()
  showSent(t)
  if (socket && socket.readyState === WebSocket.OPEN) {
    // S51：带上联网开关意图 —— 引擎据此**只在这一轮**注入 web_search 工具
    // （关闭时工具不放进 schema，模型看不到它，自然不会去调）。
    advanceAvatarGeneration()
    presenceEvent('chat:sent')
    socket.send(JSON.stringify({ type: 'chat:user', text: t, web_search: webSearchOn.value }))
    log(`[chat] 发送: ${t}`)
  } else {
    showSpeech('(引擎未连接)')
  }
}

function send(): void {
  const text = input.value.trim()
  if (!text) return
  sendText(text)
  input.value = ''
}

// ── S51：联网检索开关（聊天坞，发送键左侧）────────────────────────────────
// ★ 默认值**跟随引擎侧总开关**，而不是常量 false。
//
// 为什么必须这样（实测踩过的坑）：调试台的「总开关」与这里的地球按钮**是两个开关**。
// 用户开启了总开关（enabled=true、key 已配、工具已注册），但这里默认 false →
// 每轮都带 `web_search:false` → 引擎把 `web_search` 从工具表里**过滤掉** →
// 模型看不到它、直接回答"我又不是气象站"（日志特征：轮数=1/3，没有工具轮）。
// 两个开关却不给提示，用户永远查不到原因。
//
// 规则：**用户没显式选过 → 跟随引擎**；显式点过按钮 → 尊重他的选择（localStorage）。
const SEARCH_KEY = 'yuiro.web_search'
let searchChoiceSaved: string | null = null
try { searchChoiceSaved = window.localStorage.getItem(SEARCH_KEY) } catch { searchChoiceSaved = null }
const webSearchOn = ref(searchChoiceSaved === '1')
const webSearchAvailable = ref(false)
const webSearchHint = ref('')

// ── S03：插话打断开关（聊天坞，联网开关左侧）─────────────────────────────
// 与联网开关的**关键差别**：那个是"会话级意图"（每轮随消息携带、记在 localStorage），
// 而这个的**权威在引擎配置**（`vad.barge_in_enabled`）—— 所以这里直接**读写配置**，
// 不自己存 localStorage。这样聊天坞与调试台「语音活动检测」卡片就是**同一个开关**，
// 不会出现"两处状态不一致、用户不知道该信哪个"。
// 状态来自 `useVoiceInput` 的 `bargeInEnabled`（引擎配置的前端镜像，单一真相源）；
// 这里只留一个"正在切换"的忙碌标记。
const bargeInBusy = ref(false)

/** 读引擎侧的真实状态（单一真相源）。 */
async function loadBargeIn(): Promise<void> { await loadVoiceBargeIn() }

async function toggleBargeIn(): Promise<void> {
  if (bargeInBusy.value) return
  const role=activeCharacter.value,revision=characterRevision.value
  const current=()=>role===activeCharacter.value&&revision===characterRevision.value
  const next = !bargeInEnabled.value
  bargeInBusy.value = true
  try {
    const secret=await window.yuiro?.getEngineSecret?.()||''
    if(!current())return
    const res = await fetch(`${ENGINE_API}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json','x-yuiro-secret':secret,'x-yuiro-character':role },
      body: JSON.stringify({ patch: { vad: { barge_in_enabled: next } },character_id:role,character_revision:revision }),
    })
    if(!current())return
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    bargeInEnabled.value = next
    notifySpeechSettings(role)
    // 这个开关的语义**不直观**（关 ≠ 不能用），所以两态都明说会发生什么，
    // 免得用户以为"关掉之后我说的话她就不听了"。
    showSpeech(
      next
        ? '插话打断已开启：你一开口，她会立刻停下让位'
        : '插话打断已关闭：她说话期间自动闭麦（不收音、不排队），等她说完你再讲',
    )
    log(`[voice] 插话打断：${next ? '开' : '关'}`)
  } catch (e) {
    if(!current())return
    // 失败必须说出来（不能静默），并回读真实状态避免界面与引擎不一致
    const why = e instanceof Error ? e.message : String(e)
    showSpeech(`切换打断开关失败：${why}`)
    log(`[voice] 切换打断开关失败：${why}`)
    void loadBargeIn()
  } finally {
    bargeInBusy.value = false
  }
}

// ── 语音回复 TTS 统一开关（聊天坞下拉菜单第二项）──────────────────────────
// 权威同样在引擎配置（`[tts].reply_tts_enabled`，默认开）。与打断开关共用同一个
// 下拉菜单；读写/失败回读模式与 toggleBargeIn 完全一致。
const replyTtsEnabled = ref(true)
const replyTtsBusy = ref(false)

// 聊天坞「打断 / 语音回复」下拉菜单的开关状态
const dockMenuOpen = ref(false)

function toggleDockMenu(): void {
  dockMenuOpen.value = !dockMenuOpen.value
}

function closeDockMenu(): void {
  dockMenuOpen.value = false
}

/** 点击菜单外部（或 Esc）时收起下拉菜单。 */
function onDocPointerDown(e: PointerEvent): void {
  const target = e.target as HTMLElement | null
  if (target?.closest('.dock-menu')) return
  closeDockMenu()
}

function onDockMenuKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') closeDockMenu()
}

/** 读引擎侧真实状态（单一真相源）。 */
let replySettingsRead=0
async function loadReplyTts(): Promise<void> {
  const request=++replySettingsRead,role=localStorage.getItem('yuiro-active-character')||'hiyori'
  try {
    const secret=await window.yuiro?.getEngineSecret?.()||''
    const res = await fetch(`${ENGINE_API}/config`,{headers:{'x-yuiro-secret':secret,'x-yuiro-character':role}})
    if(!res.ok)return
    const data = await res.json()
    const sec = (data?.sections ?? {}) as Record<string, { reply_tts_enabled?: boolean }>
    const v = sec.tts?.reply_tts_enabled
    if (speechSettingsAlive&&request===replySettingsRead&&role===(localStorage.getItem('yuiro-active-character')||'hiyori')&&typeof v === 'boolean') replyTtsEnabled.value = v
  } catch {
    /* 引擎未起：保持原状 */
  }
}

async function toggleReplyTts(): Promise<void> {
  if (replyTtsBusy.value) return
  const role=activeCharacter.value,revision=characterRevision.value
  const current=()=>role===activeCharacter.value&&revision===characterRevision.value
  const next = !replyTtsEnabled.value
  replyTtsBusy.value = true
  try {
    const secret=await window.yuiro?.getEngineSecret?.()||''
    if(!current())return
    const res = await fetch(`${ENGINE_API}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json','x-yuiro-secret':secret,'x-yuiro-character':role },
      body: JSON.stringify({ patch: { tts: { reply_tts_enabled: next } },
        character_id:role, character_revision:revision }),
    })
    if(!current())return
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    replyTtsEnabled.value = next
    notifySpeechSettings(role)
    showSpeech(
      next
        ? '语音回复已开启：语音和文字输入，她都会开口说'
        : '语音回复已关闭：她只回文字，不再出声',
    )
    log(`[voice] 语音回复 TTS：${next ? '开' : '关'}`)
  } catch (e) {
    if(!current())return
    const why = e instanceof Error ? e.message : String(e)
    showSpeech(`切换语音回复开关失败：${why}`)
    log(`[voice] 切换语音回复开关失败：${why}`)
    void loadReplyTts()
  } finally {
    replyTtsBusy.value = false
  }
}

function toggleWebSearch(): void {
  if (!webSearchAvailable.value) {
    // ★ 不可用时**绝不静默**：直接告诉用户为什么点不动、以及怎么开通。
    // （此前是 disabled —— 点击零反馈，用户只能靠 hover 猜，体验等同"坏了"。）
    showSpeech(webSearchHint.value || '联网检索未启用：请先在调试台「运行环境」配置搜索服务')
    log(`[search] 联网检索不可用：${webSearchHint.value || '未配置'}`)
    return
  }
  webSearchOn.value = !webSearchOn.value
  try { window.localStorage.setItem(SEARCH_KEY, webSearchOn.value ? '1' : '0') } catch { /* 隐私模式忽略 */ }
}

/**
 * 查询引擎侧可用性 —— 未配置密钥时**禁用并给出理由**。
 * 「开了却没反应」比「禁用 + 说明」糟糕得多（设计文档 §9.6）。
 */
async function loadSearchStatus(): Promise<void> {
  try {
    const res = await fetch(`${ENGINE_API}/search/status`)
    const data = await res.json()
    webSearchAvailable.value = Boolean(data?.available)
    webSearchHint.value = String(data?.hint ?? '')
    if (!webSearchAvailable.value) {
      webSearchOn.value = false
    } else if (searchChoiceSaved === null) {
      // 引擎侧已就绪且用户从未显式选过 → 默认开启（跟随引擎总开关）。
      // 隐私提示仍在：按钮本身就是可见的开关，用户随时可关（并会被记住）。
      webSearchOn.value = true
    }
  } catch (e) {
    webSearchAvailable.value = false
    // ⚠ 不要把一切都归咎于"引擎未连接"：CSP 拦截、端口不符、引擎未启动都会走到这里。
    // 实测教训：index.html 的 CSP 漏了 http://127.0.0.1:* → fetch 被拦 → 这里一律
    // 显示"引擎未连接"，而引擎其实健康（误导排查方向）。改成如实报出真实原因。
    const why = e instanceof Error ? e.message : String(e)
    webSearchHint.value = `查不到联网状态（${why}）`
    log(`[search] /search/status 请求失败：${why}`)
  }
}

/** 发一条原始消息（聊天/媒体共用；连接断开时给明确提示）。 */
function sendRaw(payload: Record<string, unknown>): void {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload))
  } else {
    showSpeech('(引擎未连接)')
  }
}

/**
 * S51：接收日记窗口转来的聊天输入（用户要求：日记里每段都让她接话）。
 *
 * 日记窗口不能自己发 `chat:user`（引擎的 chat:assistant 只回发起连接，
 * 且 control 连接按 session 存单个）——所以经主进程转到这里，用**桌宠自己的
 * session** 发送：对话 history 连续、回复显示在桌宠窗口（气泡 + 口型 + TTS）。
 */
let offRelayChat: (() => void) | null = null
/** 这一轮回复是否由日记窗口转发引发（用于回传页边批注） */
let diaryRelayPending = false

/**
 * S41：点结果卡里的条目 = 替用户说一句话。
 * 歌单卡 → 「播放歌单『X』」（引擎按名字 + 语义匹配）；歌曲卡 → 「播放《X》」。
 * 这样"列出来供我下一轮选择"就不必非得用嘴说，点一下即可。
 */
function pickResultItem(it: ResultCardItem, mode:'pick'|'open_official'|'client_play'='pick'): void {
  const card = resultCard.value
  if (!card) return
  if(mode==='open_official'){
    const id=String(it.song_id??'')
    if(/^\d+$/.test(id))void window.yuiro?.openExternal(`https://music.163.com/#/song?id=${id}`)
    return // 打开页面不等于已在客户端起播，不换播放器、不清除原版候选。
  }

  // S51：来源卡 —— 点击 = 用系统浏览器打开（核验来源），而不是"播放"。
  // 这一步是联网检索产品价值的一半：没有它，用户无法自查答案的依据。
  if (card.kind === 'source') {
    const url = String(it.url ?? '').trim()
    if (url) {
      void window.yuiro?.openExternal?.(url)
      log(`[search] 打开来源：${url}`)
    }
    resultCard.value = null
    if (resultTimer) clearTimeout(resultTimer)
    return
  }
  // 前端点选统一使用官方客户端；旧取流/mpv 实现留在后端兼容路径。
  if(mode==='pick'){
    if(card.kind==='playlist'){showSpeech('请在网易云客户端打开歌单；当前仅支持明确歌曲 ID 的直达播放。');return}
    mode='client_play'
  }
  if(officialPending.value)return
  if(mode==='client_play'){
    const id=String(it.song_id??'')
    if(!/^[1-9]\d{0,19}$/.test(id)||card.kind==='playlist')return
    if(resultTimer){clearTimeout(resultTimer);resultTimer=0}
    stopPlayback()
    sendOfficial({type:'media:play',kind:'song',song_id:id,name:it.name})
    return
  }

  if (!it.name) return
  if(it.availability==='api_unavailable'||it.availability==='api_preview'){
    showSpeech(it.availability_note || '当前 API 通道未取得完整播放地址，未播放、未替换版本。可打开官方歌曲页。')
    return
  }
  resultCard.value = null
  if (resultTimer) clearTimeout(resultTimer)

  /**
   * S45：**结构化直连**，不再"转成自然语言让模型重新搜"。
   *
   * 原实现只发一句「播放《X》」—— 引擎收到后**只能重新搜索**，而搜索是模糊匹配，
   * 于是"点的这首、放的另一首"（实测：点《LIFE》放成了 Life-Tobu）。
   *
   * 用户点一个具体条目是**确定意图**：ID 就在手里，没有任何需要模型判断的东西。
   * 所以直接把它作为结构化指令发下去，绕开 LLM 这一层模糊。
   */
  const payload: Record<string, unknown> = {
    type: 'media:play',
    name: String(it.name),
    kind: card.kind === 'playlist' ? 'playlist' : 'song',
    backend: 'builtin',
    character_id: activeCharacter.value, character_revision: characterRevision.value, session_id: sessionId.value,
  }
  if (it.encrypted_id) payload.encrypted_id = String(it.encrypted_id)
  if (it.song_id !== undefined && it.song_id !== null && it.song_id !== '') {
    payload.song_id = String(it.song_id)
  }
  if (it.playlist_id) payload.playlist_id = String(it.playlist_id)

  // 少数结果不带任何 ID → 退回自然语言（至少还能用，不静默失败）
  if (!payload.encrypted_id && !payload.song_id && !payload.playlist_id) {
    log('[media] 该条目没有 ID，退回自然语言')
    sendText(card.kind === 'playlist' ? `播放歌单「${it.name}」` : `播放《${it.name}》`)
    return
  }

  showSent(card.kind === 'playlist' ? `播放歌单「${it.name}」` : `播放《${it.name}》`)
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload))
    log(`[media] 点选直连：${it.name}`)
  } else {
    showSpeech('(引擎未连接)')
  }
}

function sendOfficial(payload:Record<string,unknown>):void {
  if(resultCharacterSwitching||officialPending.value)return
  if(!socket||socket.readyState!==WebSocket.OPEN){showSpeech('(引擎未连接)');return}
  officialPending.value=true
  socket.send(JSON.stringify({...payload,backend:'netease_client',character_id:activeCharacter.value,
    character_revision:characterRevision.value,session_id:sessionId.value,request_id:++mediaRequestId}))
}
function controlOfficial(action:'pause'|'resume'|'state'|'like'|'unlike'):void {
  if(officialPlayback.value)sendOfficial({type:'media:control',action,playback_id:officialPlayback.value.playback_id})
}

function focusChatInput(): void {
  inputRef.value?.focus()
}

// ── 对话呈现 ──
//
// 设计取舍（为什么不是聊天气泡列表）：
//   窗口尺寸≈模型尺寸，任何"往上堆叠的消息列表"都会越堆越高、压住模型的腿脚。
//   因此改为两种「单条」呈现：
//     · 桌宠回复 = 漫画说话云框，锚在头部上方 → 结构与身体分离，天生不挡腿脚；
//     · 自己发的消息 = 紧贴输入胶囊上方的一条气泡（贴底，像聊天软件的置底视角）。
//   两者都只保留"当前一条"，新内容替换旧内容，不需要滚动。

/**
 * 说话云定位输入：把「模型包围盒」交给 SpeechCloud 自行计算锚点。
 *
 * 定位/尺寸的可调参数都在 SpeechCloud.vue 顶部集中定义（ANCHOR_X_RATIO 等），
 * 这里只负责提供事实（模型在哪），不掺和视觉决策。
 *
 * 用 ref 而非 computed —— getModelRect() 读的是 Live2D 组件内的 ref，
 * 这里采用「显示前主动刷新 + 窗口尺寸变化时刷新」，语义更明确。
 */
const speechRect = ref<{ left: number; top: number; width: number; height: number }>({
  ...MODEL_FALLBACK,
})

function refreshSpeechRect(): void {
  speechRect.value = getModelRect() ?? { ...MODEL_FALLBACK }
}

/** 清掉气泡相关的全部计时器与"等播放"状态。 */
function clearSpeechTimers(): void {
  if (speechTimer) { clearTimeout(speechTimer); speechTimer = 0 }
  if (speechGraceTimer) { clearTimeout(speechGraceTimer); speechGraceTimer = 0 }
  speechHeldForPlayback = false
}

/** 无语音时的兜底：按字数估算阅读时长，到点淡出。 */
function scheduleSpeechEstimateHide(text: string): void {
  if (speechTimer) clearTimeout(speechTimer)
  const ms = Math.min(14000, Math.max(4000, text.length * 320))
  speechTimer = window.setTimeout(() => { speechVisible.value = false }, ms)
}

/** 收起气泡（播完 / 打断 / 新的一条要来）。 */
function hideSpeech(): void {
  clearSpeechTimers()
  speechVisible.value = false
}

/**
 * 展示桌宠回复（说话云）。
 *
 * `holdForPlayback=true`：**语音链路**（`llm:text`、Presence 的语音通道）——
 * 气泡一直挂着，直到 `tts:playback_end`（真的播完）才收；
 * 若宽限期内没有任何音频（TTS 关闭 / 合成失败 / 只有文字），退回按字数估算，
 * 避免气泡永久不消失。
 */
function showSpeech(text: string, holdForPlayback = false): void {
  // 空回复不弹云框（否则会留下一个只有内边距的小白块）
  if (!text.trim()) return
  refreshSpeechRect()
  speechText.value = text
  speechVisible.value = true
  clearSpeechTimers()
  if (!holdForPlayback) {
    scheduleSpeechEstimateHide(text)
    return
  }
  speechHeldForPlayback = true
  // speechTtsActive 刻意不在这里复位 —— 流式链路里音频段可能**先于** llm:text 到达，
  // 复位会把"已经在播"误判成"没语音"（它由 asr:start 按回合复位）。
  speechGraceTimer = window.setTimeout(() => {
    speechGraceTimer = 0
    if (speechHeldForPlayback && !speechTtsActive) {
      log('[speech] 本轮没有任何 TTS 活动（未开语音/合成失败），气泡退回按字数估算')
      speechHeldForPlayback = false
      scheduleSpeechEstimateHide(text)
    }
  }, SPEECH_GRACE_MS)
  // 兜底上限：极端情况（引擎中途崩、playback_end 永远不来）也不能让气泡永久挂着。
  // 60s 远大于正常回复（人设要求 ≤100 字；整段朗读也就十几秒）。
  if (speechTimer) clearTimeout(speechTimer)
  speechTimer = window.setTimeout(() => {
    log('[speech] 超过 60s 仍未收到播放完毕，强制收起气泡')
    hideSpeech()
  }, SPEECH_HARD_CAP_MS)
}

/** S39：显示工具活动状态行（"进行中"提示；几秒后自动淡出，避免旧状态挂着）。 */
function showActivity(text: string): void {
  if (!text.trim()) return
  activityText.value = text
  if (activityTimer) clearTimeout(activityTimer)
  activityTimer = window.setTimeout(() => { activityText.value = '' }, 5000)
}

/** S39：收起状态行（回复到达时调用）。 */
function clearActivity(): void {
  if (activityTimer) clearTimeout(activityTimer)
  activityTimer = 0
  activityText.value = ''
}

/** 展示自己发出的消息（贴底气泡）。回复到达后不再需要长留，超时淡出。 */
function showSent(text: string): void {
  sentMsg.value = { id: ++msgIdCounter, text }
  sentIsNew.value = true
  if (sentTimer) clearTimeout(sentTimer)
  sentTimer = window.setTimeout(() => { sentMsg.value = null }, 8000)
}

function onBubbleAnimDone(): void {
  sentIsNew.value = false
}

// ── 语音 ──
async function toggleVoice(): Promise<void> {
  if (!isRecording.value) {
    try {
      isRecording.value = true
      log('[voice] 开始监听（引擎语音模型未就绪时先等待加载完成，期间不采音）')
      // S02：带 sessionId 与 control 通道绑定同一 AgentSession
      await start({ sessionId: sessionId.value || undefined })   // 内部 waitEngineReady(60s)
      micRaf = requestAnimationFrame(animMic)
    } catch (e) {
      isRecording.value = false
      log(`[voice] 启动失败: ${e instanceof Error ? e.message : String(e)}`)
      if (micRaf) { cancelAnimationFrame(micRaf); micRaf = 0 }
      micLevel.value = 0
    }
  } else {
    isRecording.value = false
    log('[voice] 停止监听')
    await stop()
    if (micRaf) { cancelAnimationFrame(micRaf); micRaf = 0 }
    micLevel.value = 0
  }
}

function animMic(): void {
  micLevel.value = micInputLevel.value
  if (isRecording.value) micRaf = requestAnimationFrame(animMic)
}
// Presentation-only windows: the Engine socket, playback and selection IDs stay here.
const bubblePref=useSpeechBubblePref(), cardPref=useResultCardPref()
let detachedTimer=0, detachedSequence=0, detachedIdentity='', detachedKey='', detachedLast=''
let offDetached:(()=>void)|undefined
function detachedSnapshot():DetachedState {
  const identity=JSON.stringify([activeCharacter.value,characterRevision.value,sessionId.value,resultCharacterSwitching,resultCard.value,sourceCard.value,officialPlayback.value,officialPending.value,speechText.value,speechVisible.value])
  if(identity!==detachedIdentity){detachedIdentity=identity;detachedKey=`${Date.now()}:${++detachedSequence}`}
  const r=getModelRect()??MODEL_FALLBACK
  return {
    key:detachedKey,outline:contourBands(petComponent.value?.getContour?.()??null),anchor:{x:r.left,y:r.top,width:r.width,height:r.height},viewport:{width:innerWidth,height:innerHeight},gap:uiAppearance.settings.value.gap,
    // Fade protects desktop content beneath the model; detached replies remain readable/clickable.
    speech:{text:speechText.value,visible:speechVisible.value&&!resultCharacterSwitching,width:bubblePref.maxWidth.value+(uiAppearance.settings.value.speech.mode==='bubble'&&uiAppearance.settings.value.speech.comic?uiAppearance.settings.value.speech.tail:0),alpha:bubblePref.alpha.value,offsetX:bubblePref.offsetX.value,offsetY:bubblePref.offsetY.value,side:uiAppearance.settings.value.speechSide,anchorY:uiAppearance.settings.value.speech.anchorY,headY:uiAppearance.settings.value.speech.headAnchored?dialogueAnchor(uiAppearance.settings.value.speech,modelPath.value).mouthY:undefined,
      line:uiAppearance.settings.value.speech.mode==='line'?{...dialogueAnchor(uiAppearance.settings.value.speech,modelPath.value),fontSize:uiAppearance.settings.value.speech.fontSize,color:uiAppearance.settings.value.speech.lineColor,stroke:uiAppearance.settings.value.speech.lineWidth,rise:uiAppearance.settings.value.speech.lineRise,bend:uiAppearance.settings.value.speech.lineBend}:undefined},
    results:resultCard.value&&!resultCharacterSwitching?{title:resultCard.value.title,kind:resultCard.value.kind,items:JSON.parse(JSON.stringify(resultCard.value.items)),playback:officialPlayback.value?JSON.parse(JSON.stringify(officialPlayback.value)):null,busy:officialPending.value,width:resultCard.value.kind==='source'&&uiAppearance.settings.value.source.independent?uiAppearance.settings.value.source.width:cardPref.maxWidth.value,alpha:cardPref.alpha.value,side:cardPref.side.value,offsetX:cardPref.offsetX.value,offsetY:cardPref.offsetY.value}:null,
    sources:sourceCard.value&&!resultCharacterSwitching?{title:sourceCard.value.title,kind:'source',items:JSON.parse(JSON.stringify(sourceCard.value.items)),width:uiAppearance.settings.value.source.independent?uiAppearance.settings.value.source.width:cardPref.maxWidth.value,alpha:cardPref.alpha.value,side:cardPref.side.value,offsetX:cardPref.offsetX.value,offsetY:cardPref.offsetY.value}:null,
  }
}
function publishDetached():void {
  const snapshot=detachedSnapshot(),json=JSON.stringify(snapshot)
  if(json!==detachedLast){detachedLast=json;window.yuiro?.publishDetached(snapshot)}
}
onMounted(()=>{
  offDetached=window.yuiro?.onDetachedAction(a=>{
    // Recompute identity before accepting: queued old-character/old-card clicks are inert.
    const current=detachedSnapshot()
    if(a.key!==current.key||resultCharacterSwitching)return
    if(a.dismiss){if(a.kind==='speech')hideSpeech();else if(a.kind==='sources')clearSourceCard();else clearMusicCard()}
    else if(a.kind==='sources'&&Number.isInteger(a.index)){
      const url=String(sourceCard.value?.items[a.index!]?.url??'').trim()
      if(url)void window.yuiro?.openExternal(url)
    }
    else if(a.action==='client_like'||a.action==='client_unlike')controlOfficial(a.action==='client_like'?'like':'unlike')
    else if(a.action==='client_pause'||a.action==='client_resume')controlOfficial(a.action==='client_pause'?'pause':'resume')
    else if(a.kind==='results'&&Number.isInteger(a.index)){
      const item=resultCard.value?.items[a.index!]
      if(item)pickResultItem(item,a.action==='open_official'?'open_official':a.action==='client_play'?'client_play':'pick')
    }
    publishDetached()
  })
  publishDetached();detachedTimer=window.setInterval(publishDetached,100)
  mediaPollTimer=window.setInterval(()=>{if(resultCard.value&&officialPlayback.value&&!officialPending.value)controlOfficial('state')},5000)
})
watch([speechVisible,speechText,resultCard,sourceCard,officialPlayback,officialPending,shouldFade,activeCharacter,characterRevision,sessionId,uiAppearance.settings],()=>publishDetached(),{flush:'post',deep:true})
watch(()=>uiAppearance.settings.value.source.seconds,scheduleSourceHide)
watch([()=>uiAppearance.settings.value.results.seconds,()=>uiAppearance.settings.value.source.seconds,()=>!!officialPlayback.value],scheduleResultHide)
onBeforeUnmount(()=>{clearInterval(detachedTimer);clearInterval(mediaPollTimer);clearSourceCard();if(resultTimer)clearTimeout(resultTimer);offDetached?.()})
</script>

<template>
  <div class="shell-root" :data-theme="theme" :style="dockVars">
    <!--
      桌宠回复：漫画式说话云框
      锚在模型「头部上方」，尾巴指向模型本人 —— 与身体/腿脚分离，因此永不遮挡下半身。
      每次只显示当前一条回复，不再使用会越堆越高的气泡列表。
      S53：语音链路的气泡**等到真的播完**（`tts:playback_end`）才淡出，与语音同步
      消失；只有纯文字（无语音）时才退回按字数估算的阅读时长。
    -->
    <!-- Replies/results are rendered in presentation-only native windows. -->

    <!--
      S39：工具活动状态行 —— 它在干活时的可视反馈。
      "正在读取目录…" / "3/7｜在移动文件"：工具真在跑，但以前界面几秒静默，
      这正是"像卡死/像空壳"的主要来源。回复到达即收起。
    -->
    <div
      v-if="activityText"
      class="activity-line"
      :class="shouldFade ? 'fade-hidden' : 'fade-shown'"
    >
      <span class="activity-dot"></span>{{ activityText }}
    </div>

    <!--
      G7：结构化结果卡 —— 歌单雷达 / 搜索候选 / 歌曲列表的可视化。
      此前这些列表只躺在工具返回的 JSON 里，屏幕上什么都不显示，
      用户只能听到一句"已经推荐了"，无从知道具体推荐了什么。
      定位与尺寸见 components/ResultCard.vue（默认模型左侧，与回复气泡左右对称），
      可在调试台「UI」页实时调整。
    -->

    <!-- Pet Container -->
    <div class="pet" :class="shouldFade ? 'fade-hidden' : 'fade-shown'">
      <Live2DCanvas
        v-if="modelReady"
        :mouth-open="mouthOpen"
        :presence="presence"
        @receipt="sendRaw({...$event})"
        :bottom-reserve="chatOpen?Math.max(100,dockHeight+Math.max(8,54+dockY)):100"
        :model-path="modelPath"
        ref="petComponent" />
    </div>

    <!-- 悬停唤出的括号菜单（BracketMenu） -->
    <BracketMenu
      :open="menuOpen"
      :center-x="bracketCenter.x"
      :center-y="bracketCenter.y"
      :recording="isRecording"
      :chat-active="activePanel === 'chat'"
      :theme="theme"
      :class="shouldFade ? 'fade-hidden' : 'fade-shown'"
      @action="onBracketAction"
    />
    <!-- S29：计划审批卡片（plan approval）—— 大动作前先问一声 -->
    <div
      v-if="taskPlan"
      class="plan-card"
      :class="shouldFade ? 'fade-hidden' : 'fade-shown'"
      @mouseenter="forceInteractive(true)"
    >
      <div class="plan-head">这件事我想这么做，可以吗？</div>
      <div class="plan-goal">{{ taskPlan.goal }}</div>
      <ol class="plan-steps">
        <li v-for="(s, i) in taskPlan.steps" :key="i">{{ s }}</li>
      </ol>
      <div class="plan-actions">
        <button class="plan-ok" @click="resolvePlan(true)">按这个来</button>
        <button class="plan-no" @click="resolvePlan(false)">先别做</button>
      </div>
    </div>

    <!--
      S43：会话列表（Alt+S）—— "选择加载页"。
      此前前端只握着自己那一个 session_id：看不到有哪些会话、也无法切换，
      引擎重启或本地 id 丢失后只能新建，用户侧表现为"上下文全丢"却毫无提示。
    -->
    <div
      v-if="sessionsOpen"
      class="session-panel"
      :class="shouldFade ? 'fade-hidden' : 'fade-shown'"
      @mouseenter="forceInteractive(true)"
    >
      <div class="perf-head">
        <span>会话 · 点击切换</span>
        <button class="perf-close" title="关闭（Alt+S）" @click="sessionsOpen = false">×</button>
      </div>
      <button class="session-new" @click="newSession">＋ 开个新会话</button>
      <div class="session-list">
        <button
          v-for="s in sessionItems"
          :key="s.session_id"
          class="session-item"
          :class="{ current: s.session_id === sessionId }"
          :title="`${s.session_id}\n状态 ${s.state}${s.has_log ? ' · 有事件日志（可复活）' : ''}`"
          @click="switchSession(s.session_id)"
        >
          <span class="session-id">{{ s.session_id.slice(0, 8) }}</span>
          <span class="session-meta">
            {{ sessionTime(s.last_active_at) }}<template v-if="s.live"> · 在线</template>
          </span>
        </button>
        <div v-if="!sessionItems.length" class="session-empty">暂无历史会话</div>
      </div>
    </div>

    <!-- S23：Performance Gallery（Alt+G）—— 浏览表演库并现场演出 -->
    <div
      v-if="galleryOpen"
      class="perf-gallery"
      :class="shouldFade ? 'fade-hidden' : 'fade-shown'"
      @mouseenter="forceInteractive(true)"
    >
      <div class="perf-head">
        <span>表演库 · 点击现场演出</span>
        <button class="perf-close" title="关闭（Alt+G）" @click="galleryOpen = false">×</button>
      </div>
      <div class="perf-list">
        <button
          v-for="p in performances"
          :key="p.name"
          class="perf-item"
          :title="p.note || p.name"
          @click="runPerformance(p.name)"
        >
          <span class="perf-name">{{ p.name }}</span>
          <span class="perf-meta">
            {{ p.expression || '(默认表情)' }}<template v-if="p.motion"> · {{ p.motion }}</template>
          </span>
        </button>
      </div>
      <div v-if="!performances.length" class="perf-empty">表演库为空（引擎未连接？）</div>
    </div>

    <!--
      聊天坞（Chat Dock）—— 以「不挡住桌宠模型」为前提
      · 输入胶囊贴在角色脚底正中：胶囊形、无标题栏、无外框；
      · 自己发的消息只有一条，紧贴胶囊上方（贴底视角，像聊天软件默认置底）；
      · 桌宠回复不在这里 —— 走上面的漫画说话云框；
      · 语音链路提示在胶囊「内部下方」展开，开启麦克风时才出现。
    -->
    <div v-if="chatOpen" class="chat-dock" @mouseenter="forceInteractive(true)">
      <!-- 自己刚发的消息：贴底单条气泡 -->
      <div v-if="sentMsg" class="sent-line">
        <ChatBubble
          :key="sentMsg.id"
          :text="sentMsg.text"
          role="user"
          :index="sentMsg.id"
          :is-new="sentIsNew"
          @animdone="onBubbleAnimDone"
        />
      </div>

      <!-- 输入胶囊：语音提示挂在胶囊下方展开（不改变胶囊高度 → 输入框不会被上挤） -->
      <div class="composer">
        <div class="composer-main">
          <button
            v-if="showMic"
            class="cbtn mic-btn"
            :class="{ recording: isRecording }"
            @click="toggleVoice"
            title="语音输入">
            <Icon icon="solar:microphone-3-bold" width="17" />
          </button>
          <!-- S51：录音设备切换**常驻在麦克风按钮旁**。
               （只在"录音展开区"里放是不够的 —— 那块只有开麦后才出现，
               想换麦的时候它还没出现，对用户等于没有。） -->
          <MicDevicePicker v-if="showMic" bare />
          <input
            ref="inputRef"
            v-model="input"
            class="chat-input"
            placeholder="输入消息…"
            @keydown.enter.prevent="send"
          />
          <!-- 下拉菜单：把原「插话打断」单图标升级为可下拉，容纳两个开关——
               ①插话打断（保留，读写引擎 vad.barge_in_enabled）；②语音回复 TTS（新增）。
               两者权威都在引擎配置，聊天坞与调试台是同一份。 -->
          <div class="dock-menu">
            <button
              class="cbtn barge-btn"
              :class="{ on: bargeInEnabled || replyTtsEnabled, active: dockMenuOpen }"
              title="打断 / 语音回复开关（点击展开）"
              @click="toggleDockMenu">
              <Icon icon="solar:user-speak-rounded-bold" width="16" />
            </button>
            <transition name="menu-pop">
              <div v-if="dockMenuOpen" class="dock-menu-panel">
                <button class="dock-menu-item" @click="sendText('/推荐');dockMenuOpen=false" title="读取网易云客户端每日推荐并随机展示候选，不自动播放">客户端随机推荐</button>
                <button class="dock-menu-item" :disabled="!input.trim()" @click="sendText('/搜歌 '+input);input='';dockMenuOpen=false" title="使用输入框内容在网易云客户端搜索，不调用大脑或旧 API">
                  <Icon icon="solar:music-notes-bold" width="16" /><span class="dmi-label">搜歌（不经大脑）</span>
                </button>
                <button
                  class="dock-menu-item"
                  :class="{ on: bargeInEnabled }"
                  :disabled="bargeInBusy"
                  :title="bargeInEnabled
                    ? '插话打断：已开启（你一开口她就让位，点击关闭）'
                    : '插话打断：已关闭（她说完再回应你，点击开启）'"
                  @click="toggleBargeIn">
                  <Icon icon="solar:user-speak-rounded-bold" width="16" />
                  <span class="dmi-label">插话打断</span>
                  <span class="dmi-state">{{ bargeInEnabled ? '开' : '关' }}</span>
                </button>
                <button
                  class="dock-menu-item"
                  :class="{ on: replyTtsEnabled }"
                  :disabled="replyTtsBusy"
                  :title="replyTtsEnabled
                    ? '语音回复：已开启（语音/文字输入她都会出声，点击关闭）'
                    : '语音回复：已关闭（她只回文字，点击开启）'"
                  @click="toggleReplyTts">
                  <Icon icon="solar:volume-loud-bold" width="16" />
                  <span class="dmi-label">语音回复 TTS</span>
                  <span class="dmi-state">{{ replyTtsEnabled ? '开' : '关' }}</span>
                </button>
              </div>
            </transition>
          </div>
          <!-- S51：联网检索开关（发送键左侧）—— 开启/关闭两态必须一眼可见。
               注意：**不用 disabled** —— 那样点击毫无反应、用户只能靠 hover 猜原因；
               改为始终可点，不可用时点击直接给一句说明（"沉默的失效比禁用更糟"）。 -->
          <button
            class="cbtn search-btn"
            :class="{ on: webSearchOn, unavailable: !webSearchAvailable }"
            :title="webSearchAvailable ? (webSearchOn ? '联网搜索：已开启（点击关闭）' : '联网搜索：已关闭（点击开启）') : (webSearchHint || '联网搜索不可用')"
            @click="toggleWebSearch">
            <Icon icon="solar:global-bold" width="16" />
          </button>
          <button
            v-if="showSend"
            class="cbtn send-btn"
            @click="send"
            title="发送"
            :disabled="!input.trim()">
            <Icon icon="solar:plain-3-bold" width="17" />
          </button>
        </div>

        <!-- 展开区：语音引擎加载进度 -->
        <div v-if="pipelineLoading" class="composer-voice">
          <div class="ml-row">
            <span class="ml-label">语音引擎加载中（{{ loadingStage }}）</span>
            <span class="ml-pct">{{ Math.round(loadingProgress * 100) }}%</span>
          </div>
          <div class="ml-bar">
            <div class="ml-fill" :style="{ width: `${Math.round(loadingProgress * 100)}%` }"></div>
          </div>
        </div>

        <!-- 展开区：录音电平 + 语音链路阶段 -->
        <div v-if="isRecording" class="composer-voice">
          <div class="mic-bar">
            <div class="mic-fill" :style="{ width: `${micLevel * 100}%` }"></div>
          </div>
          <div class="mic-state">
            <span class="ms-item" :class="{ on: pipelineState.vad === '语音检测中' }">VAD</span>
            <span class="ms-item" :class="{ on: pipelineState.asr === '识别中…' }">ASR</span>
            <span class="ms-item" :class="{ on: pipelineState.llm === 'LLM 请求中…' }">LLM</span>
            <span class="ms-item" :class="{ on: pipelineState.tts !== '空闲' }">TTS</span>
            <span class="ms-text">{{ pipelineState.asr }}</span>
          </div>
          <!-- S51：录音设备的检测与切换（所有语音入口都要能选麦 —— 见 useAudioDevices）。
               切换在**下次开麦**时生效：当前这条流已经开着，中途换设备只会让人困惑。 -->
          <MicDevicePicker class="mic-dev" compact label="录音设备" />
        </div>
      </div>
    </div>

    <!-- 首次开启悬停渐隐的确认层（应用内，不新开窗口） -->
    <FadeOnHoverNotice
      v-if="showNotice"
      @confirm="confirmNotice"
      @cancel="cancelNotice"
    />
  </div>
</template>

<style scoped>
/* ═══════════════════════ Shell Root ═══════════════════════ */
.shell-root {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg-shell);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  color: var(--text-primary);
  /* 注意：绝不可加 -webkit-app-region: drag——它会吞掉 mousemove，
     悬停唤出的括号菜单（useBracketMenu 靠 capture 监听 mousemove）将永远唤不出（见 debug-log 坑 A） */
}

/* ═══════════════════════ Pet ═══════════════════════ */
.pet {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: 1;
  transition: opacity 250ms ease-in-out;
}
/* 悬停渐隐：悬停在模型本体上时 UI 淡出，露出下层桌面内容 */
.pet.fade-hidden {
  opacity: 0;
}
.pet.fade-shown {
  opacity: 1;
}
/* 通用渐隐类：用于括号菜单 / 气泡等窗口内 UI（与 .pet 同步淡出） */
.fade-hidden {
  opacity: 0 !important;
  transition: opacity 250ms ease-in-out;
}
.fade-shown {
  opacity: 1 !important;
  transition: opacity 250ms ease-in-out;
}

/* ═══════════════════════ Island Container ═══════════════════════ */
.island-container {
  position: absolute;
  right: 12px;
  bottom: 12px;
  z-index: 50;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

/* Collapsed button */
.collapse-btn {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-full);
  background: var(--collapse-bg);
  border: 2px solid var(--glass-border-dark);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--dur-med) var(--ease-out);
  -webkit-backdrop-filter: blur(var(--glass-blur));
  backdrop-filter: blur(var(--glass-blur));
  box-shadow: var(--shadow-float);
  -webkit-app-region: no-drag;
}
.collapse-btn:hover {
  transform: scale(1.08);
}

/* Connection dot */
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--dot-off);
  transition: background var(--dur-med);
}
.dot.ok { background: var(--dot-ok); }
.dot.err { background: var(--dot-err); }

/* ═══════════════════════ Island (expanded) ═══════════════════════ */
.island {
  background: rgba(12, 12, 16, 0.66);
  -webkit-backdrop-filter: blur(18px) saturate(1.2);
  backdrop-filter: blur(18px) saturate(1.2);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: var(--radius-2xl);
  padding: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.30);
  transition: all var(--dur-med) var(--ease-out);
  min-width: 168px;
  -webkit-app-region: no-drag;
}

/* Drawer 3×3 grid */
.drawer-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

/* 圆形控制按钮（语音 / 发送）：奶白底、无重描边，融进胶囊输入栏 */
.cbtn {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  background: transparent;
  border: none;
  color: var(--chat-text-soft);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--dur-fast) var(--ease-out);
  -webkit-app-region: no-drag;
}
.cbtn:hover { background: var(--chat-accent-soft); color: var(--chat-accent); }
.cbtn.recording {
  background: var(--rec-color);
  color: #fff;
  animation: pulse-rec 1.2s ease-in-out infinite;
}
.cbtn:disabled { opacity: 0.3; cursor: default; }
/* S51：联网开关开启态 —— 必须"一眼看出是开是关"（不能只靠点过的记忆） */
.cbtn.search-btn.on {
  background: var(--chat-accent-soft);
  color: var(--chat-accent);
}
/* 不可用（未配置搜索服务）：半透明但仍可点（点一下会说明原因） */
.cbtn.search-btn.unavailable { opacity: 0.45; }
/* 录音设备选择器：贴在语音展开区底部，左侧对齐（不要撑满整行） */
.mic-dev { margin-top: 5px; align-self: flex-start; }
/* 插话打断开关：默认是**关**的，所以关闭态刻意弱一档（不在静音时抢视线），
   开启态才亮起来 —— 两态必须一眼可辨。 */
.cbtn.barge-btn.on {
  background: var(--chat-accent-soft);
  color: var(--chat-accent);
}
.cbtn.barge-btn:not(.on) { opacity: 0.55; }
/* 下拉菜单展开时也点亮（与"任一开关开启"共用 .on，视觉一致） */
.cbtn.barge-btn.active {
  background: var(--chat-accent-soft);
  color: var(--chat-accent);
  opacity: 1;
}

/* 下拉菜单（打断 / 语音回复 TTS）：锚定按钮上方，毛玻璃小卡片 */
.dock-menu {
  position: relative;
  display: flex;
}
.dock-menu-panel {
  position: absolute;
  bottom: calc(100% + 8px);
  right: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 172px;
  padding: 5px;
  background: var(--chat-surface-solid);
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
  border: 1px solid var(--chat-border);
  border-radius: 12px;
  box-shadow: var(--chat-shadow);
  z-index: 60;
}
.dock-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--chat-text-soft);
  cursor: pointer;
  font-size: 12px;
  text-align: left;
  transition: background var(--dur-fast), color var(--dur-fast);
}
.dock-menu-item:hover { background: var(--chat-accent-soft); }
.dock-menu-item.on { color: var(--chat-accent); }
.dock-menu-item:disabled { opacity: 0.4; cursor: default; }
.dmi-label { flex: 1; }
.dmi-state {
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
}
.dock-menu-item.on .dmi-state {
  background: var(--chat-accent-soft);
  color: var(--chat-accent);
}
.menu-pop-enter-active,
.menu-pop-leave-active {
  transition: opacity var(--dur-fast), transform var(--dur-fast);
}
.menu-pop-enter-from,
.menu-pop-leave-to {
  opacity: 0;
  transform: translateY(4px) scale(0.96);
}

/* S51 修订：聊天坞的日记面板/入口已**下掉**（日记改为独立窗口，见 diary.html）——
   日记是"记录 + 让她接话"，塞进输入胶囊上方只会挤占对话空间。 */

@keyframes pulse-rec {
  0%, 100% { box-shadow: 0 0 0 0 var(--rec-color); }
  50% { box-shadow: 0 0 0 6px transparent; }
}

.collapse-btn-close {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-full);
  color: var(--text-muted);
}
.collapse-btn-close:hover { color: var(--text-primary); }

/* ═══════════════════════ Chat Dock（聊天坞） ═══════════════════════
   取代原「右下角大面板」。设计基准：不挡住桌宠模型 ——
   去掉面板外框与标题栏，只保留贴脚底的输入胶囊 + 向上流动的气泡。
   ═══════════════════════════════════════════════════════════════ */
.chat-dock {
  position: absolute;
  left:clamp(calc(min(90%, var(--dock-w,330px)) / 2),calc(50% + var(--dock-x,0px)),calc(100% - min(90%, var(--dock-w,330px)) / 2));
  /* 输入胶囊贴着预留区顶部：预留 44px 给语音提示在「下方」展开，
     这样展开时输入框纹丝不动（见 .composer-voice 的绝对定位）。 */
  bottom:clamp(8px,calc(54px + var(--dock-y,0px)),calc(100% - var(--dock-h,44px) - 8px));
  transform: translateX(-50%);
  z-index: 40;
  /* 宽度由调试台「UI」页的「聊天坞」控制（--dock-w 绑在 .shell-root 上） */
  width: min(90%, var(--dock-w, 330px));
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 7px;
  -webkit-app-region: no-drag;
  animation: dock-in var(--dur-med) var(--ease-out);
}

@keyframes dock-in {
  from { opacity: 0; transform: translateX(-50%) translateY(10px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}

/* 自己刚发的消息：贴底右对齐，只有一条，不堆叠 → 不会越推越高压住模型 */
.sent-line {
  display: flex;
  justify-content: flex-end;
  animation: sent-in var(--dur-med) var(--ease-out);
}
@keyframes sent-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Log body */
.log-body {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.6;
  max-height: 200px;
}
.log-line {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 2px 6px;
  border-radius: 6px;
  word-break: break-all;
}
.log-time {
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
  font-size: 10px;
  flex-shrink: 0;
}
.log-text { min-width: 0; }
/* 四档配色（my-neuro 标准件：info/success/error/warning） */
.log-line.lv-info { color: #93c5fd; }
.log-line.lv-success { color: #86efac; }
.log-line.lv-error { color: #fca5a5; background: rgba(252, 165, 165, 0.08); }
.log-line.lv-warning { color: #fbbf24; }
.log-filter-row { display: flex; gap: 6px; margin-bottom: 6px; }
.log-filter-btn {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}
.log-filter-btn.active {
  background: var(--btn-hover-bg);
  color: var(--text-primary);
  border-color: var(--btn-active-border);
}

/* ═══════════════════════ 输入胶囊（脚底正中） ═══════════════════════ */
/* 平时是一个纯胶囊；开启语音后，语音提示在「胶囊内部下方」展开，
   容器圆角由全胶囊过渡到圆角矩形，视觉上仍是同一个框。 */
.composer {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 0 7px;
  /* 半透奶油毛玻璃：压住模型时仍能看清轮廓 */
  background: var(--chat-surface-solid);
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
  border: 1px solid var(--chat-border);
  border-radius:var(--dock-radius,28px);
  box-shadow: var(--chat-shadow);
  pointer-events: auto;
  transition: border-color var(--dur-fast);
}
.composer:focus-within {
  border-color: var(--chat-accent);
  box-shadow: var(--chat-shadow), 0 0 0 3px var(--chat-accent-soft);
}

.composer-main {
  height:calc(var(--dock-h,44px) - 2px);
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 语音流程提示（电平 / 进度 / 阶段）
   位置：绝对定位挂在胶囊「下方」，因此它的出现不会改变胶囊高度，
   输入框不会被往上挤 —— 真正向下展开。
   形态：与胶囊同宽的独立圆角块，视觉上像从胶囊里"长"出来的下半截。 */
.composer-voice {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 9px 12px;
  background: var(--chat-surface-solid);
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
  border: 1px solid var(--chat-border);
  border-radius: 16px;
  box-shadow: var(--chat-shadow);
  animation: voice-expand var(--dur-med) var(--ease-out);
}
@keyframes voice-expand {
  from { opacity: 0; transform: translateY(-6px) scaleY(0.9); }
  to { opacity: 1; transform: translateY(0) scaleY(1); }
}

.mic-btn,
.send-btn { width: 32px; height: 32px; border-radius: var(--radius-full); }

.send-btn {
  background: var(--chat-accent);
  color: #fff;
}
.send-btn:hover:not(:disabled) { background: var(--chat-accent); transform: scale(1.06); }
.send-btn:disabled { background: transparent; color: var(--chat-muted); transform: none; }

.chat-input {
  flex: 1;
  min-width: 0;
  padding: 6px 4px;
  border: none;
  background: transparent;
  color: var(--chat-input-text);
  font-size:var(--dock-font,14px);
  font-family: inherit;
  outline: none;
  -webkit-app-region: no-drag;
  pointer-events: auto;
}
.chat-input::placeholder { color: var(--chat-input-placeholder); }

/* 麦克风电平 */
.mic-bar {
  height: 3px;
  border-radius: var(--radius-full);
  background: var(--chat-accent-soft);
  overflow: hidden;
}
.mic-fill {
  height: 100%;
  background: var(--rec-color);
  border-radius: var(--radius-full);
  transition: width 80ms linear;
}

/* 语音引擎加载进度 */
.ml-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ml-label {
  font-size: 11px;
  color: var(--chat-text-soft);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ml-bar {
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--chat-accent-soft);
  overflow: hidden;
}
.ml-fill {
  height: 100%;
  background: var(--chat-accent);
  border-radius: var(--radius-full);
  transition: width 120ms linear;
}
.ml-pct {
  min-width: 34px;
  text-align: right;
  font-size: 11px;
  color: var(--chat-text-soft);
  font-variant-numeric: tabular-nums;
}

/* 语音链路阶段（VAD / ASR / LLM / TTS） */
.mic-state {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
}
.ms-item {
  padding: 1px 7px;
  border-radius: 999px;
  color: var(--chat-muted);
  background: var(--chat-accent-soft);
  font-family: ui-monospace, monospace;
  transition: all var(--dur-fast);
}
.ms-item.on {
  color: #fff;
  background: var(--chat-accent);
  animation: kv-pulse 1.2s ease-in-out infinite;
}
.ms-text {
  color: var(--chat-text-soft);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 160px;
}
@keyframes kv-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }

/* ═══════════════════════ Settings ═══════════════════════ */
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.setting-row:last-child { border-bottom: none; }
.setting-label {
  font-size: var(--text-sm);
  color: var(--text-primary);
}
.setting-value {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.setting-value.ok { color: var(--dot-ok); }
.setting-value.err { color: var(--dot-err); }

.toggle-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: var(--radius-md);
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--dur-fast);
  -webkit-app-region: no-drag;
}
.toggle-btn:hover { background: var(--cbtn-hover); color: var(--text-primary); }

/* ── S23：Performance Gallery（Alt+G）──────────────────────────────────── */
.perf-gallery {
  position: absolute;
  right: 12px;
  top: 12px;
  width: 210px;
  max-height: 62vh;
  overflow-y: auto;
  padding: 8px;
  border-radius: 12px;
  background: rgba(24, 22, 32, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  font-size: 12px;
  color: #eee;
  z-index: 40;
}
.perf-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  opacity: 0.85;
}
.perf-close {
  border: none;
  background: transparent;
  color: #eee;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}
.perf-list { display: flex; flex-direction: column; gap: 4px; }
.perf-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 0 7px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  color: #eee;
  cursor: pointer;
  text-align: left;
}
.perf-item:hover { background: rgba(255, 255, 255, 0.14); }
.perf-name { font-weight: 600; }
.perf-meta { opacity: 0.6; font-size: 11px; }
.perf-empty { opacity: 0.6; padding: 4px 2px; }

/* ── S29：计划审批卡片（plan approval）────────────────────────────────── */
.plan-card {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  top: 12px;
  width: 260px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(24, 22, 32, 0.94);
  border: 1px solid rgba(255, 255, 255, 0.16);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.38);
  font-size: 12px;
  color: #eee;
  z-index: 45;
}
.plan-head { opacity: 0.75; margin-bottom: 4px; }
.plan-goal { font-weight: 600; margin-bottom: 6px; }
.plan-steps { margin: 0 0 8px 16px; padding: 0; opacity: 0.9; }
.plan-steps li { margin: 2px 0; }
.plan-actions { display: flex; gap: 8px; justify-content: flex-end; }
.plan-ok, .plan-no {
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  cursor: pointer;
  font-size: 12px;
}
.plan-ok { background: rgba(90, 190, 140, 0.28); color: #eaffef; }
.plan-no { background: rgba(255, 255, 255, 0.06); color: #eee; }
/* S39：工具活动状态行 —— 贴在输入区上方（不挡模型），呼吸点表示"还在进行" */
.activity-line {
  position: fixed;
  left: 50%;
  bottom: 112px;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: 70vw;
  padding: 4px 12px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.62);
  color: #f4f4f5;
  font-size: 12px;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
  z-index: 25;
}

.activity-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #7dd3fc;
  animation: activity-pulse 1.2s ease-in-out infinite;
}

@keyframes activity-pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.15); }
}

/* G7：结构化结果卡（歌单 / 搜索候选 / 歌曲列表）
   样式已随组件迁到 components/ResultCard.vue —— 那里自带定位与外观，
   并让「位置 / 尺寸」可在调试台「UI」页实时调整。 */

/* ── S43：会话列表（Alt+S）—— 选择加载页 ─────────────────────────────── */
.session-panel {
  position: absolute;
  left: 12px;
  top: 12px;
  width: 200px;
  max-height: 62vh;
  overflow-y: auto;
  padding: 8px;
  border-radius: 12px;
  background: rgba(24, 22, 32, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  font-size: 12px;
  color: #eee;
  z-index: 30;
}

.session-new {
  width: 100%;
  margin: 4px 0 6px;
  padding: 5px 8px;
  border-radius: 8px;
  border: 1px dashed rgba(125, 211, 252, 0.5);
  background: transparent;
  color: #7dd3fc;
  font-size: 12px;
  cursor: pointer;
}

.session-new:hover { background: rgba(125, 211, 252, 0.12); }

.session-list { display: flex; flex-direction: column; gap: 2px; }

.session-item {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 6px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  font-size: 12px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s ease;
}

.session-item:hover { background: rgba(255, 255, 255, 0.08); }
.session-item.current { background: rgba(125, 211, 252, 0.18); color: #7dd3fc; }
.session-id { font-family: ui-monospace, monospace; }
.session-meta { opacity: 0.6; font-size: 11px; }
.session-empty { padding: 6px; opacity: 0.5; font-size: 11px; }
</style>
