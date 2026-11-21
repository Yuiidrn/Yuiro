# Yuiro 🐚

> **Re-creating Neuro-sama** — 会听、能看、会"动手"的声控桌宠。
> 集成了对 7 个开源桌宠 / AI 伴侣项目（deskpet、Open-LLM-VTuber、my-neuro、Agentic-Desktop-Pet、OpenDesktop-Pet、Live2DPet、AIRI）的技术栈调研所长，面向研究生持续投入的原型项目。

本仓库核心链路已可运行：语音对话（ASR→LLM→TTS）、三层记忆、SystemDaemon 系统工具、网易云音乐。
**当前阶段（2026-09 起）**：主线切换为 **Runtime 演进**——把现有模块升级为统一 Harness 契约下的协同 Runtime
（目标：General Agent Harness + Embodied Desktop Runtime）。推进序列与 Sprint 见
[`docs/spec/roadmap.md`](docs/spec/roadmap.md)，目标架构见 [`docs/spec/architecture-goal.md`](docs/spec/architecture-goal.md)。

---

## 一句话架构

**Electron 桌宠壳 (Vue3)** ↔ **Python FastAPI 引擎 (Agent/语音/记忆)** ⛓ **C++ 系统操作守护进程 (真实 OS 能力，MCP 暴露)**，全链路经 **localhost HTTP/WS + 类型化事件总线** 通信。

