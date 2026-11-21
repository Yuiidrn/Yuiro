# Yuiro 架构总览

> **定位（2026-09 起）**：本文件是**当前架构说明（as-is）+ 模块接口契约**；目标架构（to-be）
> 与演进规范以 `docs/spec/` 为准，两者冲突时以 spec 为准。
> 高层结构 + 模块边界 + 数据流 + **所有模型/接口契约**。
> 调研基线：deskpet / Open-LLM-VTuber / my-neuro / Agentic-Desktop-Pet / OpenDesktop-Pet / Live2DPet / AIRI 的所长提炼（详见 README 技术栈清单）。
> 注：壳层前端采用 **TypeScript**（Vue3 + TS）实现。

---

## 0. 架构演进总纲（2026-09 起，本节优先于下文）

**目标**：在不推倒现有 Electron + Python Engine + C++ SystemDaemon 的前提下，把 Yuiro 从
"功能较完整的 AI Desktop Pet"升级为 **General Agent Harness + Embodied Desktop Runtime**
（Runtime-centric Embodied Personal Agent）。主轴是统一 Runtime Contract
（Session / Generation / Cancellation / Lifecycle / Trace）+ Harness 的六项 ownership
（Session / Context / Task / Permission / Cancellation / Tool 可见性）。

```
┌────────────────────────────────────────────────────────────┐
│ EXPERIENCE       Desktop / Chat / Voice / Live2D / Task UI │
├────────────────────────────────────────────────────────────┤
│ EMBODIMENT       SpeechRuntime · AvatarRuntime · Presence  │
├────────────────────────────────────────────────────────────┤
│ AGENT HARNESS    Session · Event Log · ContextEngine ·     │
│                  AgentLoop · Task/Plan · Cancellation      │
├────────────────────────────────────────────────────────────┤
│ CAPABILITY       Tools · Skills · Plugins · Policy /       │
│                  CapabilityView · Approval · 执行后端        │
└────────────────────────────────────────────────────────────┘
      Stable Kernel（不可插件化）：Session/Generation/Cancellation
      语义、Event Schema、Security Policy
      Pluggable Edge（可替换）：LLM/ASR/TTS/Live2D 资产/Memory 后端/Tools/UI
```

**六个一等实体**：`Session / Task / Event / Intent / Artifact / Capability`。

**当前基线审计（2026-09）**：五个维度"局部有实现、全局无契约"——

| 维度 | 现状（局部） | 缺口（全局） |
|---|---|---|
| Session | WS 建连 `uuid4`；各模块 `dict[session_id,…]` 分桶 | 无 Session 实体；control/audio 两个 id 互不相关；不可 resume |
| Generation | `AgentLoop._generations`；`TranscriptBuffer._generation`；`TTSTaskManager._epoch` | 三处各写各的；无显式 invalidate；stale 静默不可观测 |
| Cancellation | `VoicePipeline.interrupt()` 只取消播放中 TTS | LLM / 工具不可取消；LLM 阶段 interrupt 是空操作；无取消回执 |
| Lifecycle | `lifespan()` + VoicePipeline 状态机 | 无统一 Runtime 契约；命名/签名不一；状态不可统一查询 |
| Trace | C++ `trace_id` 透传 + `vlog` | 引擎无 turn/trace id；流式 chunk 无 generation；无 Event Log/Replay |

六处"已写好但未接线"的骨架：`ServiceContext`、`TTSTaskManager`、`TranscriptBuffer`、
`response_categorizer`、`skill/`、`plugins/` —— 是后续增量的现成落点，勿重复造。

**规范索引**（动代码前先读）：

| 文档 | 内容 |
|---|---|
| `docs/spec/README.md` | 总索引 + 最高锚点 + 六实体 + 四层蓝图 + 全局硬约束 |
| `docs/spec/architecture-goal.md` | 目标架构总纲、组件契约、参考裁判表、优先级、DoD、禁止事项 |
| `docs/spec/runtime-contract.md` | P0 内核规范（Session/Generation/Cancellation/Lifecycle/Trace/Event/状态机） |
| `docs/spec/roadmap.md` | Wave 推进序列、Era 0–5、Personal Brain、Sprint 机制、基线差距 |
| `docs/spec/coding-agent-protocol.md` | 开发协议、母 Prompt、护栏、测试三层 |

