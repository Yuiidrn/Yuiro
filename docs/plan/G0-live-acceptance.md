# G0 实机验收续记：Hiyori / Hotaru Shiomi

日期：2026-10-23。续接 `G0-realtime-baseline.md`。实施边界：当前配置实启、真实依赖采样、现有 SDK 预览与人工反馈；仍处 G0。最终数值以 `G0-live-artifacts/` 的正式 JSON 为准，预采样单独保留。

## 当前范围与配置

本轮资源重点：`shell/src/renderer/public/live2d/hiyori`、`shell/src/renderer/public/live2d/Hotaru Shiomi`。实际现存两目录下有 6 份 model3，引用检查均无缺失，见 `G0-live-artifacts/focus-inventory.json`。两套主要验收资源为 Hiyori 与 Hotaru casual；Hotaru child still 是可选稀疏能力补充。其余 Hotaru 外观不因为素材存在就自动获得视觉批准。

工作区已有 MaoPro、肥牛素材删除，保持原状。`model_dict.json` 仍引用这两套缺失素材，属于当前资源注册表残留问题；本轮未改注册表。

按当前配置启动真实 Engine：uvicorn `yuiro.main:app`，127.0.0.1:8200；native backend、真实 BGE-M3、SenseVoice、Qwen、SiliconFlow，VAD/ASR warmup 后 ready。文字、语音、Avatar 与 Task Registry 均可查询。使用现有配置与用户数据目录，输入为固定无工具测试短句；未读取/打印凭证，未自动批准工具。

Electron 首先从已构建的 file 入口打开，页面显示 Live2D `Network error`。开发入口 `pnpm dev --remoteDebuggingPort 9222` 可正常加载 Hiyori，故开发态通过不能推导打包态通过。本轮不修改资源路径来掩盖此差异。

## 测量口径

1. 文字：实际页面 `sendText` → 原有 control WS → 当前 Agent/Memory/LLM → 文字朗读 TTS → 原有 renderer 解码/队列 → `AudioBufferSourceNode.start`。记录在同一页面 `performance.now` 时钟上，统计首音应用启动；不包含麦克风/VAD/ASR，也不等同扬声器物理出声。
2. 语音：固定真实中文 PCM 以实时帧节奏进入 `/ws/audio` → 原有 VAD → ASR → Agent/LLM → TTS → audio WS。测试桥把真实返回音频交给现有 renderer `enqueueReplyAudio`；这一桥接不能代替原有麦克风采集和 audio WS handler 的人工实测。Python 记录最后语音帧发送至首音频接收，浏览器记录自己的播放时序，两个单调时钟不相减。
3. 模型：使用现有 renderer 模型切换与语义意图解析入口，观察实际 SDK 的 startMotion Promise 结果；截图和工程回执均不代替自然度评分。Hotaru 预览只换 renderer，不持久修改当前 Hiyori 配置/profile，故不能宣称 Hotaru 的后台配置整链已验收。

预采样曾出现多段回复尚在解码时测量器过早换轮，以及重复安装观察器的问题。`real-text-preflight.json` 仅用于排障，不计入正式统计。正式采样刷新 renderer 后安装一次观察器，并等音频段结束再换轮。用户反馈长尾不自然后，对“Engine 已发送完且仅一段”的样本，允许首音后 1.2s 调用现有 stopPlayback；各样本保留 `diagnostic_stopped_after_first_audio`。这类样本可测首音，不能证明完整播放时长或自然收尾通过。

## 人工反馈与定位线索

用户现场反馈：**“有声音，但语言或长尾不自然”**。记录见 `human-feedback.json`；声音自然度未通过。

当前发音配置中文，克隆参考转写为日文。一次当前 TTS 短句输出，经真实 ASR 转写为 `にこや。`，见 `tts-output-asr-preflight.json`；使用本机已安装 Microsoft Huihui 中文音色生成的输入语料“你好，请只回复你好。”，同一 ASR 转写为“你好，请只回复。你好。”，见 `voice-fixture-asr-preflight.json`。这些是语言失配的排查证据，尚不能排除 provider 生成质量、参考文本/音色等其他因素。没有为了通过验收切换生产 TTS 或语言。

## 可复现入口

根目录先加载 `. .\config\env.ps1`；Python 使用 `.env-local/engine-venv2/Scripts/python.exe`。

```powershell
# Engine 在 engine 目录启动；不带 reload
& ..\.env-local\engine-venv2\Scripts\python.exe -m uvicorn yuiro.main:app --host 127.0.0.1 --port 8200
# shell 目录，使用当前已安装依赖
pnpm dev --remoteDebuggingPort 9222
```

诊断脚本在根目录执行：

```powershell
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/g0_focus_inventory.py
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/g0_browser_samples.py
& .\scripts\diag\g0_make_voice_fixture.ps1
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/g0_voice_samples.py --samples 30
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/g0_avatar_live.py
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/g0_collect_live.py
```

脚本依赖正在运行且可调试的本机 renderer；不能同时开多个采样 runner。重新执行会覆写同名文件，比较前先归档；不要把不同轮次/输入模式混成一组。采样有真实云端调用，沿用当前配置的计费方式。

## 测试精简与后续阶段体验

见 [G0-test-tiers-and-stage-effects.md](G0-test-tiers-and-stage-effects.md)：本轮候选快测 771 passed / 27.63s，一项真实 BGE-M3 语义集成测试移入单独验收候选层，没有删测试、改断言或默认跳过规则。该文逐项说明 G0–G5 的体验收益和验收方式。
