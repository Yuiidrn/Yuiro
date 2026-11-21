# Yuiro Evolution Roadmap —— 推进路线

> 本文件回答"下一步做什么、按什么顺序、每个 Sprint 怎么定义"。
> 目标与契约见 [architecture-goal.md](architecture-goal.md)，内核细节见 [runtime-contract.md](runtime-contract.md)。
> 开发流程与护栏见 [coding-agent-protocol.md](coding-agent-protocol.md)。

---

## 0. 研发模式（人机协同）

```
                    YUIRO DEVELOPMENT
                           │
           ┌───────────────┴───────────────┐
           │                               │
        Human                         Coding Agent
           │                               │
   战略/审美/判断                     编码/重构/测试
   体验/创意/验收                     调试/实现/文档
   自定义人格/内容                    自动化/工程化
           │                               │
           └───────────────┬───────────────┘
                           │
                    Shared Roadmap
```

- **Human = Product Owner + Architect + Creative Director + Technical Reviewer**
  （选择 Surprise / 定义体验 / 确定优先级 / 审核 Agent Plan / 观察实现 / 运行 Showcase Test / 决定下一步）；
- **Coding Agent = 主要工程执行者**，负责完成一个"可验证的架构增量"，不是代码生成器。

**不给 Agent 大重构任务**。错误示例："把 Yuiro 重构成现代 Agent Harness"。
正确形态："实现 Surprise #03：让 Yuiro 在 3 天后记住用户主动告诉它的一件事"，并附带约束
"为实现该体验可逐步引入 Memory Runtime，但禁止大规模重构现有 AgentLoop"。

> 产品目标牵引架构，而不是架构牵引产品。

---

## 1. 推进序列（Wave）—— 工程依赖优先，同层按产品感知排序

融合原则：**P0 先行（Harness Foundation），其后同优先级内按 Era 产品感知顺序接入**。

```
当前 Yuiro（M0–M4 能力已具备，但"局部有实现、全局无契约"）
    │
    ▼
Wave 0  Harness Foundation        Session / Event Log / Generation / Cancellation / Trace   ← P0
Wave 1  Speech 接入 + Barge-in     TTSTaskManager 接线 / SpeechIntent / 真打断               ← P1 · Era 0
Wave 2  Avatar 接入                AvatarIntent / 优先级 / 情绪联动                          ← P1 · Era 1
Wave 3  Context Engine             ContextItem / Budget / Cold-Warm-Hot / Compaction        ← P1
Wave 4  Memory Lifecycle           显式记忆 → 三日记忆 → Consolidation → Relationship        ← P2 · Era 2–3
Wave 5  Task / Plan / Artifact     InteractionMode / TaskPlan / Task Journal / Checkpoint   ← P1 · Era 4
Wave 6  Security Runtime           PermissionProfile / Capability Scope / Sandbox           ← P2
Wave 7  Presence / Background      ProactiveIntent / Attention Policy / Background Task     ← P3 · Era 5
Wave 8  Subagent / Skill / Plugin  Hooks / Lazy Skill / Plugin Manifest / 受控 Subagent     ← P2–P3

贯穿：Personal Brain Track（从 Memory MVP 起即开始积累数据）
```

每个 Wave 的约束：**一个主要惊喜 + 一个架构增量 + 一个工程指标**。