**改造原则**（不可跳过）：`复用现有实现 → 抽抽象 → 适配 → 替换调用路径`；
禁止 `删除 → 重写`。AgentLoop / Memory / VoicePipeline / Live2D / SystemDaemon 均适用。

---

## 0.1 项目所长映射（取长补短表）

> 明确**每个项目把哪一项长处"借"给了 Yuiro**，避免方案只偏向单一参考（此前的确偏 AIRI 较多，现已逐项补齐）。

| 环节 | 采纳自 | 具体被采用的"长" | Yuiro 落点 |
|---|---|---|---|
| 系统操作执行基座 | **AIRI** | computer-use-mcp：执行/控制面分离、审批+审计+dry-run | `system-daemon/` (C++) + MCP |
| 桌宠透明窗口 | **AIRI** | window-contract：透明/置顶/鼠标穿透/防截屏/多工作区 | `shell/src/main/index.ts` |
| 端上语音/事件总线 | **AIRI** | AudioWorklet + 类型化 eventa 总线 | `shell` + `shared/events.ts` |
| 三层记忆 + RRF | **deskpet** | sqlite-vec 三层 + BGE-M3 + 4路RRF融合 + 实体抽取 | `engine/yuiro/memory/` |
| FastAPI 引擎基座 | **deskpet** | uvicorn + websockets + structlog + keychain | `engine/` |
| Skill 热加载 | **deskpet** | SKILL.md + script.py + watchdog 热加载 | `engine/yuiro/skill/` |
| 双语言插件桥 | **my-neuro** | JS/Python 插件经 stdin JSON-RPC 桥、注入钩子 | `engine/yuiro/plugins/` |
| 转写缓冲分组 | **my-neuro** | createTranscriptBuffer 聚合成一轮发言 | `audio.TranscriptBuffer` |
| 视觉引导 GUI 自动化 | **my-neuro** | 截屏→VLM bbox→鼠标点击（作坐标兜底） | system-daemon + Engine |
| 分段流式 TTS 按序 | **Open-LLM-VTuber** | TTSTaskManager 并行合成、按序交付 | `audio.TTSTaskManager` |
| 打断即记忆编辑 | **Open-LLM-VTuber** | `[Interrupted by user]` 回填 | `VoicePipeline.interrupt` |
| 每会话隔离 | **Open-LLM-VTuber** | ServiceContext 克隆 | `agent.ServiceContext` |
| 服务端 RMS 口型 | **Open-LLM-VTuber** | 预计算音量数组驱动嘴型 | `AudioSegment.volumes` |
| 主动互动+注意力 | **OpenDesktop-Pet** | 定时截屏→LLM 决策是否打招呼、避免打扰专注 | `engine/yuiro/proactive/` |
| 摄像头/截图随附 | **OpenDesktop-Pet** | 对话自动附带视觉上下文 | `shell` + `vision:capture` |
| 多引擎 TTS 界面化 | **OpenDesktop-Pet** | 设置面板选引擎 | shell 设置面板 |
| docstring→schema | **Agentic-Desktop-Pet** | 函数签名+文档字符串自动生成工具 schema | `tools.function_to_tool_schema` |
| 隔离上下文 subagent | **Agentic-Desktop-Pet** | 子任务独立上下文、父级只收结果 | `agent.SubagentTool` |
| todo 模型-视图 | **Agentic-Desktop-Pet** | TodoTool 返回 ASCII 视图供 LLM 决策 | `tools.TodoTool` |
| 情绪/亲密度养成 | **Agentic-Desktop-Pet** | 情绪衰减 + 亲密度/经验/等级 | `engine/yuiro/emotion/` |
| 两层 Skill 懒加载 | **Agentic-Desktop-Pet** | 元信息常驻、正文按需注入 | `skill.SkillLoader` |
| 纯前端 Live2D demo | **Live2DPet** | Electron + 本地 Live2D 最小可行验证 | 启发壳层选型 |

> 每行后面都标注了该长处在本仓库中的具体文件/模块落点，确保"所长"真正进入设计而不只是口号。

---


## 1. 三层 + 一执行基座

