import { ref } from 'vue'
import { describeMicError, useAudioDevices } from '../composables/useAudioDevices'

export interface RecorderOptions {
  /**
   * **一句说完**（尾部静音够久）时回调这一段的 16k/int16 PCM。
   *
   * 这是"边说边出字"的实现方式：引擎的 ASR（SenseVoice）是**整段**推理的，
   * 做不到真正的逐字流式；但按**静音切句**分片送识别，用户感受到的就是
   * "我说完一句，字就出来了"，无需手动停麦。
   */
  onSegment?: (pcm: ArrayBuffer) => void
  /** 句末静音判定（毫秒）：太小会把句子切碎，太大则吐字慢。默认 900。 */
  silenceMs?: number
  /**
   * 连续静音这么久就**自动停止**收麦。**默认 0 = 永不自动停**。
   *
   * 为什么默认关：写日记是"边说边想"—— 停下来思考十几秒是常态，
   * 自动收麦会把这段思考当成"说完了"，等于把记录打断（用户实测反馈）。
   * 想停就手动再点一下麦克风。
   */
  autoStopMs?: number
  /** 自动停止时通知（供 UI 说一句"停顿了，已停"）。 */
  onAutoStop?: () => void
}

/**
 * 日记语音采集（S51）：只采 PCM，**不连 /ws/audio**，并在本地按静音分句。
 *
 * 为什么不复用 `useVoiceInput`：那条链路是引擎的**对话语音链路**
 * （VAD→ASR→LLM→TTS）。日记正文走它会出三种事故：预路由把正文里的
 * "记事本/微信"当指令真的去开应用、正文进 history 污染记忆、她出声回复打断心流。
 * 语音日记只需要「音频 → 文字」，所以这里只采集 + 分句，POST /api/diary/transcribe。
 *
 * 采样约定：**16kHz / 单声道 / int16 LE**（引擎 ASR 的输入格式）。
 */
