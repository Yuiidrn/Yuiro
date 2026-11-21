# Yuiro Architecture Goal —— 目标架构总纲

> 本文件是 `docs/spec/` 的核心：定义 Yuiro 要演进成什么、各组件契约是什么、允许借鉴什么、
> 优先级如何排、什么算完成、什么绝对不做。
> 内核级细节（Generation / Cancellation / Lifecycle 的精确语义）见 [runtime-contract.md](runtime-contract.md)。

---

## 0. Goal Definition

在不推翻当前 Electron + Python Engine + C++ SystemDaemon 基础、不进行无必要大规模重写的前提下：

```
从：功能较完整的 AI Desktop Pet
                      ↓
到：General Agent Harness + Embodied Desktop Runtime
    （Runtime-centric Embodied Personal Agent）
```

当前已具备（作为起点，不是要重做的东西）：

- Electron Shell / Python Engine / C++ SystemDaemon 三层分离
- Agent Tool Loop（含工具轮限制、失败限制、成功去重、并行执行）、多 Provider LLM
- VAD / ASR / TTS / Barge-in（局部）/ Live2D / Emotion / Proactive
- sqlite-vec 三层记忆 + RRF、Tool Registry、Approval / Audit / Dry-run
- Plugin / Skill 架构骨架、TOML + Pydantic 配置体系

改造原则（判断顺序，不可跳过）：

```
1. 当前代码是否已经解决这个问题？
2. 能否抽象现有实现？
3. 能否通过 Adapter 接入新 Runtime？
4. 能否增量迁移？
5. 最后才考虑重写。
```

---

## 1. 目标架构（Harness 为中心）

```
                         YUIRO
                           │
                    Product Surface
                Desktop / Voice / Avatar
                           │
                           ▼
              ╔═══════════════════════╗
              ║     YUIRO HARNESS     ║
              ╠═══════════════════════╣
              ║ Session Runtime       ║
              ║ Event Log             ║
              ║ Context Engine        ║
              ║ Agent Loop            ║
              ║ Task / Plan Runtime   ║
              ║ Cancellation          ║
              ║ Capability / Policy   ║
              ╚═══════════╤═══════════╝
                          │
        ┌─────────────────┼───────────────────┐
        ▼                 ▼                   ▼
 Speech Runtime       Tool Runtime       Memory Runtime
        │                 │                   │
  VAD / ASR / TTS    Builtin/MCP       Episode/Semantic
  SpeechIntent       Plugin/Skill      Relationship
        │                 │
        │             SystemDaemon
        │                 │
        ▼                 ▼
 Avatar Runtime      Sandbox / OS
        │
 Live2D / Emotion
```

**Harness 是真正的中心**：用户说一句话后的完整路径——

```
用户说了一句话
    ↓
SessionRuntime（记录 user.message Event，归属到 AgentSession）
    ↓
TaskClassifier（InteractionMode：CHAT / ACTION / PLAN / TASK / BACKGROUND）
    ↓
ContextEngine（选择 Persona / Memory / Skill / Tool View，按预算组装）
    ↓
AgentLoop（决策下一步）
    ↓
Tool / Subagent（经 Capability View + Policy + Approval）
    ↓
Events（tool.requested / tool.completed / ...）
    ↓
Response
    ↓
SpeechIntent → TTS → Playback
AvatarIntent → Live2D
```

### 1.1 Stable Kernel + Pluggable Edge

```
              Yuiro Stable Kernel
                      │
         ┌────────────┼────────────┐
         │            │            │
      Session       Events     Cancellation
         │            │            │
         └────────────┼────────────┘
                      │
               Capability Policy
                      │
              ───── Kernel ─────
                      │
       ┌──────────────┼───────────────┐
       ▼              ▼               ▼
    Plugins         Skills          Providers
       │              │               │
      Tools         Workflow        LLM/TTS
```

**不能插件化的核心**（Kernel 语义）：`Session semantics`、`Generation semantics`、`Cancellation semantics`、`Event schema`、`Security policy`。
其他尽量插件化 —— 这比 DSH 的"Everything is Plugin"更适合桌宠：Speech 的 barge-in / generation / TTS / playback 要求强一致性，不能由插件自由组合。

