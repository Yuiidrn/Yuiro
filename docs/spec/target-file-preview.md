# Yuiro 目标最终形态与文件预览（方向性）

> **定位**：本文回答"Wave 0–8 完成后，代码库长什么样、每个文件负责什么、关键类是什么形态"，
> 用于提前判断方向、评估工作量、避免边做边漂。
> **它不是硬性蓝图**：每个 Wave 落地时以当时的 spec + Sprint Plan 为准；
> 预览代码是**接口与语义示意**（类名/字段/方法签名/关键注释），不是可直接运行的实现。

---

## 0. 三条演进方法论（保证不推倒重来）

结合现状（多个"单文件多类"模块 + 六处未接线骨架），文件层面固定三步走：

```
M1 包外挂    新能力先以新包形式与旧模块并存（runtime/ speech/ avatar/ context/ task/ capability/），旧文件不动
M2 Adapter   新包通过 Adapter 调用旧实现（VoicePipeline / AgentLoop / MemorySystem / ToolRegistry / SystemDaemon / Live2D）
M3 反向接线   新路径稳定后，把调用方（main.py → YuiroRuntime）切过去；旧文件保留为内部实现
M4 物理拆分   （可选、最后做）确有必要时才拆文件，且必须 re-export 保持向后兼容
```

**禁止**：先大搬家再改逻辑；为目录漂亮而移动文件；一次性重写 `audio/__init__.py` / `agent/__init__.py`。

---

## 1. 目标目录树（Wave 8 后）

### 1.1 engine/yuiro/

```
engine/yuiro/
├── main.py                    # 【变薄】FastAPI 装配 + WS 传输适配，只做"接线"
├── config.py                  # 【演化】AppConfig + 新增 RuntimeConfig / TaskConfig / ProfileConfig
├── logger.py                  # 【保留】vlog（被 trace 复用为输出端）
├── keychain.py / debug_api.py # 【保留】
├── approval.py                # 【变薄】传输层回调（连接注册表迁入 SessionManager）
│
├── runtime/                   # ★ Wave 0 新增（Stable Kernel）
│   ├── __init__.py            #   导出 AgentSession / SessionManager / AgentEvent / TraceContext
│   ├── session.py             #   AgentSession + SessionManager（含 control/audio 绑定、统一 cancel）
│   ├── events.py              #   AgentEvent + EventBus + EventLog（点分内部名 → 冒号对外名 映射）
│   ├── trace.py               #   TraceContext（trace_id + 阶段打点，复用 vlog 输出）
│   ├── cancellation.py        #   CancellationToken / CancelScope（可传播、可等待、不吞）
│   └── lifecycle.py           #   Runtime 基类/状态枚举（initialize/start/state/handle_event/cancel/shutdown）
│
├── speech/                    # ★ Wave 1 新增（Embodiment）
│   ├── __init__.py
│   ├── intent.py              #   SpeechIntent
│   ├── runtime.py             #   SpeechRuntime（Adapter 包 VoicePipeline；epoch/停播/状态机）
│   └── playback.py            #   播放与有序交付控制（接线 TTSTaskManager）
│
├── avatar/                    # ★ Wave 2 新增
│   ├── __init__.py
│   ├── intent.py              #   AvatarIntent / AvatarPriority
│   └── runtime.py             #   AvatarRuntime（优先级仲裁 → avatar:* 事件 → shell）
│
├── context/                   # ★ Wave 3 新增
│   ├── __init__.py
│   ├── item.py                #   ContextItem（source/scope/priority/token_cost/mandatory）
│   ├── sources.py             #   各 ContextSource（persona/conversation/memory/task/tools/skill）
│   └── engine.py              #   ContextEngine（budget / Cold-Warm-Hot / compaction）
│
├── task/                      # ★ Wave 5 新增
│   ├── __init__.py
│   ├── plan.py                #   TaskPlan / PlanStep
│   ├── journal.py             #   TaskJournal（持久化，可从磁盘恢复进度）
│   ├── artifact.py            #   ArtifactStore（大工具结果落盘 + summary）
│   └── runtime.py             #   TaskRuntime（状态机 + InteractionMode）
│
├── capability/                # ★ Wave 5–6 新增
│   ├── __init__.py
│   ├── view.py                #   Agent Capability View（按 role/session/task 过滤工具可见性）
│   ├── policy.py              #   PolicyEngine / PermissionProfile / Capability Scope
│   ├── hooks.py               #   HookRegistry（on_session_start / before_tool / after_tool / ...）
│   └── registry.py            #   （可选）ToolRegistry 的迁入点；Wave 5 前先复用 tools/
│
├── agent/                     # 【演化】保留为"决策执行器"，不重写
│   ├── __init__.py            #   导出层（保持向后兼容，先不拆）
│   ├── runtime.py             # ★ Wave 1–2 新增：AgentRuntime（包装 AgentLoop：cancel/generation/输出流）
│   ├── chat_service.py        #   保留（降级 responder）
│   ├── response_categorizer.py# 【接线】<think> 剥离接入主链路
│   └── subagent.py            # ★ 后期：SubagentTool 迁入，受 TaskRuntime 控制
│
├── memory/                    # 【演化 + 新增】
│   ├── __init__.py            #   现有三层检索（保留，不重写）
│   ├── runtime.py             # ★ Wave 4：MemoryRuntime（写安全：generation 校验 + 事件）
│   ├── consolidation.py       # ★ Wave 4：异步 Consolidation（Episode → Semantic/Fact/Relationship）
│   └── relationship.py        # ★ Wave 4：RelationshipStore（关系记忆）
│
├── tools/ · systemd/ · netease/ · tts_server/   # 【保留】Edge 层，只经 Adapter 接入
├── emotion/                   # 【演化】Wave 2：emotion → AvatarIntent；保留 affinity/xp/level
├── proactive/                 # 【演化】Wave 7：升级为 PresenceRuntime + Attention Policy
├── skill/                     # ★ Wave 8：从 stub 实现（Lazy / progressive disclosure）
└── plugins/                   # ★ Wave 8：从 stub 实现（Plugin manifest + Hooks 订阅）
```

