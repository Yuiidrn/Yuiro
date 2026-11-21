# 任务：将 Yuiro 的 TTS 从 edge-tts（云端）迁移为本地 GPT-SoVITS（保留 Fake Neuro 角色音色）

> 配套文档：`docs/tts-cosyvoice-migration.md`（CosyVoice 3.0 方案）。
> 本文是**备选/对比方案**：若优先级是「音色保真度最高 + Windows 最稳 + 风险最低」，
> GPT-SoVITS（直接复用已训练好的 Fake Neuro 模型）通常优于 CosyVoice 零样本克隆。

## 0. 背景与代码现状（必读）

### 0.1 Yuiro 现状（与 CosyVoice 方案完全相同，复用）
- `TTSProvider`（`engine/yuiro/audio/__init__.py:587`）：现用 `edge_tts`，
  接口 `async synthesize_segment(text) -> AudioSegment`。
- `AudioSegment`（L575）：`wav:bytes, sample_rate:int, volumes:list[float], slice_ms=20`。
  `volumes` 是逐 20ms RMS 音量数组，前端用来驱动口型。
- `_decode_audio_to_pcm`（L617，miniaudio 解码，回退 24000）、`_slice_rms`（L606）
  为**引擎无关逻辑**，任何返回音频字节的 TTS 都能复用。
- `VoicePipeline._speak`（L949）/ `interrupt`（L984）实现 barge-in，**禁止改动**。
- 配置：`config.py` `TTSConfig`（L80）、`PersonaConfig.voice`（L100）；
  `main.py` `_build_voice_pipeline`（L285）。

### 0.2 参考源 D:\Project\Yuii\desktop-pet\my-neuro 的 GPT-SoVITS 调用契约
- 本地服务：`full-hub/tts-hub/GPT-SoVITS-Bundle/api.py`，由 `2.TTS.bat` 启动：
  ```
  api.py -p 5000 -d cuda
    -s role_voice_api/neuro/merge.pth      # 说话人模型权重（音色主体，已训练好）
    -dr role_voice_api/neuro/01.wav        # 参考音频
    -dt "Hold on please, I'm busy..."      # 参考文本
    -dl "en"
  ```
- 请求格式（`tts-request-handler.js:170` 本地分支）：POST `{text, text_language}`。
  说明：**音色/参考音频已在服务启动时固化**（`-s/-dr/-dt`），所以每次合成只需
  传文本 + 语种，**无需 per-request 参考音频**。这是本方案最简单、最稳的要点。
- 返回：wav 字节（GPT-SoVITS 默认 24k/32k 单声道）。

## 1. 目标
1. 用**本地 GPT-SoVITS**（复用 my-neuro 的 GPT-SoVITS-Bundle）替换 edge-tts。
2. **最大程度保持 Fake Neuro 音色**：直接复用已训练好的 `merge.pth`（该权重本就是
   Fake Neuro），不做重新克隆即可 1:1 保真。
3. 保持口型同步（volumes/RMS）与 barge-in（interrupt）**完全不变**。
4. 不把 GPT-SoVITS 的重量级模型加载进 engine 主进程——用其自带 `runtime\python.exe`
   独立进程对外暴露 HTTP，engine 侧只做 HTTP 调用（与 CosyVoice 方案同架构）。

## 2. 架构决策（必须遵守）
- 把 `full-hub/tts-hub/GPT-SoVITS-Bundle` 整体复制到 Yuiro（如 `tts-hub/GPT-SoVITS-Bundle`），
  用其自带 `runtime\python.exe` 起服务，**与 Yuiro 主 venv 完全隔离**（无依赖冲突、无 CUDA 抢占）。
- 服务启动参数沿用 `2.TTS.bat`：`-s neuro/merge.pth -dr neuro/01.wav -dt "..." -dl "en"`。
- Yuiro engine 侧新增 `GPTSoVITSProvider(TTSProvider)`，重写 `_synthesize_audio` 用
  `httpx.AsyncClient` POST `{text, text_language}` 到该服务；其余音频/口型逻辑继承父类。
- 不要 import / 加载 GPT-SoVITS 进 engine 主进程。

## 3. 音色保持与克隆（核心问题）

### 3.1 推荐：直接复用已训练模型（保真度最高，零再训练）
- `merge.pth` 是 my-neuro 已经用 Fake Neuro 数据微调好的说话人模型。**直接拿来用，
  音色 = 原样 Fake Neuro**，不存在零样本漂移风险。这是本方案相对 CosyVoice 的最大优势。
