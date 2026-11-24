<script setup lang="ts">
import { alphaHeadCrop, previewCrop } from '../avatar/previewCrop'
import { installExpressionBlinkOrder } from '../avatar/expressionBlinkOrder'
import { installExpressionRequests } from '../avatar/expressionRequests'
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { Application, Ticker, settings, SCALE_MODES, UPDATE_PRIORITY } from 'pixi.js'
// 我们的模型是 .moc3 (Cubism 4/5)，须用 cubism4 入口，依赖 index.html 里的全局 Live2DCubismCore
import { Live2DModel } from 'pixi-live2d-display/cubism4'
import type { Live2DManifest } from '@shared'
import { useAppearance } from '../composables/useAppearance'
import { randomIdleDelay, useAvatarIdlePref } from '../composables/useAvatarIdlePref'
import { idleCandidates, resolveExpression, resolveMotion } from '../avatar/avatarSlots'
import type { AvatarPlaybackReceipt } from '../../../shared/engine-protocol'
import type { Presence } from '../avatar/presence'
import { ExpressionBaseline } from '../avatar/expressionBaseline'
import { IntentLease } from '../avatar/intentLease'
import { modelAssetUrl } from '../avatar/modelUrl'
import { gazeTarget, GazeActivity, applyGaze, followPose } from '../avatar/gaze'
import { shouldAcknowledgeListening } from '../avatar/listeningReaction'
import { useElectronRelativeMouse } from '../composables/useElectronRelativeMouse'
import { useAvatarClickPref } from '../composables/useAvatarClickPref'
import { motionKey } from '../avatar/clickFeedback'
import { applyLipSync } from '../avatar/lipSync'
import { BOTTOM_RESERVE, SIDE_MARGIN } from '../layout'
import { alphaHit, type AlphaMask } from '../utils/alphaHit'
import { useContourPref } from '../composables/useContourPref'

Live2DModel.registerTicker(Ticker)
settings.SCALE_MODE = SCALE_MODES.LINEAR

/** 兜底模型路径：外部未指定时用它（引擎配置读不到时的最后一道兜底）。 */
const DEFAULT_MODEL_PATH = '/live2d/hiyori/Hiyori.model3.json'
const { appearance } = useAppearance()

// chatOffset：聊天坞展开时窗口向左扩出的宽度，模型区整体右移该距离
// modelPath：由外部（App.vue 读引擎 persona.model_path）指定要加载的模型
const emit=defineEmits<{receipt:[value:AvatarPlaybackReceipt];ready:[path:string];failed:[path:string,message:string]}>()
let activeReceipt:{intent_id:string;session_id:string}|null=null
function finishReceipt(phase:'finished'|'cancelled'){
  if(activeReceipt)emit('receipt',{type:'avatar:receipt',...activeReceipt,phase})
  activeReceipt=null
}
const props = defineProps<{ mouthOpen: number; presence?:Presence; chatOffset?: number; modelPath?: string;preview?:boolean;bottomReserve?:number }>()

/** 当前生效的模型路径（可被 switchModel 在运行时更换）。 */
const currentModelPath = ref(props.modelPath || DEFAULT_MODEL_PATH)

/* 画布自始至终只有一块：换模型只替换 stage 上的模型，不重建画布与渲染器。 */

const canvasRef = ref<HTMLCanvasElement>()
const loadError = ref('')
let app: Application | null = null
let model: any = null
let tickerCb: (() => void) | null = null
let idleTimer: number | null = null // 待机调度定时器

/**
 * 当前模型的语义清单（主进程读取 model3 + motion3 Meta）。
 * 空 = 还没读到/读取失败：此时只按具体名工作，不猜任何动作（退化为"只演表情"）。
 */
const manifest = ref<Live2DManifest | null>(null)
/** 待机行为偏好（localStorage 共享，调试台可实时调整） */
const clickPref=useAvatarClickPref()
let lastClick='',lastClickAt=0
const idlePref = useAvatarIdlePref()
const relativeMouse=useElectronRelativeMouse()
const gazeActivity=new GazeActivity()
let gazeOwns=false,gazeWeight=0
let motionReturn: { values:Record<string,number> } | null = null
let lastRenderedPose:Record<string,number> | null = null
const returnParameterIds=['ParamAngleX','ParamAngleY','ParamAngleZ','ParamEyeBallX','ParamEyeBallY']
let resizeObserver: ResizeObserver | null = null
// 窗口贴合模型：仅首次量出真实尺寸后上报一次（避免循环）
let fitReported = false
// 模型基准尺寸（CSS px，scale=1 时的真实大小），首次量出后缓存，
// 之后布局只用它计算 scale，绝不再用 getBounds() 实时测已缩放的包围盒
// （否则会得到"已缩放尺寸→再缩放"的反馈，表现为长按/拖动时模型持续膨胀）。
let baseModelW = 0
let baseModelH = 0
// 最近一次布局结果（CSS px，相对画布左上角），供括号菜单做悬停命中
let layout = { cx: 0, cy: 0, w: 0, h: 0 }
// 模型在窗口中的包围盒（client 坐标，响应式）——状态泡定位 / 悬停命中共用
const modelRect = ref<{ left: number; top: number; width: number; height: number } | null>(null)
// 上一次应用的父容器尺寸，无变化则跳过 layoutModel，避免 ResizeObserver 自激振荡
let lastW = 0
let lastH = 0

function deviceResolution(): number {
  return Math.min(window.devicePixelRatio || 1, 2)
}

function measureModelBaseSize(): void {
  if (baseModelW > 0 && baseModelH > 0) return
  let mw = 0, mh = 0
  // 方式1（最可靠）：先在 scale=1 下量真实渲染包围盒
  try {
    if (model.getBounds) {
      model.scale.set(1, 1)
      const b = model.getBounds()
      if (b && b.width > 0 && b.height > 0) { mw = b.width; mh = b.height }
    }
  } catch { /* ignore */ }
  // 方式2：canvas 画布像素尺寸兜底
  if (!mw || !mh) {
    const info = model?.internalModel?.canvasSize
    if (info) { mw = Number(info.width) || 0; mh = Number(info.height) || 0 }
  }
  // 方式3：model.width/height 兜底
  if (!mw || !mh) { mw = Number(model.width) || 1; mh = Number(model.height) || 1 }
  baseModelW = mw
  baseModelH = mh
}

