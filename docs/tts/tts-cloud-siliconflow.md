# 任务：Yuiro 接入云端 TTS（SiliconFlow CosyVoice2 克隆 Fake Neuro 音色）

## 0. 背景与现状（必读）
- Yuiro TTS 实现：`engine/yuiro/audio/__init__.py` 的 `TTSProvider`（L587），接口
  `async synthesize_segment(text) -> AudioSegment`；`AudioSegment`（L575）含
  `wav:bytes, sample_rate:int, volumes:list[float], slice_ms=20`（volumes 是逐 20ms
  RMS，前端驱动口型）；`_decode_audio_to_pcm`（L617，miniaudio 解 mp3/wav→PCM）、
  `_slice_rms`（L606）引擎无关，任意音频字节都能复用。
- `VoicePipeline._speak`（L949）/ `interrupt`（L984）实现 barge-in，**禁止改动**。
- 参考源 D:\Project\Yuii\desktop-pet\my-neuro 的云端做法（`tts-request-handler.js:141` + `config.cloud.tts`）：
  调 SiliconFlow `POST /v1/audio/speech`，body `{model:"FunAudioLLM/CosyVoice2-0.5B",
  voice:"speech:fake-neuro:...", input, response_format, speed}`，返回音频字节。
  Fake Neuro 音色来自**一次性**把参考音频 `D:\Project\Yuii\desktop-pet\Yuiro\assets\voices\Model\Neuro`中的
  D:\Project\Yuii\desktop-pet\Yuiro\assets\voices\Model\Neuro\参考音频.wav
  D:\Project\Yuii\desktop-pet\Yuiro\assets\voices\Model\Neuro\参考文本.txt 上传克隆成 voice id
  （见 D:\Project\Yuii\desktop-pet\my-neuro `live-2d/fake_neuro_audio/process_audio.py`：上传到
  `https://api.siliconflow.cn/v1/uploads/audio/voice` 拿到 voice id）。
- 当前 Yuiro 已有 `CosyVoiceProvider`（POST 本地 tts-server）与 `GPTSoVITSProvider`
  （零样本），本次新增云端 provider，三者并存，由 `config.toml [tts].provider` 切换。

## 1. 目标
1. 用**云端 SiliconFlow CosyVoice2** 复刻 Fake Neuro 音色（与 my-neuro 一致）。
2. **低延迟无感**：用「分句 + 顺序流式播放」抵消网络/合成延迟（不做服务端音频流式，
   用句子级流水线即可让首句 ~200–400ms 出声）。
3. 口型同步（volumes/RMS）与 barge-in（interrupt）**完全不变**。
4. API Key 经 `engine/yuiro/keychain.py` 或环境变量注入，不硬编码进仓库。

## 2. 架构决策
- 新增 `CloudTTSProvider(TTSProvider)`：用 `httpx` POST SiliconFlow `/v1/audio/speech`，
  返回 wav/mp3 字节；`synthesize_segment`/`_decode_audio_to_pcm`/`_slice_rms`/`AudioSegment`
  **全部继承父类**（miniaudio 解音频，volumes 照算，口型免费复用）。
- **不**把音频流式透传复杂化：每句一次 HTTP 请求，`TTSTaskManager`
  （`audio/__init__.py:709`，已具备 seq 有序 + epoch 中断）按句排队播放，实现句级
  流式 + 句级 barge-in（对标之前文档的「分句流式」增强）。
- Key 管理：`engine/yuiro/keychain.py` 取 `SILICONFLOW_API_KEY`（回退环境变量），
  不写死在 config 或代码。

## 3. 逐文件改动契约

### 3.1 `engine/yuiro/config.py`（TTSConfig，L80）
新增/调整字段（保留现有 provider 枚举）：
```
provider: str = "edge-tts"   # 新增候选：siliconflow（云端 CosyVoice2）
# 云端 TTS（siliconflow provider 生效）
cloud_api_base: str = "https://api.siliconflow.cn/v1/audio/speech"
cloud_model: str = "FunAudioLLM/CosyVoice2-0.5B"
cloud_voice: str = ""        # Fake Neuro 克隆 voice id（如 speech:fake-neuro:xxxx）
cloud_response_format: str = "mp3"   # 或 wav（若服务端支持）
cloud_speed: float = 1.0
```
`PersonaConfig.voice`（L100）继续留给 edge-tts 预设名，不要挪用。
options 列表（~L273）加入 `"siliconflow"`。

### 3.2 `engine/yuiro/audio/__init__.py`（新增 CloudTTSProvider，不改动现有类）
```
class CloudTTSProvider(TTSProvider):
    """云端 SiliconFlow CosyVoice2 客户端（替代 edge-tts / 本地模型）。

    仅重写 _synthesize_audio：httpx POST 到 cloud_api_base，返回音频字节
    （mp3/wav 均可，父类 miniaudio 解码）。synthesize_segment/口型/解码继承父类。
    voice 为一次性克隆好的 Fake Neuro voice id（见 scripts/register_neuro_voice.py）。
    """
    def __init__(self, api_key: str, model: str, voice: str,
                 api_base: str, response_format: str = "mp3",
                 speed: float = 1.0, segment_streaming: bool = True) -> None:
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._api_base = api_base.rstrip("/")
        self._response_format = response_format
        self._speed = speed
        self._segment_streaming = segment_streaming

    async def _synthesize_audio(self, text: str) -> bytes:
        import httpx
        payload = {
            "model": self._model,
            "voice": self._voice,
            "input": text,
            "response_format": self._response_format,
            "speed": self._speed,
        }
        headers = {"Authorization": f"Bearer {self._api_key}",
                   "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(self._api_base, json=payload, headers=headers)
            r.raise_for_status()
            return r.content   # mp3/wav 字节
```
> 若服务端支持 SSE 音频流式且你追求极致首包，可后续升级为 stream=True 增量解码；
> 本期用分句 + TTSTaskManager 已足够无感，先不引入音频流解析复杂度。