| Wave | 架构增量 | 用户可见惊喜 | 工程指标 |
|---|---|---|---|
| 0 | Session / Event / Cancellation / Trace | 打断可靠、故障可查 | Interrupt→Audio Stop latency、stale 事件可观测 |
| 1 | SpeechRuntime（Adapter 化）+ TTSTaskManager 接线 | "它反应好快"、"打断立刻闭嘴" | TTFA / TTFT / ASR / TTS / E2E latency |
| 2 | AvatarRuntime + AvatarIntent | "表情跟着回答变"、"它会表演" | Intent→Animation latency |
| 3 | ContextEngine | 回答更"懂上下文"、长对话不崩 | context 占用 / 注入命中率 |
| 4 | Memory Lifecycle | "它居然记得"、"它了解我" | Recall accuracy / Retrieval latency / Consistency |
| 5 | TaskRuntime / Plan / Artifact | "它能帮我做完一件事" | Task / Tool success rate、Recovery rate |
| 6 | Security Runtime | "它做事我放心" | 越界拦截率、审计完整率 |
| 7 | Presence / Background | "它真的住在桌面上" | Intervention quality（打扰率 / 有用率） |
| 8 | Subagent / Skill / Plugin | 能力随插件扩展 | Skill 加载开销、插件健康率 |

**第一轮改造范围**（Wave 0–1，增量而非重构）：

```
SessionRuntime
    ├── Event（AgentEvent 结构化）
    ├── Task（雏形，先只做归属与生命周期）
    └── Cancellation（Session.cancel 统一入口）
Trace（turn/trace id 贯通）
    ↓
AgentLoop（保留不动）
保留、仅 Adapter 接入：VoicePipeline / Memory / ToolRegistry / SystemDaemon / Live2D
```

**最优先的不是 Subagent**，而是：`Session/Event → Context → Task → Sandbox`。

---

## 2. Era 0–5 产品线（长期方向）

```
ERA 0 Alive → ERA 1 Perform → ERA 2 Remember → ERA 3 Relate → ERA 4 Act → ERA 5 Exist
                                   ↑
                          Personal Brain Track（贯穿 Era 2–5）
```

### Era 0 — Alive（它真的活着吗？）

目标：反应迅速、语音自然、存在感明确。

- Surprise 0.1 极速回应：用户说"Yuiro"，它快速"嗯？"而不是沉默两秒；
- Surprise 0.2 打断真的有效：Yuiro 说一半，用户"等等！"→ **立即停止 TTS + Live2D 表演**；
- Surprise 0.3 语音和动作开始同步：`TTS → Lip Sync → Expression → Motion`；
- 架构上只做一件事：建立 **SpeechRuntime**（统一 VAD/ASR/LLM/TTS/Cancellation/Barge-in），
  **不重写 VoicePipeline，先 Adapter 化**；
- 指标：TTFA（Time To First Audio）。

### Era 1 — Perform（它会表演吗？）

```
LLM → Response → Emotion / Intent → Performance → Voice + Live2D
```

- 第一批表演包（不要一次做 100 个动作）：

```
Idle / Happy / Sad / Surprised / Thinking / Embarrassed / Excited / Angry / Sleepy
每个情绪拥有：Expression / Motion / Gaze / Voice style / Timing
```

- **Performance Gallery**（开发工具兼产品能力）：点击 `[Happy] [Sad] [Surprise] ...` 即现场表演；
  同时承担 Demo + Debug + Regression Test + Asset Preview；
- **不要把 LLM 输出绑到具体 Live2D motion**：`surprised → Performance Resolver → 根据当前状态选择动作`，
  换模型/换素材不需要改 Agent；
- 指标：Motion latency。

### Era 2 — Remember（它记得我吗？）

- **Memory MVP 只做一种：Explicit User Memory**（用户明确说"记住我下周要参加算法竞赛"），
  不是把每句话都永久保存；
- **三日记忆测试**（Three Days Memory Test）：

```
Day 1  用户：我下周准备参加算法竞赛。
Day 3  用户：最近压力好大。
Yuiro：是不是因为那个算法竞赛？
```

- 这个 Scenario 的工程价值高于几十个普通 unit test —— 它直接验证 **Yuiro 有没有连续性**；
- 架构：`Conversation → Memory Extraction → Memory Store → Retrieval → ContextEngine → Agent`；
- 指标：Recall accuracy。

### Era 3 — Relate（它了解我吗？）

