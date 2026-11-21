# Yuiro — AGENTS.md

> 声控桌宠（复刻 Neuro-sama）：Electron 壳 ⇄ Python 引擎 ⇄ 系统执行后端（native 默认 / C++ 守护可选）。
> **当前阶段（2026-09 起：Runtime 演进期）**：M0–M4 能力已落地并可运行——文本/语音对话（SenseVoice / faster-whisper ASR + 三路 TTS：CosyVoice / GPT-SoVITS / SiliconFlow）、sqlite-vec 三层记忆、网易云音乐接入、系统工具调用（S10 起默认 Python 原生后端，审批/dry-run/审计；C++ SystemDaemon 降级为可选后端）。
> **主线**：按 `docs/spec/roadmap.md` 的 Wave 序列演进——目标是把"功能完整的桌宠"升级为 **General Agent Harness + Embodied Desktop Runtime**。
> **进展（2026-09-12）**：Wave 0（Trace / Session / Generation / EventBus）、Wave 1（真 Barge-in、分段流式 TTS）、Wave 2 部分（AvatarIntent 表情通道）、Wave 3（ContextEngine）、Wave 4 部分（Explicit Memory）、Wave 5 部分（TaskRuntime）、Wave 6 部分（Artifact Store）**均已落地**；每个 Sprint 的计划、冒烟证据、DoD 对照与遗留见 **`docs/plan/README.md`**（执行层索引）。
> **动代码前必读 `docs/spec/`**（目标架构 / P0 内核规范 / 路线图 / 开发协议与护栏）；历史红线与排障经验见下文「契约与约定」。

## 架构演进目标（2026-09 起）

- **目标形态**：General Agent Harness + Embodied Desktop Runtime（Runtime-centric Embodied Personal Agent）。
- **主轴**：统一 Runtime Contract（Session / Generation / Cancellation / Lifecycle / Trace）+ Harness 六项 ownership（Session / Context / Task / Permission / Cancellation / Tool 可见性）。
- **六个一等实体**：`Session / Task / Event / Intent / Artifact / Capability`。
- **Stable Kernel + Pluggable Edge**：Session/Generation/Cancellation 语义、Event Schema、Security Policy 不可插件化；LLM / ASR / TTS / Live2D 资产 / Memory 后端 / Tools / UI 可替换。
- **推进顺序**：Wave 0 Harness Foundation → Wave 1 Speech（Barge-in）→ Wave 2 Avatar → Wave 3 Context Engine → Wave 4 Memory Lifecycle → Wave 5 Task/Plan → Wave 6 Security → Wave 7 Presence/Background → Wave 8 Subagent/Skill/Plugin；Personal Brain Track 贯穿。
- **规范索引**：
  | 文档 | 用途 |
  |---|---|
  | `docs/spec/README.md` | 总索引 + 最高锚点 + 全局硬约束 |
  | `docs/spec/architecture-goal.md` | 目标架构 + 组件契约 + DoD + 禁止事项 |
  | `docs/spec/runtime-contract.md` | P0 内核规范 + 现状基线（含未接线骨架清单） |
  | `docs/spec/roadmap.md` | Wave 序列 / Era 0–5 / Personal Brain / Sprint 机制 |
  | `docs/spec/coding-agent-protocol.md` | 开发协议 + 母 Prompt + 护栏 + 测试三层 |
  | `docs/spec/target-file-preview.md` | 目标形态与文件预览（目录树 + 关键类骨架 + Wave 检查表） |
- **改造原则**：`复用现有实现 → 抽抽象 → 适配 → 替换调用路径`；禁止 `删除 → 重写`。AgentLoop / Memory / VoicePipeline / Live2D / SystemDaemon 均适用。
- **每个任务五要素**：Goal / Scenario / Architecture Increment / Tests / Definition of Done；一个 Sprint = 一个主要惊喜 + 一个架构增量 + 一个工程指标。
- **新红线（违反即打回）**：Cancellation 必须传播且不得被吞掉；Generation mismatch 的结果不得进入 state / conversation / memory / TTS queue / avatar；Memory ≠ Fine-tuning（知识不进入权重）；Context 是稀缺资源（大工具结果走 Artifact Store + 摘要）；Capability ≠ Architecture（先做 Session/Context/Task，不先做 Subagent/Plugin）；Subagent 不随意 spawn。

## 三子项目与入口