### 1.2 六个一等实体

| 实体 | 回答 | 关键字段 / 形态 |
|---|---|---|
| **Session** | 我们这次交互属于谁？ | `session_id / generation / parent_session_id / state / events / active_tasks / context_snapshot / permissions / created_at / last_active_at / lifecycle` |
| **Task** | 我正在完成什么目标？ | `task_id / goal / plan / status / steps / artifacts / blockers / result` |
| **Event** | 已经发生了什么？ | `AgentEvent{event_id, session_id, generation, trace_id, type, source, timestamp, payload}` |
| **Intent** | 下一步想做什么？ | `SpeechIntent / AvatarIntent / ProactiveIntent / InterruptIntent / RetrieveMemory / ExecuteTool` |
| **Artifact** | 产生/使用了什么对象？ | `artifact_id / type / source / task_id / path / summary / metadata` |
| **Capability** | 我能做什么、被允许做什么？ | `Capability(name, tools, permissions, required_env, approval_required, availability)` |

关系：`Task → Skill → Tools → Artifacts`；`Session → Event* → Task*`；`Capability` 决定 Agent 在当前环境"允许并可用"的能力集合。

---

## 2. Harness 的六项 ownership

决定系统能否扩展的不是 Agent 有多聪明，而是谁拥有这些：

| Ownership | 含义 | 落地 |
|---|---|---|
| **Session ownership** | 一次交互属于哪个会话、哪个 generation，断线可恢复 | SessionRuntime + Event Log 持久化 |
| **Context ownership** | 哪些信息进入模型、占多少预算、如何压缩 | ContextEngine |
| **Task ownership** | 长期目标的进度、计划、恢复 | TaskRuntime + Task Journal |
| **Permission ownership** | 当前允许做什么、需要谁批准 | Capability View + Policy + Approval |
| **Cancellation ownership** | 谁能叫停什么、如何传播 | Session.cancel() 统一入口 |
| **Tool visibility ownership** | 模型此刻看到哪些工具 | Agent Capability View（动态过滤） |

---

## 3. 组件契约

### 3.1 Session —— AgentSession（不是聊天记录）

Session 不是"这是一段聊天"，而是 **Agent 从开始到结束的一条完整执行轨迹**：

- 支持 `create / resume / fork / archive`；
- 持久保存 event history，客户端断线重连后恢复一致 timeline；
- 前端（UI）不得自己生成业务 session_id；同一前端实例的 control / audio 通道必须归属同一 AgentSession；
- 具体字段 / 生命周期 / Generation 语义见 [runtime-contract.md](runtime-contract.md) §2–§4。

### 3.2 Event Log —— agent-native，不是传统日志

```
AgentEvent {
    event_id, session_id, generation, trace_id,
    type, source, timestamp, payload
}
```

必须支持的事件类别（第一版最小集）：

```
session.started / session.completed
user.message
speech.started / asr.completed / speech.intent_created
agent.started / agent.cancelled
llm.started / llm.token
tool.requested / tool.approval_required / tool.started / tool.completed
memory.retrieved
tts.started / avatar.motion_started
```

Event Log 同时改善：**恢复、调试、UI timeline、Memory、主动行为、长期任务、审计**。
（与 Hook / Intent 的区别：Event 是"已发生的事实"，见 §3.14。）

### 3.3 ContextEngine —— Context 是独立基础设施

Memory 不能解决所有 Context 问题。ContextEngine 负责组合：

```
System + Persona + Conversation + Memory + Task + Tool + User + Presence + Runtime State
        ↓
Context Builder（Retrieval / Ranking / Summarization / Compaction / Token Budget）
        ↓
LLM
```

**ContextItem 必须带 metadata**：

```
ContextItem { source, scope, priority, token_cost, freshness, relevance, mandatory }
```

**Context Budget 是一等公民**：预算应被管理（例如 system/persona 8K、active task 8K、recent conversation 16K、memory 8K、tools 8K、skill 8K、reserve 8K —— 数字不硬编码，原则是"预算被管理"）。

**Context 分三层**：

