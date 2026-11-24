import { inputLevel as measureInputLevel } from '../utils/inputLevel'
import { ref } from 'vue'
import { PlaybackAdmission } from '../../../shared/playback-admission'
import type { SpeechPlaybackIdentity, SpeechPlaybackReceipt } from '../../../shared/engine-protocol'
import { describeMicError, useAudioDevices } from './useAudioDevices'

/**
 * Voice input via mic → WS /ws/audio → engine voice pipeline.
 *
 * - 采音：getUserMedia (mono, AEC, noiseSuppression) → ScriptProcessor(4096)
 *   → 线性重采样到 16kHz int16 → 裸二进制帧发 /ws/audio
 * - 下行：接收引擎全链路事件（vad:state / asr:* / llm:* / tts:*），维护
 *   pipelineState 供 UI 显示反馈；tts:audio → 播放 + volumes 驱动 mouthOpen。
 *
 * S53：除引擎事件外，本模块还会**本地合成**一个 `tts:playback_end` 事件 ——
 * 引擎的 `tts:end` 只代表音频段已下发完，不代表已播完；气泡/口型之类的 UI
 * 需要"真的播完"这个时刻，所以由播放队列（`drainPlayQueue` 的最后一段 onended）
 * 在这里判定并发出去。打断路径不发它（由 `tts:interrupted` 收尾）。
 *
 * @param onEvent 可选回调：转发引擎链路事件 + 上述本地合成事件（type + payload）。
 */