- 做法：把 `role_voice_api/neuro/` 目录（含 `merge.pth`、`01.wav`、配置文件）一并复制进
  Yuiro 的 `tts-hub/GPT-SoVITS-Bundle/role_voice_api/neuro/`，启动参数不变。

### 3.2 备选：若需重新克隆（只有参考音频、或想换新音色）
GPT-SoVITS 以「1 分钟音频克隆」著称，流程：
1. 准备 ≥1 分钟干净「Fake Neuro」人声（去噪、去 BGM、切片 4–10s/段）→ `merge.pth` 训练数据。
2. 运行 Bundle 的预处理：文本标注 → 提取 `semantic` + `WAVLM` 特征。
3. 训练 SoVITS（~几千 step，数分钟~数十分钟 GPU）+ GPT 自回归头。
4. 导出说话人模型 `merge.pth`（或 `model.pth`+`config.json`）。
5. 用 `-s merge.pth -dr 01.wav -dt "..."` 启动服务。
> 说明：如果只是沿用现成 Fake Neuro，走 3.1 即可，不要重复训练（训练有概率劣化）。

### 3.3 中英双语
- 已训练 `merge.pth` 对中文、英文均可用（训练数据/参考文本覆盖）。
- 请求时按文本给 `text_language: "zh"` / `"en"` / `"auto"`（GPT-SoVITS 支持 auto 自动检测）。
- 若发现某语种音色漂移，优先补充该语种参考数据重训，而非改推理代码。

## 4. 逐文件改动契约

### 4.1 `engine/yuiro/config.py`（TTSConfig，L80）
新增字段（保留现有 `provider`/`segment_streaming`）：
```
tts_url: str = "http://127.0.0.1:5000"   # GPT-SoVITS 服务地址（默认 5000）
tts_text_language: str = "auto"          # zh | en | auto
reference_wav: str = ""                  # 仅记录用，推理已固化进服务；可留空
reference_text: str = ""                 # 仅记录/文档用
```
> `PersonaConfig.voice`（L100）继续留给 edge-tts 预设名，不要挪用；现有
> `[tts]->[persona]` voice 迁移逻辑（L178-185）不要破坏。

### 4.2 `engine/yuiro/audio/__init__.py`（新增类，不改动现有类）
新增 `class GPTSoVITSProvider(TTSProvider)`：
- `__init__(self, base_url, text_language="auto", segment_streaming=True)`。
- 重写 `async _synthesize_audio(self, text) -> bytes`：
  ```
  import httpx
  async with httpx.AsyncClient(timeout=30) as c:
      r = await c.post(self._url, json={"text": text, "text_language": self._lang})
      r.raise_for_status()
      return r.content   # wav 字节
  ```
- **不要重写** `synthesize_segment` / `_decode_audio_to_pcm` / `_slice_rms`，直接继承
  （miniaudio 解 wav，volumes 照算，口型免费继承）。

### 4.3 `engine/yuiro/main.py`（`_build_voice_pipeline`，L285 附近）
```
if cfg.tts.provider == "gptsovits":
    tts = GPTSoVITSProvider(base_url=cfg.tts.tts_url, text_language=cfg.tts.tts_text_language)
elif cfg.tts.provider == "cosyvoice":
    tts = CosyVoiceProvider(...)   # 见 cosyvoice 文档
else:
    tts = TTSProvider(voice=cfg.persona.voice, segment_streaming=cfg.tts.segment_streaming)
```
其余 `tts=tts` 照传，不改 `VoicePipeline`。

### 4.4 `tts-hub/GPT-SoVITS-Bundle/`（从 my-neuro 复制，独立进程）
- 整体复制 `full-hub/tts-hub/GPT-SoVITS-Bundle` 到 Yuiro。
- 把 `role_voice_api/neuro/` 一并复制（含 `merge.pth`、`01.wav`）。
- 提供 Yuiro 版 `start_tts.bat`：
  ```
  cd %~dp0tts-hub\GPT-SoVITS-Bundle
  set "PATH=%~dp0tts-hub\GPT-SoVITS-Bundle\runtime;%PATH%"
  runtime\python.exe api.py -p 5000 -d cuda ^
    -s role_voice_api/neuro/merge.pth -dr role_voice_api/neuro/01.wav ^
    -dt "Hold on please, I'm busy. Okay, I think I heard him say he wants me to stream Hollow Knight on Tuesday and Thursday." -dl "en"
  ```

