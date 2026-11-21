# 模型与依赖选型

> 每一项的**选定项、备选项、理由与借鉴来源**。选型服务于"研究生持续投入 + 可出成果"。

---

## 1. 语音

| 环节 | 选定 | 备选 | 理由 / 借鉴 |
|---|---|---|---|
| VAD | **silero-vad**（显式状态机 IDLE/ACTIVE/INACTIVE，概率+音量双阈值+平滑窗） | WebRTC VAD | deskpet / OpenLLM 的 `vad/silero.py` 已证明可行 |
| ASR | **faster-whisper**（本地） | whisper.cpp、sherpa-onnx SenseVoice、端上 transformers.js | deskpet；本地隐私；whisper.cpp 是 C++ 可选增强 |
| TTS | **edge-tts**（免费本地） | CosyVoice、GPT-SoVITS、Azure | deskpet；可换；分段流式播放 |
| 口型 | **wLipSync 逐元音权重**（AudioWorkletNode） | 服务端 RMS 预计算、纯音量 | AIRI model-driver-lipsync；作为**研究对比项** |

## 2. LLM / Agent

| 项 | 选定 | 备选 | 理由 |
|---|---|---|---|
| LLM SDK | 自建多 Provider 适配（OpenAI 兼容主） | Anthropic / Ollama / DeepSeek / Gemini | deskpet `LLMProviderRegistry`；**兼容降级**参考 AIRI |
| 本地 LLM | Ollama / llama.cpp（经 OpenAI 兼容层） | vLLM | 可离线、隐私 |
| 流式 | streamText pattern | —— | 逐 token + tool-call 事件 |
| 内心OS | `<think>/<reasoning>` 解析滤除 | LLM system 指令 | AIRI response-categoriser |

## 3. 记忆

| 项 | 选定 | 备选 | 理由 |
|---|---|---|---|
| 向量存储 | **sqlite-vec**（嵌入式，无独立 DB） | pgvector、Qdrant、Chroma | deskpet；零运维 |
| Embedding | **BGE-M3**（子进程隔离） | sentence-transformers、COHERE | deskpet；子进程避 CUDA 冲突 |
| 检索 | **RRF 融合 4 路**（vector/FTS5/recency/salience） | 纯向量 | deskpet；**研究对比项** |
| 结构化 | facts 表 + 实体抽取 | 知识图谱(NetworkX) | deskpet L3；图谱作备选/对比 |

## 4. 系统操作（核心）

| 项 | 选定 | 备选 | 理由 |
|---|---|---|---|
| 执行基座 | **C++ 原生守护进程 + MCP** | Python pyautogui、AIRI computer-use-mcp | C++ 最贴合"真实 OS 操作"；差异化创新点 |
| 协议 | **MCP (stdio/HTTP)** | 自定义 REST | OpenLLM/AIRI 一等公民 |
| 安全 | **审批 + 审计 + trace + dry-run 沙箱** | 无 | AIRI computer-use-mcp；**研究点** |
| GUI 感知 | 截屏→(可选 VLM)→定位 | DOM 控制(浏览器) | my-neuro 视觉引导；AIRI 确定性优先 |

## 5. 前端 / 壳

| 项 | 选定 | 备选 | 理由 |
|---|---|---|---|
| 壳 | **Electron** | Tauri2 | AIRI/OpenDesktop；桌宠窗口+系统兼容 |
| 渲染 | **Vue3 + UnoCSS + Pinia** | React | AIRI |
| Live2D | pixi-live2d-display + cubismcore | Spine / Three.js(VRM) | deskpet/AIRI/Live2DPet |
| 事件 | **eventa 类型化总线** | 自定义 emitter | AIRI/my-neuro；类型安全 |
| 采音 | AudioWorklet + 16kHz mono | ScriptProcessor | AIRI；性能更好 |
| 视觉随附 | 摄像头 + 截图自动附带 | 手动截屏 | OpenDesktop |

## 6. 综合"长板"模块

| 模块 | 采纳自 | 说明 |
|---|---|---|
| 双语言插件桥 | my-neuro | Python/JS 插件统一进工具循环 |
| 转写缓冲 `TranscriptBuffer` | my-neuro / AIRI | 分组 ASR 片段成一轮发言 |
| 分段流式 TTS `TTSTaskManager` | Open-LLM-VTuber | 并行合成、按序交付 |
| 打断即记忆编辑 | Open-LLM-VTuber | `[Interrupted by user]` 回填 |
| 每会话隔离 `ServiceContext` | Open-LLM-VTuber | 引擎/状态按会话克隆 |
| docstring→tool schema | Agentic-Desktop-Pet | 零摩擦工具作者 |
| 隔离 subagent | Agentic-Desktop-Pet | 子任务独立上下文 |
| todo 模型-视图 | Agentic-Desktop-Pet | TodoTool ASCII 视图 |
| 情绪/亲密度养成 | Agentic-Desktop-Pet | EmotionEngine + Character |
| 主动互动 + 注意力 | OpenDesktop-Pet | 定时观察 + 避免打扰 |
| 日志/可观测 | deskpet | structlog + prometheus |
| 密钥匙 | deskpet | OS keychain，绝不上云 |
| 建库工具 | deskpet | DDL 附加迁移 |

## 7. 基础设施

| 项 | 选定 | 理由 |
|---|---|---|
| 后端框架 | **FastAPI + uvicorn[standard] + websockets** | deskpet |
| LLM SDK | 自建多 Provider 适配 | deskpet `LLMProviderRegistry` |
| 向量存储 | sqlite-vec（嵌入式） | deskpet；零运维 |
| 事件 | eventa 类型化总线 | AIRI/my-neuro |

---

## 关键待实验项（供研究）
1. 口型：`音量驱动 vs 服务端RMS vs wLipSync逐元音` — 主观自然度对照。
2. 记忆：`纯向量 vs RRF融合 vs 知识图谱` — 召回率/连贯性对照。
3. 系统操作安全：`审批策略 / dry-run沙箱 / 失败重试` 的工程评估。
4. 养成：`情绪衰减 vs 静态人格` 对用户陪伴感的长期影响（可结合实验问卷）。

详见 [research-experiments.md](research-experiments.md)。