| 目录 | 技术 | 入口 / 构建 |
|---|---|---|
| `engine/` | Python FastAPI + uvicorn | `yuiro.main:app`（WS: `/ws/control`, `/ws/audio`；须在 `engine/` 目录内启动） |
| ├ `engine/yuiro/tts_server/` | 独立进程本地 TTS（CosyVoice2 GPU 推理，yuiro 子包，端口 5005） | `python -m yuiro.tts_server.server`（HTTP 调用，不并入主进程） |
| ├ 外部 GPT-SoVITS Bundle（`E:\AI\GPT-SoVITS-v2pro-20250604\...`，自带 runtime，端口 5000） | 本地 TTS 备选（GPT-SoVITS v2ProPlus，AR 架构，音色由说话人模型固化） | `scripts/start_gptsovits.ps1`（engine 侧 `GPTSoVITSProvider` HTTP 调用，不 import） |
| `shell/` | Electron + Vue3 + TypeScript | **pnpm**（electron-vite），`shell/package.json` |
| `system-daemon/` | C++20 CMake | **可选执行后端**（`[systemd].backend = "daemon"` 时启用）；stdio newline-JSON 的 MCP 类协议，能力在 `src/capability/`。**默认后端为 `engine/yuiro/native/`（Python 原生，无需 C++ 工具链）** |

## 环境（Windows，必须先做）

- **加载本地环境**：在仓库根目录执行 `. .\config\env.ps1`。它设置 `YUIRO_*` 并把 HF/Torch/npm/electron 缓存全部重定向到项目内 `.env-local/`（**不占 C 盘是硬约定**，别往 `C:\Users\...\AppData` 装东西）。
- Python venv 在 `.env-local/engine-venv2`（**uv** 基于独立完整 CPython 3.13.11 创建；`engine-venv` 基于 ComfyUI 裁剪版 Python 缺标准库，已废弃勿用）。**本机无 `uv` 命令**，但 `D:\software\ComfyUI-aki-v3\ComfyUI-aki-v3\python\Scripts\uv.exe` 可用；直接用 `& .env-local\engine-venv2\Scripts\python.exe ...`。
- venv2 已装 runtime + dev 依赖。**CUDA 推理依赖**：已装 `nvidia-cublas-cu12` / `nvidia-cuda-runtime-cu12`，`ASRProvider._configure_cuda_runtime` 会把其 DLL 目录加入 PATH。GPU 为 RTX 3060（驱动 596.36 / CUDA 13.2）。faster-whisper 走 ctranslate2，**不依赖 torch 的 CUDA**（torch 为 CPU 版即可）。
- 跑测试前（如需 dev 依赖）：`.env-local\engine-venv2\Scripts\python.exe -m pip install -e "engine[dev]"`（venv2 无 pip，改用 uv：`& "D:\software\ComfyUI-aki-v3\ComfyUI-aki-v3\python\Scripts\uv.exe" pip install ...`）。
- shell 的 `node_modules` 已就绪；`pnpm`/`node` 可用。
- **C++ 工具链已配置**：MSVC / CMake / Ninja 装在 `D:\cppVenv\VS2022`（约 3.35 GB）；Windows SDK 装在 `D:\Windows Kits\10`（版本 10.0.28000.0，含 WinRT 头 `Windows.Media.Control.h`）。由于 SDK 不在默认 C 盘路径，`system-daemon` 的 CMake 已通过 `CMAKE_VS_WINSDK_DIR` / `WindowsSDKDir` 环境变量适配（见其 `CMakeLists.txt`），并加 `/utf-8` 编译选项避免中文注释触发 C4819。构建命令（已固化成脚本，推荐直接用）：
  ```powershell
  cmd /c "D:\Project\Yuii\desktop-pet\Yuiro\scripts\build_daemon.bat"
  ```
  该脚本会先 `vcvarsall.bat x64` 初始化 MSVC 环境，再 configure + build（Ninja + MSVC）。注意：
  - 禁止把 `D:\software\Qt\Tools\mingw1310_64\bin` 留在 PATH 里，否则会与 MSVC 冲突导致 `yuiro.exe` 用 g++ 链接失败。
  - `system-daemon` 是 stdio newline-JSON 的 MCP 类服务，协议为 JSON-RPC 2.0（`tools/list` 列工具、`tools/call` 调工具，参数 `params.name` / `params.arguments` / `params.dry_run`）。本地冒烟测试：
    ```powershell
    cd system-daemon
    '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"app_open","arguments":{"name":"notepad"},"dry_run":true}}' | .\build\yuiro.exe
    ```
  - 单元测试：`cmake --build build --target yuiro_tests` 后运行 `.\build\yuiro_tests.exe`（或脚本里加 `BUILD_TESTING=ON`）。