- 逐渐形成 `L1 Recent Context / L2 Episode Memory / L3 Semantic / Relationship Memory`；
  出现 `User Preference / Habit / Recurring Event / Relationship / Historical Episode`；
- Surprise（偏好）：用户说"我比较喜欢你说话直接一点" → 以后输出"我直接说结论：……"；
- 关键：这是 **Memory → Behavior**，不是 Memory → Retrieval（偏好要影响 Response Style / Decision / Emotion / Interaction）；
- 指标：Consistency（跨会话一致性）。

### Era 4 — Act（它能帮我做事吗？）

- Tool 一次加一个（read_file → search → system），**不要一次加 50 个**；Agent Loop 不与具体工具绑定；
- **TaskRuntime** 从这里成为主角：

```
Task { id, goal, status, steps, context, artifacts, result }
CREATED → PLANNING → RUNNING → VERIFYING → COMPLETED
失败：FAILED → RECOVERING → RUNNING
```

- 三个递进的 Agent Surprise：
  1. "帮我看看今天的开发任务" → Task → Tool → 获取 → 整理 → 回答；
  2. "帮我整理 Yuiro 最近的开发进度" → Git / Changelog / Tests / Memory → Artifact → Summary；
  3. "帮我把这个任务做完" → **Plan → Approval → Execution → Verification**；
- 指标：Task success rate / Tool success rate / Recovery rate。

### Era 5 — Exist（它会主动存在吗？）

- Yuiro 不仅在你说话的时候存在：

```
Presence → Event → Attention Policy → Should interact?
用户离开 20min 回来 → "回来啦。"
Build completed     → "欸，刚刚编译成功了。"
```

- Presence Runtime 持续观察：`User Presence / Application State / Time / Recent Interaction / Current Task / System Events`；
- 必须克制：`Attention Policy + Cooldown + User Preference + Context Awareness + Quiet Hours + Confidence`；
- 输出用 `ProactiveIntent{urgency, interruptibility, channel}`：低 urgency 只抬头 / 气泡，高 urgency 才 TTS；
- 指标：Intervention quality。

---

## 3. Personal Brain Track（贯穿 Era 2–5，独立支线）

> 微调解决"说话风格、行为模式、工具调用习惯"；长期知识与记忆仍由 Memory 承担。
> **Memory ≠ Fine-tuning** 是架构红线。

```
PB-0 Prompt Persona
PB-1 Data Collection
PB-2 Baseline Evaluation
PB-3 0.6B LoRA（流程验证）
PB-4 Qwen3-4B / 8B LoRA
PB-5 Local Mac Inference
PB-6 Continuous Dataset
```

- **不要现在就开始微调**：第一阶段先把 `Prompt + Memory + Performance` 做到极致；
- **PB0 永远先做 Baseline**：先建立 `personality-baseline`（100–300 个固定场景：日常聊天/安慰/吐槽/争论/拒绝/惊讶/工具调用/任务失败/任务成功/长期记忆），
  比较 `Cloud Model + Prompt` 与未来 `Local Model + LoRA`，否则没有实验基线；
- **PB1 让 Yuiro 成为数据工厂**（`Training Data Pipeline`）：

```
Raw → Filter → Curate → Version → Dataset → Train
```

  绝不允许"数据库 → 直接训练"；
- **PB2 工具调用落库**：`ToolCallRecord{timestamp, session_id, tool_name, arguments, result, success, latency, error}`；
  一份数据三个用途：`Dataset / Tool Analytics / Agent Evaluation / Failure Analysis`；
- **PB3 0.6B 流程验证**：重点不是模型效果，而是整个 pipeline 能否跑通（`Dataset → mlx_lm.lora → Adapter → mlx_lm.chat → Baseline Comparison`）；
- **PB4 4B / 8B 正式模型**；**PB5 Windows / Mac 双机**：