function layoutModel(): void {
  if (!app || !model) return

  // 拖动/长按期间：只更新 modelRect 让功能泡/悬停区跟随窗口移动，
  // 不重算 scale、不读 getBounds、不触发 fit（拖动只改位置不改尺寸）。
  if ((window as any).__yuiroDragging) {
    const rect = canvasRef.value?.getBoundingClientRect()
    if (rect && layout.w > 1) {
      modelRect.value = {
        left: rect.left + layout.cx - layout.w / 2,
        top: rect.top + layout.cy - layout.h / 2,
        width: layout.w,
        height: layout.h,
      }
    }
    return
  }

  // screen 是 CSS px（renderer.width 会乘 resolution，HiDPI 下不可用）
  const w = app.renderer.screen.width
  const h = app.renderer.screen.height

  // 仅在基准尺寸缺失时测量一次，之后稳定复用，杜绝反馈放大
  measureModelBaseSize()
  const mw = baseModelW || 1
  const mh = baseModelH || 1

  // 首次拿到真实模型尺寸 → 窗口贴合（模型 + 底部功能区，消除透明空白）
  if (!props.preview && !fitReported && mw > 1 && mh > 1) {
    fitReported = true
    console.log('[live2d] fit first report', JSON.stringify({ mw, mh }))
    void window.yuiro?.fitWindowToModel({ width: Math.round(mw), height: Math.round(mh) })
  }

  // 模型区 = 窗口扣除左侧聊天坞、两侧交互余量与底部状态泡余量；
  // 模型永不进入余量区 → 括号图标/状态泡/聊天坞物理上不可能遮挡模型
  const zoneX = props.chatOffset ?? 0
  const margin=props.preview?16:SIDE_MARGIN
  const availW = Math.max(w - zoneX - margin * 2, 40)
  const availH = Math.max(h - (props.preview?24:Math.max(BOTTOM_RESERVE,props.bottomReserve??BOTTOM_RESERVE)), 40)
  const fit = Math.min(availW / mw, availH / mh) * (props.preview ? 0.85 : appearance.value.fillRatio)
  const scale = fit > 0 ? fit : 1e-6
  model.scale.set(scale, scale)
  model.anchor.set(0.5, 0.5)
  // 水平：可用区正中 + 用户调的水平偏移（调试台「UI」页）
  const cx = zoneX + margin + availW / 2 + (props.preview?0:appearance.value.xOffset)
  const cy = availH * (props.preview ? 0.5 : appearance.value.yOffset)
  model.x = cx
  model.y = cy
  layout = { cx, cy, w: mw * scale, h: mh * scale }

  // 同步响应式包围盒（client 坐标）
  const rect = canvasRef.value?.getBoundingClientRect()
  if (rect && layout.w > 1) {
    modelRect.value = {
      left: rect.left + cx - layout.w / 2,
      top: rect.top + cy - layout.h / 2,
      width: layout.w,
      height: layout.h,
    }
  }
}

function handleResize(): void {
  if (!app || !canvasRef.value) return
  const parent = canvasRef.value.parentElement
  if (!parent) return
  const w = parent.clientWidth
  const h = parent.clientHeight
  if (w <= 0 || h <= 0) return
  // 尺寸无变化则跳过 resize，但仍调 layoutModel（拖动分支只更新 modelRect，
  // 让功能泡/悬停区跟随窗口移动；非拖动分支才会真正重排）。
  const sizeChanged = !(w === lastW && h === lastH)
  if (sizeChanged) {
    lastW = w
    lastH = h
    app.renderer.resolution = deviceResolution()
    app.renderer.resize(w, h)
  }
  layoutModel()
}

/**
 * 卸载当前模型 —— 但**保留 Pixi Application 与 WebGL 上下文**。
 *
 * 为什么换模型不能销毁 Application：
 * 销毁会连带销毁 WebGL 上下文，触发 Cubism 的 updateWebGLContext()，
 * 而那时 `renderer._clippingManager` 已被释放，于是抛出
 * "Cannot set properties of undefined (setting '_currentFrameNo')"。
 * 而且重建上下文还要连带重建画布、重新 resize 窗口 —— 正是"窗口异常扩张"的来源。
 * 只把 stage 上的模型换掉，渲染器全程复用，两个问题一并消失。
 */