### 1.2 shell/（现状 → 目标）

**现状关键事实**（来自 2026-09 文件级审计，决定改动面）：

- `shared/events.ts` 声明的 15 种 ShellEvent 中，**实际经 IPC 总线运行的只有 `appearance:update` 一种**；
  引擎协议（`chat:* / emotion:set / approval:* / tts:* / proactive:*`）全部由渲染层**直连引擎 WS 的裸 JSON** 承载
  —— "事件契约"事实上是两张皮。
- 全壳层**无 session / generation / trace 概念**（`session_id` 仅在调试台 `VoiceDebug.vue` 显示用被读取一次）。
- Live2D 仅 **2 个真实驱动点**：`Live2DCanvas.vue` 的 idle 自动动作 + `setParamFloat('ParamMouthOpenY')` 口型；
  **无任何 `expression()` 调用**，`emotion:set` 目前只写日志（注释：映射后续接入）。
- `/ws/control` 与 `/ws/audio` 均**无自动重连**；采音当前是 `ScriptProcessor`（非 AudioWorklet）；
  模型路径硬编码（`model_dict.json` 登记的三模型未接入）。

**目标树**：

```
shell/src/
├── shared/
│   ├── engine-protocol.ts     # ★W0 新增：引擎 WS 协议**单一来源**（Envelope{session_id,generation,trace_id,ts}
│   │                          #   + 各事件 payload 类型 + 事件名常量），替代"渲染层裸 JSON 无类型"现状
│   ├── events.ts              # 【收敛】只保留 IPC 窗口类事件（appearance:update / fade:* / overlay:*）；
│   │                          #   与引擎重复的成员迁往 engine-protocol.ts（旧名保留一个版本周期）
│   ├── task.ts                # ★W5：Task / PlanStep / Artifact 前端类型
│   └── config.ts              # 【保留】调试台↔debug API 类型契约
├── main/index.ts              # 【小改】审批对话框支持 plan-level（level/plan/scope 字段）；窗口/托盘/穿透机制不动
├── preload/index.ts           # 【小改】requestApproval 携带新字段；窗口机制 API 不动
└── renderer/src/
    ├── App.vue                # 【瘦身】WS 连接/分发改入 useEngine；本文件回归"布局 + 面板编排"
    ├── composables/
    │   ├── useEngine.ts       # ★W0：统一引擎连接（session 握手 + 重连 + generation 过滤 + 事件分发）
    │   ├── useChat.ts         # ★W0/W5：消息流 + 任务消息（从 App.vue 拆出）
    │   ├── useVoiceInput.ts   # 【改造】接受 sessionId（?session=）+ `tts:interrupted` 停播/停口型 + 断线重连
    │   └── （其余 12 个 composable 不动）
    ├── components/
    │   ├── Live2DCanvas.vue   # 【扩展】新增 applyAvatarIntent(intent)（expression/motion/优先级仲裁）；
    │   │                      #   口型保持现有 volumes 路径（引擎不直接推 Live2D 参数）
    │   ├── TaskPanel.vue      # ★W5（Era 4）：任务步骤面板（☑/⏳/✗）
    │   ├── MemoryIndicator.vue# ★W4（Era 2）：🧠"记住了"
    │   └── （其余 5 个组件不动）
    └── dev/VoiceDebug.vue     # 【复用】已有独立 /ws/audio + 指数重连 + trace 列表 → 升级为 Event Log 查看器（W0）
```

### 1.3 system-daemon/（现状 → 目标）

**现状关键事实**（来自 2026-09 文件级审计，决定改动面）：

- 注册 **6 个工具**：`app_open / app_focus / file_create / file_read / file_write / media_control`；
  `media_bridge` 实现完整但未注册（实测 Windows 客户端不响应）。
- `tools/list` **没有 `input_schema`**（description 为 `name + " (supports dry-run)"` 自动拼接）；
  参数 schema 在引擎侧手写 —— **双维护且已出现 `approval_required` 不一致**（引擎 `file_read=True` vs daemon `file_read=false`）。
- 审批在**引擎侧**、工具级、默认 `auto` 全放行；daemon 不产生 `approval_request_id`（字段恒为空串）、不阻塞、无待审队列。
- 安全只有 `Policy::path_allowed()`（仅覆盖 3 个文件工具，base 硬编码为进程 CWD）；
  **无进程/网络白名单、无沙箱、无回滚**；`artifacts` 从未填充，`audit` 由各能力手拼（无 ts/actor），`redact()/mode()` 是 stub。
