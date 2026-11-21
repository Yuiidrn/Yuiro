---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: d9eba8b96b5df3e833811a065704faf0_1857876d961b11f195a2525400e6dd8f
    ReservedCode1: qDlbUhuUnvH+g44nmF4RnjMr532mYAEUkOIobc3mclwBEnm30H+1s7aXNaLiH5PEBku8WMKvLEm5sDuFSrSngLXpsbaqhhpTfhFmJWLRDYMkftPcvG+R/neRYmHZoV2T0wliy8GKndCn3CWx3o6GtBWj9dU4G9gKPtNx06AkV0hR2KFUCDNvcazYgFY=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: d9eba8b96b5df3e833811a065704faf0_1857876d961b11f195a2525400e6dd8f
    ReservedCode2: qDlbUhuUnvH+g44nmF4RnjMr532mYAEUkOIobc3mclwBEnm30H+1s7aXNaLiH5PEBku8WMKvLEm5sDuFSrSngLXpsbaqhhpTfhFmJWLRDYMkftPcvG+R/neRYmHZoV2T0wliy8GKndCn3CWx3o6GtBWj9dU4G9gKPtNx06AkV0hR2KFUCDNvcazYgFY=
---

# Yuiro 项目深度分析报告

> 生成日期：2026-08-12 | 项目版本：0.1.0 | 当前阶段：M0（架构骨架）→ M1（可运行骨架，部分完成）
>
> ⚠️ **时效声明（2026-09-06 补）**：本报告为生成当日的**历史快照**，其中"M0 阶段 / 接口占位"等描述已过时——项目现已完成 M1–M4（语音链路、记忆、SystemDaemon 工具调用、网易云音乐均可运行），处于 M4 → M5 迭代。现状以 `AGENTS.md` 与 `docs/init/milestones.md` 为准，本报告仅作架构溯源参考。

---

## 一、项目概述

### 1.1 项目定位

**Yuiro** 是一个复刻 Neuro-sama 风格的**声控桌面宠物（Desktop Pet）**。用户通过语音或文字与宠物互动，宠物通过 Live2D 模型展示表情和口型，并能**执行真实系统操作**（打开应用、管理文件、执行终端命令等）。

项目采用 **AIRI computer-use-mcp** 的安全哲学：**"控制面 / 执行面分离 + 审批审计 + 确定性优先"**。AI 大脑（Python Agent）负责决策，C++ 守护进程负责实际执行系统操作，中间通过 MCP 协议通信。

### 1.2 核心功能蓝图（按里程碑规划）

| 里程碑 | 功能 | 状态 |
|---|---|---|
| M0 | 架构骨架、接口定义、目录搭建 | ✅ 完成 |
| M1 | 可运行骨架：Electron 透明桌宠 + FastAPI 引擎 + 文本对话 | ✅ 部分完成 |
| M2 | 声控：VAD 语音检测 + ASR 语音识别 + TTS 语音合成 + 口型同步 | ⏳ 接口已定义，实现占位 |
| M3 | 记忆：sqlite-vec 向量存储 + BGE-M3 嵌入 + 跨会话记忆 | ⏳ 配置已定义 |
| M4 | AI 动手：SystemDaemon C++ 守护 + MCP 系统工具 + 审批队列 | ⏳ 接口已定义，实现占位 |
| M5 | 情感/主动/养成：情绪衰减 + 亲密度 + 主动互动 + 摄像头截图 | ⏳ 接口已定义 |
| M6 | 打磨/发布：性能基准、NSIS/dmg 打包、实验测评 | ⏳ 未开始 |

---

## 二、项目目录结构