```
┌─────────────────────── Electron 壳 (Vue3 + Live2D) ───────────────────────┐
│  透明无边框 / 置顶 / 鼠标穿透 / 托盘 / 自启 / 原生审批对话框                │
│  采音(AudioWorklet) + wLipSync 逐元音口型 + 动画FSM + 气泡UI              │
│                        │ eventa 类型化事件总线 IPC                        │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ WebSocket + HTTP (localhost, shared-secret)
┌───────────────▼───────────────────────────────────────────────────────────┐
│                    Python FastAPI 引擎 (Engine)                          │
│  VAD(silero) → ASR(faster-whisper) → LLM(多Provider) → TTS(按provider三选一)│
│  Agent Loop(queue+generation) + <think>滤除 + 工具调用循环                 │
│  记忆: sqlite-vec 三层 + RRF 混合检索 + 知识库 RAG + 自动注入              │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ MCP (stdio/HTTP)
┌───────────────▼───────────────────────────────────────────────────────────┐
│             C++ 系统操作守护进程 (SystemDaemon)                          │
│  进程/软件开关(WinAPI) 文件生成 终端 窗口 鼠标键盘 截图                    │
│  approval队列 + trace/audit + dry-run 沙箱                                │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 技术栈清单

| 层 | 技术 | 借鉴来源 |
|---|---|---|
| 桌面壳 | **Electron** + electron-vite | AIRI / OpenDesktop-Pet |
| 前端 | **Vue3** + Pinia + UnoCSS + PixiJS + pixi-live2d-display | AIRI / deskpet |
| 状态/事件 | **eventa**(类型化事件总线) + WebSocket 控制通道 | AIRI / my-neuro event-bus |
| Agent 后端 | **Python FastAPI** + uvicorn[standard] + websockets | deskpet |
| LLM | 多 Provider 适配 (OpenAI 兼容/Anthropic/Ollama/DeepSeek) + 兼容降级 | deskpet / AIRI / OpenLLM |
| VAD | **silero-vad**（显式状态机） | deskpet / OpenLLM |
| ASR | **faster-whisper**（+ 可选端上 transformers.js） | deskpet |
| TTS | **CosyVoice2**（本地独立进程 5005）/ **GPT-SoVITS**（外部 Bundle 5000）/ **SiliconFlow**（云端零显存），按 `config.toml [tts].provider` 三选一 | deskpet / OpenLLM |
| 口型 | **wLipSync 逐元音** + 服务端 RMS 备用 | AIRI / OpenLLM |
| 记忆 | **sqlite-vec 三层** + BGE-M3 + RRF 4路融合 + 实体抽取 | deskpet |
| 工具 | **MCP 统一抽象** + 注册表 + 权限分级 | AIRI / deskpet / my-neuro |
| **系统操作** | **C++ 独立守护进程 + MCP**（审批/审计/沙箱/dry-run） | **AIRI computer-use-mcp** |
| 存储 | sqlite + sqlite-vec + 可选 pgvector | deskpet / AIRI |

---

## 目录结构

```
Yuiro/
├── README.md                  ← 本文件
├── ARCHITECTURE.md            ← 完整架构 + 数据流 + 模型选型 + 接口契约
├── docs/
│   ├── init/                  ← milestones(路线图 M0-M6) / model-selection / DEPLOYMENT / non-c-drive / research-experiments
│   ├── system-daemon.md       ← C++ 系统操作守护设计（审批/审计/沙箱）
│   ├── features/              ← 功能设计（网易云 / 日记 / 视觉）
│   └── memories/              ← 记忆系统设计与研究
├── engine/                    ← Python FastAPI 引擎
│   ├── pyproject.toml
│   ├── config.example.toml
│   └── yuiro/
│       ├── main.py            ← FastAPI 入口 + WS 路由
│       ├── config.py          ← 配置加载
│       ├── audio/             ← VAD/ASR/TTS/管线编排
│       ├── agent/             ← Agent loop / LLM / 工具 / 记忆
│       ├── memory/            ← 三层记忆 + sqlite-vec + RRF
│       ├── tools/             ← 工具注册表 + 内置工具
│       ├── systemd/           ← C++ daemon MCP 客户端 + 协议
│       ├── emotion/           ← 情绪/亲密度养成 (Agentic)
│       ├── proactive/         ← 主动互动 + 注意力 (OpenDesktop)
│       ├── skill/             ← Skill 两层懒加载 + 热加载 (deskpet/Agentic)
│       └── plugins/           ← 双语言插件桥 (my-neuro)
├── system-daemon/             ← C++ 系统操作守护进程（可选执行后端；默认由 engine/yuiro/native/ 承担）
│   ├── CMakeLists.txt
│   ├── src/                   ← WinAPI 能力实现
│   ├── include/               ← 头文件/接口
│   └── mcp/                   ← MCP 协议定义
├── shell/                     ← Electron + Vue3 (TypeScript) 前端
│   ├── package.json
│   ├── electron.vite.config.ts
│   └── src/
│       ├── main/              ← 主进程(窗口/托盘/审批)
│       ├── preload/           ← IPC 桥
│       ├── renderer/          ← Vue3 UI + Live2D + 采音
│       └── shared/            ← 事件总线契约
└── config/                    ← 共享配置/密钥管理规范
```

> 🔎 完整"取长补短"映射表见 [ARCHITECTURE.md §0](ARCHITECTURE.md)，标明每个项目把哪项长处借给了 Yuiro。

---

## 📖 补充文档
- [部署/运行指南](docs/init/DEPLOYMENT.md) — 从零跑起 + 当前已验证状态
- [不占 C 盘约定](docs/init/non-c-drive.md) — 所有环境/缓存/模型走 `.env-local`
- [API 申请清单](config/API_KEYS.md) — 各云端 API 到哪个网站申请
- [第三方许可声明](third-party-notices.md) — Live2D 模型/运行时许可

## 当前状态

- [x] M0 架构骨架：根文档 + engine/system-daemon/shell 骨架 + 接口定义 + 环境搭建（缓存重定向 `.env-local`）
- [x] M1 可运行骨架：FastAPI 引擎 + Electron 桌宠窗口 + 文本对话 + shared-secret 鉴权
- [x] M2 声控：采音(AudioWorklet) + VAD（FSMN / silero） + ASR（SenseVoice / faster-whisper） + TTS + 口型同步
- [x] M3 记忆：sqlite-vec 三层 + RRF 混合检索 + 知识库 RAG + 自动注入
- [x] M4 AI 动手：SystemDaemon(C++) + MCP 工具 + 审批对话框 + dry-run + 审计；网易云音乐接入（ncm-cli + mpv）
- [ ] M5 情感/主动/养成：`emotion/` `proactive/` 轻量实现推进中（→ 新主线 Wave 2 / Wave 7）
- [ ] M6 打磨 + 研究 + 打包发布（→ 吸收进各 Wave 的 Showcase 与发布节奏）

**新主线（2026-09 起）**：按 `docs/spec/` 推进 Runtime 演进。**已完成**：Wave 0（Trace /
Session / Generation）、Wave 1（真 Barge-in / 分段流式 TTS）、Wave 2 部分（AvatarIntent 表情通道）、
Wave 3（ContextEngine）、Wave 4 部分（Explicit Memory）、Wave 5 部分（TaskRuntime）、
Wave 6 部分（Artifact Store）。Sprint 明细、全局测试状态与**人工验收清单**见
[docs/plan/README.md](docs/plan/README.md)。

| 规范文档 | 内容 |
|---|---|
| [docs/spec/README.md](docs/spec/README.md) | 总索引 + 最高锚点 + 六个一等实体 + 全局硬约束 |
| [docs/spec/architecture-goal.md](docs/spec/architecture-goal.md) | 目标架构 + 组件契约 + DoD + 禁止事项 |
| [docs/spec/runtime-contract.md](docs/spec/runtime-contract.md) | P0 内核规范 + 现状基线 |
| [docs/spec/roadmap.md](docs/spec/roadmap.md) | Wave 序列 + Era 0–5 + Personal Brain + Sprint 机制 |
| [docs/spec/coding-agent-protocol.md](docs/spec/coding-agent-protocol.md) | 开发协议 + 母 Prompt + 护栏 + 测试三层 |

历史里程碑见 [docs/init/milestones.md](docs/init/milestones.md)。

启动本项目需要**先后跑两个进程**：Python 引擎 + Electron 壳层。以下是当前环境（Windows PowerShell）下验证过的步骤：

## 0. 每次开新终端先做：加载本地环境

```powershell
cd d:\Project\Yuii\desktop-pet\Yuiro
. .\config\env.ps1
```

作用：设置 `YUIRO_*` 环境变量，并把 HF/Torch/npm/electron 缓存全部重定向到项目内 `.env-local/`（不占 C 盘是硬约定）。

## 1. 启动引擎（Engine，端口 8200）

推荐用脚本（自动清理 8200/5000/5005 端口残留 + 按 `config.toml [tts].provider` 同步拉起对应 TTS）：

```powershell
cd d:\Project\Yuii\desktop-pet\Yuiro
& .\scripts\engine\engine_start.ps1          # 引擎(8200) + 本地 TTS（provider=siliconflow 时不另起进程）
& .\scripts\engine\engine_stop.ps1           # 停止
# 仅起引擎调试 TTS 时：& .\scripts\engine\engine_start.ps1 -NoTTS
```

手动启动（在 `engine/` 目录内）也可以，但注意两点：

- **必须显式 `--port 8200`**——uvicorn 默认 8000，而壳层写死连 8200；
- **勿加 `--reload`**——uvicorn reloader 与 BGE-M3 的 multiprocessing spawn 冲突会导致 BrokenPipe。

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8200/health
# → {"status":"ok","version":"0.1.0"}
```