```
┌─────────────────────────────────────────────────────────────────────┐
│  Shell (Electron + Vue3)  —— 只做"脸"与"手"                         │
│  • 透明桌宠窗口(AIRI window-contract 模式)                           │
│  • 采音 AudioWorklet + wLipSync 逐元音口型                          │
│  • 气泡UI / 设置面板 / 原生审批对话框                               │
└───────────────┬─────────────────────────────────────────────────────┘
                │ eventa 类型化事件总线 + WS 控制通道(shared-secret)
┌───────────────▼─────────────────────────────────────────────────────────────┐
│  Engine (Python FastAPI)  —— 大脑                                               │
│  VAD→ASR→LLM→TTS 流水线 + Agent Loop + 记忆 + 工具                            │
│  三层记忆(RRF) · 情绪/亲密度 · 主动互动 · 插件桥 · Skill 热加载               │
└───────────────┬───────────────────────────────────────────────────────────────┘
                │ MCP (stdio / HTTP) —— 统一"手脚"抽象
┌───────────────▼───────────────────────────────────────────────────────────────┐
│  系统执行后端（S10 起可切换）—— 真实系统执行基座 (AIRI computer-use-mcp 模式)  │
│  native = engine/yuiro/native/（Python，默认）· daemon = SystemDaemon (C++，可选) │
│  进程/软件/WinAPI · 文件 · 终端 · 窗口 · 鼠标键盘 · 截图                       │
│  审批队列 + trace/audit + dry-run 沙箱                                         │
└────────────────────────────────────────────────────────────────────────────────┘
```

设计原则：
1. **壳/引擎/执行基座三层分离**，各自可独立替换。
2. **localhost-only IPC** ，WS 控制通道带 `YUIRO_SHARED_SECRET` 鉴权；API key 走系统 keychain，绝不入配置。
3. **系统操作统一经执行后端**（配权限分级 + 审批 + 审计）：S10 起默认 `native`（Python 原生，`engine/yuiro/native/`），`daemon`（C++ 守护，MCP over stdio）为可选后端，二者行为契约一致。

---

## 2. 数据流：一次语音对话

```
用户讲话
  │ AudioWorklet 采音 (16kHz mono, echoCancellation, noiseSuppression)
  ▼ WS /ws/audio
Engine: VAD（默认 FSMN-VAD，可选 silero 状态机；概率/音量双阈值）
  ▼ speech-end → ASR（默认 FunASR SenseVoice，可选 faster-whisper）→ 转写文本
Engine: Agent Loop
  │  ① 记忆自动检索注入 (三层 + RRF)
  │  ② LLM 流式生成 (streamText)
  │  ③ <think>/<reasoning> 标签滤除(内心OS不进TTS)
  │  ④ 工具调用 → 执行后端(native 原生 / daemon MCP)执行(可审批) → 结果回填
  ▼ 生成完成
Engine: TTS（按 config.toml [tts].provider：CosyVoice2 / GPT-SoVITS / SiliconFlow / edge-tts 兜底）
  │  当前为整段合成（segment_streaming 尚未接线，分段流式 + 有序播放属 Wave 1 增量）
  ▼ WS /ws/control + /ws/audio
Shell: 逐元音口型 + 气泡渲染 + 音频播放 + 动画
```

> 注：本图描述**当前链路（as-is）**。目标链路（SpeechRuntime + SpeechIntent + TTS epoch +
> 有序播放 + 全链路取消）见 `docs/spec/architecture-goal.md` §3.8 与 `docs/spec/roadmap.md` Wave 1。

---

## 3. 模块接口契约

> 说明：以下按"模块职责"描述接口契约。当前实现集中在几个单文件多类模块
> （`audio/__init__.py`、`agent/__init__.py`、`memory/__init__.py` 等）；物理拆分到
> `speech/ agent/ memory/ runtime/ capability/` 属**长期方向**
> （见 `docs/spec/runtime-contract.md` §11），不要求为了目录漂亮而移动大量文件。

### 3.1 Engine — Python

#### `config.py` — 统一配置加载
```python
@dataclass
class AppConfig:
    host: str = "127.0.0.1"
    port: int = 8200
    shared_secret: str = ""
    llm: LLMConfig
    hard_of_hearing: VADConfig  # 见下
    asr: ASRConfig
    tts: TTSConfig
    memory: MemoryConfig
    systemd: SystemDaemonConfig   # C++ 守护的 MCP 地址/鉴权
```