```
Yuiro/
├── config/                              # 项目配置文档
│   ├── API_KEYS.md                      # API Key 申请清单（占位说明）
│   ├── CONFIG_SPEC.md                   # 配置规范
│   └── env.ps1                          # PowerShell 环境变量设置脚本
├── docs/                                # 项目文档
│   ├── DEPLOYMENT.md                    # 部署指南
│   ├── milestones.md                    # 里程碑路线图
│   ├── model-selection.md               # 模型选型笔记
│   ├── non-c-drive.md                   # 非 C 盘部署说明
│   ├── research-experiments.md          # 研究实验记录
│   ├── system-daemon.md                 # C++ 守护进程设计文档
│   └── ui-guide.md                      # UI 风格规范（AIRI 视觉语言）
├── engine/                              # ═══ Python 引擎层 ═══
│   ├── config.example.toml              # 引擎配置示例（8 大配置段）
│   ├── pyproject.toml                   # Python 项目定义 + 21 个依赖
│   ├── README.md                        # 引擎子项目说明
│   ├── tests/
│   │   └── test_response_categorizer.py # 响应分类器单元测试
│   └── yuiro/                           # 引擎主包
│       ├── __init__.py                  # 包初始化（版本 0.1.0）
│       ├── config.py                    # 配置加载器（TOML + 环境变量 + keychain）
│       ├── main.py                      # FastAPI 入口 + WebSocket 路由
│       ├── agent/                       # Agent 子包
│       │   ├── __init__.py
│       │   ├── chat_service.py          # 对话服务（Mock / OpenAI 兼容）
│       │   └── response_categorizer.py  # LLM 响应分类（分离思考/口语）
│       ├── audio/                       # 音频子包（M2，占位）
│       │   └── __init__.py
│       ├── emotion/                     # 情感子包（M5，占位）
│       │   └── __init__.py
│       ├── memory/                      # 记忆子包（M3，占位）
│       │   └── __init__.py
│       ├── plugins/                     # 插件子包（M4+，占位）
│       │   └── __init__.py
│       ├── proactive/                   # 主动互动子包（M5，占位）
│       │   └── __init__.py
│       ├── skill/                       # 技能子包（M4+，占位）
│       │   └── __init__.py
│       ├── systemd/                     # 系统守护客户端子包
│       │   ├── __init__.py
│       │   └── client.py               # SystemDaemon MCP 客户端（M0 接口）
│       └── tools/                       # 工具子包
│           ├── __init__.py              # BaseTool / ToolRegistry / TodoTool
│           └── system_tool.py           # 系统操作工具（代理到 C++ 守护）
├── scripts/
│   └── setup_models.ps1                 # 模型下载脚本
├── shell/                               # ═══ Electron + Vue3 壳层 ═══
│   ├── .npmrc                           # npm 配置
│   ├── electron.vite.config.ts          # electron-vite 构建配置
│   ├── package.json                     # Node 项目定义（pnpm）
│   ├── pnpm-lock.yaml                   # 依赖锁定
│   ├── tsconfig.json                    # TypeScript 配置
│   ├── out/                             # 构建产物（已产出）
│   │   ├── main/index.js
│   │   ├── preload/index.mjs
│   │   └── renderer/                    # 含 Live2D 模型资源
│   │       ├── assets/
│   │       ├── index.html
│   │       ├── lib/                     # Live2D SDK
│   │       │   ├── live2d.min.js
│   │       │   └── live2dcubismcore.min.js
│   │       └── live2d/                  # 三个 Live2D 模型
│   │           ├── model_dict.json
│   │           ├── mao_pro/             # 猫娘模型（8 表达式 + 7 动作）
│   │           ├── shizuku/             # Shizuku 模型（4 动作）
│   │           └── 肥牛/                # 肥牛模型（7 表达式 + 13 动作）
│   └── src/                             # 源码
│       ├── main/
│       │   └── index.ts                 # Electron 主进程
│       ├── preload/
│       │   └── index.ts                 # 预加载桥（contextBridge）
│       ├── renderer/
│       │   └── src/
│       │       ├── index.html           # HTML 入口
│       │       ├── main.ts              # Vue3 入口（Pinia）
│       │       ├── App.vue              # 根组件（功能岛 + 面板）
│       │       ├── env.d.ts             # TypeScript 类型声明
│       │       ├── components/
│       │       │   └── Live2DCanvas.vue # Live2D 画布组件（PixiJS）
│       │       ├── composables/
│       │       │   ├── useMousePassthrough.ts  # 鼠标穿透逻辑
│       │       │   └── useVoiceInput.ts        # 语音输入（占位）
│       │       └── styles/
│       │           ├── main.css         # 主样式
│       │           └── tokens.css       # 设计 Token
│       └── shared/
│           ├── index.ts                 # 共享模块导出
│           └── events.ts               # 事件总线类型契约
├── system-daemon/                       # ═══ C++ 系统守护进程 ═══
│   ├── CMakeLists.txt                   # CMake 构建（C++20）
│   ├── include/yuiro/
│   │   ├── capability/
│   │   │   ├── capability.hpp           # 能力抽象基类（Capability）
│   │   │   ├── files.hpp                # 文件能力声明
│   │   │   ├── process.hpp              # 进程能力声明
│   │   │   └── terminal.hpp             # 终端能力声明
│   │   ├── mcp/
│   │   │   └── server_stdio.hpp         # MCP stdio 服务声明
│   │   └── security/
│   │       └── policy.hpp               # 安全策略声明
│   ├── src/
│   │   ├── main.cpp                     # 入口点
│   │   ├── capability/
│   │   │   ├── files.cpp                # 文件能力（M4 实现）
│   │   │   ├── process.cpp              # 进程能力：app_open/app_focus（dry-run）
│   │   │   └── terminal.cpp             # 终端能力（M4 实现）
│   │   ├── mcp/
│   │   │   └── server_stdio.cpp         # stdio JSON-RPC 回显服务
│   │   └── security/
│   │       └── policy.cpp               # 安全策略实现（审批判断 + 路径防护）
│   └── tests/
│       └── test_policy.cpp              # 安全策略测试
├── .gitignore
├── ARCHITECTURE.md                      # 项目架构文档
├── AGENTS.md                            # AI 辅助开发约定
├── README.md                            # 项目说明
└── YUIRO_ANALYSIS.md                    # 👈 本文件
```

