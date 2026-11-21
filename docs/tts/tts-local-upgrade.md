# TTS 升级与定制化方案（本地 CosyVoice2 + 预留 CosyVoice3）

> 基于 `docs/tts-cosyvoice-migration.md` 的设计思路，**针对当前项目实际约束重新适配**后形成。
> 决策：用户确认"**本地 CosyVoice2 + 预留 CosyVoice3 接口**"，拒绝云端方案（延迟高）。
> 参考音频复用 my-neuro 的 `肥牛.wav`（已复制为 `assets/voices/neuro_prompt.wav`）。

## 0. 当前 TTS 现状（已核对代码）

- `engine/yuiro/audio/__init__.py`
  - `AudioSegment`：`wav:bytes, sample_rate:int, volumes:list[float], slice_ms=20`。`volumes` 为逐 20ms RMS，前端驱动口型。
  - `TTSProvider`：edge-tts，接口 `async _synthesize_audio(text)->bytes`；`synthesize_segment` / `_decode_audio_to_pcm`（miniaudio 解 wav/mp3）/ `_slice_rms` 为**引擎无关逻辑**，任何返回音频字节的 TTS 都能复用。
  - `CosyVoiceProvider(TTSProvider)`：已是本地 `tts-server` 的 httpx 客户端，仅重写 `_synthesize_audio`，返回 wav 字节；`backend` 参数透传给 tts-server 区分 cosyvoice2/3。
  - `TTSTaskManager`：seq 有序 + epoch 中断的流式交付，已具备句子级 barge-in 基础。
  - `VoicePipeline._speak` / `interrupt`：上 ASR 锁 → 合成 → 播放 → 冷却解锁；barge-in 取消 speak。**与 TTS 引擎解耦，禁止改动**。
- 配置：`TTSConfig`：`provider`(`edge-tts`|`cosyvoice`) + `backend`(`cosyvoice2`默认|`cosyvoice3`预留) + `tts_url`/`reference_*`/`instruct_*`/`default_language`。
- 现状痛点（已解决）：edge-tts 是云端依赖、需联网、音色不可定制、中文"播音腔"。

## 1. 目标

1. 用**本地 TTS 服务（CosyVoice2）** 替换 edge-tts，断网可用、低延迟、可定制角色音色。
2. **角色音色克隆**：复用 my-neuro 的 `肥牛.wav`（→ `assets/voices/neuro_prompt.wav`）做零样本克隆，复刻 Yuiro 人设音色（中英双语）。
3. 保持口型同步（volumes/RMS）、barge-in（interrupt）、句子级 `TTSTaskManager` **完全不变**。
4. **不把重量级 torch 模型加载进 engine 主进程**（避免与 SenseVoice 抢显存/GIL），采用「独立 tts-server 进程 + HTTP 调用」架构。

## 2. 关键决策

### 2.1 显存约束（RTX 3060 6GB）
- SenseVoice-Small（CUDA, ~1GB）常驻 + silero VAD（CPU）。
- **CosyVoice2（0.5B，~2GB）**：与 SenseVoice 共存后总 ~3–4GB，3060 余量充足 → **本期采用**。
- **CosyVoice3（6–10GB）**：3060 必 OOM，故仅**预留接口**（`backend="cosyvoice3"` 在 tts-server 中给出明确报错指引，而非静默失败）。未来显存充裕或 ASR 外移到独立进程后可启用。

### 2.2 参考音频（复用 my-neuro）
- 设计文档引用的 `01.wav` 在 my-neuro 中**不存在**（仅占位空壳）。
- 真实可用：`my-neuro/live-2d/fake_neuro_audio/Reference_audio/肥牛.wav`（1.74 MB，清晰单人音）。
- 已复制为 `assets/voices/neuro_prompt.wav`，`config [tts].reference_wav` 指向它。
- `reference_text` 当前为近似占位（肥牛.wav 真实转写待用户提供，提升克隆保真度）。

### 2.3 口型/打断零改动
- `CosyVoiceProvider` 仅重写 `_synthesize_audio`，返回 **wav 字节**（标准 RIFF wav）。
- `synthesize_segment` / `_decode_audio_to_pcm` / `_slice_rms` / `AudioSegment` **全部继承**，volumes 自动计算，口型免费复用。
- `_speak` / `interrupt` / `TTSTaskManager` 不动，barge-in 行为不变。

## 3. 架构