export function useDiaryRecorder(opts: RecorderOptions = {}) {
  const recording = ref(false)
  const level = ref(0)
  const error = ref('')
  /** 正在识别中的段数（供 UI 显示"识别中…"）。 */
  const pendingSegments = ref(0)

  const { openStream } = useAudioDevices()

  const TARGET_SR = 16000
  const SILENCE_MS = opts.silenceMs ?? 900
  /** 0 = 不收麦。写日记要允许长时间停顿思考。 */
  const AUTO_STOP_MS = opts.autoStopMs ?? 0

  let ctx: AudioContext | null = null
  let stream: MediaStream | null = null
  let processor: ScriptProcessorNode | null = null
  let sink: GainNode | null = null
  /** 当前这一句的音频分片（句末静音触发 flush 后清空）。 */
  let pending: Float32Array[] = []
  let sampleRate = TARGET_SR
  /** 本句是否已经出现过人声（防把纯噪音切成段）。 */
  let heardVoice = false
  /** 本句里"超过阈值的帧"数 —— 用来区分真的在说话，还是只有一声桌椅响。 */
  let voicedFrames = 0
  /** 自上次听到人声以来的静音毫秒数。 */
  let silentMs = 0
  /** 自适应噪声底噪：只在没听到人声时缓慢跟随，避免固定阈值在不同麦克风上失效。 */
  let noiseFloor = 0.004

  /** 线性插值重采样（日记场景对音质不敏感，够用且零依赖）。 */
  function resample(input: Float32Array, from: number, to: number): Float32Array {
    if (from === to || input.length === 0) return input
    const ratio = from / to
    const len = Math.max(1, Math.floor(input.length / ratio))
    const out = new Float32Array(len)
    for (let i = 0; i < len; i++) {
      const pos = i * ratio
      const i0 = Math.floor(pos)
      const i1 = Math.min(i0 + 1, input.length - 1)
      const frac = pos - i0
      out[i] = input[i0] * (1 - frac) + input[i1] * frac
    }
    return out
  }

  function toInt16(pcm: Float32Array): Int16Array {
    const out = new Int16Array(pcm.length)
    for (let i = 0; i < pcm.length; i++) {
      const v = Math.max(-1, Math.min(1, pcm[i]))
      out[i] = v < 0 ? v * 0x8000 : v * 0x7fff
    }
    return out
  }

  /** 把当前累积的这句送出去识别（并清空，准备下一句）。 */
  function flushSegment(): void {
    const parts = pending
    const voiced = voicedFrames
    pending = []
    heardVoice = false
    voicedFrames = 0
    if (!parts.length) return
    // 有效人声太少（一声咳嗽、桌子响、环境尖响）→ 不送识别，
    // 免得凭空吐出一个莫名其妙的词。这比单纯看时长更准：噪音里超过阈值的帧很少。
    if (voiced < 3) return
    const total = parts.reduce((n, c) => n + c.length, 0)
    const merged = new Float32Array(total)
    let off = 0
    for (const c of parts) {
      merged.set(c, off)
      off += c.length
    }
    const pcm = toInt16(resample(merged, sampleRate, TARGET_SR))
    // 太短（<0.25s）多半是咳嗽/桌椅声，丢掉免得吐出一个莫名其妙的词
    if (pcm.length < TARGET_SR * 0.25) return
    // 计数只是给 UI 一个"正在识别"的粗粒度指示：识别真正的耗时在引擎侧
    // （SenseVoice 整段推理，短句通常亚秒级），这里用 1.2s 估算窗口，
    // 到点自减 —— 不必也不该为它去做精确的请求级配对。
    pendingSegments.value += 1
    window.setTimeout(() => {
      pendingSegments.value = Math.max(0, pendingSegments.value - 1)
    }, 1200)
    try {
      // Int16Array.buffer 的静态类型是 ArrayBufferLike（TS 要区分 SharedArrayBuffer），
      // 但这里必然是我们自己 new 的普通 ArrayBuffer，断言安全。
      opts.onSegment?.(pcm.buffer as ArrayBuffer)
    } catch {
      /* 回调失败不该影响录音继续 */
    }
  }

  async function start(): Promise<boolean> {
    error.value = ''
    pending = []
    heardVoice = false
    voicedFrames = 0
    silentMs = 0
    try {
      // 走共享的 openStream：使用**用户选定的麦克风**，且设备被拔掉时自动回退
      // 系统默认 —— 直接 getUserMedia 指定 deviceId 会抛 OverconstrainedError，
      // 那样"开麦"会整个失败（这正是设备检测要兜住的场景）。
      stream = await openStream()
      ctx = new AudioContext()
      sampleRate = ctx.sampleRate
      const src = ctx.createMediaStreamSource(stream)
      processor = ctx.createScriptProcessor(4096, 1, 1)
      const frameMs = (4096 / sampleRate) * 1000
      processor.onaudioprocess = (e): void => {
        const data = e.inputBuffer.getChannelData(0)
        const copy = new Float32Array(data)
        let sum = 0
        for (let i = 0; i < copy.length; i += 4) sum += copy[i] * copy[i]
        const rms = Math.sqrt(sum / (copy.length / 4))
        level.value = Math.min(1, rms * 6)

        if (!heardVoice) {
          // 只在"还没听到人声"时更新底噪，避免把持续说话当成噪声抬高阈值
          noiseFloor = noiseFloor * 0.95 + rms * 0.05
        }
        const threshold = Math.max(0.006, noiseFloor * 2.2)
        if (rms > threshold) {
          heardVoice = true
          voicedFrames += 1
          silentMs = 0
          pending.push(copy)
          return
        }
        if (!heardVoice) return  // 还没开口：不累积、不计静音
        silentMs += frameMs
        pending.push(copy)       // 尾部静音也留着，避免吃掉尾音
        if (silentMs >= SILENCE_MS) {
          flushSegment()         // 一句说完 → 送识别（字随即出现）
        }
        if (AUTO_STOP_MS > 0 && silentMs >= AUTO_STOP_MS) {
          void stop().then(() => opts.onAutoStop?.())
        }
      }
      // 必须接到 destination 才会回调（用 0 增益避免自己听自己）
      sink = ctx.createGain()
      sink.gain.value = 0
      src.connect(processor)
      processor.connect(sink)
      sink.connect(ctx.destination)
      recording.value = true
      return true
    } catch (e) {
      // 具体原因（没插麦 / 被拒权 / 被别的程序占用）处理方式完全不同，
      // 笼统一句"无法访问麦克风"用户无从下手。
      error.value = describeMicError(e)
      await stop()
      return false
    }
  }

  /** 停止采集：把没送完的最后一句也送出去（否则结尾几个字会丢）。 */
  async function stop(): Promise<void> {
    if (!recording.value) return
    recording.value = false
    level.value = 0
    flushSegment()
    try {
      processor?.disconnect()
      processor = null
      sink?.disconnect()
      sink = null
      stream?.getTracks().forEach((t) => t.stop())
      stream = null
    } catch {
      /* 清理失败不影响已送出的音频 */
    }
    try {
      await ctx?.close()
    } catch {
      /* 已关闭 */
    }
    ctx = null
  }

  return { recording, level, error, pendingSegments, start, stop }
}