---

## 三、三层架构详解

```
┌──────────────────────────────────────────────────────────┐
│  Shell (Electron + Vue3 + PixiJS + Live2D)               │
│  端口：无（浏览器 WebSocket 直连引擎）                     │
│  职责：透明桌宠窗口 / Live2D 渲染 / 功能岛 / 对话面板      │
│        / 托盘管理 / 审批对话框 / 点击穿透控制              │
├──────────────────────────┬───────────────────────────────┤
│  Engine (Python FastAPI) │  SystemDaemon (C++)            │
│  端口：8200 (WS)         │  端口：8300 (HTTP)              │
│          9100 (Metrics)  │  传输：stdio (JSON-RPC)        │
│  职责：Agent 决策         │  职责：OS 操作执行              │
│        LLM 对话           │        进程管理                │
│        ASR/TTS/VAD        │        文件操作                │
│        记忆检索           │        终端执行                │
│        情感/养成          │        输入注入                │
│        工具编排           │        截图                    │
│        审批流程           │        审计日志                │
└──────────────────────────┴───────────────────────────────┘
```

### 3.1 Shell 层（Electron + Vue3）

**技术栈**：Electron 33 + Vue 3.5 + TypeScript 5.6 + PixiJS 7.4 + Pinia 2.3

**主进程** (`src/main/index.ts`)：
- 创建透明无边框桌面覆盖窗口（420×560，alwaysOnTop，非焦点）
- 托盘菜单（设置 / 退出）
- **点击穿透控制**：`setIgnoreMouseEvents` + `sendSync`，默认不穿透（功能岛可交互）
- **审批处理**：原生 Electron `dialog.showMessageBox` 弹出审批确认
- 对话面板打开时切换 `focusable` 状态

**预加载桥** (`src/preload/index.ts`)：
- 暴露最小化 API `window.yuiro`：`send`（发事件）、`on`（订阅事件）、`setMousePassthrough`、`setFocusable`、`requestApproval`

