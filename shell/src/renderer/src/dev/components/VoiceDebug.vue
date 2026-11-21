<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'
import { Icon } from '@iconify/vue'
import { ENGINE_DEBUG_BASE } from '@shared'
import { useConfigStore } from '../stores/config'
import { describeMicError, useAudioDevices } from '../../composables/useAudioDevices'
import MicDevicePicker from '../../components/MicDevicePicker.vue'

type ConnState = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

interface TraceEvent {
  ts: number
  type: string
  summary: string
  detail: string
  tone: 'vad' | 'asr' | 'llm' | 'tts' | 'audio' | 'sys'
}

const configStore = useConfigStore()
// S51：录音设备检测 / 切换 —— 与桌宠聊天坞、日记窗口**共用同一份选择**
const { openStream, listen } = useAudioDevices()
listen()

const connState = ref<ConnState>('idle')
const connError = ref('')
const capturing = ref(false)
const micError = ref('')
const traces = ref<TraceEvent[]>([])
const lastVad = ref('')
const lastAsr = ref('')
const lastLlm = ref('')
const ttsPhase = ref<'idle' | 'synthesizing' | 'playing'>('idle')
const playingTts = ref(false)

let ws: WebSocket | null = null
let audioCtx: AudioContext | null = null
let mediaStream: MediaStream | null = null
let sourceNode: MediaStreamAudioSourceNode | null = null
let processor: ScriptProcessorNode | null = null
let silentSink: GainNode | null = null
let manualDisconnect = false
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0

// 波形：保留最近约 100ms（1600 采样 @16kHz）用于绘制。
const waveBuffer = new Float32Array(1600)
let waveHead = 0
const canvasEl = shallowRef<HTMLCanvasElement | null>(null)
let rafId = 0

const stateLabel = computed<string>(() => {
  switch (connState.value) {
    case 'connecting': return '连接中…'
    case 'open': return '已连接'
    case 'closed': return '已断开'
    case 'error': return '连接错误'
    default: return '未连接'
  }
})

function wsUrl(): string {
  const base = ENGINE_DEBUG_BASE.replace(/^http/, 'ws')
  const secret = (configStore.sections.server?.shared_secret ?? '') as string
  const value = String(secret || '').trim()
  return `${base}/ws/audio${value ? `?secret=${encodeURIComponent(value)}` : ''}`
}

function pushTrace(type: string, summary: string, detail: string, tone: TraceEvent['tone']): void {
  traces.value.push({ ts: Date.now(), type, summary, detail, tone })
  if (traces.value.length > 500) traces.value.splice(0, traces.value.length - 500)
}

function scheduleReconnect(): void {
  if (manualDisconnect || reconnectTimer) return
  const delay = Math.min(1000 * 2 ** reconnectAttempts, 10000)
  reconnectAttempts += 1
  pushTrace('sys', `连接断开，${(delay / 1000).toFixed(0)}s 后自动重连`, '', 'sys')
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connect()
  }, delay)
}

function connect(): void {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
  manualDisconnect = false
  connState.value = 'connecting'
  connError.value = ''
  const socket = new WebSocket(wsUrl())
  socket.binaryType = 'arraybuffer'
  ws = socket

  socket.onopen = () => {
    reconnectAttempts = 0
    connState.value = 'open'
    pushTrace('sys', 'WebSocket 已连接', wsUrl(), 'sys')
  }
  socket.onclose = () => {
    connState.value = 'closed'
    if (!manualDisconnect) {
      pushTrace('sys', 'WebSocket 已关闭', '', 'sys')
      scheduleReconnect()
    } else {
      pushTrace('sys', 'WebSocket 已断开（手动）', '', 'sys')
    }
  }
  socket.onerror = () => {
    connState.value = 'error'
    connError.value = '无法连接引擎 /ws/audio，请确认引擎已启动'
    pushTrace('sys', 'WebSocket 错误', connError.value, 'sys')
  }
  socket.onmessage = (ev) => {
    if (typeof ev.data !== 'string') return
    let msg: Record<string, unknown>
    try {
      msg = JSON.parse(ev.data)
    } catch {
      return
    }
    handleServerMessage(msg)
  }
}

