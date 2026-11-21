# Yuiro Spec —— 架构演进规范（长期权威基准）

当前用户指定前置项：[C0 双角色隔离与切换契约](character-cards.md)。先完成 Hiyori / Hotaru 的独立配置、数据、调试台及安全切换，再继续统一 Goal；此增量不替换已有 Session/Agent/Voice/Avatar Runtime。

> 本目录是 Yuiro 长期架构演进与开发流程的**权威规范（spec）**。
> 任何开发任务（含 Coding Agent）在动手前必须先读本目录；与仓库内其他文档冲突时，以本目录为准。

---

## 0. 战略来源与效力

本 spec 由四份战略讨论文档提炼固化而来（原文保留在 `docs/goal/` 作为战略溯源）：

| 战略来源 | 贡献的核心思想 |
|---|---|
| `docs/goal/Yuiro Architecture Evolution Goal.md` | 目标架构、Runtime Contract、Generation / Cancellation 协议、实施优先级、DoD、禁止事项 |
| `docs/goal/Yuiro Evolution Roadmap.md` | Era 0–5 六时代、Personal Brain Track、Sprint 节奏、开发协议（五要素/七步）、三层测试体系 |
| `docs/goal/Yuiro架构改进.md` | Stable Kernel + Pluggable Edge、最终蓝图、参考架构取舍、架构宣言 |
| `docs/goal/市面Agent参考.md` | **Harness 中心化升级**：六个一等实体、Event Log、ContextEngine、TaskRuntime/Plan、Sandbox/Permission、Agent Profile/Subagent、Hooks、Lazy Skills、Artifact/Checkpoint、Background Task、优先级重排 |

效力规则：

- 四份原文是**战略溯源**（对话体历史记录），只读、不逐字维护；
- **本目录是提炼后的权威版本**，后续开发只认本目录；后一份（市面Agent参考）对前几份的修正以本目录的最终整合为准；
- spec 与代码现状冲突时：不影响功能的文档偏差直接修文档；涉及行为差异的，按 `coding-agent-protocol.md` 的七步流程处理并记录。

---

## 1. 最高锚点（Architecture Principle）

> **Yuiro is a Runtime-centric embodied personal agent: a stable execution kernel coordinates
> intelligence, memory, capabilities, voice, avatar, and presence through explicit state, events,
> lifecycle, cancellation, policy, context, and observability, while external models, providers,
> tools, skills, plugins, and embodiment assets remain replaceable.**

> **Yuiro 是一个以 Runtime 为核心的具身个人智能体：通过显式的状态、事件、生命周期、取消、策略、
> 上下文和可观测机制，统一协调 Agent、Memory、Capability、Voice、Live2D 与 Presence；
> 模型、服务商、工具、技能、插件及表现资产则保持可替换。**

### 1.1 总目标（最终形态）

> **Build Yuiro as an embodied agent harness.**
> 也要建设的不再是"更多 Agent 功能"，而是一个 Codex / Claude Code 级别的 **Harness Kernel**，
> 再把 airi / my-neuro 级别的语音、Avatar、Memory、关系能力挂在这个 Kernel 上。

```
Embodied Personal Agent
    = General Agent Harness          （Agent 怎样可靠工作）
    + Realtime Embodiment Runtime     （Agent 怎样像角色一样生活）
    + Long-term Relationship Memory
    + Safe Desktop Capabilities
```

两组参照系正好互补：**桌宠项目**（airi / my-neuro / Open-LLM-VTuber）回答"怎样像角色一样生活"；
**Coding Agent**（Codex / Claude Code / OpenCode / DSH）回答"Agent 怎样可靠工作"。

### 1.2 职责四分法

```
Model    = 我是什么样的人   （行为风格 / 反应模式 / 工具使用习惯）→ Personal Brain / LoRA
Memory   = 我经历过什么     （事实 / 情节 / 偏好 / 关系）        → MemoryRuntime（数据库）
Runtime  = 我现在能做什么   （能力 / 行动 / 取消 / 恢复）        → Harness / Capability
Embodiment = 我如何表现自己 （声音 / 表情 / 动作 / 存在感）      → Speech / Avatar / Presence Runtime
```

一句话边界：**Weight defines how Yuiro behaves. Memory defines what Yuiro knows. Runtime defines what Yuiro can do.**

---

## 2. 一条主线：Harness Kernel + 具身接入

本次演进**不是**增加大量新功能，而是：

> **把已有功能从"彼此独立的模块"升级为"受统一 Harness 管理、具有统一生命周期和运行时契约的协同 Runtime"。**

真正的主轴：**统一 Runtime Contract（Session / Generation / Cancellation / Lifecycle / Trace）**
+ **Harness 的六项 ownership**（谁拥有 Session / Context / Task / Permission / Cancellation / Tool 可见性）。