```
Windows: Yuiro 全套 Runtime + LLM Provider（OpenAI API over LAN）
Mac:     mlx_lm.server + Qwen3 + LoRA
```

  Yuiro 不应该知道自己连的是云模型还是 Mac 模型，它只知道 `LLM Provider`；
- **Self-improving Personal Brain Loop**：

```
YUIRO Runtime → Interaction Data → Dataset → Evaluation → LoRA → Personal Model → YUIRO
```

  边界：**模型变得更像 Yuiro，不代表模型成为 Yuiro 的全部**。
  真正的 Yuiro = `Model + Memory + Runtime + Embodiment + Experience`。

战略约束（原样保留）：

- Windows 主机作为 Yuiro Runtime；Mac 作为模型训练/推理工坊；
- OpenAI-compatible API；MLX / LoRA / QLoRA；Qwen3 作为首批候选；
- Yuiro 自身产生训练语料；工具调用落库；Prompt baseline；0.6B 流程验证 → 4B/8B；
- 云端 / 本地模型随时切换；**知识与长期记忆不进入权重**。

---

## 4. 版本节奏（建议）

| 版本 | 核心惊喜 | 新架构 | 你负责 | Agent 负责 |
|---|---|---|---|---|
| 0.1 | 回答明显更快 | Voice tracing | 体验评价 | 链路优化 |
| 0.2 | 真正能被打断 | Cancellation | 验收自然度 | 实现取消传播 |
| 0.3 | 表情随回答变化 | Performance Intent | 设计人格表现 | Runtime |
| 0.4 | Yuiro 会表演 | Performance DSL | 动作素材 | 编排系统 |
| 0.5 | 记住一句话 | Memory MVP | 定义记忆 | 实现 |
| 0.6 | 三天后仍然记得 | Recall | Showcase | Scenario |
| 0.7 | 开始理解偏好 | Relationship Memory | 人格定义 | Retrieval |
| 0.8 | 第一次调用工具 | Tool Runtime | 选择工具 | Agent Loop |
| 0.9 | 完成一个任务 | Task Runtime | 设计任务 | Agent/Task |
| 0.10 | 失败后自己恢复 | Recovery | 验收 | Retry/Recovery |
| 0.11 | 主动发现事件 | Presence | 边界/审美 | Event system |
| 0.12 | 主动互动 | Proactive | 行为设计 | Policy |
| PB0–PB4 | 人格基线→0.6B→4B→云/本地切换 | Eval / Dataset / LoRA / Provider | 人格语料/训练标准/选择 | Pipeline/部署 |
| 1.0 | 真正的 Yuiro | Unified Runtime | 最终体验 | 工程实现 |

---

## 5. 产品功能线（Feature Tracks）

> §2 的 Era 是**产品感知的阶段**，§3 的 PB 是**模型工程支线**。
> 本节是第三条轴：**具体功能线** —— 它们横跨多个 Wave/Era，需单独排期与依赖管理。
> 三条线各有独立设计文档，本文只固定**与主路线的关系**（不重复细节）。

| 功能线 | 设计文档 | 主场 Era | 前置 Wave | 与 PB 的关系 |
|---|---|---|---|---|
| **日记 + 画像复描** | `docs/features/diary-feature-design.md` §六 | **Era 3 Relate** | Wave 4 | **PB1 数据工厂的优质语料源** |
| **视觉：多模态聊天** | `docs/features/vision-feature-design.md` | Era 1 / Era 4 | Wave 3 | —— |
| **视觉：认得人** | 同上 §六 | **Era 3 Relate** | Wave 4 + **Wave 6（安全）** | —— |
| **成长系统** | `docs/features/growth-system-design.md` | **Era 3 → Era 5 贯穿** | Wave 4 + Wave 7 | **PB 的"人格演化"产品面** |
| **联网检索** | `docs/features/web-search-design.md` | Era 1 / Era 2 | Wave 3 | 时效性问答的**来源可信度**基础；检索默认不入长期记忆（防画像污染） |