#### `audio/` — 语音管线
```python
# vad.py
class VADEngine:  # silero 状态机
    def feed(self, chunk: np.ndarray) -> VADEvent  # SpeechStart/SpeechEnd/Silence

# asr.py
class ASRProvider:  # faster-whisper
    def transcribe(self, audio: np.ndarray) -> str

# tts.py
class TTSProvider:  # edge-tts / cosyvoice
    async def synthesize_segment(self, text: str) -> AudioSegment  # + rms 音量数组

# pipeline.py
class VoicePipeline:  # 编排 VAD→ASR→LLM→TTS, 事件驱动
    async def on_audio(self, chunk: bytes)
    async def on_speech_end(self)
    def interrupt(self)  # 打断 → 记忆编辑 [Interrupted by user]
```

#### `agent/` — Agent Loop
```python
# llm.py
class LLMProvider(ABC):  # OpenAI兼容/Anthropic/Ollama/DeepSeek 适配
    async def stream_text(self, messages, tools, **kw) -> AsyncIterator[LLMChunk]
    # 含 provider 兼容降级 (content数组→字符串, 参考 AIRI issues/1500)

# agent.py
class AgentLoop:  # queue + generation 计数拒绝过期发送
    async def send(self, session_id: str, text: str) -> AsyncIterator[StreamEvent]
    # StreamEvent: Token | SpeechTag | ToolCall | ToolResult | Audio

# orchestrator_runtime
#   - 发送队列 + generation 计数 (参考 AIRI chat-orchestrator-runtime)
#   - response-categoriser: 解析 <think>/<reasoning>/<action> (参考 AIRI)
```

#### `memory/` — 三层记忆
```python
# 结构: sqlite + sqlite-vec
# L1 短期: 当前对话 buffer (sqlite WAL)
# L2 情景: 跨会话事件回忆 (messages_vec vec0 表 + FTS5 + 时间衰减)
# L3 实体: 人物/偏好/事实 (facts 表: subject/key/value/confidence/decay)
class Retriever:  # RRF 融合 4 路: vector / FTS5 / recency / salience
    async def retrieve(self, query: str, top_k: int) -> list[Memory]
class Embedder:  # BGE-M3, 子进程隔离防 CUDA 冲突, md5 mock 兜底
    async def embed(self, text: str) -> list[float]

# 自动注入: 每轮对话检索 top-N 注入 system prompt (参考 my-neuro)
```

#### `tools/` — 工具注册表
```python
class ToolRegistry:  # 自动发现 *tool.py, OpenAI schema
    def register(self, tool: BaseTool)
    def schemas(self) -> list[dict]
    async def execute(self, name: str, args: dict, task_id: str) -> str  # 必须返回 JSON 字符串

# 内置: file / web / image / ocr / todo / system(经MCP) / memory
# 权限: toolset gating + requires_env + UI 确认(危险项)
```

#### `native/` — 系统操作原生后端（S10 起默认）

```python
class NativeBackend:      # 与 SystemDaemonClient 同签名，可互换
    async def call(self, tool: str, args: dict, dry_run: bool = False) -> SystemActionResult
    # 覆盖: app_open / app_focus / media_control / file_create / file_read / file_write
    # Windows API(ctypes) + 标准库；SMTC 查询走 PowerShell 桥
    # 文件操作受 file_roots 边界约束（默认仅当前工作目录）
```

#### `systemd/` — C++ 守护 MCP 客户端（可选后端）
```python
class SystemDaemonClient:  # 封装 MCP 调用 SystemDaemon
    async def list_tools(self) -> list[ToolDef]
    async def call(self, tool: str, args: dict) -> SystemActionResult
    # SystemActionResult: { status, stdout, approval_required, trace_id, audit }
```

#### `emotion/` — 情绪 / 亲密度养成 (Agentic)
```python
class EmotionEngine:  # 情绪(快乐/悲伤/兴奋/无聊/生气) + 时间衰减 + 互动加成
    def decay()          # 定时衰减
    def boost(key, amt)  # 用户互动时增强
class Character:  # RPG 养成: affinty亲密度 / xp / level / attributes
```
> 表情随情绪 → 派发 `emotion:set` 到 Shell 驱动 Live2D 表情 (my-neuro)。