let modelRevision = 0
const contourPref = useContourPref()
const maskView = ref<HTMLCanvasElement>()
const contour = shallowRef<AlphaMask | null>(null)
const contourStats = { samples: 0, totalMs: 0, maxMs: 0, lastMs: 0, lastAt: 0, error: '' }
const sampleCanvas = document.createElement('canvas')
const sampleContext = sampleCanvas.getContext('2d', { willReadFrequently: true })
function sampleContour(): void {
  if(props.preview)return
  const now = performance.now()
  if (now - contourStats.lastAt < 125 || !model || !canvasRef.value || !sampleContext) return
  contourStats.lastAt = now
  const started = performance.now()
  try {
    const rect = canvasRef.value.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const ratio = Math.min(1, 256 / Math.max(rect.width, rect.height))
    const w = Math.max(1, Math.round(rect.width*ratio)), h = Math.max(1, Math.round(rect.height*ratio))
    if (sampleCanvas.width !== w || sampleCanvas.height !== h) { sampleCanvas.width = w; sampleCanvas.height = h }
    sampleContext.clearRect(0, 0, w, h)
    sampleContext.drawImage(canvasRef.value, 0, 0, w, h)
    const pixels = sampleContext.getImageData(0,0,w,h)
    const alpha = new Uint8Array(w*h)
    for (let i=0;i<alpha.length;i++) alpha[i]=pixels.data[i*4+3]
    contour.value = { width:w,height:h,alpha,left:rect.left,top:rect.top,cssWidth:rect.width,cssHeight:rect.height }
    window.dispatchEvent(new Event('yuiro-contour-updated'))
    if (maskView.value && contourPref.debug.value) {
      maskView.value.width=w;maskView.value.height=h
      for(let i=0;i<alpha.length;i++){pixels.data[i*4]=0;pixels.data[i*4+1]=230;pixels.data[i*4+2]=120;pixels.data[i*4+3]=alpha[i]>=contourPref.threshold.value?150:0}
      maskView.value.getContext('2d')?.putImageData(pixels,0,0)
    }
    contourStats.error=''
  } catch (e) { contour.value=null;contourStats.error=String(e) }
  const ms=performance.now()-started
  contourStats.samples++;contourStats.lastMs=ms;contourStats.totalMs+=ms;contourStats.maxMs=Math.max(contourStats.maxMs,ms)
}
function hitContour(x:number,y:number,radius=contourPref.tolerance.value):boolean {
  return !loadError.value && alphaHit(contour.value,x,y,contourPref.threshold.value,radius)
}
let restoreExpressionBlink=()=>{}
let restoreExpressionRequests=()=>{}
function unloadModel(): void {
  restoreExpressionRequests();restoreExpressionRequests=()=>{}
  restoreExpressionBlink();restoreExpressionBlink=()=>{}
  finishReceipt('cancelled')
  motionRequestRevision++;sdkMotionActive=false;speechGestureActive=false;listeningGestureActive=false
  lastListeningGestureAt=-Infinity
  modelRevision++
  expressionBaseline.reset()
  intentLease.reset()
  lastIdleMotion = ''
  lastSpeechGestureAt = 0
  lastClick='';lastClickAt=0
  gazeActivity.reset();gazeOwns=false;gazeWeight=0;motionReturn=null;lastRenderedPose=null
  stopIdle()
  // 清单与模型绑定：换模型必须重新读，否则会拿旧模型的槽位去解析
  manifest.value = null
  if (model && app) {
    try { app.stage.removeChild(model) } catch { /* ignore */ }
  }
  try { model?.destroy?.({ children: true }) } catch { /* ignore */ }
  model = null

  // 尺寸相关缓存必须复位：否则新模型会沿用旧模型的基准尺寸，算出错误缩放
  baseModelW = 0
  baseModelH = 0
  layout = { cx: 0, cy: 0, w: 0, h: 0 }
  modelRect.value = null
  // 表现状态一并复位：新模型的面部参数名可能完全不同，留着旧状态会误报/误回落
  avatarState.value = { expression: '', motion: '', motionIndex: null, until: 0 }
  clearReleaseTimer()
  motionPreviewIdx = -1
  previewIndex = -1

  // 注意：这里刻意**不复位 fitReported**。
  // 复位会让新模型再次触发 fitWindowToModel，按它的原始尺寸 resize 窗口
  // （1280×1380 这种大模型就会把窗口撑爆）—— 需求是"在原位置上变化"。
  // 窗口尺寸保持不变，新模型由 layoutModel() 按可用区域自动缩放适配。
}

/** 确保 Pixi Application 存在（全程只创建一次，换模型时复用）。 */
function ensureApp(): void {
  if (app || !canvasRef.value) return
  app = new Application({
    view: canvasRef.value,
    autoStart: true,
    backgroundAlpha: 0,
    antialias: true,
    autoDensity: true,
    resolution: deviceResolution(),
    // 不使用 resizeTo：由我们手动 handleResize 控制，避免 Pixi 内部
    // 与 ResizeObserver 叠加导致尺寸抖动/自激，进而让 layoutModel 反复放大模型。
    // 必须保留绘制缓冲：鼠标穿透/悬停的像素采样（drawImage 读 canvas）
    // 在合成后才发生，不保留会采到全透明 → 整窗穿透卡死
    preserveDrawingBuffer: true,
  })
  handleResize()

  tickerCb = () => {
    const rect=modelRect.value,now=Date.now(),mx=relativeMouse.x.value,my=relativeMouse.y.value
    const enabled=!!rect&&!props.preview&&idlePref.gazeEnabled.value&&idlePref.gazeStrength.value>0&&idlePref.reactiveEnabled.value&&avatarState.value.until<=now
    const near=enabled&&Math.abs(mx-(rect!.left+rect!.width/2))<rect!.width*1.5&&Math.abs(my-(rect!.top+rect!.height*.2))<rect!.height*1.5
    const was=gazeOwns
    gazeOwns=gazeActivity.step(mx,my,near,now,idlePref.gazeHoldMs.value)
    if(gazeOwns&&!was){
      beginPoseReturn();
      (model?.internalModel?.motionManager as any)?.stopAllMotions?.()
      avatarState.value.motion='';avatarState.value.motionIndex=null
    }else if(was&&!gazeOwns){beginPoseReturn();startIdle(true)}
    const dt=app?.ticker.deltaMS??16
    gazeWeight=avatarState.value.until>now?0:gazeWeight+(Number(gazeOwns)-gazeWeight)*(1-Math.exp(-dt/120))
    const target=gazeOwns?gazeTarget(mx,my,rect!,idlePref.gazeStrength.value):[0,0]
    model?.internalModel?.focusController?.focus(target[0],target[1])
    model?.update?.(app?.ticker.deltaMS ?? 16)
  }
  app.ticker.add(tickerCb)
  app.ticker.add(sampleContour, undefined, UPDATE_PRIORITY.UTILITY)

  const parent = canvasRef.value.parentElement
  if (parent) {
    resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(parent)
  }
  window.addEventListener('resize', handleResize)
}

/** 彻底拆解（仅组件卸载时调用）：这时才销毁 Application。 */
function teardown(): void {
  app?.ticker.remove(sampleContour)
  unloadModel()
  if (tickerCb && app) {
    try { app.ticker.remove(tickerCb) } catch { /* ignore */ }
  }
  tickerCb = null
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', handleResize)
  try { app?.destroy(true, { children: true }) } catch { /* ignore */ }
  app = null
}

/** 切换到另一个 Live2D 模型（同路径再调一次 = 重新加载）。 */
async function switchModel(path: string): Promise<void> {
  await loadModel(path)
}

// 外部更换 modelPath（例如读到了引擎配置里的新值）时自动重载
watch(() => props.modelPath, (p) => {
  if (p && p !== currentModelPath.value) void loadModel(p)
})