**渲染进程** (`src/renderer/src/`)：
- `App.vue`：根组件，管理功能岛（语音/对话/日志/设置）、对话面板（WebSocket 直连引擎）、日志面板、设置面板
- `Live2DCanvas.vue`：PixiJS 应用，使用 `pixi-live2d-display` 加载 `.moc3` 模型，自适应缩放/居中，接收 `mouthOpen` prop 驱动口型
- `useMousePassthrough.ts`：基于指针位置判断穿透（功能岛/面板不穿透，Live2D 模型区域穿透）
- `useVoiceInput.ts`：语音输入占位（M2 实现 AudioWorklet → WebSocket /ws/audio）

### 3.2 Engine 层（Python FastAPI）

**技术栈**：Python 3.11+ / FastAPI / uvicorn / Pydantic 2 / structlog

**配置系统** (`config.py`)：
- 8 大数据类：`ServerConfig` / `LLMConfig` / `VADConfig` / `ASRConfig` / `TTSConfig` / `MemoryConfig` / `SystemDaemonConfig` / `ObservabilityConfig`
- 加载链：TOML 文件 → 环境变量覆盖 → keychain 读取密钥
- AI 提供者兼容：OpenAI / Anthropic / Ollama / DeepSeek

**WebSocket 路由** (`main.py`)：
- `/ws/control`：控制通道，处理 `chat:user` → `chat:assistant` 文本对话
- `/ws/audio`：音频通道（M2 实现，接收 mic 帧、发送 TTS 数据）
- Shared-secret 鉴权：`x-yuiro-secret` 头，空 secret 时允许开发模式免鉴权

**对话服务** (`agent/chat_service.py`)：
- `ChatResponder` 抽象基类 → `MockResponder`（零配置回显） / `OpenAICompatibleResponder`（真实 LLM）
- 工厂函数 `build_responder` 按优先级获取 API key：参数传入 > 环境变量 > 系统 keychain

**响应分类器** (`agent/response_categorizer.py`)：
- 状态机提取 `<think>` / `<reasoning>` 标签内容为 `reasoning`，其余为 `speech`
- 确保 LLM 思考内容不会泄露到 TTS 朗读中

### 3.3 SystemDaemon 层（C++）

**技术栈**：C++20 / CMake / WinAPI（Windows）

**安全模型** (`security/policy.cpp`)：
- 敏感操作审批列表：`process_kill` / `terminal_exec` / `file_write` / `mouse_inject` / `keyboard_inject`
- 路径防越权：前缀匹配检查
- `ApprovalMode`：NativeDialog（原生对话框）/ AutoGrant / Deny

**能力接口** (`capability/capability.hpp`)：
- `SystemResult` 统一返回结构：trace_id / status / approval_required / stdout / artifacts / audit
- `Capability` 抽象基类：`run(args_json, trace_id, dry_run)` → `SystemResult`
- 所有能力支持 dry-run 模式（模拟执行，不注入输入）

**MCP 传输** (`mcp/server_stdio.cpp`)：
- 当前 M0 为 stdin/stdout JSON-RPC 回显循环
- M4 实现完整 dispatch 表（`tools/call` → capability 路由）

---

## 四、事件总线契约

项目定义了完整的类型安全事件系统（`shell/src/shared/events.ts`）：

| 事件类型 | 方向 | 说明 | 状态 |
|---|---|---|---|
| `chat:user` / `chat:assistant` | Shell ↔ Engine | 文本对话 | ✅ 已实现 |
| `voice-input:start` / `voice-input:stop` | Renderer → Engine | 语音采集控制 | ⏳ M2 |
| `tts:start` / `tts:interrupted` | Engine → Renderer | TTS 播放与打断 | ⏳ M2 |
| `lip-sync:param` | Engine → Renderer | 口型参数驱动 Live2D | ⏳ M2 |
| `action:tool-call` | Engine ↔ Shell | 系统工具调用 | ⏳ M4 |
| `approval:required` / `approval:resolve` | Engine ↔ Shell | 审批请求与结果 | ⏳ M4 |
| `emotion:set` | Engine → Renderer | 情绪驱动表情 | ⏳ M5 |
| `proactive:greet` | Engine → Renderer | 主动打招呼 | ⏳ M5 |
| `vision:capture` | Engine → Renderer | 截图/摄像头采集 | ⏳ M5 |
| `attachment:add` | Renderer → Engine | 附加图片/截图 | ⏳ M5 |