function disconnect(): void {
  manualDisconnect = true
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  ws?.close()
  ws = null
  connState.value = 'idle'
  stopCapture()
}

function handleServerMessage(msg: Record<string, unknown>): void {
  const type = String(msg.type ?? '')
  const sessionId = String(msg.session_id ?? '').slice(0, 8)
  switch (type) {
    case 'vad:state': {
      const state = String(msg.state ?? '')
      const prob = msg.prob !== undefined ? ` · 概率 ${msg.prob}` : ''
      const db = msg.db !== undefined ? ` · 能量 ${msg.db}dB` : ''
      lastVad.value = state === 'active' ? '检测到语音 (active)' : '静音 (inactive)'
      pushTrace('vad:state', `VAD → ${state}`, `state=${state}${prob}${db}`, 'vad')
      break
    }
    case 'vad:error': {
      lastVad.value = 'VAD 错误'
      pushTrace('vad:error', String(msg.message ?? 'VAD 处理失败'), `session=${sessionId}`, 'vad')
      break
    }
    case 'asr:start': {
      lastAsr.value = '识别中…'
      pushTrace('asr:start', '开始语音识别', `session=${sessionId}`, 'asr')
      break
    }
    case 'asr:text': {
      const text = String(msg.text ?? '')
      const dur = msg.duration_ms !== undefined ? ` · 耗时 ${msg.duration_ms}ms` : ''
      lastAsr.value = text
      pushTrace('asr:text', text, `session=${sessionId}${dur}`, 'asr')
      break
    }
    case 'asr:error': {
      lastAsr.value = '识别失败'
      const dur = msg.duration_ms !== undefined ? ` · 耗时 ${msg.duration_ms}ms` : ''
      pushTrace('asr:error', String(msg.message ?? '识别失败'), `session=${sessionId}${dur}`, 'asr')
      break
    }
    case 'llm:start': {
      const input = String(msg.input ?? '')
      lastLlm.value = 'LLM 请求中…'
      pushTrace('llm:start', '发送给 LLM', `input=${input}`, 'llm')
      break
    }
    case 'llm:text': {
      const text = String(msg.text ?? '')
      const dur = msg.duration_ms !== undefined ? ` · 耗时 ${msg.duration_ms}ms` : ''
      lastLlm.value = text
      pushTrace('llm:text', text, `session=${sessionId}${dur}`, 'llm')
      break
    }
    case 'tts:start':
      ttsPhase.value = 'synthesizing'
      playingTts.value = true
      pushTrace('tts:start', '开始合成', `session=${sessionId}`, 'tts')
      break
    case 'tts:synthesize': {
      const text = String(msg.text ?? '')
      ttsPhase.value = 'synthesizing'
      pushTrace('tts:synthesize', 'TTS 合成中', `text=${text.slice(0, 60)}`, 'tts')
      break
    }
    case 'tts:ready': {
      const dur = msg.duration_ms !== undefined ? `${msg.duration_ms}ms · ` : ''
      const wav = msg.wav_bytes !== undefined ? `wav ${msg.wav_bytes}B · ` : ''
      const vols = msg.volumes_count !== undefined ? `${msg.volumes_count} 音量片` : ''
      ttsPhase.value = 'playing'
      pushTrace('tts:ready', '合成完成，播放中', `${dur}${wav}${vols}`, 'tts')
      break
    }
    case 'tts:end':
      ttsPhase.value = 'idle'
      playingTts.value = false
      pushTrace('tts:end', '播放结束', `session=${sessionId}`, 'tts')
      break
    case 'tts:audio': {
      const wav = String(msg.wav ?? '')
      const sampleRate = Number(msg.sample_rate ?? 24000)
      const sliceMs = Number(msg.slice_ms ?? 20)
      const volumes = Array.isArray(msg.volumes) ? msg.volumes.length : 0
      pushTrace('tts:audio', '音频段到达', `${sampleRate}Hz · ${sliceMs}ms · ${volumes} 音量片`, 'audio')
      void playWav(wav)
      break
    }
    default:
      pushTrace(type || 'unknown', String(msg.text ?? ''), JSON.stringify(msg).slice(0, 200), 'sys')
  }
}