```
Cold Context  → Database / event log / memory（不直接喂模型）
Warm Context  → Task state / summaries / relevant memory（按需加载）
Hot Context   → 当前模型调用真正使用的 prompt
```

**铁律**：`Long-term state ≠ LLM context`；`session ≠ ever-growing messages`。

**Memory 与 Context 解耦**：

```
MemoryRuntime → MemoryCandidates → ContextEngine → Budget/relevance/scope → ContextItems → Agent
```

Memory 只负责"找"；ContextEngine 负责"用不用、用多少、放哪里"。

**Tool Result 必须 Context-aware**：大结果（如 500KB JSON）不能整段回灌 LLM：

```
Tool Result → Artifact Store → Result Summary → LLM Context（需要细节时 read artifact slice）
```

### 3.4 Agent Loop（保留 + 受 Harness 管理）

**必须保留现有 AgentLoop 的优秀机制**，不得为 Runtime 抽象而削弱：

- tool round limit / tool failure limit / successful tool deduplication
- parallel tool execution / result ordering / no-progress termination
- generation checking / final summarization

**最终状态模型**：

```
IDLE → THINKING → TOOL_CALLING → TOOL_RESULT → THINKING → RESPONDING → COMPLETED
任何阶段都允许：INTERRUPTED / CANCELLED / FAILED
```

反例（禁止）：

```
TTS stopped but LLM continues invisibly
```

`Model ≠ Agent`；`Agent = Model + Harness`。Agent 只负责"决定下一步做什么"，Harness 负责"让这个决定可靠、安全、可观察地执行"。

### 3.5 TaskRuntime / Plan —— 跨多轮的目标

**AgentRuntime vs TaskRuntime**：

```
AgentRuntime = 怎么思考和执行一步
TaskRuntime  = 为什么执行、执行到哪里、下一步是什么
```

**InteractionMode**（不能把所有输入当成同一种 Chat Turn）：

```
CHAT       简单问题
ACTION     简单工具操作（如"打开网易云音乐"）→ Immediate Action
PLAN       复杂敏感任务 → Plan → Approval → Task
TASK       多步执行（如"整理毕业设计资料"）→ Long-running Task
BACKGROUND 独立耗时任务 → 后台执行 + 进度通知
```

**TaskPlan 是数据结构，不是一段 Markdown**：

```
TaskPlan {
    goal, assumptions, steps[],
    required_capabilities, risk_level,
    approval_requirement, completion_criteria
}
```

**Task 状态机**：

```
CREATED → PLANNING → WAITING_APPROVAL → RUNNING → PAUSED → VERIFYING → COMPLETED
异常：CANCELLED / FAILED / BLOCKED（FAILED 可 → RECOVERING → RUNNING）
```

**Task Journal**（长任务不能依赖模型"记得做过什么"）：

```
TaskState { goal, plan, completed_steps, current_step, artifacts, blockers, next_actions, status }
```

Task State 与 Conversation Memory、Relationship Memory 三者**必须分开**存储与检索。

### 3.6 Capability —— Tool / Skill / Task 三层

```
Capability
├── Tool   原子动作        （read_file / get_weather / play_animation）
├── Skill  多 Tool 组合出的可复用能力流程（analyze_git_progress / comfort_user）
└── Task   有生命周期的目标（"分析 Yuiro 最近一周开发进度"）
```

```
Task → Skill → Tools → Artifacts
```

**Agent Capability View**（解决 Tool Context Explosion）：

```
Global Tool Registry → Capability Policy → (Role × Session) → Agent Capability View → LLM Tools
```

工具可见性按 `agent / capability / current task / availability / permission` 动态过滤；不得把所有工具全量塞给模型。

### 3.7 Security —— 从 Policy-oriented 升级到 Sandbox + Permission + Approval

目标安全链：

```
Agent → Capability → Permission → Sandbox → Approval → Execution → SystemDaemon
```

- **Policy**："不允许访问 `../`"（规则层）；
- **Sandbox**："即使 Agent 想访问，也在操作系统层面访问不到"（真正的隔离强度，这是 SystemDaemon 下一阶段重点）；
- **Approval 分层**（不是每个文件都问一次）：