async function loadModel(path?: string): Promise<void> {
  contour.value=null
  if (!canvasRef.value) return
  ensureApp()
  if (!app) return
  unloadModel()
  const revision = modelRevision

  const modelPath = path || currentModelPath.value || DEFAULT_MODEL_PATH
  currentModelPath.value = modelPath
  const assetUrl = modelAssetUrl(modelPath, window.location.href)
  // 重置上一次的错误（HMR / 重载后 ref 仍可能保留旧 loadError）
  loadError.value = ''

  // 调试：验证模型 JSON 是否可达
  if (window.location.protocol !== 'file:') fetch(assetUrl).then(r => {
    if (revision === modelRevision && !r.ok) loadError.value = `[Live2D] HTTP ${r.status} 访问 ${modelPath}`
  }).catch(err => {
    if (revision === modelRevision) loadError.value = `[Live2D] 网络错误: ${err.message}`
  })

  try {
    const loaded = await Live2DModel.from(assetUrl, {
      autoUpdate: false,
      // SDK默认会在motionFinish后自动续播Idle，绕过本项目的停顿和让位。
      // 指向不存在的内部组，让所有待机动作只由startIdle调度。
      idleMotionGroup: '__yuiro_external_idle__',
      // v0.5.0 起 autoInteract 已废弃，改由这两项分别控制。
      // 都关掉：避免模型自建交互管理器、持有已销毁渲染器的引用
      autoHitTest: false,
      autoFocus: false,
    })
    if (revision !== modelRevision || !app) {
      loaded.destroy({ children: true })
      return
    }
    model = loaded
    app.stage.addChild(model)
    // 先跑一帧让模型几何就绪，layoutModel 里的 getBounds 才能拿到真实尺寸
    model.update?.(0)
    layoutModel()

    // ── 待机 + 模型清单（S53）──
    // 以前是 startRandomMotion('Idle') 播完立刻续播，等于"随机动作永远不停"；
    // 现在只播 idle 语义槽位、播完停顿数秒，表情固定在 neutral。
    const mm = model.internalModel?.motionManager as any
    const internal = model.internalModel as any
    // SDK 默认会额外叠加同一 focus 到头、眼和身体；由本组件统一写入，避免双重控制。
    internal.updateFocus=()=>{}
    restoreExpressionBlink=installExpressionBlinkOrder(internal)
    restoreExpressionRequests=installExpressionRequests(internal.motionManager?.expressionManager)
    const gazeIds=new Set<string>(internal.coreModel.getModel().parameters.ids)
    internal.on('beforeModelUpdate',()=>{
      if(revision!==modelRevision)return
      if(gazeWeight>.001)applyGaze(internal.coreModel,gazeIds,internal.focusController.x,internal.focusController.y,gazeWeight)
      if(motionReturn){
        let settled=true
        for(const [id,from] of Object.entries(motionReturn.values)){
          const target=internal.coreModel.getParameterValueById(id)
          const eye=id.startsWith('ParamEye')
          const next=followPose(from,target,app?.ticker.deltaMS??16,eye)
          motionReturn.values[id]=next
          internal.coreModel.setParameterValueById(id,next)
          if(Math.abs(target-next)>(eye?.005:.15))settled=false
        }
        if(settled)motionReturn=null
      }
      lastRenderedPose={}
      for(const id of returnParameterIds)if(gazeIds.has(id))lastRenderedPose[id]=internal.coreModel.getParameterValueById(id)
      const ids=mm.lipSyncIds as string[] | undefined
      if(ids?.length)applyLipSync(internal.coreModel,ids,props.mouthOpen)
    })
    mm?.on?.('motionFinish',()=>{
      if(revision===modelRevision&&sdkMotionActive)completeAppearance()
    })
    mm?.on?.('motionLoadError', (err: unknown) => {
      console.error('[live2d] motionLoadError:', err)
    })
    await loadManifest(modelPath, revision)
    if (revision !== modelRevision) return
    releaseToIdle()
    startIdle()
    requestAnimationFrame(()=>requestAnimationFrame(()=>{if(revision===modelRevision)emit('ready',modelPath)}))

  } catch (e: any) {
    if (revision !== modelRevision) return
    console.error('[Live2D] 加载失败:', e)
    loadError.value = '[Live2D] 加载失败: ' + (e?.message || String(e))
    emit('failed', modelPath, loadError.value)
  }
}

/* 口型不再挂 watch —— 改由每帧 ticker 在 model.update 之前写入（见 ensureApp），
   否则动作曲线会把口型覆盖掉。这里只留一个说明，避免后人又加回 watch。 */

/** 模型在窗口中的包围盒（client 坐标），供括号菜单悬停命中。 */
function getModelRect(): { left: number; top: number; width: number; height: number } | null {
  return modelRect.value
}

/* ── 模型清单 / 待机调度（S53）─────────────────────────────────────────── */

/** 读取当前模型的语义清单（失败只降级，不影响渲染）。 */
async function loadManifest(path: string, revision = modelRevision): Promise<void> {
  try {
    const loaded = (await window.yuiro?.inspectPetModel?.(path)) ?? null
    if (revision !== modelRevision) return
    manifest.value = loaded
    const m = manifest.value
    console.log(
      '[live2d] manifest:', m?.expressions.length ?? 0, '表情 /',
      m?.motions.length ?? 0, '动作 / idle 候选', m?.index.idle.length ?? 0,
      m ? `（未识别 ${m.coverage.unmappedExpressionCount} 表情 / ${m.coverage.unmappedMotionCount} 动作）` : '',
    )
    for (const w of m?.warnings ?? []) console.warn('[live2d]', w)
  } catch (e) {
    if (revision !== modelRevision) return
    manifest.value = null
    console.warn('[live2d] 读取模型清单失败（退化为"只演表情"）:', e)
  }
}

function stopIdle(): void {
  if (idleTimer !== null) {
    window.clearTimeout(idleTimer)
    idleTimer = null
  }
}

/**
 * 待机调度：只从 idle 槽位里挑动作，**播完停顿数秒**再播下一个。
 *
 * - 池子为空（模型没有 idle 资源 / 偏好被关闭）→ 完全静止，只留呼吸与眨眼；
 * - 表演进行中（`until > now`）主动让位，1 秒后再看；
 * - 用 NORMAL 优先级播放，不会打断正在进行的表演。
 */