- `trace_id` 由 daemon 自造回传，但引擎**不传入**上游 trace_id，daemon 也不落盘；
  协议无 `initialize` / 版本协商 / 取消（引擎 60s 超时放弃时 daemon 仍在执行）。

**目标树**：

```
system-daemon/
├── include/yuiro/
│   ├── capability/
│   │   ├── capability.hpp      # 【扩展】新增 scope()/permissions() 与 supports_rollback()（默认实现，老能力零改动）
│   │   ├── transaction.hpp     # ★W5：Tool Transaction（prepare/commit/rollback + rollback_token）
│   │   ├── files.hpp           # 【改造】文件三工具接入事务（执行前备份 → 回滚 token）
│   │   └── （process.hpp / media.hpp 不动）
│   ├── mcp/server_stdio.hpp    # 【扩展】initialize 协商；params 透传 trace_id / session_id
│   └── security/
│       ├── policy.hpp          # 【扩展】CapabilityScope / PermissionProfile（取代硬编码名单）
│       └── sandbox.hpp         # ★W6：路径/进程约束（OS 层拒绝越界）
├── src/
│   ├── capability/
│   │   ├── transaction.cpp     # ★W5：文件类 rollback（移动/写入前备份 + token 管理）
│   │   ├── files.cpp           # 【改造】dry_run 预演真实错误 + 事务接入 + audit 结构化（ts/actor/trace）
│   │   └── （process.cpp / media.cpp / media_bridge.cpp 不动）
│   ├── mcp/server_stdio.cpp    # 【扩展】tools/list 补 input_schema 与 scope；
│   │                           #   tools/call 透传 trace_id；audit 由 server 层统一组装
│   └── security/
│       ├── policy.cpp          # 【扩展】scope 校验 + redact() 落地
│       └── sandbox.cpp         # ★W6：拒绝越界（不依赖调用方自觉）
└── tests/                      # 【扩展】协议层（tools/list、tools/call）+ 事务 + scope 用例
                                #   （现状仅 5 条 policy assert）
```

---

## 2. 现有文件 → 目标映射（谁动、怎么动、哪个 Wave）

| 现状 | 目标归宿 | 处理方式 | Wave |
|---|---|---|---|
| `main.py`（735 行，含 `_build_*` + 三套发事件方式） | `runtime/composition.py` + 薄 `main.py` | 逻辑迁出，WS 只做传输适配 | W0 起逐 Wave 变薄 |
| `approval.py` 的 `_control_conns/_audio_conns` | `runtime/session.py`（SessionManager 持有绑定） | 迁入；approval 保留为回调 | W0 |
| `AgentLoop._generations`（5 处静默 stale） | `runtime/session.py`（Session.generation）+ `agent/runtime.py` | **接管**：显式 invalidate + stale 可观测 | W0 |
| `VoicePipeline.interrupt()`（只取消 TTS 播放） | `speech/runtime.py`（`stop()` → epoch++ + 停播 + 联动 Agent cancel） | **Adapter 包装**，不重写 VoicePipeline | W1 |
| `TTSTaskManager`（epoch 已实现未接线） | `speech/playback.py` 使用 | **接线**（并修复 `wait_next` 空转） | W1 |
| `TranscriptBuffer._generation`（未调用） | `speech/runtime.py` 使用 | **接线** | W1 |
| `AgentLoop._history/_state_notes`（per-session dict） | `AgentSession`（可选迁入） | 先不动，W4 视需要迁 | W4 |
| `emotion/`（已接线 `emotion:set`） | `avatar/runtime.py` 的 emotion source | 保留引擎，输出改走 AvatarIntent | W2 |
| `MemorySystem.remember()`（`del session_id`） | `memory/runtime.py`（写安全 + session 归属） | 包装，不改检索 | W4 |
| `ToolRegistry`（全局工具表） | `capability/view.py` 过滤 | 包装为 Capability View | W5 |
| `SubagentTool`（零引用） | `agent/subagent.py` + `task/runtime.py` 控制 | **接线并加约束** | W8 |
| `skill/` `plugins/`（纯 stub） | `skill/` `plugins/` 实装 | 从零实现 | W8 |
| `audio/__init__.py`（1308 行，9 个类） | `speech/*`（物理拆分） | **最后做**，re-export 兼容 | W2+ 可选 |
| `shell/src/shared/events.ts`（15 种事件仅 1 种在跑） | `shared/engine-protocol.ts`（引擎协议单一来源） | 拆分：窗口事件留 events.ts，引擎协议迁出 | W0 |
| `shell/src/renderer/src/App.vue`（903 行，内联 WS + 分发） | `composables/useEngine.ts` + `useChat.ts` | 逻辑迁出、App 瘦身 | W0 |
| `shell/src/renderer/src/components/Live2DCanvas.vue`（无 expression） | 新增 `applyAvatarIntent` | 扩展，不重写 | W2 |
| `engine/yuiro/systemd/client.py`（丢 audit、不传 trace） | 协议扩字段 + 结果解析 | 改造 | W5 |
| `system-daemon/src/mcp/server_stdio.cpp`（无 schema / 无 trace 透传） | 协议扩展（input_schema / trace_id / audit 统一） | 扩展 | W5–6 |
| `system-daemon/src/security/policy.cpp`（仅 path_allowed） | 扩展 scope + sandbox 落地 | 扩展 | W6 |

