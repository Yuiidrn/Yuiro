# 任务：将 Yuiro 的 TTS 从 edge-tts（云端）迁移为本地 CosyVoice 3.0（保留 Fake Neuro 角色音色 + 中英双语）

## 0. 背景与两端代码现状（必读）

当前项目（Yuiro）是 Python 语音引擎，TTS 实现在 `engine/yuiro/audio/__init__.py`：

- `TTSProvider`（`audio/__init__.py:587`）：现用 `edge_tts`，接口为
  `async synthesize_segment(text) -> AudioSegment`。
- `AudioSegment`（`audio/__init__.py:575`）：字段 `wav:bytes, sample_rate:int,
  volumes:list[float], slice_ms:int=20`。`volumes` 是**逐 20ms 的 RMS 音量数组**，
  由前端用来驱动角色口型（嘴型同步）。
- `_decode_audio_to_pcm`（L617，用 miniaudio 解码为 float32 单声道 PCM，
  失败回退 sample_rate=24000）、`_slice_rms`（L606，算 RMS）为**引擎无关逻辑，
  任何返回音频字节的 TTS 都能复用**。
- `VoicePipeline._speak`（L949）：上 ASR 锁 → `tts.synthesize_segment(reply)`
  → `play_callback` → 冷却后解锁；`interrupt(session)`（L984）取消 speak 任务实现
  **barge-in（语音打断）**。这两个逻辑**禁止改动**，它们与 TTS 引擎解耦。
- 配置：`engine/yuiro/config.py` 的 `TTSConfig`（L80-83，字段 `provider`,
  `segment_streaming`）、`PersonaConfig.voice`（L100）；`config.toml` 的
  `[tts]` + `[persona]`；`main.py` 的 `_build_voice_pipeline`（L223-290）用
  `tts = TTSProvider(voice=cfg.persona.voice, segment_streaming=cfg.tts.segment_streaming)`。

参考项目（D:\Project\Yuii\desktop-pet\my-neuro）已用本地 TTS 服务（`http://127.0.0.1:5000` GPT-SoVITS），其
`2.TTS.bat` 表明 Fake Neuro 音色由参考音频
`full-hub/tts-hub/GPT-SoVITS-Bundle/role_voice_api/neuro/01.wav`
及其转写文本（`-dt` 参数，内容："Hold on please, I'm busy. Okay, I think I heard
him say he wants me to stream Hollow Knight on Tuesday and Thursday."）定义。

## 1. 目标

1. 用**本地 CosyVoice 3.0**（FunAudioLLM，Apache-2.0 可商用）替换 edge-tts。
2. 复刻 Fake Neuro 音色：用上述 `01.wav` + 转写文本作为 CosyVoice 的
   `prompt_wav` / `prompt_text`（零样本克隆），实现**中英同音色**。
3. 保持现有口型同步（volumes/RMS）与 barge-in（interrupt）**完全不变**。
4. 不把 CosyVoice 的重量级 torch 模型加载进 engine 主进程（避免与 SenseVoice
   ASR 抢显存/GIL）。采用"独立本地服务 + HTTP 调用"架构。

## 2. 架构决策（必须遵守）

- 新建**独立进程** `cosyvoice-server/`（FastAPI 或同类），加载 CosyVoice3 权重
  （GPU），暴露 `POST /tts`，入参 `{text, prompt_text, prompt_wav, instruction}`，
  返回 **wav 字节**。
- Yuiro engine 侧只新增一个 `CosyVoiceProvider(TTSProvider)` 子类，重写
  `_synthesize_audio` 用 `httpx.AsyncClient` POST 到该服务；`synthesize_segment`、
  `_decode_audio_to_pcm`、`_slice_rms`、`AudioSegment` **全部继承父类，不复制不改动**。
- 不要 import cosyvoice 进 engine 主进程（即不要 in-process 方案）。

## 3. 逐文件改动契约

### 3.1 `engine/yuiro/config.py`（TTSConfig，L80）

新增字段（保留现有 `provider`/`segment_streaming`）：

```
tts_url: str = "http://127.0.0.1:5005"
reference_wav: str = ""        # Fake Neuro 参考音频绝对路径
reference_text: str = ""       # 参考音频转写（见背景 0）
instruct_zh: str = "用自然的中文语气说。"
instruct_en: str = "Speak in natural English."
default_language: str = "auto"
```

注意：`PersonaConfig.voice`（L100）继续留给 edge-tts/Microsoft 预设名，
**不要挪用**；CosyVoice 音色由 `[tts].reference_*` 描述。现有 `[tts]->[persona]`
voice 迁移逻辑（L178-185）不要破坏。

### 3.2 `engine/yuiro/audio/__init__.py`（新增类，不改动任何现有类）

新增 `class CosyVoiceProvider(TTSProvider)`：

- `__init__(self, base_url, reference_wav, reference_text, instruct_zh="",
  instruct_en="", default_language="auto", segment_streaming=True)`。
- 重写 `async _synthesize_audio(self, text) -> bytes`：
  - 判定语种（简单按中/英字符或 `default_language`）；有 instruction 时调服务
    的 instruct 模式，否则 zero-shot。
  - `POST {base_url}/tts` json=`{text, prompt_text:reference_text,
    prompt_wav:reference_wav, instruction:对应语种instruction}`，
    `return r.content`（wav 字节）。设置合理 timeout（建议 30s）。