---

## 五、技术栈总览

### 5.1 Python 引擎依赖（21 个）

| 类别 | 依赖 | 版本要求 |
|---|---|---|
| Web 框架 | fastapi | ≥0.115 |
| ASGI 服务器 | uvicorn[standard] | ≥0.30 |
| WebSocket | websockets | ≥12 |
| 数据验证 | pydantic / pydantic-settings | ≥2.6 / ≥2.0 |
| 日志 | structlog | ≥24.0 |
| 密钥管理 | keyring | ≥25.0 |
| 语音检测 | silero-vad | ≥5.0 |
| 语音识别 | faster-whisper | ≥1.0 |
| 语音合成 | edge-tts | ≥6.1 |
| 数值计算 | numpy | ≥1.26 |
| 向量存储 | sqlite-vec | ≥0.1 |
| 嵌入模型 | FlagEmbedding (BGE-M3) | ≥1.3 |
| LLM 客户端 | openai / anthropic | ≥1.40 / ≥0.30 |
| HTTP 客户端 | httpx | ≥0.27 |
| MCP 协议 | mcp | ≥1.0 |
| 监控 | prometheus-client | ≥0.20 |

### 5.2 Shell 前端依赖

| 类别 | 依赖 | 版本要求 |
|---|---|---|
| 桌面框架 | electron | ^33.2.0 |
| UI 框架 | vue | ^3.5.13 |
| 状态管理 | pinia | ^2.3.0 |
| 工具库 | @vueuse/core | ^11.3.0 |
| 2D 渲染 | pixi.js | ^7.4.3 |
| Live2D | pixi-live2d-display / live2dcubismcore | 0.5.0-beta / ^1.0.2 |
| 构建 | electron-vite / vite / typescript | ^2.3.0 / ^5.4.11 / ^5.6.3 |
| 打包 | electron-builder | ^25.1.8 |
| 类型检查 | vue-tsc | ^2.1.10 |

### 5.3 C++ 守护进程

- 标准：C++20
- 构建：CMake 3.20+
- Windows 依赖：shell32.lib / user32.lib
- 无外部第三方依赖（M0 阶段纯标准库 + WinAPI）

---

## 六、已落地的功能组件分析

### 6.1 可运行状态（M1 已完成部分）

| 功能 | 实现细节 | 完成度 |
|---|---|---|
| Electron 透明桌宠窗口 | 无边框、透明、置顶、非焦点、内容保护 | ✅ 100% |
| Live2D 模型渲染 | PixiJS 7 + pixi-live2d-display，3 个模型（肥牛/mao_pro/shizuku） | ✅ 100% |
| 点击穿透控制 | 基于指针位置 + sendSync 同步穿透切换 | ✅ 100% |
| 功能岛 UI | 语音/对话/日志/设置按钮 + 连接状态指示 | ✅ 100% |
| 对话面板 | WebSocket 直连引擎，发送/接收文本 | ✅ 100% |
| FastAPI 引擎 | /ws/control 文本对话通道 + shared-secret 鉴权 | ✅ 100% |
| Mock 对话 | 零配置回显，无需 API key 即可跑通管线 | ✅ 100% |
| 配置系统 | TOML + 环境变量 + keychain，8 大配置段 | ✅ 100% |
| 响应分类器 | `<think>/<reasoning>` 标签提取，防止思考内容 TTS 朗读 | ✅ 100% |

### 6.2 接口已定义但实现占位的功能