---

## 3. 关键文件预览

### 3.1 `runtime/session.py`（Wave 0 · 最关键）

```python
"""AgentSession：一次交互从开始到结束的完整执行轨迹（不是聊天记录）。"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class SessionState(str, Enum):
    CREATING = "creating"
    ACTIVE = "active"
    SUSPENDED = "suspended"   # 通道断开但可 resume（Event Log 保留）
    CLOSED = "closed"


@dataclass
class AgentSession:
    session_id: str
    generation: int = 0
    parent_session_id: str | None = None
    state: SessionState = SessionState.ACTIVE
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    active_tasks: dict[str, str] = field(default_factory=dict)  # task_id -> owner runtime
    control_ws: object | None = None   # 传输绑定（不参与业务）
    audio_ws: object | None = None

    def next_generation(self) -> int:
        """新用户回合：generation++（旧代际的一切异步结果从此作废）。"""
        self.generation += 1
        self.last_active_at = time.time()
        return self.generation

    def invalidate(self, reason: str) -> int:
        """显式失效（barge-in / stop / reset）；等价于开新代际但不启动新回合。"""
        self.generation += 1
        self.last_active_at = time.time()
        return self.generation


class SessionManager:
    """会话注册表 + 统一取消入口 + 传输绑定（control/audio 归同一 session）。"""

    def __init__(self, *, events, speech=None, agent=None, avatar=None) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._events = events
        self._speech, self._agent, self._avatar = speech, agent, avatar

    def create(self) -> AgentSession:
        s = AgentSession(session_id=uuid4().hex)
        self._sessions[s.session_id] = s
        return s

    def attach_control(self, ws, *, session_id: str | None = None) -> AgentSession:
        """control 建连：带 session_id 则 resume，否则新建。"""
        s = self._sessions.get(session_id or "") or self.create()
        s.control_ws, s.state = ws, SessionState.ACTIVE
        return s

    def attach_audio(self, ws, *, session_id: str | None = None) -> AgentSession:
        """audio 建连：带 ?session= 绑定同一会话；不带则沿用旧行为（独立临时会话）。"""
        s = self._sessions.get(session_id or "") or self.create()
        s.audio_ws = ws
        return s

    async def cancel(self, session_id: str, reason: str) -> None:
        """统一取消入口（唯一允许触发跨 Runtime 取消的地方）。"""
        s = self._sessions.get(session_id)
        if s is None:
            return
        s.invalidate(reason)
        if self._agent:  await self._agent.cancel(session_id, reason)   # 关 LLM 流 / 停工具
        if self._speech: await self._speech.stop(session_id, reason)    # epoch++ / 停播
        if self._avatar: await self._avatar.cancel_speech_action(session_id)
        await self._events.publish_event(s, "session.cancelled", {"reason": reason})

    def suspend(self, session_id: str) -> None:
        """通道断开：保留 Event Log，可 resume。"""
        s = self._sessions.get(session_id)
        if s and not s.control_ws and not s.audio_ws:
            s.state = SessionState.SUSPENDED
```

### 3.2 `runtime/events.py`（Wave 0）

```python
"""AgentEvent + EventBus + EventLog：agent-native 事件（不是传统日志）。"""
from __future__ import annotations
import json, time
from dataclasses import dataclass, field, asdict
from uuid import uuid4


@dataclass
class AgentEvent:
    type: str                 # 内部点分名："llm.first_token" / "tool.completed"
    source: str               # runtime 名："AgentRuntime" / "SpeechRuntime"
    session_id: str
    generation: int
    trace_id: str
    event_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)


# 对外 WS 事件保持现有冒号风格（前端零破坏）；映射集中一处，禁止散落。
_WIRE_TYPE_MAP = {
    "session.started": "session:ready",
    "llm.first_token": "llm:first_token",
    "tts.first_audio": "tts:first_audio",
    "speech.interrupted": "tts:interrupted",
    "tool.completed": "tool:completed",
    "avatar.motion": "avatar:motion",
    # ...
}


class EventBus:
    """进程内 typed 事件总线：asyncio + dataclass，不引入 broker。"""

    def __init__(self, *, log=None) -> None:
        self._handlers: dict[str, list] = {}
        self._log = log

    def subscribe(self, prefix: str, handler) -> None: ...

    async def publish(self, event: AgentEvent) -> None:
        if self._log:
            await self._log.append(event)
        for h in self._handlers.get(event.type, []):
            await h(event)

    async def publish_event(self, session, type_: str, payload: dict) -> None:
        """便捷入口：自动补 session/generation/trace 字段。"""
        ...

    @staticmethod
    def to_wire(event: AgentEvent) -> dict:
        """内部事件 → 前端 JSON（唯一转换点）。"""
        return {"type": _WIRE_TYPE_MAP.get(event.type, event.type),
                "session_id": event.session_id, "generation": event.generation,
                "trace_id": event.trace_id, "ts": event.timestamp, **event.payload}


class EventLog:
    """落盘（sqlite 或 jsonl）；支持按 session 复原 timeline（resume / replay 基础）。"""

    async def append(self, event: AgentEvent) -> None: ...
    async def timeline(self, session_id: str) -> list[AgentEvent]: ...
```

