# Yuiro Runtime Contract —— P0 内核规范

> 本文件定义"统一 Runtime Contract"的精确语义：Session / Generation / Cancellation / Lifecycle /
> Trace / Event / 状态机 / 错误处理 / Composition Root。
> 它是所有后续 Runtime（Agent / Speech / Avatar / Memory / Capability）改造的地基。
> 目标层描述见 [architecture-goal.md](architecture-goal.md)。

---

## 1. Runtime 的统一定义

这里的 Runtime 不是简单的 Python module。每一个 Runtime 必须承担：

```
State / Lifecycle / Concurrency / Coordination
```

- **State**：知道自己当前状态（显式状态，不是散落的 boolean / None / magic string）；
- **Lifecycle**：支持 `initialize → start → ready → run → interrupt → stop → shutdown`；
- **Concurrency**：明确当前 task、task owner、generation、cancellation、stale result；
- **Coordination**：可响应 user event / system event / session event / interrupt / shutdown / capability change。

### 1.1 Runtime Contract（最小方法集）

每个 Runtime 最终至少满足（实现可不同，语义必须一致）：

```python
initialize()      # 依赖注入完成、资源获取，不做业务
start()           # 进入可服务状态（允许异步）
state()           # 返回显式状态对象
handle_event(e)   # 响应事件 / 接收 Intent
cancel(reason)    # 取消当前工作（传播式）
shutdown()        # 有序释放，幂等
```

### 1.2 Runtime 是"操作系统层"

```
Runtime = Session + State + Event + Lifecycle + Cancellation + Coordination
        + Policy + Context + Trace + Replay
```

Agent / Voice / Memory / Live2D / Task / Tool / Presence 都运行在 Runtime 之上，而不是彼此互相调用。

---

## 2. Session Runtime

新增或逐步抽象：

```
YuiroRuntime
└── SessionManager
    └── AgentSession
```

### 2.1 AgentSession 字段（最小集）

```
session_id
generation
parent_session_id          # fork 时使用
abort_controller / cancellation_token
state                      # 显式生命周期状态
created_at / updated_at / last_active_at
active_tasks               # task_id 集合（含 owner 信息）
context_snapshot           # ContextEngine 的会话侧快照（可选，逐步引入）
permissions                # 会话级 PermissionProfile（逐步引入）
lifecycle                  # creating → active → suspended → closed
```

### 2.2 归属规则（硬性）

- 所有 Agent / Speech / Avatar / Tool 任务都必须关联 `session_id + generation + task_id`；
- **同一前端实例**的 `/ws/control` 与 `/ws/audio` 必须归属**同一 AgentSession**（当前实现是两个互不相关的 uuid4，属于必须修掉的现状缺陷）；
- 前端不得生成业务 session_id；引擎是唯一权威；
- 断线重连（resume）时，允许从 Event Log 恢复 timeline；不允许"断线即失忆"。

### 2.3 现状落地提示

当前 `ServiceContext`（agent 包内）是唯一的会话隔离设计且零引用；`approval.py` 的连接注册表是事实上的"会话表"。
P0 改造应从"把两者合并升级为 SessionManager"入手，而不是另起一套。

---

## 3. Generation Protocol

`generation = logical conversation generation`（逻辑会话代际）。

保留并扩大现有 generation 机制的作用：

- 每当用户开始新的有效交互（新消息 / 新语音 / 显式 interrupt）：`generation++`；
- **必须提供显式失效入口**（`invalidate(reason)` / `Session.cancel()`），不能只依赖"下一回合自增"隐式触发；
- 旧 generation 的异步结果：

```
MUST NOT mutate current state
MUST NOT enter current conversation
MUST NOT enter current memory
MUST NOT enter current TTS queue
MUST NOT trigger current avatar action
```

即：`generation mismatch → stale result → discard`。

**stale 丢弃必须是可观测的**：不得静默 `return`（当前 5 处 stale 检查都是静默返回，调用方无法区分"正常结束"与"被代际作废"）——
应产出 `StaleResult` 事件或明确返回值，并在 Trace 中标记。

---

## 4. Cancellation Protocol

Generation 不能代替真正的 cancellation。必须形成 **Generation + Cancellation 双层机制**：

- **Cancellation**：尽可能真正停止正在运行的任务（LLM 请求 / 工具执行 / TTS 合成 / 播放 / Avatar 动作）；
- **Generation**：即使旧任务无法立即停止，其返回结果也绝不能污染当前状态。

### 4.1 统一取消入口

```
User Barge-in / UI stop / Session reset / Task cancel
      │
      ▼
Session.cancel(reason)
      ├── cancel LLM（关闭流 / abort 请求）
      ├── cancel Tool（含等待中的审批）
      ├── cancel TTS（epoch++ / 清缓冲）
      ├── stop playback
      ├── cancel avatar action
      └── invalidate generation（generation++）
```

**禁止**只调用 `voice_pipeline.interrupt()` 然后让 Agent 在后台继续运行。