let lastIdleMotion = ''
const expressionBaseline = new ExpressionBaseline()
const intentLease = new IntentLease()
function startIdle(immediate=false): void {
  stopIdle()
  if(props.preview)return
  if (!model || !idlePref.enabled.value) return
  const pool = idleCandidates(manifest.value, idlePref.maxDurationMs.value,idlePref.fixedMotion.value)
  if (!pool.length) return

  const tick = (): void => {
    idleTimer = null
    if (!model) return
    if (gazeOwns || avatarState.value.until > Date.now() || (idlePref.reactiveEnabled.value && props.presence && props.presence !== 'idle')) {
      idleTimer = window.setTimeout(tick, 1000)
      return
    }
    const alternatives = pool.filter((motion) => `${motion.group}#${motion.index}` !== lastIdleMotion)
    const candidates = alternatives.length ? alternatives : pool
    const pick = candidates[Math.floor(Math.random() * candidates.length)]
    lastIdleMotion = `${pick.group}#${pick.index}`
    const played = playMotion(pick.group, pick.index, 2 /* MotionPriority.NORMAL */)
    const hold = played || pick.durationMs || 2600
    idleTimer = window.setTimeout(
      tick,
      hold + randomIdleDelay(idlePref.intervalMinMs.value, idlePref.intervalMaxMs.value),
    )
  }

  // 进入待机先停顿一下，避免刚加载 / 刚演完就立刻抽动
  idleTimer = window.setTimeout(
    tick,
    immediate?0:randomIdleDelay(idlePref.intervalMinMs.value, idlePref.intervalMaxMs.value),
  )
}

/** 回到待机表情：优先模型的 neutral 槽位，没有就回落默认。 */
function releaseToIdle(): void {
  const neutral = resolveExpression(manifest.value, { expression_slot: 'neutral' })
  applyExpression(neutral.from === 'slot' ? neutral.name : '')
  avatarState.value.motion = ''
  avatarState.value.motionIndex = null
}

// ── 头像意图通道（表情 / 动作 / 回落）─────────────────────────────────────
/**
 * 桌宠表现的**唯一入口**：表情 + 动作 + "演完自动回落"的时长。
 *
 * 为什么收成一个入口：此前表情、动作、待机循环三处各自直接调 model.expression /
 * startRandomMotion，于是留下三个反复出现的坑 ——
 *   1) 表演结束后没人负责收表情：引擎若没发后续意图，表情就永远挂着；
 *   2) 表情名 / 动作组 / 动作索引不存在时**静默无效**，看起来像"随机不生效"；
 *   3) 动作优先级混乱：调试台预览会被待机循环顶掉，点了像没反应。
 * 现在统一在这里：校验 → 应用 → 排定回落 → 结果记进 avatarState 供调试台显示。
 *
 * 时长优先级：运行时真实动作时长 > 意图里的 duration_ms > 0（0 = 不排回落）。
 * 这条"带 duration 才算一次表演、不带就是常驻状态"的规则正好对上引擎语义：
 * perform 带 duration_ms，emotion:set 不带 → 情绪一直有效直到下次变化。
 */
interface AvatarIntentPayload {
  source?:string
  intent_id?:string
  session_id?:string
  priority?: number
  emotion?: string | null
  expression?: string | null
  /** 语义槽位（S53）：具体名不可用时由模型清单解析 */
  expression_slot?: string | null
  motion?: string | null
  motion_index?: number | null
  /** 语义槽位（S53）：具体组不可用时由模型清单解析 */
  motion_slot?: string | null
  /** 表演名（仅日志） */
  performance?: string | null
  duration_ms?: number
}

/** 当前生效的表现状态（调试台可读："现在在演什么 / 还要多久"）。 */
const avatarState = ref({
  expression: '',
  motion: '',
  motionIndex: null as number | null,
  /** 回落时间戳（0 = 常驻，不回落） */
  until: 0,
})

// 仅发布非敏感表现状态，供同源调试台观测；预览组件不覆盖真实模型。
watch([avatarState,()=>props.presence,currentModelPath],()=>{
  if(props.preview)return
  try{localStorage.setItem('yuiro-avatar-status',JSON.stringify({
    model:currentModelPath.value,presence:props.presence||'idle',...avatarState.value,at:Date.now()
  }))}catch{/* 存储不可用不阻断演出 */}
},{deep:true})

/** 回落定时器：新意图进来会替换它，所以只对"最后一次表演"生效。 */
let releaseTimer: number | null = null

function clearReleaseTimer(): void {
  if (releaseTimer !== null) {
    window.clearTimeout(releaseTimer)
    releaseTimer = null
  }
  avatarState.value.until = 0
}

/** 排定"演完回落"：时长到了把表情收回默认（引擎不发消息也不会一直挂着）。 */
let motionRequestRevision = 0
let sdkMotionActive = false
let speechGestureActive = false
let listeningGestureActive = false
function cancelPerformance():void{
  (model?.internalModel?.motionManager as any)?.stopAllMotions?.()
  finishReceipt('cancelled');completeAppearance()
}
function completeAppearance():void{
  if(sdkMotionActive)beginPoseReturn()
  motionRequestRevision++
  sdkMotionActive=false
  speechGestureActive=false;
  listeningGestureActive=false;
  // 部分角色资源自带Loop=true；时长兜底回落也必须停止SDK循环，不能只清UI状态。
  (model?.internalModel?.motionManager as any)?.stopAllMotions?.()
  finishReceipt('finished')
  clearReleaseTimer();intentLease.reset()
  restorePresenceExpression()
  avatarState.value.motion='';avatarState.value.motionIndex=null
  startIdle()
}
function beginPoseReturn():void{
  if(lastRenderedPose)motionReturn={values:{...lastRenderedPose}}
}
function scheduleRelease(durationMs: number): void {
  clearReleaseTimer()
  if (!(durationMs > 0)) return
  avatarState.value.until = Date.now() + durationMs
  releaseTimer = window.setTimeout(completeAppearance, durationMs)
}

/**
 * 应用表情（含校验）：空串 = 回落默认。
 * 返回是否真的应用成功 —— 调用方可据此提示"这个名字当前模型没有"。
 */
function applyExpression(name: string): boolean {
  const target = String(name ?? '').trim()
  const em = (model?.internalModel?.motionManager as any)?.expressionManager
  if (!target) {
    try { em?.resetExpression?.() } catch { /* 模型未就绪：忽略 */ }
    avatarState.value.expression = ''
    return true
  }
  const known = listExpressions()
  if (known.length && !known.includes(target)) {
    console.warn(`[live2d] 当前模型没有表情「${target}」（可用：${known.join('、') || '无'}）`)
    return false
  }
  try {
    model?.expression?.(target)
    avatarState.value.expression = target
    return true
  } catch (e) {
    console.warn('[live2d] 应用表情失败:', e)
    return false
  }
}