### 3.3 `runtime/trace.py`（Wave 0）

```python
"""TraceContext：一次用户输入 = 一个 trace，阶段打点复用 vlog 输出。"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class TraceContext:
    session_id: str
    generation: int
    trace_id: str = field(default_factory=lambda: uuid4().hex[:12])
    _t0: float = field(default_factory=time.monotonic)
    _marks: dict[str, float] = field(default_factory=dict)

    def mark(self, stage: str) -> float:
        """记录一个阶段时间戳并打日志（stage 命名见 S01 卡片）。"""
        dt = time.monotonic() - self._t0
        self._marks[stage] = dt
        # vlog("trace", f"[{self.trace_id}] {stage} +{int(dt*1000)}ms")
        return dt

    def summary(self) -> dict[str, float]:
        """输出各阶段耗时（ms），写入 EventLog 的 interaction.completed 事件。"""
        return {k: round(v * 1000, 1) for k, v in self._marks.items()}
```

### 3.4 `runtime/cancellation.py`（Wave 0）

```python
"""CancellationToken：可传播、可等待、不被吞的取消语义。"""
from __future__ import annotations
import asyncio


class Cancelled(Exception):
    """正常控制流：取消不是系统错误，日志按 expected 处理。"""


class CancellationToken:
    def __init__(self) -> None:
        self._reason = ""
        self._flag = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._flag.is_set()

    def cancel(self, reason: str = "") -> None:
        self._reason = reason or self._reason
        self._flag.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise Cancelled(self._reason)


class CancelScope:
    """把 token 绑定到一批 asyncio task / 工具执行 / LLM 流，统一 cancel + await 收敛。"""

    def __init__(self) -> None:
        self.token = CancellationToken()
        self._tasks: list[asyncio.Task] = []

    def track(self, task: asyncio.Task) -> None: ...

    async def cancel_and_wait(self, timeout: float = 1.0) -> None: ...
```

### 3.5 `agent/runtime.py`（Wave 1–2）——AgentLoop 不重写，只包装

```python
"""AgentRuntime：给现有 AgentLoop 套上 Session / Generation / Cancellation / Trace。"""


class AgentRuntime:
    def __init__(self, loop, *, sessions, events) -> None:
        self._loop = loop
        self._sessions = sessions
        self._events = events
        self._scopes: dict[str, CancelScope] = {}

    async def send(self, session_id: str, text: str, *, style_hint: str = ""):
        session = self._sessions.get(session_id)
        trace = TraceContext(session_id, session.generation)
        scope = self._scopes.setdefault(session_id, CancelScope())
        try:
            async for chunk in self._loop.send(session_id, text, style_hint=style_hint):
                scope.token.raise_if_cancelled()          # 取消在流中即时生效
                yield chunk
        except Cancelled:
            await self._events.publish_event(session, "agent.cancelled", {"reason": scope.token._reason})
        finally:
            pass

    async def cancel(self, session_id: str, reason: str) -> None:
        scope = self._scopes.get(session_id)
        if scope:
            scope.token.cancel(reason)
            await scope.cancel_and_wait()
```

### 3.6 `speech/intent.py` + `speech/runtime.py`（Wave 1）

```python
"""SpeechIntent：说什么是 Intent，怎么播放是 SpeechRuntime 的事。"""
from dataclasses import dataclass


@dataclass
class SpeechIntent:
    session_id: str
    generation: int
    text: str
    priority: int = 0
    interruptible: bool = True     # 低优先（如主动问候）不允许打断对话
```

```python
"""SpeechRuntime：Adapter 包装 VoicePipeline；epoch + 停播 + 状态机。"""


class SpeechRuntime:
    def __init__(self, pipeline, *, events) -> None:
        self._pipe = pipeline            # 现有 VoicePipeline（不重写）
        self._tasks: dict[str, TTSTaskManager] = {}
        self._events = events
        self._state: dict[str, str] = {}  # IDLE/LISTENING/TRANSCRIBING/THINKING/SPEAKING/INTERRUPTED

    async def speak(self, intent: SpeechIntent) -> None:
        """Agent 输出 → 分句 → TTSTaskManager 并行合成 → 顺序播放。"""
        mgr = TTSTaskManager.from_provider(self._pipe.tts)
        self._tasks[intent.session_id] = mgr
        for seq, sentence in enumerate(split_sentences(intent.text)):
            asyncio.create_task(mgr.enqueue(seq, sentence))
        while True:
            seg = await mgr.wait_next()              # 修复后的 wait_next 可被取消
            await self._pipe.play(intent.session_id, seg)

    async def stop(self, session_id: str, reason: str) -> None:
        mgr = self._tasks.get(session_id)
        if mgr:
            await mgr.interrupt()                    # epoch++ / clear buffer
        await self._pipe.stop_playback(session_id)   # 前端收 speech:interrupted
        await self._events.publish_event(..., "speech.interrupted", {"reason": reason})

    def state(self, session_id: str) -> str: ...
```

### 3.7 `avatar/intent.py` + `runtime.py`（Wave 2）

```python
from dataclasses import dataclass
from enum import IntEnum


class AvatarPriority(IntEnum):
    IDLE = 0
    EMOTION = 1
    SPEECH = 2
    USER_INTERACTION = 3
    SYSTEM = 4


@dataclass
class AvatarIntent:
    source: str                       # agent | emotion | speech | system
    generation: int
    emotion: str | None = None
    expression: str | None = None
    motion: str | None = None
    priority: AvatarPriority = AvatarPriority.EMOTION
    duration_ms: int | None = None
```