```
LEVEL 1  read_file          → 自动
LEVEL 2  open_application   → 自动/策略
LEVEL 3  delete_file        → tool approval
LEVEL 4  批量整理用户文件    → plan approval（Plan → approve → 自主执行大量步骤）
```

- **PermissionProfile**（AgentSession 创建时携带）：`NORMAL / TRUSTED / READ_ONLY / PRIVACY`；
- **Capability Scope**（借鉴手机权限域）：

```
filesystem: ~/Documents/Yuiro/**
network:    api.openai.com, music.163.com
process:    whitelist applications
media:      unrestricted
clipboard:  read/ask
screen:     ask
```

- 继续保留：approval、dry-run、trace_id、audit、sensitive tool policy、path traversal protection。

### 3.8 Speech Runtime

保留：VAD（silero / FSMN 配置化）、ASR、TTS、TTSTaskManager、Playback、InterruptController。

```
Microphone → PCM → VAD → Speech Segment → ASR → User Utterance
    → AgentRuntime → Response Stream → Sentence Segmenter → TTSTaskManager
    → Ordered Audio → Playback
```

要求：

- VAD 只判断"用户是否正在讲话"，不负责 Agent / Memory / TTS / Avatar；
- ASR 只做 `audio → transcription`，携带 `session_id / generation / timestamp`，不直接改 history / memory / emotion；
- TTSTaskManager 必须真正接入执行路径：支持并行 synthesis、顺序 playback、epoch invalidation、cancellation、stale audio suppression；
- **TTS epoch**：每次 interrupt `epoch++ / buffer.clear() / cancel task`，旧 epoch 音频 `MUST NEVER PLAY`；
- **SpeechIntent**：

```
SpeechIntent { session_id, generation, text, priority, interruptible=True }
    ↓
SpeechRuntime → TTS Task → Playback
```

- **Barge-in 是跨 Runtime 操作**（不是 Voice 自己的 feature）：

```
User starts speaking → VAD → Session interrupt
    → AgentRuntime.cancel() → SpeechRuntime.stop_tts() → Playback.stop()
    → AvatarRuntime.cancel_speech_action() → generation++ → new user turn
```

禁止只调用 `voice_pipeline.interrupt()` 然后让 Agent 在后台继续运行。

### 3.9 Avatar Runtime

保留现有 Live2DCanvas，不重写；新增 Runtime 抽象：

```
AvatarRuntime
├── AvatarIntent
├── Expression / Motion / LipSync
├── Priority
└── Cancellation
```

```
AvatarIntent(
    source="agent|emotion|speech|system",
    generation, emotion, expression, motion, priority, duration
)
```

优先级（高可打断低）：

```
SYSTEM > USER_INTERACTION > SPEECH > EMOTION > IDLE
```

Renderer 只负责 `AvatarIntent → Live2D`；**Agent 永不直接控制 Live2D API / Cubism 参数**。

### 3.10 Memory Runtime

保留现有检索基础（Vector / FTS / RRF / Recency / Salience / Facts），升级 **Memory Lifecycle**：

```
Current Turn → Short-Term → Episode → (async) Consolidation
    → Semantic Memory → Fact Memory → Relationship Memory
```

类型：

| 类型 | 内容 | 例 |
|---|---|---|
| Short-Term | 当前上下文 | 当前对话 |
| Episodic | 发生过的具体事件 | "2026-09-08 用户完成毕业论文" |
| Semantic | 长期稳定知识 | "用户长期使用 C++" |
| Fact | 结构化事实 | subject/key/value/confidence/decay |
| Relationship | 人与 Agent 之间的经历 | "共同讨论过某个项目" |

要求：

- Consolidation 异步进行，**不得阻塞用户正常聊天**；不是每轮都复杂化；
- Retrieval 保留 RRF 融合（vector / FTS / recency / salience → reranking/filter → context）；
- **Memory Write Safety**：只有 `current generation` 允许写入当前 Memory；旧 generation 的 LLM/tool/TTS/summary 结果不得进入当前 Memory；
- Relationship + Emotion 闭环：`Experience → semantic importance / emotional intensity / relationship relevance / novelty / recurrence → Memory Runtime`；`affinity/xp/level` 保留但不由 affinity 单独代表关系。