### 4.2 语义要求

- Cancellation 是**正常控制流**，不是系统错误：不产生 stack trace 噪音；
- 日志级别必须能区分 `expected cancellation` 与 `unexpected failure`；
- 取消必须**可传播**且**可被等待**（`cancel()` 之后允许 `await` 收敛完成）；
- 任何 `except Exception` 都不得吞掉 `CancelledError`；
- 取消完成后，所有下游（TTS 队列 / 播放 / Avatar）必须处于确定的静默状态。

### 4.3 现状落地提示

- `VoicePipeline.interrupt()` 目前只取消"播放中的 TTS task"；在 LLM / 工具阶段是空操作，且不联动 Agent 的 generation；
- `TTSTaskManager`（epoch + 按序交付）已实现但未接线，是 barge-in 改造的现成落点；
- `AgentLoop` 没有 `abort()` API、没有 per-turn task 句柄；`OpenAIProvider` 无 abort 语义（只有超时）。

---

## 5. Lifecycle

### 5.1 统一生命周期语义

```
initialize → start → ready → run → interrupt → stop → shutdown
```

- 不要求所有 Runtime 完全相同实现，但命名与语义必须一致（当前 `warmup` / `start` / `connect` / `close` / `stop` 混用）；
- `state()` 必须可查询，且状态机对外可见（当前只有 VoicePipeline 有私有 `_state`，被 main.py 直接读私有字段）；
- 启动失败 / 降级必须有显式状态（ERROR / DEGRADED），不允许静默半可用；
- `shutdown()` 必须幂等、有序，并释放子进程 / 连接 / 文件句柄（含 BGE-M3 子进程、SystemDaemon、mpv/ncm daemon）。

### 5.2 组合根（Composition Root）

把现有 `main.py` 的 `_build_agent() / _build_memory() / _build_voice() / _build_daemon()` 方向明确为：

```
YuiroRuntime.create(config)
    configuration
        ↓
    dependency construction
        ↓
    runtime initialization
```

`main.py` 不再承担业务逻辑（只做 FastAPI app 装配 + WS 传输适配）。

---

## 6. Trace / Observability

所有跨 Runtime 操作尽可能具备：

```
trace_id / session_id / generation / task_id / runtime / event / duration / status
```

示例：

```
trace=abc123 session=s001 generation=42 runtime=AgentRuntime
event=tool_call tool=read_file status=success duration=34ms
```

### 6.1 要求

- 一次用户输入 = 一个 trace：WS 收包 → ASR → Context → LLM → tool_call → 审批 → 工具 → TTS → Avatar 全链路共享同一 `trace_id`；
- `LLMChunk` 等流式事件必须携带 `generation`（当前没有，导致事件不可回溯、不可去重）；
- 工具执行（含并行 gather）结果必须与请求 id 关联；
- Trace 输出到结构化日志 / Event Log / 调试面，三者可关联；
- 新增关键分支必须打带阶段标记的 `vlog`（沿用仓库既有「链路日志分阶段定位」红线）。

### 6.2 Replay

Trace 可保存、可回放：

```
Scenario → Trace → Save → Replay（新 Runtime / 新 LLM）→ Compare
```

这是 Scenario-driven development 与 Showcase Test 的工程基础（见 `coding-agent-protocol.md`）。

---

## 7. Event / Intent 协议

### 7.1 Event 与 Intent 的区别

```
Event  = 已经发生的事情（UserSpeechStarted / TTSStarted / ToolCompleted / BargeInDetected）
Intent = 系统希望执行的动作（CancelAgent / SpeakText / PlayMotion / RetrieveMemory / ExecuteTool）
```

不得混用。补充第三个概念：

```
Hook = 扩展点（before_tool / after_tool），≠ Event，≠ Intent
```

### 7.2 通信方式（不过早引入重型设施）

优先：

```
explicit interface + typed event / intent
```

Python Engine 内部使用：`asyncio` + `typed dataclass` + `queue` + `event dispatcher`。
不引入 Kafka / RabbitMQ / Redis Streams；不引入进程外消息总线。

### 7.3 什么该 Event 化

只有以下情况优先 Event / Intent：

- 跨 Runtime 通信；
- 生命周期变化；
- 用户事件；
- 异步状态变化。

明确同步调用（如 Agent → Tool 派发）保持同步，不要为了"统一"而 Event 化。

---

## 8. State Machine（禁止状态散落）

不要让状态散落在 `boolean / None / magic string`：

```
speaking=True, recording=False, locked=True   ← 禁止继续扩散
```

逐步统一成显式状态：

```
Speech: IDLE / LISTENING / TRANSCRIBING / THINKING / SPEAKING / INTERRUPTED
Agent:  IDLE / THINKING / TOOL_CALLING / TOOL_RESULT / RESPONDING / CANCELLED / COMPLETED / FAILED
Task:   CREATED / PLANNING / WAITING_APPROVAL / RUNNING / PAUSED / VERIFYING / COMPLETED / CANCELLED / FAILED / BLOCKED
Avatar: IDLE / LISTENING / THINKING / SPEAKING / INTERACTING / INTERRUPTED
```