```python
class AvatarRuntime:
    """唯一允许操作 Live2D 的组件；Agent/Emotion 只发 Intent。"""

    async def apply(self, intent: AvatarIntent) -> None:
        current = self._current.get(intent.generation)
        if current and intent.priority < current.priority:
            return                                   # 低优先级不覆盖高优先级
        await self._emit(intent)                     # → shell: avatar:intent → Live2D adapter

    async def cancel_speech_action(self, session_id: str) -> None:
        """barge-in：Speaking 动画取消 → Listening 动画。"""
        ...
```

### 3.8 `context/item.py` + `engine.py`（Wave 3）

```python
@dataclass
class ContextItem:
    source: str        # persona | conversation | memory | task | tools | skill
    scope: str         # session | task | global
    content: str
    priority: int
    token_cost: int
    mandatory: bool = False
    freshness: float = 0.0
    relevance: float = 0.0


class ContextEngine:
    """Memory 只负责'找'；ContextEngine 负责'用不用、用多少、放哪里'。"""

    def __init__(self, *, budget: int, sources: list) -> None: ...

    async def build(self, session, *, query: str, task=None) -> list[dict]:
        items: list[ContextItem] = []
        for src in self._sources:
            items += await src.collect(session, query=query, task=task)
        items = self._rank(items)
        items = self._fit_budget(items, self._budget)      # mandatory 优先；超出 → compaction/丢弃
        return [{"role": "system", "content": it.content} for it in items]
```

### 3.9 `task/` + `capability/`（Wave 5–6）

```python
class TaskStatus(str, Enum):
    CREATED = "created"; PLANNING = "planning"; WAITING_APPROVAL = "waiting_approval"
    RUNNING = "running"; PAUSED = "paused"; VERIFYING = "verifying"
    COMPLETED = "completed"; CANCELLED = "cancelled"; FAILED = "failed"; BLOCKED = "blocked"


@dataclass
class TaskPlan:
    goal: str
    assumptions: list[str]
    steps: list[PlanStep]
    required_capabilities: list[str]
    risk_level: str                 # low | medium | high
    approval_requirement: str       # none | tool | plan
    completion_criteria: list[str]


class TaskRuntime:
    """跨多轮的目标：AgentRuntime 管一步，TaskRuntime 管为什么/到哪了/下一步。"""

    async def create(self, session, goal: str, mode: str) -> "Task": ...
    async def plan(self, task_id: str) -> TaskPlan: ...          # PLAN 模式
    async def approve(self, task_id: str, plan: TaskPlan) -> None: ...
    async def advance(self, task_id: str) -> None: ...           # 状态机推进 + Journal 落盘
    async def cancel(self, task_id: str, reason: str) -> None: ...
    async def resume(self, task_id: str) -> None: ...            # 从 Task Journal 恢复
```

```python
class CapabilityView:
    """Agent 此刻能看到哪些工具（解决 Tool Context Explosion）。"""

    def __init__(self, registry, policy): ...
    def visible_tools(self, *, role: str, session, task=None) -> list[dict]:
        return [t for t in self._registry.schemas()
                if self._policy.allows(role=role, session=session, tool=t["function"]["name"])]
```

### 3.10 `main.py` 最终形态（逐 Wave 变薄）

```python
"""FastAPI 入口：只做传输适配，业务全在 runtime/。"""
from yuiro.runtime import YuiroRuntime

runtime = YuiroRuntime.create(load_config())     # composition root：配置 → 装配 → 初始化


@app.websocket("/ws/control")
async def control(ws: WebSocket) -> None:
    await ws.accept()
    session = runtime.sessions.attach_control(ws, session_id=ws.query_params.get("session"))
    await runtime.events.send_to(session, "session.started", {"session_id": session.session_id})
    async for msg in ws.iter_json():
        await runtime.handle_control(session, msg)      # chat:user / approval:resolve / interrupt


@app.websocket("/ws/audio")
async def audio(ws: WebSocket) -> None:
    await ws.accept()
    session = runtime.sessions.attach_audio(ws, session_id=ws.query_params.get("session"))
    async for frame in ws.iter_bytes_or_json():
        if isinstance(frame, bytes):
            await runtime.speech.on_audio(session, frame)
        elif frame.get("type") == "interrupt":
            await runtime.sessions.cancel(session.session_id, "barge-in")
```

### 3.11 shell 侧：协议单一来源与关键文件（Wave 0 起步）

**`shared/engine-protocol.ts`（★W0 新增，引擎 WS 协议唯一权威）**：

