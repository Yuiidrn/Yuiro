<script setup lang="ts">
/** 轻量记录编辑器：复用现有独立日记会话，原文直存不经过Agent或LLM。 */
import { computed, onBeforeUnmount, onMounted, ref,watch } from 'vue'
import {useLocalStorage} from '@vueuse/core'
import { Icon } from '@iconify/vue'
import { ENGINE_DEBUG_BASE } from '@shared'
import { useDiaryRecorder } from './useRecorder'
import DiaryPanel from '../dev/components/DiaryPanel.vue'
import { useUiAppearance } from '../composables/useUiAppearance'
import type { DiarySaveRawRequest, DiaryInteractionRequest } from '../../../shared/engine-protocol'
import { useTheme } from '../composables/useTheme'
import '../dev/styles.css'
import DiaryMedia from './DiaryMedia.vue'
import type {DiaryAsset} from '../dev/api'
import MicDevicePicker from '../components/MicDevicePicker.vue'

const ui=useUiAppearance();const {theme}=useTheme()
watch([ui.resolvedSkin,theme],()=>window.yuiro.setDiaryAppearance({skin:ui.resolvedSkin.value,theme:theme.value}),{immediate:true})
const archiveVersion=ref(0)
let disposed=false,draftEpoch=0,connectionEpoch=0,acceptSegments=true,quipTimer=0,quipId=0
const appendBusy=ref(false)
let appendPromise:Promise<boolean>|null=null,appendDone:((ok:boolean)=>void)|null=null,appendText='',appendTimer=0
function finishAppend(ok:boolean){window.clearTimeout(appendTimer);appendBusy.value=false;const resolve=appendDone;appendDone=null;appendPromise=null;if(ok&&draftInput.value.trim()===appendText){draftInput.value=''}resolve?.(ok)}
const quipThinking=ref(false),draftQuip=ref('')
const settingsOpen=ref(false)
const shortOn=useLocalStorage('yuiro-diary-short-enabled',true),paragraphOn=useLocalStorage('yuiro-diary-paragraph-enabled',true),ttsOn=useLocalStorage('yuiro-diary-tts-enabled',false)
const segmentIds=ref<string[]>([]),responses=ref<Record<string,string>>({})
let replyRequest:{id:number,segment:string|null}|null=null,audioEpoch=0
let audioQueue:Promise<void>=Promise.resolve(),currentAudio:HTMLAudioElement|null=null,audioDone:(()=>void)|null=null
let composing=false
let currentRole=localStorage.getItem('yuiro-active-character')||'hiyori'
const roleDrafts=new Map<string,{text:string;title:string;assets:DiaryAsset[]}>()
const diaryTitle=ref(''),attachments=ref<DiaryAsset[]>([]),mediaBusy=ref(false)
const ENGINE_WS = 'ws://127.0.0.1:8200/ws/control'

const conn = ref<'connecting' | 'ok' | 'off'>('connecting')
const active = ref(false)
const segments = ref<string[]>([])
const draftInput = ref('')
/** 可选低频日记回应，默认关闭；独立日记通道，不进入 Agent 工具循环。 */
const status = ref('')

const reviewMode = ref(false)
const preview = ref<{ raw: string; polished: string; note?: string } | null>(null)
const usePolished = ref(false)
const privacy = ref<'local_only' | 'shared' | 'discard'>('local_only')
const busy = ref(false)

const closingReview = ref('')
const done = ref(false)

/** 视图：记录 / 博客归档（保留内部 album 标识以兼容调用）。 */
const mode = ref<'write' | 'album'>('write')

/* ── 「她问」的问题脚本 ────────────────────────────────────────────────────
 * 刻意不做成 LLM 实时生成：问题脚本要**稳**（每次打开都一样、不会卡在加载），
 * 也避免把写日记变成等待模型。她的"回应"是真实的（走聊天链路回传）。
 * 问题按段落依次推进，最后一条会一直沿用（想写多长都行）。
 */
const QUESTIONS = [
  '今天有什么让你停了一下的事？',
  '当时你心里，是什么感觉？',
  '有没有一句想留给明天的话？',
]
/** 每个已记录段落对应的问题（用于回显成"问答"） */
const questions = ref<string[]>([])
/** 段落 index → 她的页边批注 */
const marginalia = ref<Record<number, string>>({})
/** 已转发给桌宠、等待回复的段落 index（FIFO，保证批注不串段） */