/**
 * 播放动作（组名 + 可选索引；不传索引 = 该组随机）。
 * 返回**实际播放到的时长**（ms；0 = 失败或读不到）。
 *
 * 用 PriorityForce 而非默认优先级：调试台「试播」与引擎表演都必须能打断
 * 正在播的待机动作，否则会出现"点了没反应"（S34 反馈过）。
 */
let motionPlaybackRevision = 0
function playMotion(group: string, index?: number | null, priority = 3 /* FORCE */, onStarted?:(ok:boolean)=>void): number {
  const mm = (model?.internalModel?.motionManager as any)
  if (!mm) return 0
  const groups = listMotions()
  const hit = groups.find((g) => g.group === group)
  if (!hit) {
    console.warn(`[live2d] 当前模型没有动作组「${group}」（可用：${groups.map((g) => g.group).join('、') || '无'}）`)
    return 0
  }
  const idx = index === undefined || index === null
    ? Math.floor(Math.random() * hit.count)
    : Number(index)
  if (!Number.isInteger(idx) || idx < 0 || idx >= hit.count) {
    console.warn(`[live2d] 动作索引越界：${group}#${idx}（该组共 ${hit.count} 个）`)
    return 0
  }
  try {
    if(priority>=3)motionReturn=null
    const revision=modelRevision
    const request=motionRequestRevision,playback=++motionPlaybackRevision
    const settle=(ok:boolean)=>{
      if(revision!==modelRevision||request!==motionRequestRevision||playback!==motionPlaybackRevision)return
      if(!ok){
        console.warn(`[live2d] 动作未启动：${group}#${idx}`)
        if(avatarState.value.motion===group&&avatarState.value.motionIndex===idx){
          avatarState.value.motion='';avatarState.value.motionIndex=null
        }
      }
      onStarted?.(ok)
    }
    Promise.resolve(mm.startMotion?.(group, idx, priority)).then(
      ok=>settle(ok===true),
      error=>{console.warn('[live2d] 动作启动失败',error);settle(false)},
    )
    avatarState.value.motion = group
    avatarState.value.motionIndex = idx
    return motionDurationMs(group, idx)
  } catch (e) {
    console.warn('[live2d] 播放动作失败:', e)
    return 0
  }
}

/**
 * 读该动作的真实时长（ms）。
 *
 * 优先问运行时自己：动作数据就在内存里，比任何外部时长表都准
 * （引擎那份 duration 表是手维护的，换模型就对不上）。探测失败返回 0，
 * 由调用方回落到引擎给的 duration_ms。
 */
function motionDurationMs(group: string, index: number): number {
  try {
    const mm: any = model?.internalModel?.motionManager
    const bucket = mm?.motionGroups?.[group]
    const motion = Array.isArray(bucket) ? bucket[index] : bucket?.motions?.[index]
    const d = motion?.getDuration?.() ?? motion?.duration
    if (typeof d === 'number' && d > 0) {
      // Cubism4 的时长可能是秒（<1000 视为秒），统一成毫秒
      return d < 1000 ? Math.round(d * 1000) : Math.round(d)
    }
  } catch { /* 探测失败：交给调用方回落 */ }
  return 0
}

/**
 * 应用一次"头像意图"（表情 + 动作 + 时长）。引擎 / 调试台 / 快捷键都走这里。
 *
 * S53：意图里可能只有**语义槽位**（引擎不写死模型私有坐标），这里结合当前模型的
 * 清单解析成具体资源：
 *   表情：具体名（校验存在）→ 槽位 → 不改 / 回落；
 *   动作：具体组#索引（校验存在）→ 槽位 → **没有就只演表情**（绝不随机凑一个）。
 */