**首次运行前置条件**（只做过就不用管）：

- 配置文件：`engine/config.toml` 不存在的话，从 `engine/config.example.toml` 复制一份；
- LLM API key：走 OS keychain，不落盘。可以在壳层的开发者调试台里设置并持久化；没配 key 时引擎会用 mock 后端，文字聊天能跑但回复是假的。

## 2. 启动壳层（Shell，Electron 桌宠窗口）

新开一个 PowerShell（同样先执行第 0 步的 env.ps1），然后：

```powershell
cd d:\Project\Yuii\desktop-pet\Yuiro\shell
pnpm dev
```

`node_modules` 已就绪，无需再 `pnpm install`。启动后会弹出透明桌宠窗口（肥牛 Live2D 模型），右下角是功能岛。

## 3. 验证整条链路

1. 功能岛上的连接圆点变绿 = `/ws/control` 已连上引擎；
2. 打开聊天面板发一条文字消息 → 应收到助手回复（引擎终端有 `[yuiro][chat]` 日志）；
3. 点麦克风按钮开启语音 → 对着麦克风说话，日志面板应依次出现 `VAD → ASR → LLM → TTS` 阶段反馈（模型已在引擎启动时后台预热，首次语音识别不会再卡 10 秒）；
4. 说"帮我打开记事本"类指令 → 会弹**原生审批对话框**，批准后由 SystemDaemon 执行。

## 常见坑

| 现象 | 原因 |
|---|---|
| 壳层圆点一直黄/红 | 引擎没起，或端口不是 8200 |
| 语音说了没反应 | 看引擎终端日志区分"链路断了"还是"链路慢"（ASR 模型加载）；也确认系统麦克风权限 |
| 系统操作工具不工作 | S10 起默认走 **Python 原生后端**（`[systemd].backend = "native"`），不需要 cmake/C++ 工具链；仅当切到 `daemon` 时才需先构建 `system-daemon/build/yuiro.exe` |
| 中文日志乱码 | PowerShell 执行 `chcp 65001` 切 UTF-8 |
| 想跑引擎测试 | venv2 没装 dev 依赖时先装（venv2 无 pip，用 uv 装，见 `AGENTS.md`），再在 `engine/` 内 `pytest tests/ -q` |

补充说明：`docs/init/DEPLOYMENT.md` 为早期快照，其中"M1、faster-whisper 未装"的进度描述已过时；当前进度以本文档「当前状态」与 `AGENTS.md` 为准，直接按上面步骤启动即可。