function ensureAudioCtx(): AudioContext {
  if (!audioCtx) audioCtx = new AudioContext()
  if (audioCtx.state === 'suspended') void audioCtx.resume()
  return audioCtx
}

async function startCapture(): Promise<void> {
  micError.value = ''
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    micError.value = '请先连接 /ws/audio'
    return
  }
  try {
    // 走共享的 openStream：用**用户选定的麦克风**，设备不在时自动回退系统默认
    mediaStream = await openStream()
  } catch (e) {
    micError.value = describeMicError(e)
    return
  }
  const ctx = ensureAudioCtx()
  sourceNode = ctx.createMediaStreamSource(mediaStream)
  processor = ctx.createScriptProcessor(4096, 1, 1)
  processor.onaudioprocess = (e) => handleAudioFrame(e)
  silentSink = ctx.createGain()
  silentSink.gain.value = 0
  sourceNode.connect(processor)
  processor.connect(silentSink)
  silentSink.connect(ctx.destination)
  capturing.value = true
  pushTrace('sys', '麦克风采集已开启', '16kHz int16 单声道 PCM 上行', 'sys')
  startWaveLoop()
}

function stopCapture(): void {
  capturing.value = false
  stopWaveLoop()
  if (processor) {
    processor.onaudioprocess = null
    processor.disconnect()
    processor = null
  }
  if (sourceNode) {
    sourceNode.disconnect()
    sourceNode = null
  }
  if (silentSink) {
    silentSink.disconnect()
    silentSink = null
  }
  if (mediaStream) {
    for (const track of mediaStream.getTracks()) track.stop()
    mediaStream = null
  }
}

function handleAudioFrame(e: AudioProcessingEvent): void {
  const input = e.inputBuffer.getChannelData(0)
  const pcm = resampleTo16k(input, e.inputBuffer.sampleRate)
  pushWaveSamples(pcm)
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(pcm.slice().buffer)
  }
}

function resampleTo16k(input: Float32Array, inputRate: number): Int16Array {
  const ratio = inputRate / 16000
  const outLen = Math.max(0, Math.floor(input.length / ratio))
  const out = new Int16Array(outLen)
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio
    const idx = Math.floor(pos)
    const frac = pos - idx
    const a = input[idx] ?? 0
    const b = input[idx + 1] ?? a
    const s = a + (b - a) * frac
    out[i] = Math.max(-32768, Math.min(32767, Math.round(s * 32767)))
  }
  return out
}

function pushWaveSamples(pcm: Int16Array): void {
  const n = Math.min(pcm.length, waveBuffer.length)
  const start = Math.max(0, pcm.length - n)
  for (let i = 0; i < n; i++) {
    waveBuffer[waveHead] = pcm[start + i] / 32768
    waveHead = (waveHead + 1) % waveBuffer.length
  }
}

function startWaveLoop(): void {
  stopWaveLoop()
  const draw = (): void => {
    drawWave()
    rafId = requestAnimationFrame(draw)
  }
  rafId = requestAnimationFrame(draw)
}

function stopWaveLoop(): void {
  if (rafId) cancelAnimationFrame(rafId)
  rafId = 0
}