```ts
/** 引擎 WS 协议唯一定义：control / audio 两个通道共用。
 *  渲染层禁止再出现裸 JSON 解析（现状 App.vue / useVoiceInput 各自 parse）。*/
export interface EngineEnvelope {
  type: EngineEventType;
  session_id: string;   // 引擎权威下发（session:ready）
  generation: number;   // 旧代际事件前端直接丢弃
  trace_id?: string;
  ts?: number;
}

export type EngineEventType =
  | 'session:ready' | 'session:cancelled'
  | 'chat:assistant' | 'llm:first_token'
  | 'tts:audio' | 'tts:first_audio' | 'tts:interrupted'
  | 'avatar:intent' | 'memory:recall'
  | 'task:update' | 'tool:completed'
  | 'emotion:set' | 'proactive:greet'
  | 'approval:required' | 'pipeline:state' /* ... */;

export interface AvatarIntentPayload {
  source: 'agent' | 'emotion' | 'speech' | 'system';
  emotion?: string; expression?: string; motion?: string;
  priority: number; duration_ms?: number;
}

export interface TaskUpdatePayload {
  task_id: string; status: string; goal: string;
  steps: { index: number; title: string; status: 'pending' | 'running' | 'done' | 'failed' }[];
}
```

**`composables/useEngine.ts`（★W0，替代 App.vue 内联 WS）**：

```ts
export function useEngine() {
  // 单例：control 通道；onopen 后等待 session:ready 拿到 session_id
  // 事件分发：handlers[type] → 丢弃 generation < current 的旧事件
  // 重连：指数退避（复用 VoiceDebug 的 scheduleReconnect 模式，App.vue 现在没有）
  const sessionId = ref(''); const generation = ref(0);
  function send(msg: Record<string, unknown>) { /* 自动补 session_id */ }
  function on(type: EngineEventType, h: (e: EngineEnvelope) => void) { ... }
  return { sessionId, generation, send, on, status };
}
```

**`useVoiceInput.ts` 的三处硬改造**：

```ts
// 1) audio 连接带上会话：/ws/audio?secret=...&session=<sessionId>
// 2) 处理 tts:interrupted → 清空播放队列 + stopMouthLoop()（现状只处理 tts:audio）
// 3) 断线重连（现状 onclose 只 emit 事件，下次 start() 才重建）
```

**`Live2DCanvas.vue` 扩展点（不重写）**：

```ts
// 现状：只有 idle 自循环 + setParamFloat('ParamMouthOpenY')
// 新增（defineExpose）：
function applyAvatarIntent(intent: AvatarIntentPayload) {
  // 优先级低于当前动作 → 忽略；否则 expression → model.expression(i)
  // motion → motionManager.startMotion(group, index, priority)
}
// 口型仍由 props.mouthOpen（volumes）驱动；引擎不直接推 Live2D 参数
```

**审批对话框（main + preload）扩展**：

```ts
requestApproval(req: {
  approvalRequestId: string; tool: string; summary: string;
  level?: 1 | 2 | 3 | 4;                       // 新增：审批分层
  plan?: { goal: string; steps: string[] };    // LEVEL 4：plan-level 审批
}): Promise<{ requestId: string; approved: boolean; scope?: 'once' | 'session' }>
```

### 3.12 system-daemon 侧：协议扩展与事务（Wave 5–6）

**协议扩展（`server_stdio.cpp` + `client.py` 同步改，字段全部可选、向后兼容）**：

```jsonc
// tools/call 新增字段
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"file_write",
  "arguments":{"path":"...","content":"..."},
  "dry_run":false,
  "trace_id":"abc123",            // ★ 与引擎 trace 打通（现状 daemon 自造、上游不知道）
  "session_id":"s001",
  "permission_profile":"normal"   // ★ W6
}}

// tools/list 每项新增（解决 schema 双维护）
{"name":"file_write","description":"写入文件（覆盖）",
 "approval_required":true,"dry_run":true,
 "input_schema":{ /* JSON Schema，daemon 为单一来源，引擎透传给 LLM */ },
 "scope":["filesystem.write"],
 "supports_rollback":true}
```

**`capability.hpp` 扩展（默认实现，老能力零改动）**：

```cpp
class Capability {
 public:
  virtual std::string name() const = 0;
  virtual bool approval_required() const { return false; }
  virtual bool supports_dry_run() const { return true; }
  // ★ 新增
  virtual std::vector<std::string> scope() const { return {}; }  // "filesystem.write" / "process.launch"
  virtual bool supports_rollback() const { return false; }
  virtual SystemResult run(const std::string& args_json,
                           const std::string& trace_id, bool dry_run) = 0;
};
```

**`transaction.hpp`（★W5，文件类先做）**：

```cpp
struct RollbackToken { std::string token_id; std::string kind; std::string payload_json; };

class TransactionalCapability : public Capability {
 public:
  bool supports_rollback() const override { return true; }
  virtual SystemResult prepare(const std::string& args_json, const std::string& trace_id) = 0; // 校验+备份计划
  virtual SystemResult commit(const RollbackToken& token) = 0;                                  // 执行
  virtual SystemResult rollback(const RollbackToken& token) = 0;                                // 撤销
};
// SystemResult 扩展：增加 rollback_token 字段（JSON 原样回传，引擎存入 Artifact/EventLog）
```

**`sandbox.cpp`（★W6）**：

```cpp
// 目标：即使能力被调用，也在 OS 层拒绝越界（Policy 是"规则"，Sandbox 是"访问不到"）
class Sandbox {
 public:
  static bool allow_path(const std::filesystem::path& p, const Scope& scope);
  static bool allow_process(const std::string& exe, const Scope& scope);
};
```

**引擎侧同步改造（`engine/yuiro/systemd/client.py`）**：