```
当前 Yuiro（功能已完整，局部有实现、全局无契约）
    │
    ▼
① P0 Harness Foundation：Session / Event Log / Generation / Cancellation / Trace
    │
    ▼
② P1 Context Engine（context source / budget / lazy skill）
    │
    ▼
③ P1 Task Runtime（plan / state / checkpoint）＋ Speech / Avatar 接入 Harness
    │
    ▼
④ P2 Security Runtime（sandbox / permissions / capability view）
    │
    ▼
⑤ P2 Memory Lifecycle（episode / semantic / relationship）
    │
    ▼
⑥ P2 Subagent → ⑦ P3 Plugin / Hooks → ⑧ P3 Background Agent
    │
    ▼
最终：Yuiro Harness（可取消、可追踪、可恢复、可扩展、可组合）
```

**优先级铁律**（目标优先级序列，详见 `roadmap.md`）：

```
P0 Harness Foundation  Session / Event / Cancellation
P1 Context Engine      context source / budget / skill
P1 Task Runtime        plan / state / checkpoint
P1 Speech + Avatar     接入 Harness（Adapter 化）
P2 Security Runtime    sandbox / permissions / capability
P2 Memory Lifecycle    episode / semantic / relationship
P2 Subagent            parallel / isolation / verification
P3 Plugin / Hooks
P3 Background Agent
```

- 不要先开发 Plugin，再解决 Cancellation；
- 不要先增加 Live2D 动作，再解决 Agent stale result；
- 不要先增加 Memory Retrieval 算法，再解决 Memory Lifecycle；
- 不要先做 Subagent，再做 Session / Event / Context；
- 每个阶段只在满足 spec 的 Definition of Done 后才算完成。

---

## 3. 六个一等实体（建模骨架）

架构围绕六个实体建模，它们分别回答：

| 实体 | 回答的问题 | 归属 |
|---|---|---|
| **Session** | 我们这次交互属于谁？ | Harness（Persistent AgentSession，可 resume / fork / archive） |
| **Task** | 我正在完成什么目标？ | Harness / TaskRuntime（跨多轮，有状态机与 Task Journal） |
| **Event** | 已经发生了什么？ | Harness / Event Log（agent-native，可持久化、可回放） |
| **Intent** | 下一步想做什么？ | Runtime 间通信（SpeechIntent / AvatarIntent / ProactiveIntent / InterruptIntent） |
| **Artifact** | 产生 / 使用了什么对象？ | Capability 层（Artifact Store，工具大结果不进 context） |
| **Capability** | 我能做什么、被允许做什么？ | Capability & Execution（Tool / Skill / Plugin / Policy / Sandbox）；**S11 起 `capability/` 已落地**：RiskLevel × 四档 PermissionProfile → ALLOW / ASK / DENY + CapabilityView 工具可见性；Sandbox 由执行后端承担（参数级边界） |

配套区分（不得混用）：

```
Conversation Memory = 用户和我聊了什么
Relationship Memory = 我们之间发生过什么
Task State          = 我正在做什么      ← 独立于记忆，放 Task Journal / Artifact
Model Personality   = 我说话做事像谁    ← 放 LoRA，不放进 Memory，也不放进 Task
```

---

## 4. 最终目标蓝图（四层）

```
┌──────────────────────────────────────────────────────────────────┐
│ EXPERIENCE LAYER                                                 │
│ Desktop / Chat UI / Voice / Live2D / Proactive / Task Panel      │
├──────────────────────────────────────────────────────────────────┤
│ EMBODIMENT RUNTIME                                               │
│ SpeechRuntime（VAD/ASR/TTS/Playback）· AvatarRuntime（Intent/    │
│ Expression/Motion/Priority）· Emotion · Presence                 │
├──────────────────────────────────────────────────────────────────┤
│ AGENT HARNESS                                                    │
│ SessionRuntime · Event Log · ContextEngine · Agent Loop          │
│ Task/Plan Runtime · Cancellation · Skill · Subagent · Artifact   │
├──────────────────────────────────────────────────────────────────┤
│ CAPABILITY & EXECUTION                                           │
│ Tools · Plugins · MCP · Sandbox · Policy · Approval ·            │
│ Execution Backend(native/SystemDaemon) · Providers · Storage     │
└──────────────────────────────────────────────────────────────────┘
        │                                        │
        ▼                                        ▼
   Stable Kernel 语义                       Pluggable Edge
（不可插件化：Session/Generation/             （可替换：LLM/ASR/TTS/
  Cancellation 语义、Event Schema、             Live2D 资产/Memory 后端/
  Security Policy）                            Tools/Plugins/Skills/UI）
```

**Stable Kernel + Pluggable Edge**（取舍总原则）：

- **Kernel（尽量稳定，改动需 spec 级论证）**：Runtime、Session、State、Event、Lifecycle、Cancellation、Context、Trace、Policy、Capability、Persistence、Interfaces。
- **Edge（允许不断变化，替换不得引发内核改造）**：LLM、ASR、TTS、Live2D 模型、动画资产、Memory 后端、Tools、Plugins、Skills、UI、本地/云模型。