export function useVoiceInput(onEvent?: (type: string, payload: Record<string, unknown>) => void) {
  const speaking = ref(false)
  let disposed=false,closingAudio:Promise<void>|null=null
  const inputLevel = ref(0)
  /**
   * 是否有**回合正在进行**（识别 → LLM → TTS 播放）。
   *
   * 为什么不能复用 `pipelineState`：它那一格 `llm` 只会被 `llm:start` / `llm:text`
   * 写入、**从不复位**，拿它判断"她还在说吗"永远为真（每条消息都会空打断一次）。
   * 这里用事件驱动一个明确的布尔：`asr:start` 置真；
   * `tts:end` / `tts:interrupted` / `asr:error` 置假 —— 语义单一、可靠。
   *
   * 用途：文字链路**发新消息即打断旧回合**（改口），见 App.vue 的 `sendText`。
   */
  const turnBusy = ref(false)

  /**
   * 插话打断开关（引擎配置 `vad.barge_in_enabled` 的前端镜像，**默认关**）。
   *
   * ⚠ 它管的**不只是引擎**：关闭时，她说话期间**话筒要静默** —— 不上行、
   * 不识别、不排队（见 `onaudioprocess` 里的门控）。用户明确要的效果是
   * "屏蔽桌宠说话时的收音和请求"，而不只是"引擎侧不打断"。
   */
  const bargeInEnabled = ref(false)

  // （不用字符串比较 `pipelineState.tts` 判"她在说"：那既晚又脆，
  //   改文案就会失效。改用事件驱动的 `turnBusy` —— 从 asr:start 到 tts:end
  //   全程为真，正好与引擎侧提前置位的 `_speaking` 对齐。）

  /** 从引擎配置读真实状态（单一真相源：聊天坞图标与调试台卡片是同一个开关）。 */
  let bargeRead=0
  async function loadBargeIn(): Promise<void> {
    const request=++bargeRead,role=localStorage.getItem('yuiro-active-character')||'hiyori'
    try {
      const secret=await window.yuiro?.getEngineSecret?.()||''
      const res = await fetch(`${ENGINE_API}/config`,{headers:{'x-yuiro-secret':secret,'x-yuiro-character':role}})
      if(!res.ok)return
      const data = await res.json()
      // 段名两种都试：FIELD_META 里叫 `vad`，config.toml 表名是 `hard_of_hearing`
      const sec = (data?.sections ?? {}) as Record<string, { barge_in_enabled?: boolean }>
      const v = sec.vad?.barge_in_enabled ?? sec.hard_of_hearing?.barge_in_enabled
      if (!disposed&&request===bargeRead&&role===(localStorage.getItem('yuiro-active-character')||'hiyori')&&typeof v === 'boolean') bargeInEnabled.value = v
    } catch {
      /* 引擎未起：保持原状，不臆测 */
    }
  }
  const mouthOpen = ref(0)
  // 引擎语音管线冷启动状态（pipeline:state 事件驱动）
  const engineReady = ref(false)
  const pipelineLoading = ref(false)
  const loadingStage = ref('')
  const loadingProgress = ref(0)
  // 链路状态（供 UI 反馈）：vad / asr / llm / tts
  // 初始值统一为中文"空闲"，与 App.vue 模板判断 pipelineState.tts !== '空闲' 一致，
  // 避免首次开启语音时 TTS 默认闪烁 + 显示英文 idle 文本。
  const pipelineState = ref<{
    vad: string
    asr: string
    llm: string
    tts: string
  }>({ vad: '空闲', asr: '空闲', llm: '空闲', tts: '空闲' })

  let audioCtx: AudioContext | null = null
  let resettingOutput:Promise<void>|null=null
  let mediaStream: MediaStream | null = null
  let sourceNode: MediaStreamAudioSourceNode | null = null
  let processor: ScriptProcessorNode | null = null
  let silentSink: GainNode | null = null
  let ws: WebSocket | null = null
  let mouthRaf = 0
  let mouthStart = 0
  let mouthVolumes: number[] = []
  let mouthSliceMs = 20
  // TTS 有序播放队列：后端可能按句流式回传多个 tts:audio 段，
  // 必须 FIFO 串行播放（decodeAudioData 异步，先解码完的段会先 start 导致乱序/重叠）。
  type PlayItem={wav:string;sampleRate:number;sliceMs:number;volumes:number[];identity?:SpeechPlaybackIdentity;streaming?:boolean}
  let playQueue:PlayItem[]=[]
  const maxQueuedBytes=16*1024*1024
  const maxDecodeAheadSeconds=2
  const decodeWake=new Set<()=>void>()
  let queuePeakBytes=0, underrunCount=0, underrunGapMs=0
  function bufferedBytes():number {
    return playQueue.reduce((n,item)=>n+item.wav.length*2+item.volumes.length*8,0)
  }
  const playbackAdmission = new PlaybackAdmission()
  type StreamEntry=PlayItem&{source:AudioBufferSourceNode;start:number;end:number;started:boolean;epoch:number}
  let streamEntries:StreamEntry[]=[]
  let streamCursor=0,streamStartTimer:ReturnType<typeof setTimeout>|undefined
  let streamLastEnd=0
  let streamNeedsRebuffer=false
  let streamGroup=''
  let streamRebufferTarget=.96
  let rebufferWake:(()=>void)|undefined
  function queuedStreamSeconds():number {
    let duration=0
    for(const item of playQueue){
      if(!item.streaming)break
      duration+=item.volumes.length*item.sliceMs/1000
    }
    return duration
  }
  function wakeRebuffer(force=false):void {
    if(force||engineSentAll||queuedStreamSeconds()>=streamRebufferTarget)rebufferWake?.()
  }
  async function waitForRebuffer():Promise<void> {
    if(!streamNeedsRebuffer||engineSentAll||queuedStreamSeconds()>=streamRebufferTarget)return
    emit('tts:playback_buffering',{})
    // 已经断供时积累约2–4块再续读；单块尾句或故障不能无限等后继。
    await new Promise<void>(resolve=>{
      const timer=setTimeout(done,1500)
      function done():void {
        clearTimeout(timer)
        if(rebufferWake===done)rebufferWake=undefined
        resolve()
      }
      rebufferWake=done
    })
  }
  const streamWaiters:Array<()=>void>=[]
  function notifyStreamStart(entry:StreamEntry):void {
    if(entry.started||entry.epoch!==playbackEpoch)return
    entry.started=true
    emit('tts:playback_start',{})
    playbackReceipt('audio:playback_started',entry.identity)
  }
  function tickStreamStarts():void {
    streamStartTimer=undefined
    const now=audioCtx?.currentTime??0
    for(const entry of streamEntries)if(entry.start<=now)notifyStreamStart(entry)
    const next=streamEntries.find(entry=>!entry.started)
    if(next)streamStartTimer=setTimeout(tickStreamStarts,Math.max(4,Math.min(25,(next.start-now)*1000)))
  }
  let currentPlaybackIdentity:SpeechPlaybackIdentity|undefined
  let voiceSessionId=''
  let audioGeneration=-1
  function playbackReceipt(type:SpeechPlaybackReceipt['type'],identity?:SpeechPlaybackIdentity):void {
    if(identity && ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type,...identity} satisfies SpeechPlaybackReceipt))
  }
  let playRunning = false
  // S03：当前正在播放的 source 与唤醒回调 —— 打断时立即停播（本地操作，不等引擎）
  let currentSource: AudioBufferSourceNode | null = null
  let currentPlayResolve: (() => void) | null = null

  /**
   * S53：判断"她这一轮真的说完（播完）了"所需的两个信号。
   *
   * 为什么不能直接用引擎的 `tts:end`：它只代表**音频段已经全部下发给前端**
   * （引擎把 `tts:audio` 发完就收了），此时本地队列可能还在播好几秒。
   * 所以必须"引擎说再无新段" + "本地队列播空"同时成立，才算播完。
   */
  let engineSentAll = false   // 引擎已声明不再有新段（tts:end / tts:reply_end）
  let pendingSegments = 0     // 已入队但尚未播完的段数（含正在播的那段）
  // 本轮是否**真正入队过音频**（有声）。区分"播完收气泡"与"压根没音频→退回字数估算"：
  // 统一 TTS 开关关闭 / 合成失败时没有任何音频，此时不该发 `tts:playback_end`
  // （否则气泡会在 tts:end 后 ~200ms 就消失，用户根本来不及看），应留给宽限期兜底。
  let playedThisTurn = false

  /** 播完时向 UI 发一次本地事件（气泡据此收尾）；打断路径不经过这里。 */
  function maybeEmitPlaybackEnd(): void {
    if (!engineSentAll || pendingSegments > 0) return
    engineSentAll = false  // 只发一次
    if (!playedThisTurn) {
      // 空合成只结束等待表现；气泡仍按字数估算，不能伪装成“播完”。
      emit('tts:playback_empty', {})
      return
    }
    playedThisTurn = false
    emit('tts:playback_end', {})
  }

  // S51：录音设备的检测 / 切换（与日记窗口、调试台共用同一份选择）
  const { openStream } = useAudioDevices()

  /** 默认引擎地址：与壳层其他部分一致（localhost-only）。 */
  const DEFAULT_WS = 'ws://127.0.0.1:8200/ws/audio'
  /** 引擎 HTTP API 前缀（读"插话打断"开关的配置用）。 */
  const ENGINE_API = 'http://127.0.0.1:8200/api'
  const WS_CONNECT_TIMEOUT_MS = 5000

  function emit(type: string, payload: Record<string, unknown>): void {
    onEvent?.(type, payload)
  }

  /** 等待引擎语音管线就绪（pipeline:state=ready），超时返回 false。
   *
   * 加载期间【不开麦】，进度由 handleServerMessage 的 pipeline:state 事件
   * 更新 loadingStage / loadingProgress，供 UI 显示。等待通过轮询 engineReady
   * 标志完成（由 pipeline:state=ready 置位）。
   */
  function waitEngineReady(timeoutMs: number): Promise<boolean> {
    if (engineReady.value) return Promise.resolve(true)
    return new Promise<boolean>((resolve) => {
      const t0 = performance.now()
      const poll = (): void => {
        if (engineReady.value) return resolve(true)
        if (performance.now() - t0 > timeoutMs) return resolve(false)
        requestAnimationFrame(poll)
      }
      poll()
    })
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

  function stopMouthLoop(): void {
    if (mouthRaf) cancelAnimationFrame(mouthRaf)
    mouthRaf = 0
    mouthVolumes = []
    mouthOpen.value = 0
  }

  function driveMouth(): void {
    // 使用音频图时钟；设备冷启动/暂停时墙钟仍走，不能提前消耗口型片。
    const now=audioCtx?.currentTime??mouthStart
    const active=streamEntries.find(entry=>entry.start<=now&&entry.end>now)
    const elapsed=(now-(active?.start??mouthStart))*1000
    const idx=Math.floor(elapsed/(active?.sliceMs||mouthSliceMs))
    const v=streamEntries.length?(active?.volumes[idx]??0):elapsed>0?(mouthVolumes[idx]??0):0
    // RMS 语音能量约 0.05~0.3 → 映射到 0..1（乘以系数并钳位）
    mouthOpen.value = Math.min(1, Math.max(0, v * 3))
    mouthRaf = requestAnimationFrame(driveMouth)
  }

  async function ensureAudioCtxRunning(): Promise<void> {
    if(disposed)throw new Error('语音实例已释放')
    if(resettingOutput)await resettingOutput
    if(disposed)throw new Error('语音实例已释放')
    if (!audioCtx) audioCtx = new AudioContext()
    if (audioCtx.state === 'suspended') await audioCtx.resume()
  }

  /** 把一段 tts:audio 入队（FIFO），由后台串行播放器严格按顺序播放。 */
  function enqueuePlay(wavBase64: string, sampleRate: number, sliceMs: number, volumes: number[],identity?:SpeechPlaybackIdentity,streaming=false,streamId='',turn?:{session_id?:unknown;generation?:unknown}): void {
    if(disposed){playbackReceipt('audio:playback_finished',identity);return}
    if (!wavBase64) return
    if (!playbackAdmission.accept(turn ?? identity)) {
      playbackReceipt('audio:playback_finished',identity)
      return
    }
    if(streaming&&streamId&&streamId!==streamGroup){
      // 新句首块不受上一句的网络欠载惩罚，已有音频仍按原队列播完。
      streamGroup=streamId;streamLastEnd=0
      streamNeedsRebuffer=false;streamRebufferTarget=.96
      wakeRebuffer(true)
    }
    if(bufferedBytes()+wavBase64.length*2+volumes.length*8>maxQueuedBytes){
      stopPlayback()
      playbackReceipt('audio:playback_finished',identity)
      emit('tts:playback_error',{reason:'audio-buffer-budget'})
      return
    }
    playQueue.push({ wav: wavBase64, sampleRate, sliceMs, volumes,identity,streaming })
    queuePeakBytes=Math.max(queuePeakBytes,bufferedBytes())
    pendingSegments++
    playedThisTurn = true
    wakeRebuffer()
    void drainPlayQueue()
  }

  /** 串行播放队列：同一时刻只有一个 bufferSource 在播，按入队顺序串联，杜绝乱序/重叠。 */
  async function drainPlayQueue(): Promise<void> {
    if (playRunning) return
    playRunning = true
    try {
      while (playQueue.length > 0) {
        if(playQueue[0].streaming&&streamNeedsRebuffer){
          await waitForRebuffer()
          streamNeedsRebuffer=false
          if(!playQueue.length)break
        }
        const item = playQueue.shift()!
        if(item.streaming)await scheduleStream(item)
        else {
          const epoch=playbackEpoch
          if(streamEntries.length)await new Promise<void>(resolve=>streamWaiters.push(resolve))
          if(epoch!==playbackEpoch){playbackReceipt('audio:playback_finished',item.identity);continue}
          await playOne(item.wav,item.sampleRate,item.sliceMs,item.volumes,item.identity)
        }
      }
    } finally {
      playRunning = false
    }
  }

  /** 提前解码并在音频图时钟连续排期，避免每480ms等待onended后再解码造成缝隙。 */
  async function scheduleStream(item:PlayItem):Promise<void> {
    const epoch=playbackEpoch
    let scheduled=false
    try {
      await ensureAudioCtxRunning()
      if(epoch!==playbackEpoch)return
      // 最多提前解码约2秒；压缩音频留在有界队列，停播立即唤醒等待者。
      while(streamCursor-audioCtx!.currentTime>maxDecodeAheadSeconds){
        await new Promise<void>(resolve=>{
          const done=():void=>{clearTimeout(timer);decodeWake.delete(done);resolve()}
          const timer=setTimeout(done,25)
          decodeWake.add(done)
        })
        if(epoch!==playbackEpoch)return
      }
      const raw=Uint8Array.from(atob(item.wav),c=>c.charCodeAt(0))
      const buffer=await audioCtx!.decodeAudioData(raw.buffer)
      if(epoch!==playbackEpoch)return
      const source=audioCtx!.createBufferSource()
      source.buffer=buffer;source.connect(audioCtx!.destination)
      const start=Math.max(streamCursor,audioCtx!.currentTime+.02)
      // 仅记录音频图上的供给缺口，不将网络首块时间误称为实际首音。
      if(streamLastEnd>0&&start-streamLastEnd>.03){
        const gapMs=Math.round((start-streamLastEnd)*1000)
        underrunCount++;underrunGapMs+=gapMs
        console.warn('[voice] 流式音频缓冲欠载 gap_ms='+gapMs)
        emit('tts:playback_underrun',{gap_ms:gapMs})
        streamRebufferTarget=Math.min(1.92,streamRebufferTarget+.48)
      }
      const entry:StreamEntry={...item,source,start,end:start+buffer.duration,started:false,epoch}
      source.onended=()=>{
        if(epoch!==playbackEpoch)return
        notifyStreamStart(entry)
        playbackReceipt('audio:playback_finished',entry.identity)
        streamEntries=streamEntries.filter(x=>x!==entry)
        pendingSegments=Math.max(0,pendingSegments-1)
        if(currentSource===source)currentSource=null
        if(!streamEntries.length){
          streamCursor=0;stopMouthLoop()
          if(!engineSentAll){
            streamNeedsRebuffer=true
            emit('tts:playback_buffering',{})
          }
          for(const resolve of streamWaiters.splice(0))resolve()
        }
        maybeEmitPlaybackEnd()
      }
      source.start(start)
      scheduled=true
      streamCursor=entry.end;streamLastEnd=entry.end;streamEntries.push(entry);currentSource=source
      if(!mouthRaf)driveMouth()
      if(!streamStartTimer)tickStreamStarts()
    } catch {
      emit('tts:playback_error',{reason:'stream-decode-or-schedule'})
    } finally {
      if(!scheduled){
        playbackReceipt('audio:playback_finished',item.identity)
        if(epoch===playbackEpoch){pendingSegments=Math.max(0,pendingSegments-1);maybeEmitPlaybackEnd()}
      }
    }
  }

  /** 播放单段（await 到该段自然结束再返回，保证串行）。 */
  let playbackEpoch = 0
  async function playOne(wavBase64: string, sampleRate: number, sliceMs: number, volumes: number[],identity?:SpeechPlaybackIdentity): Promise<void> {
    const epoch = playbackEpoch
    currentPlaybackIdentity=identity
    try {
      await ensureAudioCtxRunning()
      if (epoch !== playbackEpoch) return
      const bin = atob(wavBase64)
      const bytes = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
      const buffer = await audioCtx!.decodeAudioData(bytes.buffer.slice(0))
      if (epoch !== playbackEpoch) return
      const src = audioCtx!.createBufferSource()
      src.buffer = buffer
      src.connect(audioCtx!.destination)
      // 口型驱动：按播放进度取 RMS 音量片（仅作用于当前段）
      stopMouthLoop()
      mouthVolumes = volumes
      mouthSliceMs = sliceMs || 20
      mouthStart = audioCtx!.currentTime
      driveMouth()
      await new Promise<void>((resolve) => {
        currentSource = src
        currentPlayResolve = resolve
        src.onended = () => {
          if (epoch === playbackEpoch) stopMouthLoop()
          resolve()
        }
        src.start()
        emit('tts:playback_start', {})
        // S01：真正开始出声时回执（端到端 TTFA 观测点；引擎按 session 关联 trace）
        if (ws && ws.readyState === WebSocket.OPEN) {
          if(identity)playbackReceipt('audio:playback_started',identity)
          else ws.send(JSON.stringify({ type: 'audio:playback_started' }))
        }
      })
      if (epoch === playbackEpoch) {
        currentSource = null
        currentPlayResolve = null
      }
    } catch {
      if (epoch === playbackEpoch) stopMouthLoop()
    } finally {
      playbackReceipt('audio:playback_finished',identity)
      if(currentPlaybackIdentity===identity)currentPlaybackIdentity=undefined
      // S53：这一段（含解码失败）结束 → 计数减一；若引擎已说"没有更多段"，
      // 此刻就是"她真的说完了"的瞬间（气泡据此收尾）。
      if (epoch === playbackEpoch) {
        pendingSegments = Math.max(0, pendingSegments - 1)
        maybeEmitPlaybackEnd()
      }
    }
  }

  /** S03：barge-in 立即停播 —— 清空队列 + 停止当前段 + 停口型（本地操作，不等引擎）。 */
  function stopPlayback(): void {
    playbackAdmission.cancel()
    emit('tts:playback_cancelled', {})
    playbackEpoch++
    for(const wake of [...decodeWake])wake()
    wakeRebuffer(true)
    streamNeedsRebuffer=false;streamRebufferTarget=.96
    streamGroup=''
    if(streamStartTimer)clearTimeout(streamStartTimer)
    streamStartTimer=undefined
    if(streamEntries.some(entry=>entry.source===currentSource))currentSource=null
    for(const entry of streamEntries){
      entry.source.onended=null
      try{entry.source.stop()}catch{/* 取消尚未出声的排期也必须停止。 */}
      playbackReceipt('audio:playback_finished',entry.identity)
    }
    streamEntries=[];streamCursor=0;streamLastEnd=0
    for(const resolve of streamWaiters.splice(0))resolve()
    playbackReceipt('audio:playback_finished',currentPlaybackIdentity)
    currentPlaybackIdentity=undefined
    for(const item of playQueue)playbackReceipt('audio:playback_finished',item.identity)
    playQueue.length = 0
    const src = currentSource
    if (src) {
      src.onended = null
      try { src.stop() } catch { /* 尚未 start 或已停止 */ }
      currentSource = null
    }
    if (currentPlayResolve) {
      const resolve = currentPlayResolve
      currentPlayResolve = null
      resolve()  // 唤醒 playOne，让 drainPlayQueue 继续（队列已清空 → 直接退出）
    }
    stopMouthLoop()
    // S53：被打断不算"播完"——清掉两个信号，避免气泡把打断误当成正常收尾
    // （打断的收尾由 App.vue 的 tts:interrupted 分支立即处理）。
    engineSentAll = false
    pendingSegments = 0
    playedThisTurn = false
  }

  /**
   * 文字回复 TTS 的**回合开始**（chat:assistant 且开关开启时调用）：
   * 复位"是否出过声 / 引擎是否已发完"，让本轮回复的播放收尾判定独立于上一轮。
   */
  function beginReplyPlayback(): void {
    engineSentAll = false
    playedThisTurn = false
    streamLastEnd=0
    streamNeedsRebuffer=false;streamRebufferTarget=.96
    emit('tts:playback_waiting', {})
  }

  function resetPlaybackSession(): void {
    stopPlayback()  // 旧解码/排期先作废，再接受权威新连接的低generation。
    playbackAdmission.reset()
    // 无采音时在权威会话交接释放旧音频图，避免跨角色复用已停顿的设备时钟。
    // 普通stop/回合切换不关闭，开麦时也不能切断同一Context上的输入节点。
    if(audioCtx&&!mediaStream&&!processor){
      const previous=audioCtx
      audioCtx=null
      const closing=previous.close().catch(()=>console.warn('[voice] 旧会话音频图关闭失败'))
      resettingOutput=closing
      void closing.then(()=>{if(resettingOutput===closing)resettingOutput=null})
    }
  }

  /** 把控制通道下发的 tts:reply_audio 入队播放（复用语音链路的同一条 FIFO 队列）。 */
  function enqueueReplyAudio(payload: {
    session_id?: unknown
    generation?: unknown
    wav?: unknown
    sample_rate?: unknown
    slice_ms?: unknown
    volumes?: unknown
    streaming?:unknown
    stream_id?:unknown
  }): void {
    const volumes = Array.isArray(payload.volumes) ? (payload.volumes as number[]) : []
    enqueuePlay(
      String(payload.wav ?? ''),
      Number(payload.sample_rate ?? 24000),
      Number(payload.slice_ms ?? 20),
      volumes,
      undefined,
      payload.streaming===true,
      typeof payload.stream_id==='string'?payload.stream_id:'',
      payload,
    )
  }

  /**
   * 文字回复 TTS 的**收尾**（tts:reply_end）：声明引擎不再有新段，返回"本轮是否真的
   * 出过声"。未出声（合成失败/开关中途关）时由调用方退回"按字数估算收起气泡"。
   */
  function endReplyAudio(): boolean {
    const hadAudio = playedThisTurn
    engineSentAll = true
    wakeRebuffer(true)
    maybeEmitPlaybackEnd()
    return hadAudio
  }

  function handleServerMessage(msg: Record<string, unknown>): void {
    const type = String(msg.type ?? '')
    if(type==='vad:state'||type.startsWith('asr:')||type.startsWith('llm:')||type.startsWith('tts:')){
      if(!voiceSessionId||msg.session_id!==voiceSessionId||
        msg.character_id!==localStorage.getItem('yuiro-active-character')||
        !Number.isInteger(msg.generation)||Number(msg.generation)<audioGeneration)return
      if(type!=='tts:audio')audioGeneration=Number(msg.generation)
    }
    switch (type) {
      case 'pipeline:state': {
        const state = String(msg.state ?? '')
        loadingStage.value = String(msg.stage ?? '')
        loadingProgress.value = Number(msg.progress ?? 0)
        if (state === 'ready') {
          engineReady.value = true
          pipelineLoading.value = false
        } else if (state === 'loading' || state === 'init') {
          // init: 引擎刚启动/前端晚于 warmup 连上 → 也视为加载中，
          // 否则 engineReady 永远不会被置为 true（导致 60s 超时）
          engineReady.value = false
          pipelineLoading.value = true
        } else if (state === 'error') {
          engineReady.value = false
          pipelineLoading.value = false
        }
        emit(type, msg)
        break
      }
      case 'vad:state': {
        const state = String(msg.state ?? '')
        pipelineState.value.vad = state === 'active' ? '语音检测中' : '静音'
        emit(type, msg)
        break
      }
      case 'asr:start':
        pipelineState.value.asr = '识别中…'
        turnBusy.value = true
        // 新语音回合开始 → 复位"本轮是否出过声"（TTS 开关关闭时不会再有 tts:start 来复位）
        playedThisTurn = false
        emit(type, msg)
        break
      case 'asr:text':
        pipelineState.value.asr = String(msg.text ?? '')
        emit(type, msg)
        break
      case 'asr:error':
        pipelineState.value.asr = `识别失败: ${String(msg.message ?? '')}`
        turnBusy.value = false
        emit(type, msg)
        break
      case 'asr:dropped': {
        // ★ 引擎在这些**早退分支**（音频过短 / 空转写 / 判为噪音）不会有任何后续事件。
        //   不收尾的话 UI 会一直停在"识别中…"（用户实测："总是卡住在识别中"）。
        const why = String(msg.reason ?? '')
        pipelineState.value.asr =
          why === 'noise' ? '没听清（判为噪音）' : '未识别到语音'
        turnBusy.value = false
        emit(type, msg)
        break
      }
      case 'llm:start':
        pipelineState.value.llm = 'LLM 请求中…'
        emit(type, msg)
        break
      case 'llm:text':
        pipelineState.value.llm = String(msg.text ?? '')
        emit(type, msg)
        // 流式朗读可能早于最终文本；保持首段等待/缓冲，真正开声由播放器通知。
        if (pipelineState.value.tts === '合成中…' || pendingSegments > 0) emit('tts:playback_waiting', {})
        break
      case 'tts:start':
        streamLastEnd=0
        streamNeedsRebuffer=false;streamRebufferTarget=.96
        // fall through：与tts:synthesize共用既有回合状态初始化。
      case 'tts:synthesize':
        pipelineState.value.tts = '合成中…'
        // S53：新一轮开始 → 重新计"引擎是否已说再无新段"，并复位"本轮是否出过声"
        engineSentAll = false
        playedThisTurn = false
        emit(type, msg)
        break
      case 'tts:ready':
        pipelineState.value.tts = '播放中'
        emit(type, msg)
        break
      case 'tts:end':
        pipelineState.value.tts = '空闲'
        turnBusy.value = false
        // S53：引擎侧已把音频段**发完**（不是播完）。若本地队列此刻已播空
        // （常见：段少/合成快），立即算播完；否则等最后一段 onended 时再发。
        engineSentAll = true
        wakeRebuffer(true)
        maybeEmitPlaybackEnd()
        emit(type, msg)
        break
      case 'tts:interrupted': {
        // S03：引擎确认打断 —— 立即停播（清队列 + 停当前段 + 停口型）
        pipelineState.value.tts = '已打断'
        turnBusy.value = false
        stopPlayback()
        emit(type, msg)
        break
      }
      case 'tts:audio': {
        const identity:SpeechPlaybackIdentity={session_id:String(msg.session_id||''),
          character_id:String(msg.character_id||''),generation:Number(msg.generation),
          playback_id:String(msg.playback_id||'')}
        if(!identity.playback_id || identity.session_id!==voiceSessionId ||
          identity.character_id!==localStorage.getItem('yuiro-active-character') ||
          !Number.isInteger(identity.generation)||identity.generation<audioGeneration)return
        audioGeneration=identity.generation
        const volumes = Array.isArray(msg.volumes) ? (msg.volumes as number[]) : []
        emit(type, msg)
        enqueuePlay(
          String(msg.wav ?? ''),
          Number(msg.sample_rate ?? 24000),
          Number(msg.slice_ms ?? 20),
          volumes,
          identity,
          msg.streaming===true,
          typeof msg.stream_id==='string'?msg.stream_id:'',
        )
        break
      }
      case 'approval:required': {
        // 系统操作审批（语音场景）：原生对话框 → 回传裁决
        emit(type, msg)
        void (async () => {
          const res = await window.yuiro?.requestApproval({
            approvalRequestId: String(msg.request_id ?? ''),
            tool: String(msg.tool ?? ''),
            summary: String(msg.summary ?? ''),
          })
          emit('approval:resolve', { request_id: msg.request_id, approved: res?.approved ?? false })
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
              type: 'approval:resolve',
              request_id: msg.request_id,
              approved: res?.approved ?? false,
            }))
          }
        })()
        break
      }
      default:
        emit(type, msg)
    }
  }

  let inputEpoch = 0
  function checkInputEpoch(epoch: number): void {
    if (epoch !== inputEpoch) throw new Error('语音启动已取消，请在当前角色下重新开启麦克风')
  }
  async function start(options?: { wsUrl?: string; sessionId?: string }): Promise<void> {
    if(disposed)throw new Error('语音实例已释放')
    if (speaking.value) return
    const epoch = ++inputEpoch
    if(voiceSessionId!==(options?.sessionId||'')){audioGeneration=-1;voiceSessionId=options?.sessionId||''}
    // 调试台可热改打断开关，不能沿用上次连接时的缓存继续屏蔽输入。
    await loadBargeIn()
    checkInputEpoch(epoch)
    // 带引擎 WS 鉴权密钥（?secret=），避免 4401 未授权断开
    let url = options?.wsUrl ?? DEFAULT_WS
    try {
      const secret = (await (window as any).yuiro?.getEngineSecret?.()) || ''
      if (secret && !url.includes('secret=')) {
        url = `${url}${url.includes('?') ? '&' : '?'}secret=${encodeURIComponent(secret)}`
      }
    } catch {
      // 取不到密钥则按无鉴权尝试
    }
    checkInputEpoch(epoch)
    // S02：带 ?session= 绑定同一 AgentSession（与 /ws/control 共享 history/generation）
    if (options?.sessionId && !url.includes('session=')) {
      url = `${url}${url.includes('?') ? '&' : '?'}session=${encodeURIComponent(options.sessionId)}`
    }
    // 建立 /ws/audio 连接（带超时，避免引擎不响应时永久挂起）
    if (!ws || ws.readyState === WebSocket.CLOSED) {
      ws = new WebSocket(url)
      const activeSocket = ws
      ws.binaryType = 'arraybuffer'
      ws.onmessage = (ev) => {
        if (ws !== activeSocket) return
        if (typeof ev.data !== 'string') return
        let msg: Record<string, unknown>
        try {
          msg = JSON.parse(ev.data)
        } catch {
          return
        }
        handleServerMessage(msg)
      }
      ws.onclose = (event) => {
        if (ws !== activeSocket) return
        if (event.code === 1012) { stopPlayback(); void stop() }
        emit('ws:closed', {})
        ws = null
      }
      await new Promise<void>((resolve, reject) => {
        if (!ws) return reject(new Error('ws not created'))
        const timer = setTimeout(() => {
          cleanup()
          reject(new Error('连接引擎 /ws/audio 超时（引擎是否已启动？）'))
        }, WS_CONNECT_TIMEOUT_MS)
        const onOpen = (): void => { cleanup(); resolve() }
        const onError = (): void => { cleanup(); reject(new Error('无法连接引擎 /ws/audio')) }
        const onClose = (ev: CloseEvent): void => {
          cleanup()
          reject(new Error(`语音通道被关闭 (${ev.code}${ev.reason ? `: ${ev.reason}` : ''})`))
        }
        const cleanup = (): void => {
          clearTimeout(timer)
          ws?.removeEventListener('open', onOpen)
          ws?.removeEventListener('error', onError)
          ws?.removeEventListener('close', onClose)
        }
        ws.addEventListener('open', onOpen)
        ws.addEventListener('error', onError)
        ws.addEventListener('close', onClose)
      })
    }
    checkInputEpoch(epoch)
    if (ws.readyState !== WebSocket.OPEN) {
      throw new Error('语音通道未就绪')
    }
    // 冷启动门控：引擎语音模型（SenseVoice/BGE-M3）未就绪前【不开麦】，
    // 避免加载期语音堆积成请求队列；等待期间由 pipeline:state 事件推进进度提示。
    // 超时 60s（SenseVoice 冷启动 + 首次识别可能较慢），超时才报错。
    if (!engineReady.value) {
      emit('mic:waiting', { stage: loadingStage.value })
      const ok = await waitEngineReady(60000)
      checkInputEpoch(epoch)
      if (!ok) {
        throw new Error('语音引擎加载超时，请稍候再试')
      }
    }
    // 采音
    try {
      // 走共享的 openStream：使用**用户选定的麦克风**，设备不在时自动回退系统默认
      const opened = await openStream()
      if (epoch !== inputEpoch) {
        for (const track of opened.getTracks()) track.stop()
        checkInputEpoch(epoch)
      }
      mediaStream = opened
      console.log('[render][voice] 麦克风已开启，开始采音')
    } catch (e) {
      const name = e instanceof Error ? e.name : 'unknown'
      console.error(`[render][voice] 打开麦克风失败 (${name}): ${describeMicError(e)}`)
      // 抛**可读**的错误：上层会把它显示给用户（气泡 / 日志），
      // 而 DOMException 的英文原文（如 OverconstrainedError）没人看得懂。
      throw new Error(describeMicError(e))
    }
    await ensureAudioCtxRunning()
    checkInputEpoch(epoch)
    sourceNode = audioCtx!.createMediaStreamSource(mediaStream)
    processor = audioCtx!.createScriptProcessor(4096, 1, 1)
    processor.onaudioprocess = (e) => {
      // ★ 打断关闭 + 她正在说话（合成 / 播放中）→ **根本不上行**：话筒静默。
      //   这就是用户要的"屏蔽桌宠说话时的收音"：音频连发都不发出去，
      //   自然不会产生识别结果，也不会在引擎里排队成"下一个请求"。
      //   引擎侧还有第二道闸（`_process_audio_chunk` 直接丢弃），双保险。
      const input = e.inputBuffer.getChannelData(0)
      inputLevel.value=measureInputLevel(input)
      if (!bargeInEnabled.value && turnBusy.value) return
      const pcm = resampleTo16k(input, e.inputBuffer.sampleRate)
      if (ws && ws.readyState === WebSocket.OPEN && pcm.length > 0) {
        ws.send(pcm.slice().buffer)
      }
    }
    silentSink = audioCtx!.createGain()
    silentSink.gain.value = 0
    sourceNode.connect(processor)
    processor.connect(silentSink)
    silentSink.connect(audioCtx!.destination)
    speaking.value = true
    emit('mic:start', {})
  }

  async function stop(): Promise<void> {
    inputEpoch++
    speaking.value = false
    inputLevel.value=0
    // 关闭采音不等于停止已经在播的回复；口型由播放生命周期负责。
    if(!currentSource)stopMouthLoop()
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
    emit('mic:stop', {})
  }

  function sendInterrupt(): void {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'interrupt' }))
      emit('interrupt:sent', {})
    }
  }

  function dispose(): Promise<void> {
    if(disposed)return closingAudio??Promise.resolve()
    disposed=true
    stopPlayback()
    void stop()
    const socket=ws
    ws = null
    socket?.close()
    const context=audioCtx
    audioCtx=null
    const currentClosing=context&&context.state!=='closed'?context.close().catch(()=>{
      console.warn('[voice] 音频图关闭失败')
    }):Promise.resolve()
    closingAudio=Promise.all([currentClosing,resettingOutput]).then(()=>{})
    return closingAudio
  }

  function playbackBudgetState():Record<string,number> {
    return {queued_bytes:bufferedBytes(),queue_peak_bytes:queuePeakBytes,
      max_queued_bytes:maxQueuedBytes,scheduled:streamEntries.length,
      decode_ahead_seconds:Math.max(0,streamCursor-(audioCtx?.currentTime??0)),
      decode_waiters:decodeWake.size,pending:pendingSegments,
      underruns:underrunCount,underrun_gap_ms:underrunGapMs}
  }

  return {
    inputLevel,
    speaking,
    turnBusy,
    bargeInEnabled,
    loadBargeIn,
    mouthOpen,
    pipelineState,
    engineReady,
    pipelineLoading,
    loadingStage,
    loadingProgress,
    start,
    stop,
    sendInterrupt,
    // 文字回复 TTS（控制通道 tts:reply_audio / tts:reply_end）的播放接入
    beginReplyPlayback,
    resetPlaybackSession,
    enqueueReplyAudio,
    endReplyAudio,
    stopPlayback,
    playbackBudgetState,
    dispose,
  }
}