function restorePresenceExpression():void{
  const thinking=idlePref.reactiveEnabled.value&&props.presence==='thinking'?resolveExpression(manifest.value,{expression_slot:'thinking'}):null
  applyExpression(thinking?.name||expressionBaseline.current())
}
let lastSpeechGestureAt = 0
let lastListeningGestureAt = -Infinity
watch([()=>props.presence,idlePref.reactiveEnabled],([presence],[previous])=>{
  if(listeningGestureActive&&(!idlePref.reactiveEnabled.value||presence!=='thinking')){
    (model?.internalModel?.motionManager as any)?.stopAllMotions?.()
    finishReceipt('cancelled');completeAppearance()
  }
  if(speechGestureActive&&(!idlePref.reactiveEnabled.value||props.presence!=='speaking')){
    (model?.internalModel?.motionManager as any)?.stopAllMotions?.()
    finishReceipt('cancelled');completeAppearance()
  }
  if(!model||avatarState.value.until>Date.now())return
  restorePresenceExpression()
  const now=Date.now()
  if(!props.preview&&shouldAcknowledgeListening(previous,presence,idlePref.reactiveEnabled.value,
    avatarState.value.until>now,gazeOwns,now,lastListeningGestureAt,idlePref.gestureCooldownMs.value)){
    const nod=resolveMotion(manifest.value,{motion_slot:'nod'})
    if(nod&&nod.durationMs>0&&nod.durationMs<=idlePref.gestureMaxMs.value){
      lastListeningGestureAt=now
      applyAvatarIntent({motion:nod.group,motion_index:nod.index,duration_ms:nod.durationMs,priority:2,source:'listening-ack'})
      return
    }
  }
  if(!idlePref.reactiveEnabled.value||props.preview||props.presence!=='speaking')return
  if(now-lastSpeechGestureAt<idlePref.gestureCooldownMs.value)return
  const nod=resolveMotion(manifest.value,{motion_slot:'nod'})
  // 只使用已映射的短动作；未知时长或大动作不用于说话微反应。
  if(!nod||nod.durationMs<=0||nod.durationMs>idlePref.gestureMaxMs.value)return
  lastSpeechGestureAt=now
  applyAvatarIntent({motion:nod.group,motion_index:nod.index,duration_ms:nod.durationMs,priority:2,source:'speech-gesture'})
})
function applyAvatarIntent(intent: AvatarIntentPayload): void {
  const expr = resolveExpression(manifest.value, intent)
  const temporary = Number(intent.duration_ms ?? 0) > 0 || !!intent.motion || !!intent.motion_slot
  const priority = Number.isFinite(intent.priority) ? Number(intent.priority) : (temporary ? 3 : 1)
  if (!intentLease.accepts(priority, Date.now())) {
    // 保存新的基础情绪，等当前表演结束再恢复，不破坏回落定时器。
    if (!temporary && expr.from !== 'none') expressionBaseline.update(expr.name, false)
    return
  }
  finishReceipt('cancelled')
  const request=++motionRequestRevision
  sdkMotionActive=false
  speechGestureActive=intent.source==='speech-gesture'
  listeningGestureActive=intent.source==='listening-ack'
  let exprOk = true
  if (expr.from === 'reset') exprOk = applyExpression('')
  else if (expr.from !== 'none') exprOk = applyExpression(expr.name)
  if (expr.from !== 'none' && exprOk) expressionBaseline.update(expr.name, temporary)

  const motion = resolveMotion(manifest.value, intent)
  const engineMs = Number(intent.duration_ms ?? 0)
  /** 兜底时长：既没读到真实时长、意图也没带时，用它保证 idle 能恢复 */
  const FALLBACK_HOLD_MS = 2600
  let realMs = 0
  if (motion) {
    realMs = playMotion(motion.group, motion.index,3,ok=>{
      if(request!==motionRequestRevision||!model)return
      if(!ok){finishReceipt('cancelled');completeAppearance();return}
      sdkMotionActive=true
      if(expr.from!=='none')applyExpression(expr.name)
      const actual=motionDurationMs(motion.group,motion.index)||motion.durationMs||engineMs||2600
      intentLease.hold(priority,Date.now()+actual+500)
      scheduleRelease(actual+500) // SDK finish优先，额外宽限仅作丢事件兜底。
      if(activeReceipt)emit('receipt',{type:'avatar:receipt',...activeReceipt,phase:'started',duration_ms:actual})
    })
    // 运行时读不到真实时长 → 用清单里的 Meta.Duration（比引擎的手维护表更准）
    if (!realMs) realMs = motion.durationMs
  }
  // 调试/回归用：一行说清"这次到底演了什么"（console.debug 不干扰常规日志）
  console.debug(
    '[live2d] intent',
    intent.performance || intent.emotion || '',
    '→',
    expr.name || (expr.from === 'reset' ? '(默认)' : '(不变)'),
    motion ? `${motion.group}#${motion.index}` : '(无动作)',
  )

  const holdMs = realMs || (engineMs > 0 ? engineMs : 0) || (motion ? FALLBACK_HOLD_MS : 0)
  intentLease.hold(priority, Date.now() + holdMs)
  if(intent.intent_id&&holdMs>0){
    activeReceipt={intent_id:intent.intent_id,session_id:intent.session_id||''}
    if(!motion)emit('receipt',{type:'avatar:receipt',...activeReceipt,phase:'started',duration_ms:holdMs})
  }
  // 有时长的都是"一次表演"：期间暂停待机，避免两套动作互相打断。
  // 只要暂停过就必须排一次回落，否则待机会永久停摆。
  if (holdMs > 0) stopIdle()
  scheduleRelease(motion?holdMs+10000:holdMs)

  if (expr.from !== 'none' && !exprOk && !motion) {
    console.warn('[live2d] 本次意图没产生任何可见变化:', intent)
  }
  if (expr.from === 'concrete' && expr.name !== String(intent.expression)) {
    // 理论上不会发生（resolveExpression 只在存在时返回 concrete），留作防御
    console.warn('[live2d] 表情名与解析结果不一致:', intent.expression, expr)
  }
}

/* ── 动作 / 表情的动态枚举 ──────────────────────────────────────────────
 * 这里原本把动作组名与表情名写死成某一个模型专属（TapBody / 13 个、
 * expression1~7），一旦换成别的模型就全部失效。现在统一从运行时的
 * motionManager.definitions / expressionManager.definitions 读取，
 * 因此任何模型（hiyori 的 Idle/TapBody/Extra、肥牛的 TapBody、
 * mao_pro 的空组名…）都能正确列出自己的动作与表情。
 * ─────────────────────────────────────────────────────────────────── */

/** 当前模型可用的动作组（含每组动作数），已剔除空组。 */
function listMotions(): { group: string; count: number }[] {
  const mm = model?.internalModel?.motionManager as any
  const defs = mm?.definitions
  if (!defs || typeof defs !== 'object') return []
  return Object.keys(defs)
    .filter((k) => k && Array.isArray(defs[k]) && defs[k].length > 0)
    .map((k) => ({ group: k, count: defs[k].length }))
}

/** 当前模型可用的表情名。 */
function listExpressions(): string[] {
  const mm = model?.internalModel?.motionManager as any
  const defs = mm?.expressionManager?.definitions
  if (!Array.isArray(defs)) return []
  return defs.map((d: any) => String(d?.Name ?? '')).filter(Boolean)
}

/** 播放指定表情（名字来自 listExpressions）——调试台与快捷键都走这里。 */
function playExpression(name: string): void {
  applyExpression(name)
}

/** S14：逐个预览动作（Alt+M）——遍历运行时枚举到的第一组，不再写死组名。 */
let motionPreviewIdx = -1
function cycleMotionPreview(): string {
  const groups = listMotions()
  if (!groups.length) return '(该模型无可用动作)'
  motionPreviewIdx = (motionPreviewIdx + 1) % groups[0].count
  playMotion(groups[0].group, motionPreviewIdx)
  return `${groups[0].group} #${motionPreviewIdx + 1}`
}

/** S05：逐个预览表情（Alt+E）——同样改为运行时枚举。 */
let previewIndex = -1
function cycleExpressionPreview(): string {
  const list = listExpressions()
  if (!list.length) return '(该模型无可用表情)'
  previewIndex = (previewIndex + 1) % list.length
  playExpression(list[previewIndex])
  return list[previewIndex]
}