function drawWave(): void {
  const canvas = canvasEl.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const w = canvas.width
  const h = canvas.height
  ctx.clearRect(0, 0, w, h)
  ctx.strokeStyle = '#7c9cff'
  ctx.lineWidth = 1.5
  ctx.beginPath()
  for (let x = 0; x < w; x++) {
    const idx = (waveHead - (w - x) + waveBuffer.length * 2) % waveBuffer.length
    const v = waveBuffer[idx] ?? 0
    const y = h / 2 + v * (h / 2 - 4)
    if (x === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.stroke()
}

async function playWav(wavBase64: string): Promise<void> {
  if (!wavBase64) return
  try {
    const bin = atob(wavBase64)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
    const ctx = ensureAudioCtx()
    const buffer = await ctx.decodeAudioData(bytes.buffer.slice(0))
    const src = ctx.createBufferSource()
    src.buffer = buffer
    src.connect(ctx.destination)
    src.start()
  } catch {
    pushTrace('sys', '音频解码失败', 'wav base64 无法解码为可播放 PCM', 'sys')
  }
}

function sendInterrupt(): void {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'interrupt' }))
    pushTrace('sys', '已发送 interrupt', '打断当前 TTS 播放', 'sys')
  }
}

function timeLabel(ts: number): string {
  const d = new Date(ts)
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

onBeforeUnmount(() => {
  manualDisconnect = true
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  stopCapture()
  ws?.close()
  ws = null
})
</script>

<template>
  <div class="voice-debug">
    <div class="voice-top">
      <div class="card card-conn">
        <h3 class="card-title">语音通道 /ws/audio</h3>
        <div class="conn-row">
          <span class="state-pill" :class="connState">{{ stateLabel }}</span>
          <button v-if="connState !== 'open'" class="btn btn-primary" @click="connect">连接</button>
          <button v-else class="btn" @click="disconnect">断开</button>
        </div>
        <p v-if="connError" class="err-text">{{ connError }}</p>
        <div class="conn-row mt">
          <button class="btn" :disabled="capturing || connState !== 'open'" @click="startCapture">
            {{ capturing ? '采集中' : '开启麦克风' }}
          </button>
          <button class="btn" :disabled="!capturing" @click="stopCapture">停止采集</button>
          <button class="btn btn-warn" :disabled="connState !== 'open'" @click="sendInterrupt">
            interrupt 打断
          </button>
        </div>
        <!-- S51：录音设备的检测与切换（与桌宠 / 日记共用同一份选择，切换下次开麦生效） -->
        <div class="conn-row mt">
          <MicDevicePicker label="录音设备" :disabled="capturing" />
        </div>
        <p v-if="micError" class="err-text">{{ micError }}</p>
      </div>

      <div class="card card-wave">
        <h3 class="card-title">实时波形 <span class="card-sub">16kHz int16 单声道</span></h3>
        <canvas ref="canvasEl" width="480" height="120" class="wave-canvas"></canvas>
      </div>

      <div class="card card-state">
        <h3 class="card-title">链路状态</h3>
        <dl class="kv">
          <div><dt>VAD</dt><dd :class="{ processing: lastVad.startsWith('检测到') }">{{ lastVad || '—' }}</dd></div>
          <div><dt>ASR</dt><dd class="kv-text" :class="{ processing: lastAsr === '识别中…' }">{{ lastAsr || '—' }}</dd></div>
          <div><dt>LLM</dt><dd class="kv-text" :class="{ processing: lastLlm === 'LLM 请求中…' }">{{ lastLlm || '—' }}</dd></div>
          <div><dt>TTS</dt><dd :class="{ processing: ttsPhase === 'synthesizing' }">
            {{ ttsPhase === 'synthesizing' ? '合成中…' : ttsPhase === 'playing' ? '播放中' : '空闲' }}
          </dd></div>
        </dl>
      </div>
    </div>

    <div class="card card-trace">
      <div class="trace-head">
        <h3 class="card-title">链路事件流</h3>
        <button class="btn btn-mini" @click="traces = []">清空</button>
      </div>
      <div class="trace-list">
        <div v-if="traces.length === 0" class="trace-empty">暂无事件，连接并开启麦克风后开始。</div>
        <div v-for="(t, i) in traces" :key="i" class="trace-item" :class="t.tone">
          <span class="trace-time">{{ timeLabel(t.ts) }}</span>
          <span class="trace-type">{{ t.type }}</span>
          <span class="trace-summary">{{ t.summary }}</span>
          <span v-if="t.detail" class="trace-detail">{{ t.detail }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.voice-debug { display: flex; flex-direction: column; gap: 16px; }
.voice-top { display: grid; grid-template-columns: 320px 1fr 300px; gap: 16px; }

.card { border: 1px solid var(--border); border-radius: 14px; background: var(--card); padding: 16px; }
.card-title { margin: 0 0 12px; font-size: 14px; font-weight: 600; }
.card-sub { font-size: 11px; color: var(--muted); font-weight: 400; margin-left: 6px; }

.conn-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.conn-row.mt { margin-top: 14px; }
.state-pill { font-size: 12px; padding: 3px 10px; border-radius: 999px; }
.state-pill.idle { color: var(--muted); background: var(--card-head); }
.state-pill.connecting { color: var(--warn); background: color-mix(in srgb, var(--warn) 14%, transparent); }
.state-pill.open { color: var(--ok); background: color-mix(in srgb, var(--ok) 14%, transparent); }
.state-pill.closed { color: var(--muted); background: var(--card-head); }
.state-pill.error { color: var(--err); background: color-mix(in srgb, var(--err) 14%, transparent); }

.err-text { margin: 8px 0 0; font-size: 12px; color: var(--err); }

.wave-canvas {
  width: 100%;
  height: 120px;
  border-radius: 10px;
  background: var(--input);
  border: 1px solid var(--border-soft);
}

.kv { margin: 0; }
.kv div { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border-soft); font-size: 13px; }
.kv div:last-child { border-bottom: none; }
.kv dt { color: var(--muted); flex-shrink: 0; }
.kv dd { margin: 0; color: var(--text); text-align: right; min-width: 0; }
.kv-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 180px; }
.kv dd.processing { color: var(--warn); animation: kv-pulse 1.2s ease-in-out infinite; }
@keyframes kv-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }

.btn { padding: 7px 14px; border-radius: 8px; border: 1px solid var(--border); background: transparent; color: var(--text); cursor: pointer; font-size: 13px; }
.btn:hover { background: var(--card-head); }
.btn:disabled { opacity: 0.4; cursor: default; }
.btn-primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn-primary:disabled { opacity: 0.4; }
.btn-warn { border-color: color-mix(in srgb, var(--warn) 60%, transparent); color: var(--warn); }
.btn-mini { padding: 4px 10px; font-size: 12px; }

.card-trace { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.trace-head { display: flex; align-items: center; justify-content: space-between; }
.trace-list { flex: 1; max-height: 360px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.trace-empty { font-size: 12px; color: var(--muted); padding: 20px 0; text-align: center; }
.trace-item {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 12px;
  background: var(--card-head);
}
.trace-time { color: var(--muted); font-family: ui-monospace, monospace; flex-shrink: 0; }
.trace-type {
  flex-shrink: 0;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-family: ui-monospace, monospace;
}
.trace-summary { color: var(--text); word-break: break-all; }
.trace-detail { color: var(--muted); font-family: ui-monospace, monospace; margin-left: auto; flex-shrink: 0; }

.trace-item.vad .trace-type { background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); }
.trace-item.asr .trace-type { background: color-mix(in srgb, var(--ok) 16%, transparent); color: var(--ok); }
.trace-item.llm .trace-type { background: color-mix(in srgb, var(--warn) 16%, transparent); color: var(--warn); }
.trace-item.tts .trace-type { background: color-mix(in srgb, #c084fc 16%, transparent); color: #c084fc; }
.trace-item.audio .trace-type { background: color-mix(in srgb, #f472b6 16%, transparent); color: #f472b6; }
.trace-item.sys .trace-type { background: var(--border); color: var(--muted); }
</style>