| 功能 | 占位位置 | 设计方案 |
|---|---|---|
| 语音采集与 VAD | `useVoiceInput.ts` / `audio/__init__.py` | AudioWorklet 16kHz → silero-vad 状态机 |
| ASR 语音识别 | `config.py` ASRConfig | faster-whisper small/int8 |
| TTS 语音合成 | `config.py` TTSConfig | edge-tts 分段流式 |
| 口型同步 | `events.ts` LipSyncPayload | wLipSync 或 RMS 驱动 `ParamMouthOpenY` |
| 记忆系统 | `memory/__init__.py` / MemoryConfig | sqlite-vec + BGE-M3 + RRF 检索 |
| 系统工具执行 | `systemd/client.py` / `system_tool.py` | MCP 协议 → C++ 守护 |
| 审批队列 | `main/index.ts` registerApprovalHandler | 原生 Electron 对话框 |
| 情绪系统 | `emotion/__init__.py` | 情绪衰减 `emotion:set` |
| 主动互动 | `proactive/__init__.py` | 定时观察 + LLM 决策 |
| 工具自动生成 | `tools/__init__.py` function_to_tool_schema | docstring → OpenAI schema |

---

## 七、关键设计决策

| 决策 | 理由 | 影响 |
|---|---|---|
| 三层架构分离 | 控制面/执行面分离 → 安全审计独立 | 增加进程间通信复杂度 |
| C++ 守护进程 | 直接 WinAPI 操作、独立沙箱、无 GC 停顿 | C++ 生态 LLM 工具链弱，只能做"手" |
| MCP 协议通信 | 标准化工具调用接口、审批/审计协议内置 | MCP 生态尚在演进中 |
| Shared-secret 鉴权 | 本地进程间简单有效，避免 OAuth 复杂度 | 密钥需妥善管理 |
| 密钥走 keychain | 防止明文密钥落盘 | 增加配置前准备步骤 |
| 点击穿透区域判断 | 避免透明窗口完全遮罩桌面 | 实现复杂度较高 |
| Mock 优先开发 | 无需 API key 即可跑通管线 | 零成本验证架构 |
| 思维标签分离 | 防止 LLM 推理内容 TTS 朗读 | 依赖 LLM 输出格式规范 |

---

## 八、当前可改进点

### 8.1 代码层面

1. **大量占位桩（stub）待实现**：`audio/`、`emotion/`、`memory/`、`proactive/`、`skill/`、`plugins/` 包仅有 `__init__.py`，无实质代码。`systemd/client.py` 的 `connect()` 和 `call()` 抛出 `NotImplementedError`。

2. **SystemDaemon 为 echo 回显**：`server_stdio.cpp` 仅做 JSON-RPC 回显，未实现 capability dispatch。`files.cpp` / `terminal.cpp` 为空实现。

3. **useVoiceInput.ts 完全空白**：`start()` / `stop()` 函数体为空，AudioWorklet 相关代码未编写。

4. **ToolRegistry 未实现**：`schemas()` 和 `execute()` 方法体为 `...`（Ellipsis），工具自动发现机制缺失。

5. **缺少错误处理与重连逻辑**：WebSocket 断连后无自动重连机制，前端仅显示状态变化。

6. **测试覆盖极低**：仅有 `test_response_categorizer.py` 一个测试文件，覆盖 3 个纯函数场景。无集成测试、无 Shell 层测试、无 C++ 测试。

### 8.2 架构层面

7. **WebSocket 直连绕过主进程**：渲染进程用浏览器原生 WebSocket 直连 `127.0.0.1:8200`，无法在主进程中做流量审计或中间件拦截。`shared-secret` 暴露在渲染进程 JavaScript 上下文中。

8. **缺少引擎健康监控**：`/health` endpoint 存在但未被 Shell 使用，引擎挂掉时前端无感知（仅 WebSocket 断连）。

9. **Live2D 模型路径硬编码**：`MODEL_PATH = '/live2d/肥牛/feiniu.model3.json'` 在组件中硬编码，不支持运行时切换模型。