```python
# 现状：不解析 audit、不传 trace_id
# 目标：
#   call(tool, args, *, dry_run, trace_id, session_id)      ← params 透传
#   SystemActionResult 增加 artifacts / rollback_token / audit(对象，含 ts/actor/trace)
```

---

## 4. 关键设计决策（预览已采用，落地时先确认）

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| D1 | Session 归属 | 引擎权威：control 建连创建并回发 `session:ready`；audio 带 `?session=` 绑定 | 不信任前端生成 id；兼容旧前端（无参时独立会话） |
| D2 | 事件命名 | 内部点分（`llm.first_token`）→ 对外冒号（`llm:first_token`），映射集中在 `events.py` | 内部结构化可检索；前端零破坏；不散落映射 |
| D3 | per-session 状态接管 | 只接管"会话身份 + 取消 + trace"；`_history/_state_notes` 暂不动 | 最小改动、可回滚；防一次性大水漫灌 |
| D4 | 文件物理拆分 | Wave 2 之前不拆 `audio/__init__.py`、`agent/__init__.py`；拆分单独 Sprint + re-export | 拆分本身零产品价值，且易引入回归 |
| D5 | 配置新增 | `RuntimeConfig`（trace/eventlog）、`TaskConfig`、`ProfileConfig` 三段，向后兼容默认值 | 业务代码不读 env；Profile 是 Wave 6 权限前置 |
| D6 | 事件双通道 | 内部 `AgentEvent`（dataclass）；对外 JSON 由 `to_wire()` 单点转换 | Event / Hook / Intent 三者分离，不混一个总线 |
| D7 | 引擎协议单一来源 | 前端新增 `shared/engine-protocol.ts` 为唯一权威；渲染层禁止裸 JSON 解析 | 消除现状"IPC 事件表 vs 引擎裸 JSON"两张皮 |
| D8 | daemon schema 单一来源 | `tools/list` 返回 `input_schema`，引擎透传不再手写 schema | 消除双维护，已出现 `approval_required` 冲突 |

---

## 5. 每个 Wave 结束时的"形态检查表"

| Wave | engine 侧 | shell 侧 | system-daemon 侧 |
|---|---|---|---|
| W0 | `runtime/` 包存在；`session:ready`；`Session.cancel()` 能停 LLM 流；`trace_id` 出现在日志与事件里；`AgentEvent` 落 EventLog | `useEngine` 统一连接（session 握手 + 重连 + generation 过滤）；`engine-protocol.ts` 建立；VoiceDebug 升级为 Event Log 查看器 | —（不动） |
| W1 | `speech/` 包存在；`tts:interrupted` 由引擎真实发出；`TTSTaskManager` 在播放路径上；打断后 LLM 与 TTS 同时停止 | `useVoiceInput` 带 `?session=`；`tts:interrupted` 停播 + 停口型；两条 WS 断线重连 | —（不动） |
| W2 | `avatar/` 包存在；`emotion:set` 收敛为 `AvatarIntent`；动作/表情不再互相打架 | `Live2DCanvas.applyAvatarIntent` 生效（expression/motion/优先级）；emotion 转发 intent | —（不动） |
| W3 | `context/` 包存在；`_build_messages` 改为 `ContextEngine.build`；存在 ContextItem 元数据与预算裁剪 | —（无感） | —（不动） |
| W4 | `memory/runtime.py` 存在；旧 generation 的写入被拒绝且有事件；`consolidation` 异步运行 | `MemoryIndicator`（🧠"记住了"）；调试台 MemoryManager 复用 | —（不动） |
| W5 | `task/` 包存在；长任务可从 Task Journal 恢复；大工具结果进 ArtifactStore | `TaskPanel` 显示 `task:update` | `transaction.hpp/cpp`（文件类 rollback）；`tools/list` 补 `input_schema` |
| W6 | `capability/policy.py` 存在；PermissionProfile 生效 | 审批对话框支持 plan-level（level/plan/scope） | `sandbox.hpp/cpp` + scope 校验 + `redact()` 落地 |
| W7 | `presence` 由 `proactive/` 演化；`ProactiveIntent{urgency}` 决定是否出声 | `proactive:greet` 支持 urgency/channel（气泡 vs TTS） | —（不动） |
| W8 | `skill/` `plugins/` 不再是 stub；Subagent 只能由 TaskRuntime 创建 | 插件 UI 贡献位（widget 插槽，可选） | —（按插件需要扩展能力） |

---

## 6. 不变量（预览与实现都不得违反）

1. **现有行为兼容**：Wave 期间旧通道（`chat:assistant`、`emotion:set` 等）必须继续可用，新增字段只加不改；
2. **AgentLoop / Memory / VoicePipeline / Live2D / SystemDaemon 不重写**，只包装与接线；
3. **迁移顺序**：先包外挂 → 再 Adapter → 再切调用方 → 最后考虑拆文件；
4. **单点转换**：内部事件名 → 对外事件名的映射只允许存在于 `runtime/events.py`；
5. **取消传播链完整**：`Session.cancel()` 是唯一入口，任何"只停一半"的实现视为未完成；
6. **预览不是承诺**：类名/文件名可在对应 Wave 的 Sprint Plan 中调整，但"包边界与职责"不应改变；
   改变包边界 = 架构变更，需回到 `architecture-goal.md` 与 `runtime-contract.md` 重新论证。