### 3.11 Presence / Proactive

```
Presence Event → Attention Policy → Should Yuiro act? → (yes) Agent → Performance
```

- 必须 event-driven + policy-driven，**不是**"LLM 每秒问一次我要不要说话"；
- 主动 ≠ 高频打扰：Attention Policy + Cooldown + User Preference + Context Awareness + Quiet Hours + Confidence；
- 真正的 Proactive 消费 `Task Events / Memory Events / System Events / User Presence`；
- 输出用 `ProactiveIntent{urgency, interruptibility, channel}`：低 urgency 只抬头/气泡，高 urgency 才 TTS；
- Background Task 是桌宠相比 coding CLI 更天然的场景："你帮我慢慢整理这个文件夹，我先干别的"。

### 3.12 Hooks —— 薄扩展边界

```
Event = 系统事实广播      （tool.completed）
Hook  = 扩展点            （after_tool()）
Intent= 要执行的动作      （SpeakIntent）
```

第一版 Hook 清单：

```
on_session_start / on_user_input / before_context_build / after_memory_retrieval
before_llm / after_llm / before_tool / after_tool
before_speech / after_speech / on_barge_in / on_avatar_action / on_session_end
```

Plugin 通过 `subscribe hooks` 接入，**不得直接依赖 AgentRuntime internals**。

### 3.13 Skill —— Agent workflow / instruction / behavior package

- Skill 不是 Plugin；Skill 也不拥有自己的 Tool Runtime，统一调用 CapabilityRuntime；
- **Lazy / Progressive disclosure**：`Metadata always available → Relevant Skill selected → Skill body loaded lazily`；
- 目录形态：

```
skills/research-paper/
├── SKILL.md
├── scripts/        （parse_pdf.py / search_refs.py）
├── templates/
└── resources/
```

- 使用流程：`Agent → Skill Metadata → Need? → Load SKILL.md → Grant required capabilities → Execute workflow`。

### 3.14 Subagent

- **挂在 TaskRuntime 之下**，不允许 LLM 随意 spawn；由 Task 控制预算、权限、并发、取消、上下文；
- 只在四种情况 delegation：**上下文太大 / 任务可并行 / 需要不同能力或权限 / 需要独立验证**；
- 禁止"Agent 套娃"（聊天 → planning → research → tool → response）；
- 备用角色（按需启用，不默认全开）：`ResearchAgent / SystemAgent / MemoryAgent / VisionAgent / VerifyAgent`；
- **Verification Agent 不默认启用**：仅高风险操作（如"删除所有重复文件"）进入 `Plan → Verify(scope/irreversible/suspicious/mismatch) → Approval`。

### 3.15 Artifact 与 Checkpoint / Rollback

- Artifact 是一等实体；`Artifact{artifact_id, type, source, task_id, path, summary, metadata}`；
- 大工具结果、截图、报告、生成文档全部进 Artifact Store，LLM 只看 summary，需要时按片读取；
- 桌面 Agent 的 Checkpoint 应发展成 **Tool Transaction**（不是 Git checkpoint）：

```
ToolExecution { dry_run() → execute() → verify() → rollback() }
move_files: dry_run → record original paths → execute → rollback token
用户："恢复刚才的操作。" → rollback(transaction_id)
```

- 安全三件套：`Approval + Checkpoint + Rollback`。

### 3.16 Plugin / Profile

- Plugin 第一阶段只实现稳定生命周期：`load → initialize → ready → execute → shutdown`；
- Plugin 必须具备：`plugin_id / version / capabilities / tools / configuration / health`；
- Plugin Manifest（含权限声明）：

```
Plugin Manifest { capabilities, engine entry, UI contributions, permissions, configuration schema }
```

- 统一关系：`Plugin → Capability → Tool`（不要 Plugin / Tool / Skill 三套平行生态）；
- **Profile**（bundle stack + patch layer，可组合运行环境）：

```
Normal / Privacy / Study / Coding / Companion / Minimal
例（Privacy）：network restricted / screen denied / memory write temporary only / system tools ask / proactive disabled
```

- DSH 的"Everything is Plugin"**只借一半**：plugin composition / profile / host-client extension 可借鉴；不引入 Cordis、不把 Session/Speech 等内核语义插件化。