```
┌─────────────────────┐   HTTP POST /tts   ┌──────────────────────────┐
│  Yuiro engine        │ ─────────────────▶│  tts-server (独立进程)    │
│  (LLM+记忆+编排)     │ ◀──── wav bytes ──│  CosyVoice2 (GPU 3060)    │
│  CosyVoiceProvider   │                   │  ~2GB，与 SenseVoice 共存 │
│  (httpx.AsyncClient) │                   └──────────────────────────┘
└─────────────────────┘
```

- `tts-server/`：独立 FastAPI 进程，加载 CosyVoice2 权重（GPU），暴露 `POST /tts` 与 `GET /health`。
- engine 主进程仅 `CosyVoiceProvider` 子类 + `httpx` 调用，**不 import 任何 TTS torch 模型**。

## 4. 逐文件改动契约（已落地）

### 4.1 `engine/yuiro/config.py`（TTSConfig）
新增 `backend: str = "cosyvoice2"`；`provider` 默认保持 `edge-tts`（配置层切 `cosyvoice`）；`reference_wav` 默认指 `assets/voices/neuro_prompt.wav`。

### 4.2 `engine/yuiro/audio/__init__.py`（`CosyVoiceProvider`）
`__init__` 增加 `backend` 参数；`_synthesize_audio` 的 payload 透传 `backend` 给 tts-server；超时 60s。不重写父类解码/口型逻辑。

### 4.3 `engine/yuiro/main.py`（`_build_voice_pipeline`）
`cfg.tts.provider == "cosyvoice"` 时实例化 `CosyVoiceProvider(..., backend=cfg.tts.backend)`；否则回退 `TTSProvider(voice=cfg.persona.voice)`。

### 4.4 `tts-server/`
- `app.py`：`_load_model(backend)` 懒加载 CosyVoice2（`iic/CosyVoice2-0.5B`），`backend="cosyvoice3"` 明确报错指引；`_infer` 用 `inference_zero_shot`/`inference_instruct` 返回 24kHz RIFF wav 字节。
- `start_tts_server.ps1`：venv2 激活 + 注入 nvidia wheel `bin` 到 PATH + `TQDM_DISABLE=1`。
- `test_voice.py`：POST 中英样例，写出 `samples/`，人工试听音色一致性。

### 4.5 下载脚本 `scripts/download_cosyvoice_modelscope.py`
ModelScope 拉 `iic/CosyVoice2-0.5B` → `.env-local/models/cosyvoice2-0.5B`（HF 国内常代理，故用 ModelScope）。

### 4.6 `config.toml` / `config.example.toml`
`[tts]`：`provider="cosyvoice"`、`backend="cosyvoice2"`、`reference_wav` 指 neuro_prompt.wav、占位 `reference_text`。

## 5. 验收标准（DoD）

1. `tts-server` 独立启动，`/health` 通过，`model_loaded=true`，显存 < 3GB（CosyVoice2）。
2. 用 `neuro_prompt.wav` 输出的中英样本，音色可辨认为同一说话人（主观试听）。
3. 端到端：说话 → ASR → LLM → TTS 回传，`wav`（可播）+ `volumes`（口型正常）。
4. 播放中插话触发 `interrupt()`，TTS 取消、ASR 锁释放（barge-in 不变）。
5. `provider="edge-tts"` 回退路径仍可用。
6. `backend="cosyvoice3"` 时启动/推理给出明确"显存不足/未启用"指引，不静默失败。

## 6. 禁止（Do NOT）

- 不改 `AudioSegment` / `_slice_rms` / `_decode_audio_to_pcm` / `_speak` / `interrupt` / 口型 / barge-in。
- 不把 TTS torch 模型 import 进 engine 主进程。
- 不改 `PersonaConfig.voice` 语义。

## 7. 风险与注意

- 显存：3060 6GB 用 CosyVoice2；CosyVoice3 需 ASR 外移或更大显存。
- 零样本克隆对参考音频质量敏感；`reference_text` 为占位，提供准确转写可提升保真度。
- 首次合成延迟略高于 edge-tts，可用 `TTSTaskManager` 按标点分句流式缓减。

## 8. 后续扩展（本期不做）

- 句子级流式：复用 `TTSTaskManager` 把 reply 按标点分句 `enqueue` + `wait_next` 顺序播放，实现句子级 barge-in。
- CosyVoice3 启用：把 ASR 也外移到独立 voice-runtime 后，将 `backend` 切 `cosyvoice3`。
- 多角色音色：把 `reference_*` 改为 per-persona 字典。