### 5.1 三条关键关系（本节的真正价值）

**① 成长系统 = Personal Brain Track 的产品语义**

§3 的 PB-0→PB-6 是**工程路径**（Prompt → Data → LoRA → Personal Model）；
成长系统是它在**产品上的读法** —— 用户看到的不是"换了个 adapter"，
而是"**她长大了**"。

```
PB-0 Prompt Persona   ←→  成长阶段 A：prompt / instruct 参数化
PB-1 Data Collection  ←→  成长的燃料（互动数据、共同经历）
PB-3 0.6B LoRA        ←→  成长阶段 C 的流程验证（先用小模型跑通"分阶段"）
PB-4 4B/8B LoRA       ←→  成长阶段 C 的正式形态
```

**★ 推论（重要）**：**成长系统的阶段划分应当复用 PB 的模型阶段**，而非另定一套 ——
否则会出现"产品说她长大了、但模型没变"的割裂。**一个 stage，一个模型，一套提示词。**

**② 日记是 PB1 最干净的语料源**

PB1 强调 `Raw → Filter → Curate`、绝不允许"数据库直接训练"。
日记的独特价值：**用户自述、有意识写下、且经用户授权** ——
信噪比远高于对话流水（后者充斥寒暄、重试、工具噪声）。

**★ 但必须守住边界**：日记可用于**画像与记忆**，能否用于**训练**需**单独授权**。
两者隐私语义不同 —— **进记忆是"她记得"，进训练是"她变成"**。**默认不用于训练。**

**③ 视觉的两半，优先级差一整档**

多模态聊天（用户主动发图）与认得人（摄像头）**不是同一个功能**：
前者失败只是"答不好"，后者失败是"**认错人 / 泄露隐私**"。
因此 **多模态聊天可进 v1，认得人必须等到 Wave 6（Security Runtime）之后**，
且必须满足三条硬约束：**opt-in + 仅存特征向量 + 一键关闭**。

### 5.2 推进方式：**依赖就绪 + 体验驱动**（不是版本排期）

> ⚠ **本节曾经是一张"按版本号线性排期"的表**（0.7 → 0.7.5 → 0.8 → …）。
> 那张表与项目**已经确立的治理规则冲突**，已删除：
>
> - **实际版本节奏已走完 v1.0**（见 `docs/plan/V1-acceptance.md`），
>   用它去推算"现在该在 0.7 还是 0.8"没有意义；
> - **v1.0 之后的工作方式是「只有真实体验反馈才触发新 Sprint」**
>   （`V1-acceptance.md` §9）。而版本排期表属于"对齐 spec 清单"式的推进 ——
>   正是那条规则明确排除的做法。
>
> **结论：功能线的启动时机由体验反馈决定，不由本表决定。**

本表只回答两件事：**前置条件是否就绪**、**内部先后依赖是什么**。

| 功能线 | 前置条件 | 就绪？ | 内部先后 |
|---|---|---|---|
| **日记 v1** | Wave 4 Memory Lifecycle | ✅ | 先于画像复描（画像需要日记攒数据） |
| **画像复描 v1.5** | 日记 v1 + 数据积累 | ⏳ | 必须在日记 v1 之后 |
| **视觉 v1：多模态聊天** | Wave 3 Context | ✅ | 与日记互不依赖，可任意先后 |
| **成长 v1（prompt / instruct 参数化）** | 无（纯配置） | ✅ | 独立；但**声线与 persona 必须同源切换** |
| **认得人 v1.5** | Wave 4 + **Wave 6 Security** | ✅ | **必须晚于 Security**（隐私风险等级最高） |
| **成长 v2（LoRA 分阶段）** | **PB-3 流程跑通** | ❌ | 依赖 PB；且 stage 应与 PB 阶段同源 |

**★ 三条硬约束**（与体验反馈无关，不可协商）：