### 4.5 `config.toml` / `config.example.toml`
```
[tts]
provider = "gptsovits"        # 或 "edge-tts" / "cosyvoice" 以兼容
tts_url = "http://127.0.0.1:5000"
tts_text_language = "auto"
```

## 5. 验收标准（Definition of Done）
1. `start_tts.bat` 启动 GPT-SoVITS 服务，端口 5000 健康。
2. 独立 `test_voice.py` 用服务合成中英样本，音色与原 Fake Neuro **一致**（直接复用
   `merge.pth` 应近乎无损）。
3. 端到端：前端 → ASR → LLM → TTS 回传 `tts:audio` 含 `wav`（可播放）+ `volumes`（口型正常）。
4. 播放中插话触发 `interrupt()`，TTS 取消、ASR 锁释放、新输入被处理（barge-in 与原一致）。
5. `provider="edge-tts"` 回退路径仍可用。

## 6. 明确禁止（Do NOT）
- 不要修改 `AudioSegment`、`_slice_rms`、`_decode_audio_to_pcm`、`VoicePipeline`
  的 `_speak`/`interrupt`、barge-in、口型相关任何代码。
- 不要把 GPT-SoVITS 直接 import 进 engine 主进程。
- 不要改动 `PersonaConfig.voice` 语义或现有配置迁移逻辑。

## 7. 风险与注意
- **许可**：GPT-SoVITS 代码 MIT，但其预训练基座模型 / 部分权重可能带非商用限制；
  若项目未来**商用**，CosyVoice3（Apache-2.0）更干净——这是本方案相对 CosyVoice 的主要短板。
- **Windows 友好度**：Bundle 自带 `runtime\python.exe`，已在 my-neuro 验证可跑，
  比 CosyVoice 的 Windows 部署风险低（CosyVoice 偏 Linux/需自踩 CUDA）。
- **显存**：服务独立进程，与 SenseVoice ASR 互不干扰；约 2–4GB 即可。
- **流式**：GPT-SoVITS-Bundle `api.py` 为非流式（返回整段 wav）。句子级 barge-in
  需分句 + `TTSTaskManager`（见下）。
- **维护**：Bundle 较重（含整个 runtime），占磁盘但部署稳。

## 8. 后续扩展（本期不做，仅记录）
- 句子级流式：复用 `TTSTaskManager`（`audio/__init__.py:646`，seq 有序 + epoch 中断），
  把 reply 按标点分句逐句 `enqueue` + `wait_next` 顺序播放，实现句子级 barge-in。
- 多角色：每个角色一个 `merge.pth`，按 persona 切换 `-s` 启动参数或 per-request refer。
- 真流式：GPT-SoVITS 有社区流式方案，但成熟度低，单独评估。

## 9. 与 CosyVoice 3.0 方案对比（选型参考）
| 维度 | GPT-SoVITS（本文） | CosyVoice 3.0 |
|---|---|---|
| 音色保真 | ★★★★★ 直接复用训练模型，近无损 | ★★★★ 零样本克隆，可能轻微漂移 |
| Windows 部署 | ★★★★★ Bundle 自带 runtime，已验证 | ★★★ 偏 Linux，CUDA 踩坑 |
| 许可（商用） | ⚠️ 基座可能非商用 | ★★★★★ Apache-2.0 |
| 中英灵活度 | ★★★★ 已训练模型双语种 | ★★★★★ instruct2 显式控语种 |
| 显存占用 | 2–4GB | 4–6GB |
| 流式能力 | 弱（非流式） | 中（有流式 API） |
| 推理速度/首包延迟 | ★★★ AR GPT 阶段是瓶颈，长文本偏慢、偶发重复 | ★★★★★ NAR 架构，无 AR 瓶颈，更快更稳 |
| 迁移代码量 | 极小（请求仅 text+language） | 极小（请求 text+参考） |

**结论**：音色保真 + 部署稳妥优先选 GPT-SoVITS；**商用合规 + 语种灵活 + 推理速度/低延迟
（barge-in 响应）优先选 CosyVoice**。两者 engine 侧代码改动量一致，且可共存（同一 `provider`
字段切换）。注意：若把「语音打断响应快」作为硬指标，CosyVoice 的流式首包延迟显著优于
GPT-SoVITS 的非流式整段返回。