- `engine/config.toml` 不存在：从 `engine/config.example.toml` 复制创建。

## 命令

```powershell
# 引擎 + 本地 TTS：推荐用脚本（自动清理 8200/5005/5000 端口残留 + 用 venv2 启动；
# 不带 --reload，因为 uvicorn reloader 会与 BGE-M3 的 multiprocessing spawn 冲突导致 BrokenPipe）
& .\scripts\engine\engine_start.ps1        # 启动引擎(8200) + 按 config.toml [tts].provider 起本地 TTS
#                                   #   provider=gptsovits → GPT-SoVITS(5000)；cosyvoice → tts_server(5005)
& .\scripts\engine\engine_stop.ps1         # 停止（WMI 强杀，释放 8200/5005/5000，连带 TTS 进程）
#   -NoTTS 开关：仅起引擎、不同步起 TTS（调试 TTS 时用）
#   & .\scripts\engine\engine_start.ps1 -NoTTS

# 另开终端：
# 引擎日志（实时跟随）
Get-Content .env-local\engine_start.err.log -Tail 30 -Wait

# TTS 日志（按当前 provider）：
Get-Content .env-local\gptsovits.err.log -Tail 30 -Wait    # GPT-SoVITS(5000)
Get-Content .env-local\tts_server.err.log -Tail 30 -Wait   # CosyVoice(5005)


# 单独调试 GPT-SoVITS（在仓库根目录）
& .\scripts\tts\start_gptsovits.ps1 -Role MyGO_要乐奈           # 起 5000 服务（外部 Bundle）
# 验证 GPT-SoVITS 合成（httpx POST {text, text_language} 到 5000）

# 单独调试 CosyVoice（在仓库根目录）
& .\engine\yuiro\tts_server\start_tts_server.ps1    # 仅起端口 5005 的 tts 服务
& .env-local\engine-venv2\Scripts\python.exe -m yuiro.tts_server.test_voice   # 验证音色

# 手动启动引擎（在 engine/ 目录内；必须显式 --port 8200，壳层连的是 8200；勿加 --reload）
cd engine
& ..\.env-local\engine-venv2\Scripts\python.exe -m uvicorn yuiro.main:app --host 127.0.0.1 --port 8200

# 引擎测试（先装 dev 依赖；在 engine/ 目录内）
& ..\.env-local\engine-venv2\Scripts\python.exe -m pytest tests/ -q

# 壳层（在 shell/ 目录内）
pnpm dev          # 开发
pnpm typecheck    # vue-tsc --noEmit（改 TS 后必须过）
pnpm build        # electron-vite build → out/
pnpm build:win    # + electron-builder 打包
```

## 网易云音乐接入

基于网易云**官方** ncm-cli（`@music163/ncm-cli`），不走逆向接口。
完整设计与实测结论见 `docs/features/netease-music-design.md`（**改动前必读**）。

- **依赖**：ncm-cli（npm 全局）+ mpv（`D:\cppVenv\mpv`，已由 `config/env.ps1` 并入 PATH）
- **凭证**：appId / privateKey 由 ncm-cli 自身托管（`ncm-cli config set`），
  **不进本仓库、不进日志**；`[netease]` 配置段只放非敏感项
- **登录是前提**：`search` / `playlist` / `recommend` / `song` 等命令
  **登录后才动态加载**，未登录时调用会报 unknown command

三条硬事实（均为实测所得，勿凭直觉推翻）：

1. **Windows 客户端「不能点歌」，但「可以被控制」**（2026-09-16 厘清；旧版把两者
   混为一谈，结论过于悲观）：
   - **点歌不可行**：`orpheus://` 投递、`cloudmusic.exe --webcmd`、
     `--player orpheus`（报"仅支持 macOS"）——均失败（09-16 复测仍无效）。
     → 声音由 mpv 发出，与桌面客户端是**两个独立播放源**，同时开着会有两个声音。
   - **控制可行**：客户端「设置」勾选 **「开启 SMTC」** 后即注册系统媒体会话
     （实测 `aumid=cloudmusic.exe`，可读 title/artist，可 play/pause/next/prev）。
     ⚠️ 旧版称"客户端不注册会话"是**错误结论**——真因是查询桥用了 pwsh 7 才有的
     `IAsyncOperation.GetAwaiter()`，Windows PowerShell 5.1 下**从未成功**，
     失败被误读成"没有会话"（已在 `native/ops.py` 修复：改 `AsTask`+`Await`）。