### 3.17 App Server / UI-independent Engine

`Yuiro Engine ≠ Yuiro Desktop UI`：核心 Harness 不绑定 Electron。

```
Yuiro Desktop / Yuiro CLI / Mobile Remote / Web Control Panel
                        ↓
                   Yuiro Harness
```

不要求现在实现，但架构上不得堵死；Python Engine 必须保持 UI-independent。

### 3.18 Agent Profile —— Character ≠ Agent Role

用户始终看到同一个 **Yuiro**；内部可以有不同 role（不是人格分裂）：

```
Yuiro / Conversation
Yuiro / Research
Yuiro / System
Yuiro / Memory
Yuiro / Vision
```

每个 role 可带不同 `prompt / model / toolset / permission / context policy`。
Role 的权限与工具可见性由 Capability View 决定（例：ResearchAgent 根本不应拥有 `shutdown_process / delete_file`）。

---

## 4. 参考架构裁判表

| 架构问题 | 最有价值参考 | Yuiro 应吸收 |
|---|---|---|
| Agent Loop | Codex / Open-LLM-VTuber | Harness-managed loop |
| Session | Codex | create/resume/fork/event persistence |
| Plan | Claude Code | Plan → approve → execute |
| Cancellation | airi / Codex | generation + abort |
| Speech | airi / my-neuro | intent + barge-in |
| Tool Registry | OpenCode / airi | filtered capability view |
| Permission | Codex / OpenCode | resource-scoped policy |
| Sandbox | Codex / Claude Code | filesystem/network containment |
| Plugin | DSH / my-neuro | stable kernel + pluggable edge |
| Skill | Claude Code | lazy-discovered instruction package |
| Context | Codex / Claude Code | scoped, layered context |
| Subagent | Claude Code / OpenCode | isolation/parallel/specialization |
| Long Task | Claude Code | task artifacts/journal |
| Checkpoint | Claude Code | reversible effects |
| Memory | airi | episodic/semantic/relationship lifecycle |
| Avatar | airi / my-neuro | intent + desktop interaction |
| Security | Codex / Claude Code + Yuiro | sandbox + approval + audit |
| Observability | Codex | agent-native event timeline |

四家总体取舍：

- **Codex：强烈借鉴**（Thread/Session、App Server/Core 边界、Event persistence、Sandbox + Approval、agent-native telemetry）；
- **Claude Code：强烈借鉴**（Plan Mode、Checkpoint、Hooks、Skills、Subagents、长任务 artifact、sandbox）；但 Git/worktree 语义要转换成 Desktop Task/Transaction 语义；
- **OpenCode：选择性强烈借鉴**（Agent Profile、Primary/Subagent、权限与工具可见性分离、LLM Runtime adapter 边界）；不照抄 Build/Plan 等具体 coding 角色；
- **DSH：借思想，不追实现**（plugin composition、profile、host/client extension）；developer-preview 阶段，不引入 Cordis / "一切皆插件" 作为核心依赖。

---

## 5. 实施优先级（已按 Harness 升级重排）

```
P0  Harness Foundation      Session / Event / Cancellation
P1  Context Engine          context source / budget / skill
P1  Task Runtime            plan / state / checkpoint
P1  Speech + Avatar         接入 Harness（Adapter 化）
P2  Security Runtime        sandbox / permissions / capability
P2  Memory Lifecycle        episode / semantic / relationship
P2  Subagent                parallel / isolation / verification
P3  Plugin / Hooks
P3  Background Agent
```

第一轮改造范围（增量，不是大改重构）：

```
SessionRuntime
    ├── Event
    ├── Task（雏形）
    └── Cancellation
ContextEngine（雏形）
    ↓
AgentLoop
保留不动、仅以 Adapter 接入：VoicePipeline / Memory / ToolRegistry / SystemDaemon / Live2D
```

第二轮：`Plan / Artifact / Checkpoint / Skill / Capability View`。
第三轮：`Subagent / Background Task / Plugin hooks / Relationship consolidation`。

**最优先的不是 Subagent**，而是：`Session/Event → Context → Task → Sandbox`。

---