10. **配置加载路径固定**：`load_config()` 默认读取 `./config.toml`，在打包分发时路径可能变化。

### 8.3 工程化层面

11. **无 CI/CD 配置**：缺少 GitHub Actions / 构建流水线。

12. **日志系统不完善**：Shell 层仅有 `logs` 数组存储运行时日志，无结构日志、无日志落盘。

13. **缺少 Docker 支持**：本地开发需要独立安装 Python 3.11+ / Node.js / CMake 等环境。

14. **无版本兼容性检查**：Shell 和 Engine 版本号各自独立，无版本协商机制。

---

## 九、模块依赖关系图

```
                    ┌──────────────────────┐
                    │     App.vue           │
                    │  (功能岛 + 面板 + WS)  │
                    └──────┬───────┬───────┘
                           │       │
              ┌────────────┘       └────────────┐
              ▼                                 ▼
    ┌─────────────────┐              ┌─────────────────────┐
    │ Live2DCanvas.vue│              │ useMousePassthrough │
    │ (PixiJS Live2D) │              │ useVoiceInput (M2)  │
    └────────┬────────┘              └─────────────────────┘
             │ PixiJS + pixi-live2d-display
             ▼
    ┌─────────────────┐
    │ 肥牛/mao_pro/    │
    │ shizuku .moc3    │
    └─────────────────┘

                           WebSocket
              ┌────────────────┴────────────────┐
              ▼                                 ▼
    ┌─────────────────┐              ┌─────────────────────┐
    │ /ws/control     │              │ /ws/audio (M2)      │
    │ chat:user→reply │              │ mic 帧→TTS/lipsync  │
    └────────┬────────┘              └─────────────────────┘
             │
    ┌────────┴────────┐
    │  ChatResponder   │
    │  (Mock/OpenAI)   │
    └────────┬────────┘
             │
    ┌────────┴────────┐
    │ ResponseCategor. │
    │ <think> → speech │
    └─────────────────┘

                      MCP (stdio/HTTP) (M4)
              ┌────────────────┴────────────────┐
              ▼                                 ▼
    ┌─────────────────┐              ┌─────────────────────┐
    │ SystemDaemonClient│            │  SystemDaemon (C++) │
    │ (Python)         │              │  stdio JSON-RPC     │
    └─────────────────┘              └──────────┬──────────┘
                                                │
                              ┌─────────────────┼─────────────────┐
                              ▼                 ▼                  ▼
                     ┌──────────┐     ┌──────────────┐    ┌──────────┐
                     │ Capability│    │   Security    │    │   MCP    │
                     │ process/  │     │  Policy/Audit │    │  server  │
                     │ files/    │     │  approval/    │    │  stdio   │
                     │ terminal  │     │  dry-run      │    │          │
                     └──────────┘     └──────────────┘    └──────────┘
```

---

## 十、总结

Yuiro 是一个**架构设计严谨、模块分离清晰**的桌面宠物项目。其核心亮点在于：

1. **三层多语言架构**：TypeScript(Shell) / Python(Engine) / C++(Daemon)，每层专精其领域，通过 WebSocket + MCP 协议解耦
2. **安全优先哲学**：控制面/执行面分离、dry-run 沙箱、审计日志、密钥走 keychain，借鉴了 AIRI computer-use-mcp 的成熟设计
3. **良好的接口契约**：事件类型系统、配置数据类、能力抽象基类，即使实现占位也能明确知道每个模块的输入输出
4. **Mock 优先可测试**：无 API key 也能跑通完整管线，降低开发门槛

目前项目处于 **M0 架构骨架 → M1 可运行骨架** 过渡阶段，文本对话管线已可运行，Live2D 渲染已就绪，但语音、记忆、系统操作等核心功能均为接口占位。后续迭代需重点实现 M2-M4 的核心能力。

---

*本报告基于对项目全部源码文件（排除 node_modules / __pycache__ / dist / out 目录）的完整阅读和分析生成。*
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