- **不要重写** `synthesize_segment` / `_decode_audio_to_pcm` / `_slice_rms`，
  直接继承——miniaudio 能解 wav，volumes 照常计算，口型免费继承。

### 3.3 `engine/yuiro/main.py`（`_build_voice_pipeline`，L285 附近）

改为按 `cfg.tts.provider` 选择：

```
if cfg.tts.provider == "cosyvoice":
    tts = CosyVoiceProvider(
        base_url=cfg.tts.tts_url,
        reference_wav=cfg.tts.reference_wav,
        reference_text=cfg.tts.reference_text,
        instruct_zh=cfg.tts.instruct_zh,
        instruct_en=cfg.tts.instruct_en,
        default_language=cfg.tts.default_language,
        segment_streaming=cfg.tts.segment_streaming,
    )
else:
    tts = TTSProvider(voice=cfg.persona.voice, segment_streaming=cfg.tts.segment_streaming)
```

其余 `tts=tts` 照传，不要改 `VoicePipeline` 其他逻辑。

### 3.4 `cosyvoice-server/`（新建，独立进程）

- 用官方 `from cosyvoice.cli.cosyvoice import CosyVoice` 加载 CosyVoice3 权重。
- 端点 `POST /tts` 调用 `model.inference_zero_shot(text, prompt_text, prompt_wav)`
  或 `model.inference_instruct2(text, instruction, prompt_wav, prompt_text)`，
  把返回的 speech tensor 写成 **wav 字节**返回。
- 常驻进程，加载一次。提供 `start_server.bat`（Windows，激活 venv + 设 CUDA
  PATH）与 `test_voice.py`（用 `01.wav` 验证零样本音色是否保真）。
- **重要**：先写独立验证脚本确认 CosyVoice3 的真实 API 签名与返回字段名
  （不同版本可能是 `tts_speech` / `tts_speechs`），再写服务，不要想当然。

### 3.5 `config.toml` / `config.example.toml`

`[tts]` 下加示例：

```
provider = "cosyvoice"        # 或留 "edge-tts" 以兼容
tts_url = "http://127.0.0.1:5005"
reference_wav = "D:/.../assets/voices/neuro_prompt.wav"
reference_text = "Hold on please, I'm busy. Okay, I think I heard him say he wants me to stream Hollow Knight on Tuesday and Thursday."
instruct_zh = "用自然的中文语气说。"
instruct_en = "Speak in natural English."
```

把 my-neuro 的 `01.wav` 复制到 Yuiro `assets/voices/neuro_prompt.wav`。

## 4. 验收标准（Definition of Done）

1. `tts_url` 服务独立启动，健康检查通过。
2. `test_voice.py` 用参考音频输出的中英样本，**音色与 Fake Neuro 参考音频
   可辨认为同一说话人**（主观听感 + 如有可能 speaker similarity）。
3. 端到端：前端说话 → ASR → LLM → TTS 回传，`tts:audio` payload 含
   `wav`（可播放）+ `volumes`（口型正常开合）。
4. 播放中用户插话触发 `interrupt()`，TTS 立即取消、ASR 锁释放、新输入被处理
   （barge-in 行为与原 edge-tts 一致）。
5. `provider="edge-tts"` 回退路径仍可用（不破坏兼容）。

## 5. 明确禁止（Do NOT）

- 不要修改 `AudioSegment`、`_slice_rms`、`_decode_audio_to_pcm`、
  `VoicePipeline` 的 `_speak`/`interrupt`、barge-in、口型相关任何代码。
- 不要把 cosyvoice 直接 import 进 engine 主进程。
- 不要改动 `PersonaConfig.voice` 语义或现有配置迁移逻辑。
- 不要追求 token 级真流式（本期范围外；会引入 websocket 重写，风险高）。

## 6. 风险与注意

- CosyVoice3 较新，API 可能与 CosyVoice2 不同，先验证再接线。
- Windows + CUDA + funasr 环境踩坑多，服务独立进程可隔离但需确认总显存足够
  （SenseVoice + CosyVoice 约 6–10GB）。
- 零样本克隆对参考音频质量敏感，若音色保真度不足，优先换更干净的参考音频
  而非改代码。
- 首次合成延迟可能高于 edge-tts，可用分句流式缓减（见下"后续扩展"）。

## 7. 后续扩展（本期不做，仅记录）

- 句子级流式：复用已有 `TTSTaskManager`（`audio/__init__.py:646`，已具备 seq
  有序 + epoch 中断），把 reply 按标点分句逐句 `enqueue` + `wait_next` 顺序播放，
  实现句子级 barge-in（对标 my-neuro 的分段队列）。
- 多角色音色：把 `reference_*` 改为 per-persona 字典。
- token 级真流式：需 CosyVoice 流式 API + websocket，结构性改动，单独评估。

## 8. 执行建议顺序

1. 先 standalone 验证 CosyVoice3 本地推理 + Fake Neuro 音色（最高风险，先啃）。
2. 写 `cosyvoice-server` + 启动脚本。
3. 加 `CosyVoiceProvider` + `config.py` 字段 + `main.py` 分支（口型/打断不动）。
4. 配 `config.toml`，端到端联调验收。
5. 可选：句子级流式增强。