1. **认得人必须排在 Wave 6（Security）之后** —— 这不是"体验问题"而是隐私红线；
2. **成长 v2 依赖 PB-3** —— 没有 PB 的模型阶段，产品上的"长大"只能停留在提示词层面；
3. **三条线都不排在 Wave 0–3 之前** —— 它们全都吃 ContextEngine /
   Memory Lifecycle 的成熟度（这三个前提**现在都已满足**）。

**★ 三条线当前状态（2026-09-17）**：

```
前置条件：  全部就绪（Wave 0–7 完成、Era 0–5 可达、PB-0 完成）
实现进度：  0%（仅有设计文档）
启动条件：  真实体验反馈（V1-acceptance.md 的清单）
```

**读法**：**现在不是"排到了第几步"，而是"随时可启动、但按规则要等反馈"。**

### 5.3 三条线与 S47 排序优化的呼应

画像、`【我是谁】`（自我叙事）、persona **都属于"变化极慢"的内容** →
放进 ContextEngine 的**稳定前缀区**（可缓存）。

**这不是巧合**：**低频变化的知识天然适合进缓存前缀**，
所以这三条功能线**不会伤害** S47 拿到的前缀缓存收益 ——
设计时就该把"注入位置"当作功能设计的一部分，而不是实现时再补。

---

## 5. Sprint 机制

### 5.1 节奏（两周一个小循环）

```
选择 Surprise → 写 Scenario + DoD → Coding Agent（Code + Tests）
    → Human Review → Accept / Iterate → Release → 新惊喜
```

每个循环只允许：**一个主要惊喜 + 一个架构增量 + 一个工程指标**（降低失控概率）。

### 5.2 Sprint 模板（每次任务固定填写）

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT XX
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:
SURPRISE:            （用户会看到什么惊喜）
USER EXPERIENCE:     （可观察行为，越具体越好）
ARCHITECTURE:        （本次允许新增的最小架构增量）
FILES:               （预计改动的文件）
CODING AGENT:        （任务指令 / 约束）
TEST:                （Unit + Scenario）
PERFORMANCE:         （before/after 指标）
DEFINITION OF DONE:  （什么条件下才能结束）
HUMAN ACCEPTANCE:    （需要人亲自验收什么）
CUSTOM ASSET:        （需要人提供的自定义产物）
NEXT UNLOCK:         （本次为下一次解锁什么能力）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

`NEXT UNLOCK` 很重要：每个 Sprint 都应为下一个 Sprint 解锁能力。

### 5.3 惊喜清单（产品动力源）

| 编号 | 惊喜 | 对应 Wave |
|---|---|---|
| S001 | 第一次正确记住用户三天前说过的事情 | Wave 4 |
| S002 | 用户突然打断，Yuiro 立即闭嘴并停止动作 | Wave 0–1 |
| S003 | 用户说"我成功了"，Yuiro 自动庆祝 | Wave 2 |
| S004 | 用户长时间工作，Yuiro 主动提醒休息 | Wave 7 |
| S005 | 用户回来时，Yuiro 主动说"回来啦" | Wave 7 |
| S006 | Yuiro 自己完成一个 Task | Wave 5 |
| S007 | Yuiro 在不看完整历史的情况下恢复长期任务 | Wave 5 |
| S008 | 本地微调后的 Yuiro 一句话就能体现独特人格 | PB4 |

### 5.4 UI 随能力同步演进

```
Era 0  简洁聊天面板
Era 1  Avatar + Chat + Emotion feedback
Era 2  Memory indicator（🧠"记住了"）
Era 4  Task panel（☑ 获取 Git 状态 / ☑ 分析最近提交 / ⏳ 生成总结）
Era 5  Agent Dashboard（Current Task / Memory / Activity / Tools / Mood / Presence）
```

UI 不独立做，每次都有理由升级。

---

## 6. 与 M0–M6 的关系（历史里程碑 → 新主线）