2. **播放链路 = 引擎自管 mpv（2026-09-12 起）**：`netease/api.py`（自签名直连
   开放平台取直链）+ `netease/player.py`（spawn mpv + `\\.\pipe\yuiro-mpv` IPC）。
   **ncm-cli 仅用于登录**（扫码 + Node 钩子取 accessToken）。
   ⚠️ 旧版"播放依赖 `NCM_DAEMON=1` 常驻进程"**已废弃**——ncm-cli 登录态下取到
   playUrl 却**始终不启动播放器**（实测 16s 内 mpv 进程恒为 0）。其 daemon 的
   30s 自杀 / 3s 超时问题随之失效，`client.py::ensure_daemon()` 与
   `_keepalive_loop` 属**遗留路径**（仅在显式使用 ncm-cli 播放时才会走到）。
   （注：`mpv` 目录里的 `mpv.com` 仍需保持改名状态——PATH 会把 `.COM` 解析成
   那个 0KB 控制台包装器而非 `mpv.exe`。）
3. **ID 有两种形态不可混用**：`originalId`（明文数字）用于播放，
   `id`（32 位 hex）用于歌词与歌单写操作。

LLM 工具：`netease_search` / `netease_play` / `netease_control` /
`netease_playlist` / `netease_recommend` / `netease_lyric`。

**控制的分工**（2026-09-16）：
- `netease_control` → 桌宠自己放的歌（mpv IPC）；**mpv 空闲时会自动转投 SMTC**，
  去控制用户自己开着的播放器，避免回一句"没有在播放"（见
  `tools/netease_tool.py::_forward_to_system`）。
- `media_control`（SMTC）→ 用户自己开着的播放器（已开启 SMTC 的网易云客户端、
  浏览器等）。控制动作**优先按 AUMID 锁定会话**，找不到才降级全局媒体键
  （媒体键是误控根因，故仅作兜底）。

`media_bridge`（URI 投递）因证实**无法点歌**而未注册到 MCP 工具表，
详见 `system-daemon/include/yuiro/capability/media_bridge.hpp` 注释。

## 契约与约定

- **端口**：Engine 8200（localhost-only）、本地 TTS 5005（CosyVoice2）或 5000（GPT-SoVITS，两者互斥按 provider 选）、SystemDaemon HTTP 8300（可选）、Metrics 9100。
- **TTS 进程隔离（架构红线）**：本地 TTS 推理一律跑在**独立进程**，`engine` 主进程只经 HTTP 调用（`CosyVoiceProvider` / `GPTSoVITSProvider` 只发请求、绝不 import 推理核心，避免与 SenseVoice ASR 抢显存/GIL）。**不要把 TTS 推理并入 `uvicorn yuiro.main:app` 同进程**。两条路径：
  - **CosyVoice2**：`yuiro.tts_server.server`（端口 5005，yuiro 子包，~4.8GB 显存）。推理核心在 `engine/yuiro/audio/cosyvoice_engine.py`，torch/cosyvoice import 惰性。
  - **GPT-SoVITS**：外部 Bundle（`E:\AI\GPT-SoVITS-v2pro-20250604\...`，自带 `runtime\python.exe`，端口 5000），engine 侧 `GPTSoVITSProvider` POST `{text, text_language}` 到 `/`，音色在服务启动时用 `-g/-s`(说话人模型)+`-dr`(参考音频)固化。**不 import、不复制 Bundle 进 engine**（磁盘大，只引用外部路径）。
  - 启动编排：`scripts/engine_start.ps1` 读取 `config.toml [tts].provider` 自动分支；`scripts/start_gptsovits.ps1` 单独起 GPT-SoVITS（可选 `-Role` 切换角色）。
  - **SiliconFlow 云端 TTS**（`SiliconFlowProvider`，零本地显存，无需独立进程）：`provider=siliconflow` 时 `engine_start.ps1` 不再起本地 TTS，直接用 HTTPS 调 `https://api.siliconflow.cn/v1/audio/speech`。**零样本克隆用请求体 `references=[{audio:<base64 data-url>, text:<参考转写>}]` 且不可同时设 `voice`**（实测 `/v1/audio/voice-cloning` 路径 404 不可用，内联 references 克隆有效）。参考音频 `assets/voices/Model/Neuro/参考音频.wav`，启动时 base64 缓存复用。API key 走 keychain（`service=yuiro-siliconflow`，用户名 `tts`），`config.toml` 不写明文 key。