任何阶段都允许：`INTERRUPTED / CANCELLED / FAILED`。

---

## 9. Error Handling

Runtime 必须区分错误类型：

```
Cancelled / Timeout / ToolFailure / LLMFailure / SpeechFailure /
StaleResult / ConfigurationError / SecurityDenied
```

- 禁止 `except Exception: pass`；
- 尤其不能吞掉 cancellation；
- 对可恢复错误（Timeout / ToolFailure）应有明确降级路径，且降级必须可观测（状态、事件、日志三选二）。

---

## 10. 配置架构

- 当前 `AppConfig` 继续作为配置入口，**短期不重构**；
- 随系统扩大可逻辑分组：

```
RuntimeConfig
├── AgentConfig / SpeechConfig / MemoryConfig
├── AvatarConfig / ToolConfig / SystemConfig
└── ProactiveConfig / ProfileConfig（新增：Profile 选择）
```

- 保持 `Pydantic + TOML + frontend schema`；
- **业务代码不能到处读取环境变量**：`Config → Typed Config → Runtime / Components`。

---

## 11. 目标目录方向（长期，非第一优先级）

```
engine/yuiro/
├── runtime/
│   ├── session.py / lifecycle.py / cancellation.py / events.py / trace.py
├── agent/
│   ├── runtime.py / loop.py / context.py / ...
├── speech/
│   ├── runtime.py / vad.py / asr.py / tts.py / playback.py / intent.py
├── avatar/
│   ├── runtime.py / intent.py / ...
├── memory/
│   ├── runtime.py / retrieval.py / consolidation.py / episode.py / facts.py / relationship.py
├── capability/
│   ├── runtime.py / registry.py / policy.py / artifact.py
├── plugins/ · skill/ · systemd/
```

> **目录结构不是第一目标。Runtime Contract 才是第一目标。**
> 如果现有目录结构可以实现目标，不要为了"看起来漂亮"移动大量文件。

---

## 12. 必须测试的 Race Conditions（P0 验收底线）

```
LLM response arrives            while user starts speaking
TTS segment 2 arrives           after interrupt
Tool returns                    after Agent cancellation
Memory consolidation finishes   after session reset
Avatar animation callback       after generation invalidation
Stale tool result               arrives after new generation started
Approval approved               after task cancelled
```

所有这些必须：

```
NOT corrupt current state
```

测试策略见 `coding-agent-protocol.md` 的测试三层（Unit / Scenario / Showcase）。

---

## 13. 现状基线（2026-09 审计结论）

| 维度 | 现有（局部有实现） | 缺口（全局无契约） |
|---|---|---|
| **Session** | WS 建连即 `uuid4().hex`；各模块用 `dict[session_id, …]` 分桶；tool/approval 已带 session_id | 无 Session 实体/注册表/生命周期；control 与 audio 的 id 互不相关（同一前端两个会话，history 割裂）；前端不可续用 session；记忆层 `del session_id` 无会话隔离 |
| **Generation** | `AgentLoop._generations`（5 处 stale 检查，静默 return）；`TranscriptBuffer._generation`（实现未用）；`TTSTaskManager._epoch`（实现未接线） | 无统一类型/来源；无显式 invalidate；stale 不可观测；与 Speech/Cancellation 不联动 |
| **Cancellation** | `VoicePipeline.interrupt()` 可取消播放中 TTS；前端 `{"type":"interrupt"}` 已接；SpeechStart 自动 barge-in | LLM 请求不可取消；工具执行（含审批等待）不可取消；LLM 阶段 interrupt 是空操作；无 `tts:interrupted` 等回执；AgentLoop 无 abort API |
| **Lifecycle** | `lifespan()` 统一启动/关闭；VoicePipeline 有 init→loading→ready→error 状态机；ProactiveScheduler start/stop | 无统一 Runtime 契约，命名/签名不一；状态不可统一查询；无健康/降级汇总 |
| **Trace** | C++ daemon `trace_id` 已透传给工具；`vlog` + `log_ring`；`tool_trace` 本地记录 | 引擎无 turn/request/tool-call id；流式 chunk 无 id/generation；工具并行结果无 id 关联；无 Trace/Replay/Event Log |

**可直接复用的现成骨架**（"已写好但未接线"）：

- `TTSTaskManager`：并行合成 + 按序交付 + epoch 取消（P1 Speech 改造落点）；
- `TranscriptBuffer`：代际计数 + 禁止过期 flush（P1 Speech 落点）；
- `ServiceContext`：会话隔离设计（P0 Session 落点，需先接线再演进）；
- `response_categorizer`：`<think>` 剥离（接线检查）；
- `skill/`、`plugins/`：纯 stub（P3 从零实现，勿当已有能力）。