### 3.3 `engine/yuiro/main.py`（`_build_voice_pipeline`，L285 附近）
在 cosyvoice / gptsovits 分支后加：
```
elif cfg.tts.provider == "siliconflow":
    from yuiro.keychain import get_secret   # 或实际 keychain 导入路径
    api_key = get_secret("SILICONFLOW_API_KEY") or os.environ.get("SILICONFLOW_API_KEY", "")
    tts = CloudTTSProvider(
        api_key=api_key,
        model=cfg.tts.cloud_model,
        voice=cfg.tts.cloud_voice,
        api_base=cfg.tts.cloud_api_base,
        response_format=cfg.tts.cloud_response_format,
        speed=cfg.tts.cloud_speed,
        segment_streaming=cfg.tts.segment_streaming,
    )
```
其余 `tts=tts` 照传，不改 VoicePipeline。
（同时把 `CloudTTSProvider` 加进 L230 的 import 行。）

### 3.4 `scripts/register_neuro_voice.py`（新建，一次性）
镜像 my-neuro `process_audio.py`：读 `live-2d/fake_neuro_audio/Reference_audio/肥牛.wav`
（或 Yuiro `assets/voices/neuro_prompt.wav`）+ 其**准确转写文本**，
`POST https://api.siliconflow.cn/v1/uploads/audio/voice`
（model=FunAudioLLM/CosyVoice2-0.5B, file, text=转写, customName=neuro），
打印返回的 voice id。把该 id 填入 `config.toml [tts].cloud_voice`。
> 转写文本必须匹配 肥牛.wav 真实内容（config 里现有中文占位是错误的，需用户听写确认）。

### 3.5 `config.toml` / `config.example.toml`
```
[tts]
provider = "siliconflow"
cloud_model = "FunAudioLLM/CosyVoice2-0.5B"
cloud_voice = "speech:fake-neuro:xxxxxxxx"   # 由 3.4 脚本获得
cloud_response_format = "mp3"
cloud_speed = 1.0
```
API Key 不放 toml，走 keychain / 环境变量 `SILICONFLOW_API_KEY`。

## 4. 无感（低延迟）交付（重要）
- 把 `_speak`（L949）改为**分句流式**：LLM 回复按标点切句 → 逐句
  `TTSTaskManager.enqueue(seq, seg)` → `wait_next()` 顺序 `play_callback`。
  这样首句合成完即播（~200–400ms 云端 TTFA + 网络），后续句流水跟进，用户感知无停顿。
- `interrupt()` 的 epoch 中断天然丢弃缓冲句，barge-in 句级生效（无需改 VoicePipeline）。
- 若本期暂不实现分句，至少保证 `synthesize_segment` 单句可用；分句增强作为后续 PR。

## 5. 验收标准（DoD）
1. `scripts/register_neuro_voice.py` 成功拿到 voice id，音色听感 = Fake Neuro。
2. 端到端：前端→ASR→LLM→云端 TTS→回传 `tts:audio` 含 `wav`（可播放）+ `volumes`（口型正常）。
3. 分句流式下首句出声延迟 < 500ms（用户无感）；播放中插话 `interrupt()` 立即取消、ASR 解锁。
4. `provider="edge-tts"` 回退仍可用；Key 不出现在仓库/日志。

## 6. 明确禁止（Do NOT）
- 不改 `AudioSegment`/`_slice_rms`/`_decode_audio_to_pcm`/`VoicePipeline` 的
  `_speak`/`interrupt`/barge-in/口型相关代码（分句增强只在 `_speak` 调用方组织，不破坏原有单句路径）。
- 不硬编码 API Key 到 config / 源码。
- 不要把云端音频流式解析复杂度在本期引入（分句流水线已够）。

## 7. 风险与注意
- **费用/隐私/网络**：云端按字符计费、文本离机、依赖网络与配额——这是采用云端方案的固有代价。
- **voice id 账号绑定**：voice id 属于上传时用的 SiliconFlow 账号/key，换 key 需重新注册。
- **转写准确性**：参考音频转写填错会严重失真，务必用 肥牛.wav 真实内容。
- **mp3 解码**：父类 miniaudio 能解 mp3，volumes 正常；若选 wav 格式同样兼容。

## 8. 执行顺序
1. 写 `CloudTTSProvider` + config 字段 + main 分支 + import（口型/打断不动）。
2. 写 `scripts/register_neuro_voice.py`，用 肥牛.wav 注册拿 voice id，填 config。
3. 配 keychain/环境变量，端到端联调。
4. （增强）分句 + TTSTaskManager 流式，压到无感。