const currentQuestion = computed(
  () => QUESTIONS[Math.min(segments.value.length, QUESTIONS.length - 1)],
)

const today = new Date()
const todayLabel = computed(() => {
  const wd = ['日', '一', '二', '三', '四', '五', '六'][today.getDay()]
  return `${today.getMonth() + 1} 月 ${today.getDate()} 日 · 周${wd}`
})

/** 识别任务串行链：多句可能同时返回，串行才能保证**顺序**追加（不乱序）。 */
let transcribeChain: Promise<void> = Promise.resolve()

/** 把一段语音送去识别 —— 结果**追加到输入框**，让用户可以边看边改。 */
async function transcribeIntoDraft(pcm: ArrayBuffer,epoch=draftEpoch): Promise<void> {
  try {
    if(epoch!==draftEpoch||disposed)return
    const secret=await window.yuiro.getEngineSecret()
    if(epoch!==draftEpoch||disposed)return
    const res = await fetch(`${ENGINE_DEBUG_BASE}/api/diary/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream','x-yuiro-secret':secret },
      body: pcm,
    })
    if(epoch!==draftEpoch||disposed)return
    const body = (await res.json()) as { ok?: boolean; text?: string; note?: string }
    if (body.ok && body.text) {
      // ★ 追加到**键入区**（而不是直接成一段）：说一句出来一句，用户能看见、
      // 能改，说完整段再按回车记下 —— 这才是"语音当作输入法"的手感。
      draftInput.value = draftInput.value + body.text
      status.value = ''
    } else if (body.note) {
      status.value = body.note
    }
  } catch {
    if(epoch!==draftEpoch||disposed)return
    status.value = '识别失败（引擎没连上？）'
  }
}

function enqueueTranscribe(pcm: ArrayBuffer): void {
  if(!acceptSegments)return
  const epoch=draftEpoch
  transcribeChain = transcribeChain.then(() => transcribeIntoDraft(pcm,epoch))
}

// 必须**解构出顶层 ref**：Vue 模板只自动解包顶层 ref，嵌套在普通对象里的 ref
// 不会解包 —— `rec.recording` 在模板里是 Ref 对象（恒真、且 `rec.level * 100` 类型报错）。
//
// 语音采用「**静音分句、边说边出字**」：录音器在本地判断句末（尾部静音），
// 每说完一句就把那段送去识别，文字随即出现在输入框。
//
// ★ 刻意**不自动收麦**：写日记是边说边想，停下来思考十几秒是常态 ——
// 自动收麦会把思考当成"说完了"（用户实测反馈）。听多久由用户决定，
// 想停就再点一次麦克风。（停顿本身仍会按句切分，所以"说完一句就出字"不受影响。）
const {
  recording: recRecording,
  level: recLevel,
  error: recError,
  pendingSegments: recPending,
  start: startRecording,
  stop: stopRecording,
} = useDiaryRecorder({
  onSegment: (pcm) => enqueueTranscribe(pcm),
})

let ws: WebSocket | null = null
let reconnectTimer = 0


const canConfirm = computed(() => !!preview.value && !busy.value)

async function wsUrl(): Promise<string> {
  let secret = ''
  try {
    secret = (await window.yuiro?.getEngineSecret?.()) || ''
  } catch {
    secret = ''
  }
  return secret ? `${ENGINE_WS}?secret=${encodeURIComponent(secret)}` : ENGINE_WS
}

function send(payload: Record<string, unknown>): boolean {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    status.value = '引擎未连接，内容仍保留在编辑区'
    return false
  }
  ws.send(JSON.stringify(payload));return true
}

async function connect(): Promise<void> {
  if(disposed)return
  const connection=++connectionEpoch
  conn.value = 'connecting'
  let socket:WebSocket
  try {
    const url=await wsUrl()
    if(disposed||connection!==connectionEpoch)return
    const previous=ws
    socket = new WebSocket(url)
    ws=socket
    previous?.close()
  } catch {
    if(disposed||connection!==connectionEpoch)return
    cancelQuip();conn.value = 'off'
    scheduleReconnect()
    return
  }
  const current=()=>!disposed&&connection===connectionEpoch&&ws===socket
  socket.onopen = (): void => {
    if(!current())return
    conn.value = 'ok'
    send({ type: 'diary:start' })
  }
  socket.onmessage = (e): void => {
    if(!current())return
    try {
      onMessage(JSON.parse(String(e.data)) as Record<string, unknown>)
    } catch {
      /* 非 JSON 帧（理论上没有）忽略 */
    }
  }
  socket.onclose = (): void => {
    if(!current())return
    ws=null
    cancelQuip();finishAppend(false)
    busy.value=false
    conn.value = 'off'
    scheduleReconnect()
  }
  socket.onerror = (): void => {
    if(!current())return
    conn.value = 'off'
  }
}

function scheduleReconnect(): void {
  if(disposed)return
  window.clearTimeout(reconnectTimer)
  reconnectTimer = window.setTimeout(() => void connect(), 2000)
}

/** 段落被删/重排时，把问题与批注裁到同一长度（否则会错位到别的段落上）。 */
function trimAligned(): void {
  const n = segments.value.length
  questions.value = questions.value.slice(0, n)
  for (const key of Object.keys(marginalia.value)) {
    if (Number(key) >= n) delete marginalia.value[Number(key)]
  }
}

function onMessage(msg: Record<string, unknown>): void {
  const type = String(msg.type || '')
  switch (type) {
    case 'diary:state':
      if (msg.active === false) {
        active.value = false
        status.value = '日记会话已结束'
      } else {
        active.value = true
        status.value = ''
      }
      break
    case 'diary:draft': {
      const segs = msg.segments as string[] | undefined
      const previous=segments.value
      segments.value = segs ?? (msg.text ? String(msg.text).split('\n\n') : [])
      segmentIds.value=Array.isArray(msg.segment_ids)?msg.segment_ids as string[]:segments.value.map((text,i)=>previous[i]===text&&segmentIds.value[i]?segmentIds.value[i]:crypto.randomUUID())
      trimAligned()
      if(appendDone&&segments.value.at(-1)===appendText)finishAppend(true)
      break
    }
    case 'diary:response': {
      const request=replyRequest
      if(!request||msg.request_id!==request.id)break
      quipThinking.value=false
      const text=String(msg.text||'')
      if(request.segment&&segmentIds.value.includes(request.segment))responses.value[request.segment]=text
      else if(!request.segment)draftQuip.value=text
      if(msg.note)status.value=String(msg.note)
      break
    }
    case 'diary:audio': {
      if(!ttsOn.value||!replyRequest||msg.request_id!==replyRequest.id)break
      const epoch=audioEpoch,wav=String(msg.wav||'')
      audioQueue=audioQueue.then(async()=>{
        if(epoch!==audioEpoch)return
        await new Promise<void>(resolve=>{
          audioDone=resolve;const audio=new Audio('data:audio/wav;base64,'+wav);currentAudio=audio
          audio.onended=()=>resolve();audio.onerror=()=>resolve()
          void audio.play().catch(()=>{if(epoch===audioEpoch)status.value='语音播放失败，文字仍保留';resolve()})
        })
      })
      break
    }
    case 'diary:response_end':
      if(replyRequest&&msg.request_id===replyRequest.id){quipThinking.value=false;if(msg.note)status.value=String(msg.note)}
      break
    case 'diary:preview':
      busy.value = false
      if (msg.ok) {
        preview.value = {
          raw: String(msg.raw_text || ''),
          polished: String(msg.polished_text || msg.raw_text || ''),
        }
        // 解构失败时仍然可落库（§2.3：记忆绝不丢失），但要如实说
        if (!msg.deconstructed) status.value = '这篇没能整理出结构，原文照样能存'
        reviewMode.value = true
      } else {
        status.value = String(msg.note || '提交失败')
      }
      break
    case 'diary:submitted':
      busy.value = false
      if (msg.ok) {
        roleDrafts.delete(currentRole)
        draftInput.value = '';diaryTitle.value='';attachments.value=[]
        done.value = true
        preview.value = null
        reviewMode.value = false
        segments.value = []
        questions.value = []
        marginalia.value = {}

        status.value =
          privacy.value === 'discard' ? '已经扔掉，什么都没留下' : '记下了'
        archiveVersion.value++
      } else {
        status.value = String(msg.note || '保存失败')
      }
      break
    case 'diary:review':
      closingReview.value = String(msg.text || '')
      break
    case 'diary:recall_hint':
      status.value = '可在“所有记录”中浏览'
      break
    case 'diary:error':
      finishAppend(false)
      busy.value = false
      status.value = String(msg.note || '出错了')
      break
    default:
      break
  }
}

// ── 输入 ──────────────────────────────────────────────────────────────────
/** 追加经引擎确认后才清空输入；可选回应走独立日记通道，不转发Agent。 */
function commitSegment(allowBusy=false): Promise<boolean> {
  if(appendPromise)return appendPromise
  if((busy.value&&!allowBusy)||!active.value||conn.value!=='ok')return Promise.resolve(false)
  const text=draftInput.value.trim();if(!text)return Promise.resolve(true)
  appendBusy.value=true;appendText=text;appendPromise=new Promise(resolve=>{appendDone=resolve})
  const result=appendPromise
  if(!send({type:'diary:append',text,literal:true})){finishAppend(false);return result}
  appendTimer=window.setTimeout(()=>{finishAppend(false);busy.value=false;status.value='未确认追加，输入内容仍保留，请检查连接后再试'},8000)
  return result
}

function stopDiaryAudio(){audioEpoch++;currentAudio?.pause();audioDone?.();audioDone=null;currentAudio=null;audioQueue=Promise.resolve()}
function cancelQuip():void{
  if(replyRequest)send({type:'diary:quip_cancel'})
  replyRequest=null;quipThinking.value=false;stopDiaryAudio()
}
function requestCompanion(text:string,kind:'short'|'paragraph',segment:string|null=null){
  if(!text.trim()||busy.value||conn.value!=='ok')return
  cancelQuip();replyRequest={id:++quipId,segment};quipThinking.value=true
  send({type:'diary:interact',request_id:replyRequest.id,text,kind,segment_id:segment,tts:ttsOn.value} satisfies DiaryInteractionRequest)
}
async function appendAndRespond(){
  const text=draftInput.value.trim();if(!text||busy.value)return
  cancelQuip()
  if(await commitSegment()){
    const id=segmentIds.value.at(-1)
    if(paragraphOn.value&&id)requestCompanion(text,'paragraph',id)
  }
}
function editorKey(e:KeyboardEvent){
  if(e.key!=='Enter'||e.isComposing||composing)return
  if(e.ctrlKey){e.preventDefault();void appendAndRespond();return}
  if(e.shiftKey)return
  const target=e.target as HTMLTextAreaElement
  const line=target.value.slice(0,target.selectionStart).split('\n').at(-1)||''
  if(shortOn.value)requestCompanion(line,'short')
}
function compositionStart(){composing=true}
function compositionEnd(){composing=false}
watch([busy,reviewMode,mode],()=>{if(busy.value||reviewMode.value||mode.value!=='write')cancelQuip()})
watch(ttsOn,()=>{if(!ttsOn.value){stopDiaryAudio();if(replyRequest)send({type:'diary:quip_cancel'})}})

/** 只取第一句、限长 —— 页边批注要短，长了会喧宾夺主。 */
function firstSentence(text: string): string {
  const t = String(text || '').replace(/\s+/g, ' ').trim()
  if (!t) return ''
  const m = t.match(/^[^。！？!?…]{1,60}[。！？!?…]?/)
  return (m?.[0] || t).slice(0, 60)
}

function undo(): void {
  if(busy.value||!send({ type: 'diary:undo' }))return
  cancelQuip()
  questions.value.pop()
  const last = segments.value.length - 1
  if (last >= 0) delete marginalia.value[last]
}

// ── 语音：一次点击开始，边说边出字（识别结果进输入框，不直接成段）─────────
async function toggleVoice(): Promise<void> {
  if (recRecording.value) {
    await stopRecording()
    status.value = ''
    return
  }
  const ok = await startRecording()
  if (!ok) {
    status.value = recError.value
    return
  }
  status.value = '在听了 —— 说完一句字就出来；中途想多久都行，想停再点一下麦克风'
}

// ── 提交与确认 ────────────────────────────────────────────────────────────
async function prepareSave(raw:boolean):Promise<void>{
  if(busy.value||mediaBusy.value||conn.value!=='ok'||!active.value)return
  const epoch=draftEpoch;busy.value=true
  try{
    if(recRecording.value)await stopRecording()
    await transcribeChain
    if(epoch!==draftEpoch)return
    if(!await commitSegment(true)){busy.value=false;return}
    status.value=raw?'正在保存原文…':'正在整理，原文保留…'
    if(!send(raw?({type:'diary:save_raw',privacy:privacy.value,title:diaryTitle.value,attachment_ids:attachments.value.map(x=>x.id)} satisfies DiarySaveRawRequest):{type:'diary:submit'}))busy.value=false
  }catch(e){busy.value=false;status.value=String(e)}
}
function submit(){void prepareSave(false)}
function saveRaw(){void prepareSave(true)}

function confirmSave(): void {
  if(busy.value||!preview.value)return
  busy.value = true
  if(!send({
    type: 'diary:confirm',
    title:diaryTitle.value,attachment_ids:attachments.value.map(x=>x.id),
    privacy: privacy.value,
    quip_mode: false,
    use_polished: usePolished.value,
  }))busy.value=false
}

function cancelReview(): void {
  reviewMode.value = false
  preview.value = null
}

function writeAgain(): void {
  cancelQuip();draftEpoch++;draftInput.value='';diaryTitle.value='';attachments.value=[];privacy.value='local_only'
  responses.value={};segmentIds.value=[];draftQuip.value=''
  done.value = false
  closingReview.value = ''
  status.value = ''
  mode.value = 'write'
  send({ type: 'diary:start' })
}

function exitDiary(): void {
  if(!done.value&&(segments.value.length||draftInput.value.trim())&&!window.confirm('还有未保存内容，确定关闭并丢弃本次草稿？'))return
  cancelQuip();draftEpoch++;acceptSegments=false
  if(recRecording.value)void stopRecording()
  send({ type: 'diary:exit' })
  window.setTimeout(() => window.close(), 120)
}

async function switchTo(next:'write'|'album'){
  if(next==='album'&&recRecording.value)await stopRecording()
  cancelQuip();mode.value=next
}
function roleChanged(e:StorageEvent){
  if(e.key!=='yuiro-active-character'||!e.newValue||e.newValue===currentRole)return
  roleDrafts.set(currentRole,{text:[...segments.value,draftInput.value].filter(Boolean).join('\n\n'),title:diaryTitle.value,assets:attachments.value})
  cancelQuip();finishAppend(false);acceptSegments=false;draftEpoch++;connectionEpoch++;window.clearTimeout(quipTimer)
  if(recRecording.value)void stopRecording().finally(()=>{acceptSegments=true});else acceptSegments=true
  ws?.close();currentRole=e.newValue;segments.value=[];segmentIds.value=[];responses.value={};draftQuip.value='';questions.value=[];marginalia.value={};draftInput.value=roleDrafts.get(currentRole)?.text||'';diaryTitle.value=roleDrafts.get(currentRole)?.title||'';attachments.value=roleDrafts.get(currentRole)?.assets||[]
  reviewMode.value=false;preview.value=null;busy.value=false;done.value=false;active.value=false;closingReview.value='';privacy.value='local_only'
  ui.setCharacter(currentRole);archiveVersion.value++;void connect()
}
onMounted(() => {
  window.addEventListener('storage',roleChanged)
  void connect()


})
onBeforeUnmount(() => {
  cancelQuip();finishAppend(false);disposed=true;draftEpoch++;connectionEpoch++;acceptSegments=false;window.clearTimeout(quipTimer);window.removeEventListener('storage',roleChanged)
  window.clearTimeout(reconnectTimer)

  if (recRecording.value) void stopRecording()
  ws?.close()
})
</script>

<template>
 <div class="journal-app">
  <header class="journal-bar"><div><span class="journal-brand">日常</span><span class="journal-date">{{todayLabel}}</span></div><nav><button :class="{selected:mode==='write'}" @click="switchTo('write')">写记录</button><button :class="{selected:mode==='album'}" @click="switchTo('album')">所有记录</button></nav><span class="connection" :class="conn" :title="conn==='ok'?'已连接':conn==='connecting'?'连接中':'离线'" :aria-label="conn==='ok'?'已连接':'连接未就绪'" role="status"></span><button @click="settingsOpen=!settingsOpen" :aria-expanded="settingsOpen" aria-label="日记设置" title="日记设置" class="settings-trigger"><Icon icon="solar:tuning-2-linear" width="20"/></button></header>
  <Transition name="settings"><aside v-if="settingsOpen" class="diary-settings" @keydown.esc="settingsOpen=false"><button class="text-button" @click="settingsOpen=false">关闭设置</button><h2>日记陪伴</h2><label><input v-model="shortOn" type="checkbox"/>Enter 换行时短回应</label><label><input v-model="paragraphOn" type="checkbox"/>Ctrl+Enter 追加段落后完整回应</label><label><input v-model="ttsOn" type="checkbox"/>朗读陪伴回应（当前角色声音）</label><button class="text-button" @click="cancelQuip">停止回应与播放</button><details class="settings-help"><summary>快捷键与保存说明</summary><p class="subtle">Shift+Enter 仅换行。草稿暂存于当前会话，保存前请勿关闭。既有记忆只读，日记共享由你选择。</p></details><label>保存范围<select v-model="privacy"><option value="local_only">仅日记保存</option><option value="shared">共享到角色记忆</option></select></label><button class="btn" :disabled="busy" @click="submit">整理后审阅</button></aside></Transition>
  <main class="journal-content">
   <DiaryPanel v-if="mode==='album'" :key="archiveVersion" embedded @write="switchTo('write')" />
   <section v-else class="journal-editor">
    <template v-if="done"><span class="journal-kicker">SAVED</span><h1>{{privacy==='discard'?'本次内容未保存':'已经记下了'}}</h1><p class="subtle">可以继续写，也可以去看看以前的记录。</p><p v-if="closingReview">{{closingReview}}</p><div class="actions"><button class="btn btn-primary" @click="writeAgain">新记录</button><button class="btn" @click="switchTo('album')">所有记录</button></div></template>
    <template v-else-if="reviewMode&&preview"><button class="text-button" :disabled="busy" @click="cancelReview">← 继续编辑</button><h1>审阅记录</h1><p class="subtle">原文始终保留，由你决定保存哪一版。</p><div class="review-options"><label><input v-model="usePolished" type="radio" :value="false"/>保存原文</label><label><input v-model="usePolished" type="radio" :value="true"/>采用整理稿</label></div><pre class="review-text">{{usePolished?preview.polished:preview.raw}}</pre><button class="btn btn-primary" :disabled="!canConfirm" @click="confirmSave">{{busy?'保存中…':'确认保存'}}</button></template>
    <template v-else><input v-model="diaryTitle" class="diary-title" maxlength="160" placeholder="给今天起个标题…" aria-label="日记标题" :disabled="busy"/>
     <div v-if="segments.length" class="draft-segments"><div v-for="(seg,i) in segments" :key="i"><p>{{seg}}</p><div v-if="responses[segmentIds[i]]" class="diary-aside">{{responses[segmentIds[i]]}}</div></div><button class="text-button" :disabled="busy" @click="undo">撤销最后一段</button></div>
     <textarea @compositionstart="compositionStart" @compositionend="compositionEnd" v-model="draftInput" class="journal-input" rows="7" placeholder="从这里开始，慢慢写…" :disabled="busy||appendBusy" aria-label="日记正文" @keydown="editorKey" />
     <p v-if="draftQuip" class="diary-aside" aria-live="polite">{{draftQuip}}</p>
     <span v-if="quipThinking" class="quip-status" role="status">在旁边想一句…</span>
     <div class="editor-meta"><span>{{segments.join('').length+draftInput.length}} 字</span><button class="text-button" :disabled="busy||!draftInput.trim()||conn!=='ok'" @click="appendAndRespond()" title="Ctrl+Enter 追加并回应">追加段落 <span class="key-hint">Ctrl ↵</span></button></div>
     <DiaryMedia :key="currentRole" v-model="attachments" :disabled="busy" @busy="mediaBusy=$event"/>
     <div class="record-tools"><button class="btn" :disabled="busy||conn!=='ok'" @click="toggleVoice"><Icon :icon="recRecording?'solar:stop-circle-bold':'solar:microphone-3-bold'" width="16"/>{{recRecording?'停止录音':'语音输入'}}</button><MicDevicePicker compact label="麦克风" :disabled="recRecording||busy"/><span v-if="recPending" class="subtle">识别中…</span><span v-if="recRecording" class="mic-level" :style="{opacity:.3+recLevel*.7}">正在录音</span><button class="btn btn-primary save-inline" :disabled="busy||mediaBusy||conn!=='ok'||!active||(!segments.length&&!draftInput.trim()&&!diaryTitle.trim()&&!attachments.length&&!recRecording)" @click="saveRaw">{{busy?'处理中…':'保存原文'}}</button></div>

    </template>
    <p v-if="status" class="editor-status" role="status">{{status}}</p>
   </section>
  </main>
 </div>
</template>
<style scoped>
.diary-settings{position:fixed;right:0;top:100px;bottom:0;width:min(340px,90vw);box-sizing:border-box;z-index:10;background:var(--bg);color:var(--text);border-left:1px solid var(--border);padding:24px;overflow:auto;box-shadow:-8px 0 30px #0002}.diary-settings label{display:block;margin:20px 0;font-size:13px}.diary-settings select{display:block;margin-top:10px}.diary-aside{white-space:pre-wrap;font-size:13px;color:var(--accent);border-left:2px solid var(--border);padding-left:12px;line-height:1.8}.quip-status{font-size:11px;color:var(--muted)}.quip-pace{display:block;margin-top:10px}
.journal-app{height:100vh;display:flex;flex-direction:column;background:var(--bg);color:var(--text);font-family:'Segoe UI','Microsoft YaHei',sans-serif}.journal-bar{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:48px 24px 18px;border-bottom:1px solid var(--border-soft);-webkit-app-region:drag}.journal-brand{font-size:11px;letter-spacing:.18em;color:var(--accent)}.journal-date{font-size:11px;color:var(--muted);margin-left:12px}.journal-bar nav{display:flex;gap:6px;margin-left:auto}.journal-bar button{border:0;background:transparent;color:var(--text-soft);font:inherit;font-size:12px;padding:7px 10px;border-radius:8px;cursor:pointer;-webkit-app-region:no-drag}.journal-bar button.selected{background:var(--accent-soft);color:var(--accent)}.connection{font-size:10px;color:var(--muted)}.journal-content{flex:1;min-height:0;overflow:auto;padding:32px 24px 48px}.journal-editor{max-width:720px;margin:auto}.journal-kicker{font-size:10px;letter-spacing:.14em;color:var(--muted)}h1{font-size:25px;font-weight:500;line-height:1.5;margin:12px 0}.subtle{font-size:12px;line-height:1.8;color:var(--text-soft)}.journal-input{display:block;width:100%;min-height:190px;resize:vertical;box-sizing:border-box;margin-top:24px;padding:16px 0;background:transparent;border:0;border-bottom:1px solid var(--border);border-radius:0;font:16px/1.9 'Segoe UI','Microsoft YaHei',sans-serif;color:var(--text)}.journal-input:focus{outline:none;border-bottom-color:var(--accent)}.editor-meta{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:10px;color:var(--muted);margin-top:10px}.text-button{border:0;background:none;color:var(--accent);font:inherit;font-size:12px;cursor:pointer;padding:5px 0}.record-tools,.actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:24px 0}.record-tools .btn{display:flex;align-items:center;gap:6px}.save-options{border-top:1px solid var(--border-soft);padding-top:18px;font-size:12px;line-height:1.8}.save-options select{margin-left:8px;padding:6px;border:1px solid var(--border);border-radius:7px;color:inherit;background:var(--input)}.save-options details{margin-top:16px}.save-options summary{cursor:pointer;color:var(--muted)}.draft-segments{margin:24px 0;font-size:16px;line-height:1.9}.draft-segments p{white-space:pre-wrap}.draft-segments small{color:var(--accent)}.review-options{display:flex;gap:20px;margin-top:20px;font-size:13px}.review-text{font:15px/1.9 'Segoe UI','Microsoft YaHei',sans-serif;white-space:pre-wrap;overflow-wrap:anywhere;margin:24px 0}.editor-status{font-size:12px;color:var(--text-soft);line-height:1.7}.btn:disabled,.text-button:disabled{opacity:.5;cursor:default}.mic-level{font-size:11px;color:var(--accent)}

/* 内容优先：紧凑导航、宽松正文、按需设置。 */
.journal-bar{padding:42px clamp(20px,4vw,48px) 14px;gap:14px;min-height:42px;flex-wrap:nowrap;border-bottom-color:var(--border-soft)}
.journal-brand{font-size:16px;letter-spacing:.08em;font-weight:600;color:var(--text)}
.journal-date{font-size:12px;letter-spacing:0;margin-left:16px}
.journal-bar nav{background:var(--card);border:1px solid var(--border-soft);padding:4px;border-radius:14px;gap:2px}
.journal-bar nav button{padding:8px 16px;border-radius:10px;transition:background .18s ease,color .18s ease,box-shadow .18s ease}
.journal-bar nav button.selected{box-shadow:0 2px 8px #00000008}
.journal-bar .settings-trigger{display:grid;place-items:center;width:38px;height:38px;padding:0;border:1px solid var(--border-soft);border-radius:12px;transition:background .18s ease,transform .18s ease}
.settings-trigger:hover,.settings-trigger[aria-expanded=true]{background:var(--accent-soft)}
.settings-trigger:active{transform:scale(.96)}
.connection{width:6px;height:6px;border-radius:50%;background:var(--muted);flex-shrink:0;-webkit-app-region:no-drag}.connection.ok{background:var(--accent)}.connection.off{background:var(--err)}
.journal-content{padding:clamp(24px,4vh,44px) clamp(24px,6vw,72px) 40px;scrollbar-width:thin;scrollbar-color:var(--border) transparent}
.journal-editor{max-width:920px;width:100%;animation:page-in .22s ease both}
.journal-editor h1{font-size:clamp(23px,2.8vw,30px);font-weight:500;margin:8px 0 24px;letter-spacing:.01em}
.journal-input{min-height:clamp(220px,35vh,380px);margin-top:12px;line-height:2;font-size:17px;transition:border-color .2s ease}.journal-input::placeholder{color:var(--muted);opacity:.8}
.editor-meta{font-size:12px;align-items:center}.key-hint{margin-left:8px;font-size:11px;color:var(--muted)}
.record-tools{margin:24px 0 18px}.actions{border-top:1px solid var(--border-soft);padding-top:20px;margin-top:24px;gap:20px}
.diary-aside{padding:12px 16px;border-radius:0 10px 10px 0;background:var(--card);font-size:14px;animation:page-in .2s ease both}
.diary-settings{top:104px;right:16px;bottom:16px;width:min(360px,calc(100vw - 32px));border:1px solid var(--border-soft);border-radius:18px;padding:24px;box-shadow:0 12px 40px #00000012;scrollbar-width:thin}
.diary-settings h2{font-size:20px;font-weight:500;margin:20px 0}.diary-settings label{padding:14px 0;margin:0;border-bottom:1px solid var(--border-soft);line-height:1.7}.diary-settings input{accent-color:var(--accent);margin-right:8px}.diary-settings select{width:100%;padding:10px;border-radius:9px;border:1px solid var(--border);background:var(--card);color:var(--text)}.diary-settings>.btn{margin-top:20px}.settings-help{margin:20px 0;font-size:12px;color:var(--muted)}.settings-help summary{cursor:pointer}
.settings-enter-active,.settings-leave-active{transition:opacity .2s ease,transform .2s ease}.settings-enter-from,.settings-leave-to{opacity:0;transform:translateX(16px)}
button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
@keyframes page-in{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
@media(max-width:600px){.journal-bar{padding-inline:16px;gap:9px;flex-wrap:wrap}.journal-date{display:none}.journal-bar nav button{padding:8px 10px}.journal-content{padding:24px 20px}.journal-input{font-size:16px}.key-hint{display:none}}
@media(prefers-reduced-motion:reduce){.journal-app *{animation:none!important;transition:none!important}}

.diary-title{display:block;width:100%;box-sizing:border-box;border:0;background:transparent;color:var(--text);font:500 clamp(23px,2.8vw,30px)/1.6 "Segoe UI","Microsoft YaHei",sans-serif;padding:4px 0 14px;outline:none}.diary-title:focus{box-shadow:0 1px var(--border)}.diary-title::placeholder{color:var(--muted)}.save-inline{margin-left:auto}.record-tools{border-top:1px solid var(--border-soft);padding-top:20px}
</style>