function playClickFeedback():boolean{
  if(!model||props.preview||Date.now()-lastClickAt<600)return false
  const pool=clickPref.read(currentModelPath.value,manifest.value)
  if(!pool.enabled||!pool.motions.length)return false
  const alternatives=pool.motions.filter(x=>x!==lastClick)
  const choices=alternatives.length?alternatives:pool.motions
  const key=choices[Math.floor(Math.random()*choices.length)]
  const motion=manifest.value?.motions.find(x=>motionKey(x)===key)
  if(!motion)return false
  lastClick=key;lastClickAt=Date.now()
  applyAvatarIntent({motion:motion.group,motion_index:motion.index,duration_ms:motion.durationMs||2600,
    expression_slot:motion.slot==='thinking'?'thinking':['greet','celebrate'].includes(motion.slot)?'happy':undefined,priority:4})
  return true
}
defineExpose({
  playAgentReaction:(intent:AvatarIntentPayload)=>{
    if(props.preview||!idlePref.reactiveEnabled.value||!idlePref.agentReactionsEnabled.value)return
    const motion=resolveMotion(manifest.value,intent)
    // 自动微反应只用有时长的短动作；超长/未知动作保留表情反馈。
    const short=motion&&motion.durationMs>0&&motion.durationMs<=idlePref.agentMaxMs.value
    applyAvatarIntent({...intent,motion:short?motion.group:null,motion_index:short?motion.index:null,
      motion_slot:null,priority:2,source:'activity'})
  },
  preparePreview:async(intent:AvatarIntentPayload,valid:()=>boolean)=>{
    const revision=modelRevision,mm=model?.internalModel?.motionManager as any
    const motion=resolveMotion(manifest.value,intent)
    if(motion){
      let timer:ReturnType<typeof setTimeout>|undefined
      try{
        const loaded=await Promise.race([mm?.loadMotion(motion.group,motion.index),
          new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('动作资源加载超时')),5000)})])
        if(!loaded)throw new Error('动作资源不可用')
      }finally{clearTimeout(timer)}
    }
    if(revision!==modelRevision||!valid())return false
    cancelPerformance();applyAvatarIntent({expression:''});applyAvatarIntent(intent)
    return true
  },
  capturePreview:(head=false)=>{
    const source=canvasRef.value
    if(!source||!app||layout.w<=1||layout.h<=1)return ''
    // layout是画布局部坐标；client包围盒会因页面滚动/吸顶改变，不能用于裁剪。
    const crop=previewCrop(layout,false,source.width,source.height,
      app.renderer.screen.width,app.renderer.screen.height)
    const output=document.createElement('canvas');output.width=180;output.height=240
    const ctx=output.getContext('2d')
    ctx?.drawImage(source,crop.sx,crop.sy,crop.sw,crop.sh,
      crop.dx,crop.dy,crop.dw,crop.dh)
    if(head&&ctx){
      const region=alphaHeadCrop(ctx.getImageData(0,0,180,240).data,180,240)
      const portrait=document.createElement('canvas');portrait.width=180;portrait.height=180
      if(region)portrait.getContext('2d')?.drawImage(source,
        crop.sx+(region.sx-crop.dx)*crop.sw/crop.dw,
        crop.sy+(region.sy-crop.dy)*crop.sh/crop.dh,
        region.sw*crop.sw/crop.dw,region.sh*crop.sh/crop.dh,6,6,168,168)
      return portrait.toDataURL('image/png')
    }
    return output.toDataURL('image/png')
  },
  playClickFeedback,
  getGazeState:()=>({owns:gazeOwns,weight:gazeWeight,focusX:model?.internalModel?.focusController?.x,focusY:model?.internalModel?.focusController?.y}),
  cancelPerformance,
  hitContour,
  getContour: () => contour.value,
  contourStats,
  canvasRef,
  modelRect,
  getModelRect,
  getLocalModelRect:()=>({left:layout.cx-layout.w/2,top:layout.cy-layout.h/2,width:layout.w,height:layout.h}),
  applyAvatarIntent,
  cycleExpressionPreview,
  playMotion,
  cycleMotionPreview,
  // 模型更换与动作/表情枚举（调试台「外观」页使用）
  switchModel,
  getModelPath: () => currentModelPath.value,
  listMotions,
  listExpressions,
  playExpression,
  // 当前表现状态（表情 / 动作 / 回落时间戳）——调试台用它显示"现在在演什么"
  getAvatarState: () => ({ ...avatarState.value }),
})

// 外观变化（调试窗口改窗口尺寸/缩放/偏移）时重新布局
watch(
  () => [appearance.value.fillRatio, appearance.value.yOffset,props.bottomReserve] as const,
  () => layoutModel(),
)

// 待机偏好改动（调试台实时调整）→ 立即按新参数重启调度
watch(
  () => [
    idlePref.enabled.value,
    idlePref.intervalMinMs.value,
    idlePref.intervalMaxMs.value,
    idlePref.maxDurationMs.value,
  ] as const,
  () => { if (model) startIdle() },
)

watch(idlePref.fixedMotion,()=>{
  if(!model)return
  if(avatarState.value.until<=Date.now()){
    (model.internalModel?.motionManager as any)?.stopAllMotions?.()
    avatarState.value.motion='';avatarState.value.motionIndex=null
  }
  startIdle(true)
})

// 聊天坞展开/收起 → 模型区右移/还原，重新布局
watch(() => props.chatOffset, () => layoutModel())

onMounted(() => { void loadModel() })
// 卸载与「切换模型」走同一套拆解逻辑，避免两处清理代码不一致导致泄漏
onBeforeUnmount(teardown)
</script>

<template>
  <div v-if="loadError" class="debug-error">{{ loadError }}</div>
  <canvas ref="canvasRef" class="live2d-canvas" />
  <canvas v-show="contourPref.debug.value" ref="maskView" class="contour-preview" />
</template>

<style scoped>
.contour-preview { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; z-index:4; }
.debug-error {
  position: absolute; top: 8px; left: 8px; z-index: 100;
  max-width: calc(100% - 16px); padding: 8px 12px;
  background: rgba(220, 38, 38, 0.92); color: #fff;
  font-size: 13px; font-family: ui-monospace, monospace;
  border-radius: 6px; line-height: 1.4;
  word-break: break-all; pointer-events: auto;
}
.live2d-canvas {
  width: 100%;
  height: 100%;
  display: block;
  pointer-events: none;
}
</style>