## 6. Definition of Done（阶段验收）

### Agent

```
用户输入 → Agent → LLM → Tool → LLM → Response
用户打断 → Agent cancellation → 旧 LLM 不再污染状态
```

### Speech

```
VAD → ASR → Agent → TTS → Playback
用户开始讲话 → Barge-in → TTS stop → Agent cancel → 旧音频全部 invalid
```

### Memory

```
conversation → short-term → episode → consolidation → long-term
旧 generation 不能写当前 Memory
```

### Avatar

```
Agent → AvatarIntent → Live2D
Speaking → Barge-in → Speaking animation cancelled → Listening animation
```

### Tools

```
Agent → Capability → Policy → Approval → Tool → 执行后端（native / SystemDaemon）
具备：trace_id / audit / permission / cancellation
```

### Harness（新增）

```
Session 可 create/resume；Event Log 可从磁盘复原一条完整 timeline；
Task 可从 Task Journal 恢复；ContextEngine 输出受预算约束；
旧 generation 的任何异步结果不得进入当前 state / conversation / memory / TTS queue / avatar action。
```

---

## 7. 明确不做（Do NOT）

### 7.1 架构层面

1. 不为了架构而架构（没有具体用例的抽象不做；100 个 interface 解决不了 cancellation/lifecycle/race condition 就是失败）；
2. 不微服务化（单机 `Single Process + Modular Runtime`）；
3. 不引入重量级 Message Broker（asyncio Queue + typed dataclass + event dispatcher 足够）；
4. 不把所有东西都 Event 化（Agent→Tool 明确同步调用保持同步）；
5. 不推倒 Memory（Vector + FTS + RRF 是正确基础，升级生命周期而非重写检索）；
6. 不推倒 AgentLoop（保留 §3.4 全部机制，只加 Runtime / Cancellation / Lifecycle）；
7. 不把 Live2D 做成 Agent API；
8. 不把长期事实知识存进模型权重（Memory ≠ Fine-tuning）；
9. 不把模型人格逻辑放进 Memory 层、不把长期记忆逻辑塞进 AgentLoop；
10. 不复制 DSH 的 "Everything is Plugin"；
11. 不追求 Agent 能力无限膨胀（Yuiro 首先是 Personal Companion，能力增长服从陪伴体验）；
12. 不因为"现代 Agent 都有"就加入复杂 Planner（`LLM → Tool → Result` 够用就不用 `Planner → Planner → Executor`）；
13. 不照搬 coding-specific 语义（Git worktree / Build 角色等要转换后再用）；
14. 未经明确批准不引入新框架、不重命名大范围代码、不删除"因为新架构更干净"就删的既有行为。

### 7.2 运行时层面

15. 禁止 `except Exception: pass` 吞掉取消；
16. 禁止只停 TTS 而让 LLM 在后台继续运行；
17. 禁止 LLM 直达任意 OS 命令；
18. 禁止无 lifecycle / cancellation 处理的后台自主行为；
19. 禁止无测试场景的功能；
20. 禁止 Subagent 由 LLM 随意 spawn；
21. 禁止把大工具结果整段回灌 LLM context；
22. 禁止 session 变成 ever-growing messages。

---

## 8. 最终成功标准

当 Yuiro 能自然处理下面这个场景时，架构升级真正成功：

```
用户："帮我查一下今天的天气。"
  → Agent → Memory / Context → Tool Call → System / External Capability
  → LLM → 开始流式回答 → TTS → Live2D Speaking
  → 用户突然开始讲话 → VAD → Barge-in
  → Session.cancel() ├── LLM cancel ├── Tool cancel ├── TTS cancel
                     ├── Playback stop ├── Avatar cancel └── generation++
  → 旧结果全部失效
  → ASR → 新的 Agent Turn → Memory 正确记录 → Avatar 根据新的 Intent 行动
```

整个过程中**不存在**：旧 LLM 结果污染新对话、旧音频继续播放、旧 Tool 修改当前状态、
旧 Avatar 动作覆盖新状态、旧 Memory 写入当前会话。

最终形态：

> **可运行、可取消、可追踪、可恢复、可扩展、可组合的本地 Embodied Agent Harness。**