| 旧里程碑 | 状态 | 新主线定位 |
|---|---|---|
| M0 架构骨架 | 已完成 | 前置条件 |
| M1 可运行骨架 | 已完成 | Era 0 的文本链路基础（Wave 0 需补 Session/Event） |
| M2 声控 | 已完成 | Era 0 基础（VAD/ASR/TTS 已有；**Barge-in 未达标**，属 Wave 1） |
| M3 记忆 | 已完成 | Era 2 的 retrieval 基础（**Lifecycle 缺失**，属 Wave 4） |
| M4 AI 动手 | 已完成 | Era 4 的 Tool/SystemDaemon 基础（**Session/Task/Cancellation 缺失**，属 Wave 0/5） |
| M5 情感/主动/养成 | 轻量实现 | 情感 → Era 1/Wave 2；主动 → Era 5/Wave 7 |
| M6 打磨 + 研究 | 未完成 | 被吸收进各 Wave 的 Showcase Test 与发布节奏 |

其余细节（M0–M6 原始记录）保留在 `docs/init/milestones.md`。

---

## 7. 当前基线差距（2026-09 审计，摘要）

完整五维表见 [runtime-contract.md](runtime-contract.md) §13。核心结论：

> **五个维度目前是"局部有实现、全局无契约"**——
> Generation 与 Cancellation 各有 2–3 个互不相识的本地点实现，Session 只是散落的 `dict[str, …]` 键，
> Lifecycle 只有 FastAPI lifespan + VoicePipeline 状态机，Trace 只有 C++ daemon 的 `trace_id` 透传。

六处"已写好但未接线"的现成骨架（可直接作为改造落点，勿重复造）：

```
ServiceContext · TTSTaskManager · TranscriptBuffer
response_categorizer · skill/ · plugins/
```

---

## 8. 建议 Sprint 序列（前六步，供 Human 决策）

| # | Sprint | Surprise / 体验 | 架构增量 | 指标 |
|---|---|---|---|---|
| S01 | Voice Latency Observatory | 先"看清"链路：每次语音交互有完整阶段耗时 | Trace 基线（turn id + 阶段时间戳），**不改行为** | TTFA / TTFT / ASR / TTS / E2E |
| S02 | Session & Generation 统一 | 文字与语音属于同一个"我"，断线不失忆 | SessionManager + AgentSession + 显式 invalidate + Event Log 雏形 | stale 事件可观测；session 归属正确率 |
| S03 | 真 Barge-in | 用户"等等！"→ 立即闭嘴且**后台也停** | Session.cancel 全链路传播 + TTSTaskManager 接线 + `tts:interrupted` 回执 | Interrupt→Audio Stop latency |
| S04 | AvatarIntent 通道 | 表情/动作随回答变化，且不互相打架 | AvatarRuntime + AvatarIntent + 优先级 + Emotion 联动 | Intent→Animation latency |
| S05 | Explicit Memory MVP | "记住我下周要参加算法竞赛" | Memory Extraction + 写入按 generation 保护 + Memory→Behavior 雏形 | 显式记忆召回率 |
| S06 | 三日记忆 Showcase | Day1 说、Day3 被记得 | Recall Scenario + Replay 基建 + UI memory indicator | 三日召回；Showcase 通过率 |

规则：S01 只做观测（"先 instrument，再优化"）；S02 必须先行于 S03；S06 是验证 Memory 架构是否值得继续投入的"卧槽时刻"。

---

## 9. 人负责的自定义资产（Coding Agent 无法替代）

```
assets/
  personality/    Yuiro 的口头禅 / 表情偏好 / 互动方式 / 人格
  performances/   特殊动画 / 特殊场景
  memories/       私人记忆
  scenarios/      场景剧本（memory / voice / agent / avatar / showcase）
  prompts/        人格与提示词
  evaluation/     人格评估集（personality-baseline）
  easter-eggs/    彩蛋
```

这些是仓库中的**正式资产**，与代码同样对待。