- **镜像优先（资源获取约束）**：凡需联网获取依赖、模型、库或二进制，一律**优先用国内可达镜像**，默认能走镜像就不直连官方源。已知可用镜像：
  - PyPI 包：`https://mirrors.aliyun.com/pypi/simple/`（uv/pip 加 `--index-url`；本机实测官方 pypi 时快时慢，nvidia 大包必走镜像）。
  - HuggingFace 模型：**ModelScope**（`modelscope.snapshot_download`，见 `scripts/setup/downloads/download_bge_m3_modelscope.py`）；HF 官方 CDN 国内常需代理，勿作为默认。
  - Python 解释器（uv）：`UV_PYTHON_DOWNLOADS_MIRROR=https://registry.npmmirror.com/-/binary/python-build-standalone`。
  - 示例：BGE-M3 落在 **`engine/models/bge-m3`**（`[memory].embedder = "models/bge-m3"` 相对 `engine/` 解析；两个下载脚本的落点都对齐到该目录，勿再下到 `.env-local/models/bge-m3` 造出重复权重）；CUDA 用 aliyun 镜像装 `nvidia-*` wheel。**注意**：npmmirror 的 `/pypi/simple/...` 路径会 404，PyPI 镜像请用 aliyun 而非 npmmirror。
- **鉴权**：两个 WS 通道校验请求头 `x-yuiro-secret` 等于 `YUIRO_SHARED_SECRET`，否则 `4401` 关闭。
- **系统操作只经执行后端**（S10 起修订）：`Agent → Capability → Approval → 执行后端`。后端可切换：`[systemd].backend = "native"`（`engine/yuiro/native/`，**默认**，Python 原生）/ `"daemon"`（C++ SystemDaemon，可选，产物需先构建）。**不要绕过后端直接在工具里加 OS 调用**（安全链是架构红线）；native 的文件读写受 `[systemd].file_roots` 边界约束（默认仅 engine 目录）。两个后端行为契约一致（工具名/参数/dry-run 文案/错误语义）。
- **事件契约（2026-09 起拆分）**：`shell/src/shared/events.ts` 只承载 **IPC 窗口类事件**（`appearance:update` / `fade:*` / `overlay:*`，现状仅 `appearance:update` 真正在用）；**引擎 WS 协议**（`chat:*` / `emotion:set` / `approval:*` / `tts:*`）目前是渲染层直连引擎的裸 JSON —— 目标态收敛为 `shell/src/shared/engine-protocol.ts` **单一来源**（见 `docs/spec/target-file-preview.md` §3.11，Wave 0 落地）。改引擎事件先改 protocol 类型，不要再往 events.ts 里加引擎事件。
- **`shell/src/` 下存在与 `.ts` 并存的过期 `.js` 副本**（旧转译残留，不会参与构建）。只改 `.ts`，不要同步改 `.js`；构建产物在 `out/`（gitignore）。
- ruff：line-length 100，target py311（见 `engine/pyproject.toml`）。仓库文档/注释/UI 用中文。
- **渲染层日志统一走主进程终端（开发准则）**：`shell/src/main/index.ts` 已给桌宠窗口 webContents 加 `console-message` 转发，渲染层 `console.log` 会以 `[render]`/`[render:warn]`/`[render:error]` 打到 `pnpm dev` 终端，**无需开 F12 DevTools**。排查前端交互/渲染问题先看终端日志（如 `[bracket] open`、`[drag] start`、`[live2d] motionManager has:...`），再决定是否开 F12 看 DOM/网络。新增渲染层关键分支时，用带 `[模块名]` 前缀的 `console.log`（如 `[live2d]`、`[bracket]`），确保能转发到终端。
- **链路日志分阶段定位（红线）**：聊天/语音/记忆等长链路必须在**每个环节打 `vlog` 阶段标记**，让"卡住时能从日志判断执行到哪"。
  - `chat` 链路：`vlog("chat", ...)` 已有「处理 chat:user → 调用 AgentLoop/LLM → 收到首 token → 回复 chat:assistant（耗时）」。
  - `agent` 链路：`AgentLoop.send` 每轮 LLM 调用开始、LLM 首 token 耗时、流式结束；**LLM 建流失败必须打异常类型+消息**（`agent/__init__.py:OpenAIProvider.stream_text`），否则「聊天无回复」时无从知道是连接失败(APIConnectionError)、key 无效(401)还是超时。
  - 排查「无回复」先看 engine_start.out.log（`vlog` 打 stdout，非 err.log）的 `[chat]`/`[agent]` 段。