#### `proactive/` — 主动互动 + 注意力模型 (OpenDesktop)
```python
class AttentionObserver:  # 定时截屏(经SystemDaemon) + 可选摄像头
    async def next_capture() -> {screenshot?, camera?, ts}
class ProactiveDecider:   # LLM 决策是否打招呼, 避免打扰专注用户
    async def should_greet(obs) -> {greet, reason, message?}
class ProactiveScheduler: # 定时 observe→decide→(greet)
```

#### `skill/` — Skill 系统 (deskpet + Agentic)
```python
class SkillLoader:  # 两层: 元信息常驻 / 正文按需; watchdog 热加载
    def list_metadata() -> [SkillManifest]
    def load_body(name) -> Skill
    async def invoke_script(name, args) -> str   # 受限子进程跑 script.py
```

#### `plugins/` — 双语言插件桥 (my-neuro)
```python
class Plugin(ABC):     # Python 插件基类: on_init/on_user_input/get_tools/execute_tool
class JSONRPCBridge:   # JS 插件: stdin/out 新行 JSON, id+timeout
class PluginManager:   # 收集插件工具进 ToolRegistry + 注入钩子
```

### 3.2 SystemDaemon — C++

见 [docs/system-daemon.md](docs/system-daemon.md)。核心接口：
```cpp
// mcp 工具能力清单 (经 MCP 暴露给 Engine)
- app_open(name)            // ShellExecute 打开软件
- app_focus(name)           // WinAPI 窗口聚焦
- process_list() / process_kill(pid)
- file_create(path, content) / file_read(path) / file_write(path)
- terminal_exec(cmd, cwd, background)
- window_screenshot(rect?)  // 供视觉/审批
- mouse_inject(x, y, btn) / keyboard_inject(keys)
// 每工具带: approval_required, dry_run 能力
```

### 3.3 Shell — Electron + Vue3

#### 事件总线契约 (`src/shared/`)
```ts
// 类型化事件 (eventa 风格) — 主进程 ↔ 渲染进程 ↔ Engine
type ShellEvents =
  | { type: 'voice-input:start' } | { type: 'voice-input:stop' }
  | { type: 'tts:start'; segmentId: string } | { type: 'tts:interrupted' }
  | { type: 'lip-sync:param'; mouthOpen: number; visemes: number[] }
  | { type: 'action:tool-call'; tool: string; args: unknown }
  | { type: 'approval:required'; req: ApprovalRequest }  // → 原生对话框
  | { type: 'approval:resolve'; approved: boolean }
```

#### 桌宠窗口 (主进程)
```ts
// 参考 AIRI window-contract.ts
const win = new BrowserWindow({
  frame: false, transparent: true, alwaysOnTop: true, skipTaskbar: true,
  focusable: false, hasShadow: false, roundedCorners: false,
})
win.setIgnoreMouseEvents(true, { forward: true })
win.setAlwaysOnTop(true, 'screen-saver')
win.setContentProtection(true)
win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
win.showInactive()
```

#### 采音 + 口型 (渲染进程)
```ts
// AudioWorklet 采音 → WS /ws/audio
// wLipSync AudioWorkletNode → 逐元音权重 → getMouthOpen → Live2D 参数
// 备用: 服务端预计算 RMS 音量数组 (参考 OpenLLM stream_audio)
```

---

## 4. 关键设计决策汇总

| 决策 | 选择 | 理由 / 借鉴 |
|---|---|---|
| 壳 | Electron | AIRI/OpenDesktop 桌宠 + 系统兼容最好 |
| 引擎 | Python FastAPI | deskpet 已验证，AI 生态最全 |
| Agent LLM | 多 Provider + 兼容降级 | deskpet / AIRI |
| 记忆 | sqlite-vec 三层 + RRF | deskpet 最完整 |
| 系统操作 | **C++ 守护 + MCP** | AIRI computer-use-mcp，差异化 + 研究点 |
| 事件 | eventa 类型化总线 | AIRI / my-neuro |
| 口型 | wLipSync 逐元音 + RMS 备用 | AIRI / OpenLLM |

详见 [docs/model-selection.md](docs/model-selection.md) 的逐项理由与备选。