推论：换模型不重写 Runtime；换 Live2D 不重写 Agent；换 TTS 不重写 Memory；换 Memory 后端不影响 Voice。

---

## 5. 文档索引

| 文档 | 内容 | 何时读 |
|---|---|---|
| [architecture-goal.md](architecture-goal.md) | 目标架构总纲、六个一等实体、四层定义、各组件契约、参考架构裁判表、实施优先级、DoD、禁止事项 | 任何架构设计、接口新增前 |
| [runtime-contract.md](runtime-contract.md) | P0 内核规范：Session / Generation / Cancellation / Lifecycle / Trace / Event / 状态机 / 错误处理 / Composition Root | 动 P0 内核代码前 |
| [roadmap.md](roadmap.md) | 推进序列（Wave / P）、Era 0–5 产品线、Personal Brain Track、版本节奏、Sprint 模板、基线差距、建议 Sprint | 规划"下一步做什么"时 |
| [coding-agent-protocol.md](coding-agent-protocol.md) | 开发协议（五要素/七步）、通用母 Prompt、护栏、测试三层（Unit/Scenario/Showcase）、Trace/Replay 要求、报告模板 | 每次接到具体任务时 |
| [target-file-preview.md](target-file-preview.md) | 目标最终形态与文件预览：目标目录树、现有文件映射、关键类骨架、设计决策、Wave 形态检查表 | 评估方向与工作量、审核 Sprint Plan 时 |

历史文档定位（保留、逐步让位）：

- `ARCHITECTURE.md` —— 当前架构说明（as-is）+ 模块接口契约；目标架构以本目录为准；
- `docs/init/milestones.md` —— M0–M6 历史里程碑；新主线以 `roadmap.md` 为准；
- `docs/llm-finetune-mac-persona.md` —— Personal Brain 原始设想（战略约束已提炼进 `roadmap.md`）。

---

## 6. 全局硬约束（跨文档汇总，违反即打回）

1. **不推倒重来**：优先 `复用现有实现 → 抽抽象 → 适配 → 替换调用路径`，禁止 `删除 → 重写`。AgentLoop / Memory / VoicePipeline / Live2D / SystemDaemon 均适用。
2. **不为了架构而架构**：不引入没有具体用例的抽象；不产生 100 个 interface 却解决不了 cancellation / lifecycle / race condition。
3. **不微服务化**：单机桌面应用，长期保持 `Single Process + Modular Runtime`，不拆成 Agent/Speech/Memory/Avatar Service 走网络通信。
4. **不引入重量级 Message Broker**：asyncio Queue + typed dataclass + event dispatcher 足够；禁止 Kafka / RabbitMQ / Redis Streams。
5. **不把所有东西都 Event 化**：Agent→Tool 之类的明确同步调用保持同步；只有跨 Runtime、生命周期、用户事件、异步状态变化才用 Event/Intent。
6. **Event ≠ Hook ≠ Intent**：Event 是系统事实广播，Hook 是扩展点，Intent 是要执行的动作；不得混成一个 EventBus。
7. **Memory ≠ Fine-tuning**：长期知识与记忆不进入模型权重；LoRA 只负责行为风格 / 反应模式 / 工具习惯。
8. **Live2D 不是 Agent API**：Agent 只表达 `emotion / intensity / motion` 等意图，永不直接操作 Cubism 参数。
9. **系统操作只经执行后端**：`Agent → Capability → Permission → Sandbox → Approval → Execution Backend` 安全链不可绕过；LLM 不能直达任意 OS 命令。执行后端**可替换**：`[systemd].backend` = `native`（Python 原生，默认，S10 起）/ `daemon`（C++ SystemDaemon，可选）；两者行为契约一致——**边界在链路上，不在语言上**。
10. **Cancellation 必须传播**：Task Cancel → Agent Cancel → LLM Cancel → TTS Cancel → Avatar Cancel；禁止只停 TTS 而让 LLM 在后台继续跑。
11. **禁止吞取消**：Cancellation 是正常控制流，不得当作系统错误，更不得被 `except Exception: pass` 吞掉。
12. **Context 是稀缺资源**：`Long-term state ≠ LLM context`；不把所有工具 / Skill / 记忆全文塞进 prompt；大结果走 Artifact Store + 摘要。
13. **Capability ≠ Architecture**：多 Agent、后台 Agent、Skill 平台、插件生态都是 Capability；优先复制的是控制结构（Session / Context / Task / Permission / Cancellation ownership）。
14. **Subagent 不随意 spawn**：必须挂 TaskRuntime、受预算/权限/并发/取消控制；只在 context 太大、任务可并行、需不同能力/权限、需独立验证时才 delegation。
15. **每个能力必须有可验证 Scenario**：没有场景与验收标准的功能不做（见 protocol 的测试三层）。
16. **新增功能必须带最小架构增量**：一个 Sprint = 一个主要惊喜 + 一个架构增量 + 一个工程指标。