- **qwen3 思考模式会拖慢聊天（红线）**：qwen3 系列（`qwen3-flash`/`qwen3-plus` 等）默认 `enable_thinking=True`，模型先输出大段思考再回复，**首 token 延迟 20s+**。`OpenAIProvider.stream_text` 已针对模型名含 `qwen3` 时自动 `extra_body={"enable_thinking": False}` 关闭。若换其他 reasoning 模型，记得同样处理；排查「回复特别慢」先确认是否开了 thinking。
- **LLM key（keychain）是聊天链路命门**：聊天无回复 90% 是 LLM key 无效(401)或 base_url 与 key 不匹配（keychain 存 deepseek key 却配 qwen/阿里云 base_url → APIConnectionError 拖 20s）。排查时直接测 `OpenAIProvider.stream_text` 单发即可。
- **记忆检索超时会卡死聊天（红线）**：`MemorySystem.retrieve` 第一步 `embedder.embed()` 是子进程 Pipe 阻塞读，**若无超时且 BGE-M3 子进程卡住（GPU 竞争/模型加载慢），`await embed()` 会无限挂起**，连带卡死 AgentLoop 整条聊天链路（表现为「收到消息后无任何后续日志，前端超时断开」）。**修复**：`Embedder.embed` 的 `recv` 已加 10s 超时、`retrieve` 的 gather 已加 5s 超时，超时回退 md5 向量不阻断对话。**排查**：stderr 出现 `BGE-M3 子进程响应超时` 即此问题。
- **BGE-M3 在引擎环境嵌入不稳定 → 临时 md5 降级**：`config.toml [memory] embedder` 当前为 `"md5"`（避免每次 10s 超时拖累聊天）。若修好 BGE-M3 子进程，改回模型路径恢复语义检索。注意 Embedder 用 `spawn`（Windows 必需），测试脚本必须加 `if __name__ == '__main__'`。
- **记忆污染会压制工具调用（红线）**：`memory_writer` 每轮把「用户问→助手答」写入 L2 情景记忆；若历史上有「用户要求系统操作→助手纯文字回复（没调工具）」的失败记录，下次同类请求会经 FTS/新近度检索注入，LLM **模仿记忆里的旧模式而不调工具**（表现为裸调 `stream_text` 能触发 tool_call、引擎运行时死活不调）。**排查**：查 `data/yuiro_memory.db` 的 `messages` 表是否有污染条目（`DELETE FROM messages/msgs_fts/messages_vec WHERE rowid IN ...`，vec 表需 `conn.enable_load_extension(True)` 后 `sqlite_vec.load(conn)`）；**防护**：`[memory].memory_prompt` 已内置「记忆不约束当前行为、系统操作必须调工具」声明，勿删该句。
- **stream_text 的 tool_call chunk 必须在 try 内 yield（红线）**：`OpenAIProvider.stream_text` 把流式累积的 tool_call 放在 `finally` **之后** yield 会被 GeneratorExit 吞掉（AgentLoop 消费完 `aclose` 时序），表现为「LLM 永不调工具」——非流式正常、裸流式正常、唯独引擎链路不触发。**修复**：tool_call yield 已移入 `try` 块（`finally: stream.close()` 之前）。
- **LLM 超时无输出时兜底语会伪装成功（已修）**：`_agent_reply` 旧版空回复兜底语是「已经帮你执行了…」，但超时（APITimeoutError）时**什么都没执行**，日志却像成功。现已按 `tool_ran` 区分：工具真执行过才说「已执行」，否则说「信号不好再说一次」。排查「回复像幻觉」先看日志有无 `APITimeoutError`/`流式结束，共 0 段`。
- **架构蓝本（2026-09 更新）**：`docs/spec/` 是目标架构与开发协议的**权威规范（动代码前必读）**；`ARCHITECTURE.md` 是当前架构说明（as-is）+ 模块接口契约；`docs/init/milestones.md` 是 M0–M6 历史里程碑（新主线以 `docs/spec/roadmap.md` 为准）。本仓库技术选型优先于父目录 `D:\Project\Yuii\AGENTS.md`：ASR 默认 FunASR SenseVoice（可选 faster-whisper）、TTS 按 `[tts].provider` 三路（CosyVoice / GPT-SoVITS / SiliconFlow，edge-tts 兜底）、记忆 sqlite-vec——勿按父文档"修正"回旧选型。
