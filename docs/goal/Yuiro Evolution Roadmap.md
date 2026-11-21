可以，而且我认为**附件里的“本地模型微调 + 人格定制”不应该作为路线末端的一个孤立实验，而应该被重新定位成 Yuiro 演进过程中的一条长期支线**。

尤其是你附件里有一个判断非常关键：

> **微调解决“说话风格、行为模式、工具调用习惯”，而长期知识与记忆仍由 Memory 系统承担。** llm-finetune-mac-persona.mdMD

这恰好可以和我们前面讨论的 Agent Harness 演进路线拼起来。

下面我先把整个战略重新定型。后续如果继续推进，我建议就以这一版作为 **Yuiro 的长期总航标**。

------

# Yuiro Evolution Roadmap

## 一、先确定：你不是“一个人开发 Yuiro”

你描述的人机协同方式其实非常适合这个项目：

```
                         YUIRO DEVELOPMENT
                                │
                ┌───────────────┴───────────────┐
                │                               │
             Human                         Coding Agent
                │                               │
       战略 / 审美 / 判断                  编码 / 重构 / 测试
       体验 / 创意 / 验收                  调试 / 实现 / 文档
       自定义人格 / 内容                  自动化 / 工程化
                │                               │
                └───────────────┬───────────────┘
                                │
                         Shared Roadmap
                                │
                     Scenario + Metrics
                                │
                         Git / Tests
```

这里最重要的一点是：

## **Coding Agent 不是“代码生成器”，而是 Yuiro 的主要工程执行者。**

而你承担的是：

> **Product Owner + Architect + Creative Director + Technical Reviewer**

你不需要亲自实现每个接口。

你真正应该把时间放在：

- 下一阶段做什么
- 什么东西值得做
- 哪种行为才像你想要的 Yuiro
- 哪些架构值得保留
- 哪些实现应该推翻
- 哪些测试真正证明“变好了”
- 人格、表演、记忆、UI等自定义内容

这会比你亲自敲几千行代码更有价值。

------

# 二、所以以后不要给 Coding Agent 一个“大重构任务”

例如不要：

> “把 Yuiro 重构成现代 Agent Harness。”

这是非常危险的 Prompt。

应该变成：

> **“实现 Surprise #03：让 Yuiro 在 3 天后记住用户曾经主动告诉它的一件事情。”**

然后再告诉 Coding Agent：

```
为了实现这个体验，可以逐步引入 Memory Runtime，
但禁止大规模重构现有 AgentLoop。
```

这样 Coding Agent 会被**产品目标牵引架构**。

而不是被架构牵引产品。

------

# 三、Yuiro 的六个时代

我建议暂时不要给它定 20 个版本。

先定六个时代。

```
                    YUIRO EVOLUTION
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
     Era 0               Era 1               Era 2
    Alive               Perform              Remember
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
     Era 3               Era 4               Era 5
    Relate               Act                 Exist
       │                   │                   │
       └───────────────────┴───────────────────┘
                           │
                    YUIRO COMPANION
```

对应：

| Era  | 核心问题         | Yuiro 获得的能力                  |
| ---- | ---------------- | --------------------------------- |
| 0    | 它真的活着吗？   | 实时语音、低延迟、自然反馈        |
| 1    | 它会表演吗？     | Live2D、情绪、动作、表演          |
| 2    | 它记得我吗？     | 长期记忆                          |
| 3    | 它了解我吗？     | 关系 / 偏好 / 连续人格            |
| 4    | 它能帮我做事吗？ | Agent / Tool / Task               |
| 5    | 它会主动存在吗？ | Presence / Proactive / Background |

而**本地模型微调**不放进任何一个时代里。

它是一条贯穿 Era 2～5 的：

# `Personal Brain Track`

------

# 四、Era 0：Alive

## 目标

先把 Yuiro 做成：

> **反应迅速、语音自然、存在感明确的桌宠。**

这一阶段不搞大规模 Runtime。

------

## 第一批可感知成果

### Surprise 0.1：极速回应

用户说：

> “Yuiro。”

Yuiro 快速：

> “嗯？”

而不是沉默两秒。

------

### Surprise 0.2：打断真的有效

Yuiro：

> “然后我觉得——”

用户：

> “等等！”

Yuiro：

**立即停止 TTS + Live2D 表演。**

这会是一个非常强的体验提升。

------

### Surprise 0.3：语音和动作开始同步

说话：

```
TTS
 ↓
Lip Sync
 ↓
Expression
 ↓
Motion
```

------

## 架构上只做一件事

建立：

```
SpeechRuntime
```

它统一：

```
VAD
ASR
LLM
TTS
Cancellation
Barge-in
```

但**不重写现有 VoicePipeline**。

先 Adapter 化。

------

## Coding Agent Prompt

以后可以直接这样下：

```
[YUIRO TASK]

Goal:
Reduce perceived voice interaction latency.

User-visible scenario:
When the user finishes speaking, Yuiro should begin responding
as quickly as possible, and barge-in should stop the current speech
without stale audio/avatar actions continuing.

Constraints:
- Do not rewrite VoicePipeline.
- Preserve current provider interfaces.
- First instrument the existing pipeline.
- Every optimization must have before/after measurements.

Tasks:
1. Trace VAD → ASR → LLM → TTS → Avatar.
2. Add latency instrumentation.
3. Identify the dominant bottleneck.
4. Optimize only the bottleneck.
5. Add regression tests for cancellation.
6. Report before/after metrics.

Definition of Done:
- Tests pass.
- No stale TTS after interruption.
- No stale Avatar motion after cancellation.
- Latency metrics are recorded.
- Existing behavior remains compatible.
```

这就是以后 Coding Agent 的工作方式。

------

# 五、Era 1：Perform

这个阶段我认为可以成为你最快乐的一段开发期。

因为**视觉反馈极强**。

------

## 建立 Yuiro Performance System

从：

```
LLM
 ↓
text
```

变成：

```
LLM
 ↓
Response
 ↓
Emotion / Intent
 ↓
Performance
 ↓
Voice + Live2D
```

例如：

```
happy
  ↓
Smile
  ↓
Eye expression
  ↓
Small bounce
  ↓
Happy voice
```

------

## 第一批表演包

不要一次做 100 个动作。

先做：

```
Idle
Happy
Sad
Surprised
Thinking
Embarrassed
Excited
Angry
Sleepy
```

每个情绪拥有：

```
Expression
Motion
Gaze
Voice style
Timing
```

然后做一个：

# `Performance Gallery`

可以让你直接点击：

```
[Happy] [Sad] [Surprise]
[Thinking] [Embarrassed]
[Excited] [Sleepy]
```

Yuiro现场表演。

这本身就是一个非常好的开发测试工具。

------

# 六、Era 2：Remember

这是整个项目第一次真正的：

# “卧槽时刻”

做一个：

### `Three Days Memory Test`

Day 1：

> 我下周准备参加算法竞赛。

Day 3：

> 最近压力好大。

Yuiro：

> “是不是因为那个算法竞赛？”

如果这个测试真的跑通，你会非常清楚：

> **Memory Architecture 值得继续投入。**

------

## 架构

这时候再逐步形成：

```
Conversation
      ↓
Memory Extraction
      ↓
Memory Store
      ↓
Retrieval
      ↓
ContextEngine
      ↓
Agent
```

这时候你附件里的设计开始进入主线。

------

# 七、Era 3：Relate

这里是附件思想和 Agent Architecture 真正融合的地方。

你附件里强调：

> 不应该把知识和长期记忆塞进模型权重。 llm-finetune-mac-persona.mdMD

完全保留。

所以：

```
                Yuiro Brain
                    │
        ┌───────────┴───────────┐
        │                       │
   Runtime Memory          Model Personality
        │                       │
  facts / episodes        style / behavior
  preferences             reactions
  relationship            tool habits
        │                       │
     Database                 LoRA
```

这是非常漂亮的分工。

------

# 八、这里正式开启你的“Personal Brain Track”

附件提出的路线可以变成：

```
PB-0
Prompt Persona
      ↓
PB-1
Data Collection
      ↓
PB-2
Baseline Evaluation
      ↓
PB-3
0.6B LoRA Pipeline
      ↓
PB-4
Qwen3-4B/8B LoRA
      ↓
PB-5
Local Mac Inference
      ↓
PB-6
Continuous Dataset
```

而不是：

> 做完 Agent → 最后再微调。

------

# 九、特别重要：不要现在就开始微调

附件其实已经给出了很好的判断：

> 微调只解决 prompt 不擅长的东西。 llm-finetune-mac-persona.mdMD

因此第一阶段：

```
Prompt
+
Memory
+
Performance
```

先做到极致。

建立：

# Personality Baseline

例如 100 个固定问题：

```
普通聊天
吐槽
安慰
调侃
拒绝
知识问答
工具调用
异常情况
连续对话
```

然后记录：

```
Personality Score
Consistency
Tool Success
Response Style
```

之后 LoRA 才有意义。

否则你根本不知道：

> 微调到底有没有让 Yuiro 变好。

------

# 十、Era 4：Act

这时候才开始大规模进入 Agent Harness。

逐渐加入：

```
Session
Event
Intent
Task
Tool
Artifact
Capability
```

但还是**一个能力一个能力地加**。

------

## 第一个 Agent Surprise

> “帮我看看今天的开发任务。”

Yuiro：

```
Task
 ↓
Tool
 ↓
获取信息
 ↓
整理
 ↓
回答
```

------

## 第二个

> “帮我整理 Yuiro 最近的开发进度。”

```
Task
 ├── Git
 ├── Changelog
 ├── Tests
 └── Memory
       ↓
   Artifact
       ↓
    Summary
```

------

## 第三个

> “帮我把这个任务做完。”

这时候才需要：

```
Plan
 ↓
Approval
 ↓
Execution
 ↓
Verification
```

------

# 十一、Era 5：Exist

这是终极阶段。

Yuiro 开始：

> **不仅在你说话的时候存在。**

而是：

```
Presence
    ↓
Event
    ↓
Attention Policy
    ↓
Should interact?
```

例如：

```
用户离开电脑
       ↓
20 min
       ↓
用户回来
       ↓
Yuiro：
“回来啦。”
```

或者：

```
Build completed
      ↓
Yuiro：
“欸，刚刚编译成功了。”
```

这时候：

> **桌宠才真正成为桌面上的 Agent。**

------

# 十二、然后 UI 也不要独立做

UI 应该跟能力成长同步。

------

## UI Evolution

### Era 0

```
简洁聊天面板
```

↓

### Era 1

```
Avatar
+
Chat
+
Emotion feedback
```

↓

### Era 2

```
Memory indicator
```

例如：

> 🧠 “记住了”

↓

### Era 4

```
Task panel
```

例如：

```
Yuiro 正在处理：

☑ 获取 Git 状态
☑ 分析最近提交
⏳ 生成总结
```

↓

### Era 5

```
Agent Dashboard
```

可以看到：

```
Current Task
Memory
Activity
Tools
Mood
Presence
```

这样 UI 每次都有理由升级。

------

# 十三、建立真正属于 Coding Agent 的“开发协议”

这是我认为你整个项目最值得建立的东西之一。

以后不要每次：

> “帮我改一下 Yuiro。”

而应该建立：

# `YUIRO_DEV_PROTOCOL.md`

Coding Agent 每次工作都遵循：

```
1. Understand
2. Inspect
3. Plan
4. Implement
5. Test
6. Measure
7. Review
8. Report
```

------

## 每个任务固定五个东西

### ① Goal

我要什么。

### ② Scenario

用户最终看到什么。

### ③ Architecture Increment

这次允许新增什么架构能力。

### ④ Tests

如何证明真的完成。

### ⑤ Definition of Done

什么条件下才能结束。

------

# 十四、你作为 Human 应该控制什么？

你**不要成为代码审查流水线上的瓶颈**。

你主要控制：

### Strategic

> 下一阶段值得做什么？

### Creative

> Yuiro 应该表现成什么样？

### Architectural

> 这个抽象值得留下吗？

### Acceptance

> 这个功能真的有“感觉”吗？

### Personalization

这是 Coding Agent 无法替代你的：

```
Yuiro 的口头禅
Yuiro 的表情偏好
Yuiro 的互动方式
Yuiro 的人格
特殊动画
特殊场景
私人记忆
彩蛋
```

这些就是你的：

# Custom Assets

它们甚至应该成为仓库中的正式资产。

例如：

```
assets/
  personality/
  performances/
  memories/
  scenarios/
  prompts/
  evaluation/
  easter-eggs/
```

------

# 十五、我甚至建议你建立一个“惊喜清单”

例如：

```
YUIRO_SURPRISES.md
```

------

### S001

> 第一次正确记住用户三天前说过的事情。

### S002

> 用户突然打断，Yuiro 立即闭嘴并停止动作。

### S003

> 用户说“我成功了”，Yuiro 自动庆祝。

### S004

> 用户长时间工作，Yuiro主动提醒休息。

### S005

> 用户回来时，Yuiro 主动说“回来啦”。

### S006

> Yuiro 自己完成一个 Task。

### S007

> Yuiro 在不看完整历史的情况下恢复长期任务。

### S008

> 本地微调后的 Yuiro 一句话就能体现独特人格。

这张表会成为：

> **你的产品动力源。**

------

# 十六、测试体系最终也分成三层

```
                    YUIRO TESTING
                         │
          ┌──────────────┼──────────────┐
          │              │              │
       Unit Test      Scenario Test   Showcase Test
          │              │              │
       工程正确        行为正确        真的惊艳
```

------

## Unit

```
Memory retrieval
Tool parser
Cancellation
Event dispatch
```

------

## Scenario

```
Barge-in
Memory recall
Tool failure
Task recovery
```

------

## Showcase

这才是最有意思的：

```
Three Days Later
```

自动运行整个故事。

如果：

> Day 1：告诉 Yuiro 一件事情

三天后：

> Day 3：重新询问

然后 UI 自动展示：

```
🧠 Memory Showcase

Expected:
Yuiro remembers X

Actual:
Yuiro remembered X ✓
```

这就是你说的：

> **“更智能和令人眼前一亮的测试惊喜。”**

我非常建议做。

------

# 十七、整个项目的开发节奏，我建议固定成“两周一个小循环”

不是严格要求两周，而是建立节奏感。

```
Week N

        Human
          │
          ▼
   选择一个 Surprise
          │
          ▼
   写 Scenario + DoD
          │
          ▼
     Coding Agent
          │
     ┌────┴────┐
     │         │
   Code      Tests
     │         │
     └────┬────┘
          ▼
      Human Review
          │
     ┌────┴─────┐
     │          │
  Accept      Iterate
     │
     ▼
  Release
     │
     ▼
  新惊喜
```

每个循环只允许：

> **一个主要惊喜 + 一个架构增量 + 一个工程指标。**

这会极大降低失控概率。

------

# 十八、最终路线其实可以浓缩成这张表

| 阶段           | 惊喜                   | 架构                | 测试                   | 指标                 |
| -------------- | ---------------------- | ------------------- | ---------------------- | -------------------- |
| **0 Alive**    | “它反应好快”           | Speech Runtime      | Barge-in               | TTFA                 |
| **1 Perform**  | “它真的会表演”         | Performance Runtime | Emotion scenarios      | Motion latency       |
| **2 Remember** | “它居然记得”           | Memory Runtime      | 3-day memory           | Recall               |
| **3 Relate**   | “它真的了解我”         | Relationship Memory | Longitudinal scenarios | Consistency          |
| **4 Act**      | “它能帮我做事”         | Agent/Tool/Task     | Tool replay            | Success rate         |
| **5 Exist**    | “它真的住在我的桌面上” | Presence/Proactive  | Autonomous scenarios   | Intervention quality |
| **PB**         | “这就是我的 Yuiro”     | LoRA/Personal Brain | Personality benchmark  | Style consistency    |
| **UX**         | “越来越漂亮、自然”     | Experience Layer    | Visual regression      | Interaction quality  |

------

# 十九、而附件在整个战略中的最终位置

我会把你附件从：

> “一个以后可能做的微调方案”

提升成：

# `Yuiro Personal Brain Program`

它和主架构并行：

```
                  YUIRO
                    │
        ┌───────────┴───────────┐
        │                       │
  Agent Evolution         Personal Brain
        │                       │
 Session / Task             Dataset
 Memory / Tool              Baseline
 Context / Skill            LoRA
 Performance               Local Model
        │                       │
        └───────────┬───────────┘
                    │
              Unified Yuiro
```

而且附件中的这几个设计我建议**原样保留为战略约束**：

- Windows 主机作为 Yuiro Runtime
- Mac 作为模型训练/推理工坊
- OpenAI-compatible API
- MLX / LoRA / QLoRA
- Qwen3 作为首批候选
- Yuiro 自身产生训练语料
- 工具调用落库
- Prompt baseline
- 0.6B 流程验证
- 再到 4B/8B
- 云端 / 本地模型随时切换
- **知识和长期记忆不进入权重** llm-finetune-mac-persona.mdMD

尤其最后一点，我会把它提升成 Yuiro 的核心架构原则：

> **Weight defines how Yuiro behaves. Memory defines what Yuiro knows. Runtime defines what Yuiro can do.**

也就是：

```
                 Yuiro Intelligence
                         │
          ┌──────────────┼──────────────┐
          │              │              │
        Model          Memory         Runtime
          │              │              │
       性格/反应        经历/关系       能力/行动
          │              │              │
        LoRA          Memory DB       Agent
```

我认为这会成为你整个项目非常漂亮的一条主线。

------

# 二十、最后真正要锚定的不是 v1.0，而是这个方向

你现在完全不需要想着：

> “什么时候把完整 Runtime 做完？”

甚至不要想着：

> “什么时候架构达到完美？”

真正应该每天问的是：

> **“下一步让 Yuiro 多获得一种什么样的生命感？”**

然后让 Coding Agent 去回答：

> “为了让它获得这种能力，最小的架构增量是什么？”

于是最终会自然形成：

```
        惊喜
         ↓
       场景
         ↓
    Coding Agent
         ↓
      最小实现
         ↓
       自动测试
         ↓
      性能测量
         ↓
     架构沉淀
         ↓
       新能力
         ↓
        惊喜
         ↺
```

**这才是我认为最适合 Yuiro 的长期研发模式。**

而且你现在已经有一个非常好的起点：**现有 Yuiro 不需要被推倒重来，附件的 Personal Brain 又可以作为一条独立但逐渐汇入主干的支线。**

如果要继续往“真正可以拿去给 Cursor / Codex / Claude Code 使用”的层面走，下一份文档我建议直接做成 **《YUIRO MASTER ROADMAP + CODING AGENT PROTOCOL》**：不是普通产品规划，而是把 **Era 0～5 拆成约 15～20 个具体 Sprint，每个 Sprint 给出可直接复制给 Coding Agent 的 Prompt、允许修改的范围、测试场景、性能门槛、Git/提交策略、人工验收点，以及你应该亲自设计的“Yuiro 自定义产物”清单**。这会真正成为你后面数月乃至更长时间开发时的“总航标”。

继续。上一版解决的是“**战略方向**”，这一版我直接把它落成一套可以长期执行的 **《Yuiro Master Roadmap + Coding Agent Protocol》**。

核心思想先不变：

> **不做一次性“大重构”，而是让 Yuiro 在一个个可感知的产品惊喜中，逐渐长出 Runtime、Memory、Agent、Performance 和 Personal Brain。**

同时，把你附件中的本地模型微调路线正式纳入主路线，但作为**独立的 Personal Brain Track**，而不是让微调绑架主工程。附件明确把 `engine/yuiro/agent/`、`engine/yuiro/memory/`、`engine/yuiro/config.py` 作为未来接入点，并提出“Prompt baseline → 0.6B 流程验证 → 4B/8B 微调 → 稳定部署”的渐进路线。llm-finetune-mac-persona.mdMD

------

# 一、Yuiro 最终要建设的，不是“一个 Agent”

我建议把最终产品定义成：

# **Embodied Personal Agent**

即：

```
                         YUIRO
                           │
             ┌─────────────┴─────────────┐
             │                           │
       Intelligence                 Embodiment
             │                           │
       Agent / Memory              Voice / Live2D
       Task / Tools                Emotion / Motion
       Planning                    Performance
             │                           │
             └─────────────┬─────────────┘
                           │
                     Yuiro Runtime
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
    Session             Event               State
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                 Capability Runtime
                           │
          ┌────────────────┼────────────────┐
          │                │                │
        Tools           Skills           Plugins
          │                │                │
          └────────────────┼────────────────┘
                           │
                  Personal Brain
                           │
              ┌────────────┴────────────┐
              │                         │
           Memory                     Model
              │                         │
        What I know              How I behave
```

最终形成三个非常清晰的职责：

> **Model = 我是什么样的人**
> **Memory = 我经历过什么**
> **Runtime = 我现在能做什么**

而 Live2D + Voice 则负责：

> **我如何把自己表现出来。**

这四者是 Yuiro 最终的核心。

------

# 二、整个开发周期，我建议固定为 5 层

以后任何 Coding Agent 任务都不要直接从“改代码”开始。

固定：

```
L1 Product Scenario
        ↓
L2 Observable Behavior
        ↓
L3 Architecture Increment
        ↓
L4 Implementation
        ↓
L5 Verification
```

例如：

### ❌ 错误任务

> 重构 Memory 系统。

### ✅ Yuiro 任务

> 实现“Yuiro 能在三天后回忆起用户主动告诉它的事情”。

然后：

```
Scenario
  ↓
Memory Recall
  ↓
Memory Runtime
  ↓
具体代码
  ↓
三日记忆测试
```

这会极大改变 Coding Agent 的工作质量。

------

# 三、Phase 0：建立工程地基

## 目标

这一阶段**不追求新能力**。

只做一件事：

> **让 Coding Agent 能安全地持续改 Yuiro。**

------

## 0.1 建立 Architecture Map

让 Coding Agent 先梳理：

```
engine/
├── agent/
├── memory/
├── voice/
├── avatar/
├── config/
└── ...
```

并建立：

```
docs/
  architecture/
    overview.md
    runtime.md
    voice.md
    agent.md
    memory.md
    avatar.md
```

这里不要追求完美。

目标是：

> **Coding Agent 下一次进入项目，可以先理解再动手。**

------

# 四、0.2 建立 Architecture Rules

这是以后非常重要的东西。

例如：

```
ARCHITECTURE_RULES.md
```

规定：

### Rule 1

业务代码不得直接依赖具体 LLM Provider。

```
Agent
 ↓
LLM Interface
 ↓
Provider
```

而不是：

```
Agent
 ↓
OpenAIProvider
```

------

### Rule 2

业务代码不得直接控制 Live2D。

```
Agent
 ↓
Performance Intent
 ↓
Avatar Runtime
 ↓
Live2D
```

------

### Rule 3

取消必须具有传播语义：

```
Task Cancel
 ↓
Agent Cancel
 ↓
LLM Cancel
 ↓
TTS Cancel
 ↓
Avatar Cancel
```

------

### Rule 4

Memory 是独立能力。

Agent 可以使用 Memory：

```
Agent
 ↓
Memory
```

但不能把 Memory 逻辑散落在 AgentLoop 里面。

------

# 五、0.3 给 Coding Agent 加“刹车”

这一点非常重要。

以后所有 Coding Agent Prompt 都加入：

```
Before modifying code:

1. Inspect the existing implementation.
2. Identify the smallest safe change.
3. Do not introduce abstractions without a concrete use case.
4. Do not rewrite working subsystems unless explicitly requested.
5. Preserve backward compatibility whenever practical.
6. Run relevant tests before and after modification.
7. Report architectural impact.
```

尤其：

> **Do not rewrite working subsystems unless explicitly requested.**

这是防止 Coding Agent 把项目越写越大的关键。

------

# 六、Phase 1：Alive —— 让它“活起来”

这是第一个真正产品版本。

------

## S1：Voice Latency Observatory

建立：

```
VAD
 ↓
ASR
 ↓
LLM TTFT
 ↓
TTS TTFA
 ↓
Playback
```

全链路 tracing。

记录：

```
speech_start
speech_end
vad_confirmed
asr_partial
asr_final
llm_start
llm_first_token
tts_start
tts_first_audio
playback_start
```

------

## KPI

以后每次修改都看：

```
TTFA
TTFT
ASR latency
TTS latency
E2E latency
```

不要再靠感觉。

------

# 七、S2：真正的 Barge-in

这是非常值得优先做的功能。

场景：

```
Yuiro：
“其实我觉得这个问题可以——”

用户：
“等一下！”

立即：

​```text
VAD
 ↓
Interrupt Event
 ↓
Cancel Response
 ↓
Cancel TTS
 ↓
Stop Playback
 ↓
Stop Avatar Performance
 ↓
New Input
```

------

## 验收

不能出现：

> 用户已经打断了，Yuiro 还继续说半句话。

也不能出现：

> 声音停了，但 Live2D 还继续做上一句话的动作。

这要求建立真正的：

# Cancellation Propagation

------

# 八、Phase 2：Perform —— Yuiro 开始“表演”

这是第二个大跃迁。

------

## S3：Performance Intent

LLM 输出逐渐从：

```
{
  "text": "真的吗？"
}
```

变成：

```
{
  "text": "真的吗？",
  "emotion": "surprised",
  "intensity": 0.8,
  "performance": "surprise"
}
```

注意：

> **不要一开始要求 LLM 精确控制 Live2D 参数。**

它只表达意图。

真正执行：

```
Performance Runtime
```

------

# 九、S4：建立 Performance DSL

例如：

```
Performance
 ├── expression
 ├── motion
 ├── gaze
 ├── voice
 ├── timing
 └── priority
```

这样：

```
surprised
```

并不意味着某一个具体 Live2D motion。

而意味着：

```
surprised
 ↓
Performance Resolver
 ↓
根据当前状态选择动作
```

以后换模型、换 Live2D、换素材都不需要修改 Agent。

这就是一个非常值得保留的抽象。

------

# 十、S5：Performance Gallery

开发期间建立一个开发工具：

```
[Happy]
[Angry]
[Sad]
[Surprised]
[Thinking]
[Embarrassed]
[Excited]
[Sleepy]
```

点击即可表演。

它同时承担：

```
Demo
+
Debug
+
Regression Test
+
Asset Preview
```

这就是典型的：

> **开发工具同时成为产品能力。**

------

# 十一、Phase 3：Remember —— 第一个“卧槽时刻”

## S6：Memory MVP

只做一种：

# Explicit User Memory

用户明确说：

> “记住我下周要参加算法竞赛。”

系统：

```
Memory Extractor
 ↓
Candidate
 ↓
Persist
```

而不是把每句话都永久保存。

------

# 十二、S7：三日记忆测试

建立自动 Scenario：

```
DAY 1

User:
我下周要参加算法竞赛。
```

↓

模拟时间推进。

```
DAY 3

User:
最近压力有点大。
```

期望：

```
Yuiro:
是不是因为那个算法竞赛？
```

这个测试的重要程度甚至高于几十个普通 unit test。

因为它直接验证：

> **Yuiro 有没有连续性。**

------

# 十三、Phase 4：Relate —— 从“记得”到“了解”

这一阶段开始形成：

```
L1
Recent Context

L2
Episode Memory

L3
Semantic / Relationship Memory
```

逐渐出现：

```
User Preference
User Habit
Recurring Event
Relationship
Historical Episode
```

------

## S8：Preference Surprise

用户：

> “我比较喜欢你说话直接一点。”

以后：

> “这个方案怎么样？”

Yuiro 不再机械地：

> “这个方案具有一定优势……”

而是：

> “我直接说结论：这个方案现在不太值得做。”

这就是：

> **Memory → Behavior**

而不是简单 Memory → Retrieval。

------

# 十四、这里开始引入你的 Personal Brain

附件的核心观点在这里发挥作用：

> 长期知识和关系记忆不应该依靠模型权重保存，而应该由记忆系统承担；LoRA 更适合让模型形成稳定的行为风格和工具使用习惯。llm-finetune-mac-persona.mdMD

因此：

```
              YUIRO BRAIN

      ┌──────────────┬──────────────┐
      │              │              │
   Foundation      Memory         Runtime
     Model           │              │
      │              │              │
      │           Facts           Tools
      │           Episodes        Tasks
      │           Relations       Skills
      │              │              │
      └──────┬───────┘              │
             │                      │
          Context                   │
             │                      │
             └─────────┬────────────┘
                       │
                     Agent
```

------

# 十五、Personal Brain Track PB0：永远先做 Baseline

不要马上训练。

先建立：

# `personality-baseline`

例如 100～300 个固定场景：

```
日常聊天
安慰
吐槽
争论
拒绝
惊讶
工具调用
任务失败
任务成功
长期记忆
```

比较：

```
Cloud Model + Prompt
```

和以后：

```
Local Model + LoRA
```

否则你没有实验基线。

------

# 十六、PB1：让 Yuiro 成为“数据工厂”

你的附件这里非常有价值。

目前规划的语料来源包括：

1. L2 情景记忆；
2. 工具调用；
3. 人工编写的黄金回复。llm-finetune-mac-persona.mdMD

我建议再明确一个概念：

# `Training Data Pipeline`

```
Yuiro Conversation
        │
        ├── Raw
        │
        ├── Curated
        │
        ├── Persona
        │
        ├── Tool
        │
        └── Evaluation
```

不要直接：

```
数据库
 ↓
训练
```

必须：

```
Raw
 ↓
Filter
 ↓
Curate
 ↓
Version
 ↓
Dataset
 ↓
Train
```

否则后面数据会失控。

------

# 十七、PB2：工具调用落库

这是附件中非常值得提前实现的一点。

目前设计指出工具调用日志可以作为训练数据，但需要补充持久化。llm-finetune-mac-persona.mdMD

所以建立：

```
ToolCallRecord
```

至少记录：

```
timestamp
session_id
tool_name
arguments
result
success
latency
error
```

以后它不仅用于训练：

```
Tool logs
 ↓
Dataset
```

还可以用于：

```
Tool Analytics
Agent Evaluation
Failure Analysis
```

一份数据，三个用途。

------

# 十八、PB3：0.6B 流程验证

这时候才第一次真正训练。

附件已经给出了非常合理的路线：

> 先用 Qwen3-0.6B 验证完整流程，再进入 4B/8B。llm-finetune-mac-persona.mdMD

流程：

```
Dataset
 ↓
mlx_lm.lora
 ↓
Adapter
 ↓
mlx_lm.chat
 ↓
Baseline Comparison
```

重点不是模型效果。

重点是：

> **整个 Personal Brain Pipeline 能不能跑通。**

------

# 十九、PB4：4B / 8B 正式模型

之后才：

```
Qwen3-4B
```

然后：

```
Qwen3-8B
```

并比较：

```
Personality
Tool Calling
Latency
Memory Context
General Capability
```

附件建议 Qwen3 4B/8B 作为首选，并建议 MLX + LoRA/QLoRA。llm-finetune-mac-persona.mdMD

------

# 二十、PB5：Windows / Mac 双机架构

最终可以形成：

```
        Windows
┌────────────────────────┐
│        Yuiro            │
│                         │
│ UI                      │
│ Live2D                  │
│ Voice                   │
│ Agent                   │
│ Memory                  │
│ Runtime                 │
│                         │
│ LLM Provider            │
└───────────┬────────────┘
            │
       OpenAI API
            │ LAN
            ▼
┌────────────────────────┐
│          Mac            │
│                         │
│ mlx_lm.server           │
│ Qwen3 + LoRA            │
└────────────────────────┘
```

这和附件提出的 Windows Runtime + Mac 模型工坊设计完全一致。llm-finetune-mac-persona.mdMD

关键是：

> **Yuiro 不应该知道自己连接的是云模型还是 Mac 模型。**

它只知道：

```
LLM Provider
```

这就是为什么你现在的 `base_url` / Provider 抽象非常重要。

------

# 二十一、Phase 5：Act —— Agent 正式进化

现在才开始真正扩展 Agent。

------

## A1：Tool

第一个 Tool：

```
read_file
```

第二个：

```
search
```

第三个：

```
system
```

但不要一次加 50 个。

------

# 二十二、A2：Agent Loop

逐渐形成：

```
User
 ↓
Agent
 ↓
Reason
 ↓
Tool?
 ├── No → Answer
 │
 └── Yes
       ↓
      Tool
       ↓
    Observe
       ↓
     Reason
       ↓
      ...
```

重点：

> Agent Loop 本身不要和具体工具绑定。

------

# 二十三、A3：Task Runtime

这是 Runtime 真正开始变得有意义的地方。

```
Task
 ├── id
 ├── goal
 ├── status
 ├── steps
 ├── context
 ├── artifacts
 └── result
```

状态：

```
CREATED
 ↓
PLANNING
 ↓
RUNNING
 ↓
VERIFYING
 ↓
COMPLETED
```

失败：

```
FAILED
 ↓
RECOVERING
 ↓
RUNNING
```

这时候你之前问我的：

> Runtime 到底是什么？

就真正开始落地了：

> **Runtime = 负责让一个持续存在的 AI 状态机运行起来的环境。**

------

# 二十四、A4：第一个真正 Agent Surprise

用户：

> “帮我整理一下 Yuiro 最近的开发进度。”

Yuiro：

```
Task
 ↓
Git Tool
 ↓
Read Changelog
 ↓
Analyze
 ↓
Generate Report
```

然后：

> “我发现你最近主要在推进 Voice 和 Memory。”

这时候：

**Agent + Memory + Tool + Task 开始第一次真正合流。**

------

# 二十五、Phase 6：Exist —— Yuiro 开始主动存在

这是最后一个阶段。

建立：

# Presence Runtime

它持续观察：

```
User Presence
Application State
Time
Recent Interaction
Current Task
System Events
```

然后：

```
Event
 ↓
Attention Policy
 ↓
Should Yuiro act?
```

注意：

> **不是“LLM 每秒问一次我要不要说话”。**

应该是：

```
Event-driven
+
Policy-driven
```

这样才能控制成本和打扰程度。

------

# 二十六、最终 Runtime 会自然长成这样

```
                         YUIRO RUNTIME
                              │
      ┌───────────────────────┼────────────────────────┐
      │                       │                        │
   Session                 Agent                    Presence
      │                       │                        │
   Context                  Task                     Events
      │                       │                        │
   Memory                   Tool                     Policy
      │                       │                        │
      └───────────────────────┼────────────────────────┘
                              │
                        Event / State
                              │
               ┌──────────────┼──────────────┐
               │              │              │
             Voice         Avatar          UI
               │              │              │
             ASR/TTS       Motion         Chat
             VAD            Emotion        Panel
             Barge-in       Performance    Dashboard
```

这时候再回头看，你会发现：

**Runtime 并不是一个巨大的神秘模块。**

它其实是：

> Session + State + Event + Lifecycle + Cancellation + Coordination

逐渐生长出来的。

------

# 二十七、Coding Agent 的完整执行协议

我建议以后所有 Coding Agent 都遵守这一套。

## Step 1 — Understand

```
Read:
- current architecture
- relevant files
- existing tests
- existing interfaces
```

## Step 2 — Plan

必须先回答：

```
What changes?
Why?
What does not change?
What is the smallest implementation?
```

## Step 3 — Implement

只修改任务需要的范围。

## Step 4 — Test

至少：

```
Unit
+
Scenario
```

## Step 5 — Measure

如果涉及性能：

```
before
vs
after
```

## Step 6 — Review

回答：

```
Architecture impact:
New abstractions:
Potential technical debt:
Backward compatibility:
```

## Step 7 — Commit

一个 Scenario 尽量一个逻辑提交。

例如：

```
feat(memory): add explicit memory recall
```

而不是：

```
refactor: improve everything
```

------

# 二十八、给 Coding Agent 的“通用母 Prompt”

以后你可以把它作为基础模板。

```
You are the primary implementation engineer for the Yuiro project.

Yuiro is evolving incrementally toward an embodied personal AI
companion with:

- real-time voice interaction
- Live2D embodiment
- long-term memory
- Agent / Tool / Task execution
- proactive presence
- personalized model behavior

Your role:
- inspect the existing codebase
- implement the requested scenario
- preserve existing working behavior
- introduce only the minimum architecture required
- write regression tests
- measure performance when applicable
- document meaningful architectural changes

The human owner is responsible for:
- product direction
- experience design
- personality
- visual/aesthetic decisions
- final acceptance
- prioritization

Do NOT perform broad rewrites unless explicitly requested.

Development principle:

PRODUCT SCENARIO
→ OBSERVABLE BEHAVIOR
→ MINIMUM ARCHITECTURE INCREMENT
→ IMPLEMENTATION
→ TEST
→ MEASURE
→ REVIEW

Before coding:
1. Inspect the relevant existing implementation.
2. Identify existing abstractions that can be reused.
3. Identify the smallest safe change.
4. Explicitly list files you expect to modify.

During coding:
1. Preserve provider interfaces where practical.
2. Preserve existing behavior.
3. Avoid speculative abstractions.
4. Keep cancellation and lifecycle semantics explicit.
5. Keep external integrations behind adapters/interfaces.

After coding:
1. Run relevant tests.
2. Add regression tests for the new behavior.
3. Report changed files.
4. Report architectural impact.
5. Report remaining risks.
6. Report before/after performance if relevant.

Definition of Done is determined by:
- user-visible behavior
- automated tests
- architectural correctness
- performance/regression criteria
```

------

# 二十九、但还要给 Coding Agent 一个“禁止事项 Prompt”

这个我强烈建议加入。

```
YUIRO ENGINEERING GUARDRAILS

Do NOT:

1. Rewrite the entire architecture to solve a local problem.
2. Introduce a new framework without explicit approval.
3. Duplicate an existing abstraction.
4. Couple Agent logic directly to Live2D implementation.
5. Couple Agent logic directly to a specific LLM provider.
6. Put long-term memory logic inside the AgentLoop.
7. Put model-personality logic inside the Memory layer.
8. Store long-term factual knowledge in model weights.
9. Add background autonomy without explicit lifecycle/cancellation handling.
10. Add a feature without a testable scenario.
11. Remove existing behavior merely because a new architecture is cleaner.
12. Rename large portions of the codebase without necessity.
```

第 8 条尤其对应你的 Personal Brain 设计：

> **Memory ≠ Fine-tuning。**

附件也明确要求不要把知识/长期记忆塞进权重。llm-finetune-mac-persona.mdMD

------

# 三十、你作为 Human 的每个 Sprint，只需要做 7 件事

这会让你从“亲自编码”转向真正的项目掌舵。

```
① 选择 Surprise

② 定义体验

③ 确定优先级

④ 审核 Coding Agent Plan

⑤ 观察实现

⑥ 运行 Showcase Test

⑦ 决定下一步
```

尤其第 6 个非常重要。

不要只看：

```
pytest passed
```

而要真的：

> **坐在桌前和 Yuiro 说话。**

------

# 三十一、每一个 Sprint 的固定模板

以后你的 Roadmap 可以全部按照这个格式。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT XX
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TITLE:
Three-Day Memory Recall

SURPRISE:
Yuiro remembers something explicitly told three days ago.

USER EXPERIENCE:
...

ARCHITECTURE:
...

FILES:
...

CODING AGENT:
...

TEST:
...

PERFORMANCE:
...

DEFINITION OF DONE:
...

HUMAN ACCEPTANCE:
...

CUSTOM ASSET:
...

NEXT UNLOCK:
...
```

最后这个：

> ```
> NEXT UNLOCK
> ```

很重要。

因为每个 Sprint 都应该为下一个 Sprint 解锁能力。

------

# 三十二、于是整个路线形成真正的“科技树”

```
                    YUIRO TECHNOLOGY TREE

                         Personality
                             │
                    ┌────────┴────────┐
                    │                 │
                 Prompt             LoRA
                    │                 │
                    └────────┬────────┘
                             │
                           Model
                             │
             ┌───────────────┼───────────────┐
             │               │               │
          Memory           Agent          Performance
             │               │               │
        Retrieval          Tool             Emotion
             │               │               │
        Relationship       Task             Motion
             │               │               │
             └───────────────┼───────────────┘
                             │
                          Runtime
                             │
                    ┌────────┴────────┐
                    │                 │
                 Presence         Experience
                    │                 │
                 Proactive           UI
                    │                 │
                    └────────┬────────┘
                             │
                       YUIRO COMPANION
```

每完成一个节点，就会解锁下一批玩法。

------

# 三十三、最终的版本节奏，我建议这样定

| 版本     | 核心惊喜         | 新架构              | 你负责       | Agent负责      |
| -------- | ---------------- | ------------------- | ------------ | -------------- |
| **0.1**  | 回答明显更快     | Voice tracing       | 体验评价     | 链路优化       |
| **0.2**  | 真正能被打断     | Cancellation        | 验收自然度   | 实现取消传播   |
| **0.3**  | 表情随回答变化   | Performance Intent  | 设计人格表现 | Runtime        |
| **0.4**  | Yuiro 会表演     | Performance DSL     | 动作素材     | 编排系统       |
| **0.5**  | Yuiro 记住一句话 | Memory MVP          | 定义记忆     | 实现           |
| **0.6**  | 三天后仍然记得   | Recall              | Showcase     | Scenario       |
| **0.7**  | 开始理解偏好     | Relationship Memory | 人格定义     | Retrieval      |
| **0.8**  | 第一次调用工具   | Tool Runtime        | 选择工具     | Agent Loop     |
| **0.9**  | 完成一个任务     | Task Runtime        | 设计任务     | Agent/Task     |
| **0.10** | 失败后自己恢复   | Recovery            | 验收         | Retry/Recovery |
| **0.11** | 主动发现事件     | Presence            | 边界/审美    | Event system   |
| **0.12** | 主动互动         | Proactive           | 行为设计     | Policy         |
| **PB0**  | 人格基线         | Eval                | 人格语料     | Dataset        |
| **PB1**  | Yuiro 数据工厂   | Dataset pipeline    | 黄金数据     | Pipeline       |
| **PB2**  | 0.6B 私人脑      | LoRA pipeline       | 训练标准     | 接入           |
| **PB3**  | 4B Yuiro Brain   | Local LLM           | 人格调教     | 部署           |
| **PB4**  | 云/本地自由切换  | Provider Runtime    | 选择         | Adapter        |
| **1.0**  | 真正的 Yuiro     | Unified Runtime     | 最终体验     | 工程实现       |

------

# 三十四、这里还有一个非常重要的战略判断

你可能会发现：

> **Personal Brain 并没有排在最后。**

这是故意的。

因为你附件里最有价值的一句话实际上是：

> **Yuiro 引擎本身就是天然的数据工厂。** llm-finetune-mac-persona.mdMD

所以从 **Memory MVP** 开始，就应该开始积累：

```
Conversation
Memory
Tool Calls
Ideal Responses
Evaluation
```

到了几个月以后：

```
Yuiro
 ↓
产生数据
 ↓
筛选数据
 ↓
训练模型
 ↓
模型回来
 ↓
成为新的 Yuiro
 ↓
继续产生更好的数据
```

形成：

# **Self-improving Personal Brain Loop**

```
        ┌───────────────────────────────┐
        │                               │
        ▼                               │
     YUIRO Runtime                      │
        │                               │
        ▼                               │
    Interaction Data                    │
        │                               │
        ▼                               │
      Dataset                           │
        │                               │
        ▼                               │
    Evaluation                         │
        │                               │
        ▼                               │
       LoRA                             │
        │                               │
        ▼                               │
   Personal Model                       │
        │                               │
        └──────────→ YUIRO ─────────────┘
```

但这里一定要保持一个边界：

> **模型变得更像 Yuiro，不代表模型成为 Yuiro 的全部。**

真正的 Yuiro 仍然是：

```
Model
+
Memory
+
Runtime
+
Embodiment
+
Experience
```

------

# 三十五、我建议你最终把仓库组织成这种“产品 + 工程 + 实验”结构

概念上：

```
Yuiro/
│
├── engine/
│
├── ui/
│
├── assets/
│   ├── personality/
│   ├── performance/
│   ├── voice/
│   └── easter-eggs/
│
├── memory/
│
├── scenarios/
│   ├── memory/
│   ├── voice/
│   ├── agent/
│   ├── avatar/
│   └── showcase/
│
├── evaluation/
│   ├── personality/
│   ├── latency/
│   ├── tool/
│   └── memory/
│
├── datasets/
│   ├── raw/
│   ├── curated/
│   ├── persona/
│   └── tools/
│
├── docs/
│   ├── architecture/
│   ├── roadmap/
│   └── agent-protocol/
│
└── experiments/
    └── personal-brain/
```

这样：

> **生产代码、产品体验、测试场景、人格资产、模型实验彼此分离，但又可以互相反馈。**

------

# 三十六、最终你要追求的不是“架构完成度”

而是四条曲线同时向上：

```
                 YUIRO EVOLUTION

Experience       ╱───────────────
Intelligence    ╱
Embodiment     ╱
Reliability   ╱
              └──────────────────→ Time
```

如果某次架构重构：

```
Architecture sophistication ↑
Experience ↓
```

那就是失败。

如果一次漂亮功能：

```
Experience ↑
Architecture ↑
Reliability ↑
```

那就是优秀 Sprint。

------

# 三十七、我认为 Yuiro 最应该坚持的一条“第一性原则”

以后无论是你、我还是 Coding Agent 提出一个新架构，都拿它问一句：

> **“这个东西是否最终让 Yuiro 更像一个有连续生命状态的角色？”**

如果答案是：

### 是

做。

### 可能以后有用

放 backlog。

### 只是因为“现代 Agent 都这么设计”

暂缓。

### 只是为了架构漂亮

不要做。

------

所以，从现在开始，我建议你的开发主线正式定成：

> **Alive → Perform → Remember → Relate → Act → Exist**

而 Personal Brain 则贯穿：

> **Observe → Collect → Curate → Evaluate → Fine-tune → Deploy → Observe**

两条线最后汇合：

```
                   ALIVE
                     ↓
                  PERFORM
                     ↓
                 REMEMBER
                     ↓
                  RELATE
                     ↓
                    ACT
                     ↓
                   EXIST
                     ↑
                     │
              PERSONAL BRAIN
                     │
        Collect → Train → Evaluate
```

这条路线的好处是：**即使最终没有做到所谓“完美 Agent Runtime”，Yuiro 在中间任何一个节点都已经是一个比上一个版本明显更好的桌宠。**

而且你不需要成为主要编码者；你的核心价值会逐渐变成**给 Yuiro 注入“只有你才能决定的东西”——人格、表演、记忆规则、彩蛋、互动哲学和最终审美**。Coding Agent 则负责把这些想法稳定地变成工程。

我可以下一步直接把这套路线进一步变成一份**可放进 Yuiro 仓库的 YUIRO_MASTER_ROADMAP.md + CODING_AGENT_PROTOCOL.md + SPRINT_TEMPLATE.md 三件套**，并把当前 Yuiro 源码作为基线，把第一批 Sprint 精确落到实际目录/文件，而不是停留在架构概念层面。



可以。下一步我建议先不要急着写三个 `.md` 文件，而是先做一次**“架构改进回填审计”**：把我们之前讨论过的东西逐项对照上一版路线，确认哪些已经真正进入主架构，哪些只是作为功能点提到了，哪些还缺关键设计。

先给结论：

> **上一版路线已经吸收了大约 70%～80% 的核心架构思想，但还没有完全吸收我们之前讨论的“现代 Agent Harness / Runtime 架构”部分。**
>
> 最大的缺口不是 Live2D、Memory、Voice、Fine-tuning，而是 **Runtime 内核、Agent Harness、可观测性、恢复/回放、权限策略、Context 管理，以及“能力层”和“表现层”的彻底解耦**。

而这恰恰是下一版 `YUIRO_MASTER_ROADMAP.md` 最应该补上的部分。

------

# 一、先回答你的核心问题：之前的架构改进有没有融入？

我把我们之前讨论过的主要内容重新拉出来检查。

| 之前讨论的架构改进             | 上一版路线                                            | 当前判断                     |
| ------------------------------ | ----------------------------------------------------- | ---------------------------- |
| Stable Kernel + Pluggable Edge | 有明确提出                                            | ✅ 已融入                     |
| Runtime 概念                   | 有 Session / State / Event / Lifecycle / Cancellation | 🟡 已融入，但还不够深入       |
| Agent Loop                     | Era 4 才正式出现                                      | 🟡 已融入，但需要提前定义边界 |
| Tool Runtime                   | 有                                                    | 🟡 部分融入                   |
| Skill 系统                     | 提到，但不够系统                                      | ❌ 需要补                     |
| Task Runtime                   | 有                                                    | ✅ 已融入                     |
| Event Bus / Event-driven       | 有                                                    | 🟡 需要成为 Runtime 核心      |
| Cancellation                   | Voice / Agent 都提到                                  | ✅ 已融入                     |
| Lifecycle                      | 有                                                    | ✅ 已融入                     |
| Provider Adapter               | 有                                                    | ✅ 已融入                     |
| Memory 分层                    | 有 L2/L3                                              | ✅ 已融入                     |
| Memory → Behavior              | 已明确提出                                            | ✅ 很重要，已经融入           |
| Live2D 与 Agent 解耦           | Performance Intent                                    | ✅ 已融入                     |
| Voice Pipeline                 | VAD→ASR→LLM→TTS                                       | ✅ 已融入                     |
| Barge-in                       | 明确设计                                              | ✅ 已融入                     |
| Latency tracing                | 明确设计                                              | ✅ 已融入                     |
| Observability / Trace          | 只零散提及                                            | ❌ 不够                       |
| Replay / Deterministic Replay  | 基本没展开                                            | ❌ 明显缺口                   |
| Scenario Test                  | 有                                                    | ✅ 已融入                     |
| Showcase Test                  | 有                                                    | ✅ 已融入，而且这是很好的特色 |
| Agent Recovery                 | Task 有 FAILED/RECOVERING                             | 🟡 需要扩展                   |
| Context Compaction             | 没有系统加入                                          | ❌ 缺失                       |
| Tool approval / Policy         | 没有                                                  | ❌ 缺失                       |
| Sandbox / Capability Boundary  | 没有                                                  | ❌ 缺失                       |
| Agent State Machine            | 有雏形                                                | 🟡 需要正式化                 |
| ToolCallRecord                 | 已加入 Fine-tuning 数据闭环                           | ✅ 已融入                     |
| Training Data Factory          | 已融入                                                | ✅                            |
| Local Model Provider           | 已融入                                                | ✅                            |
| Fine-tuning 与 Memory 分离     | 明确提出                                              | ✅                            |
| Proactive Agent                | Era 5                                                 | 🟡 已融入                     |
| Presence Runtime               | Era 5                                                 | ✅                            |
| Human-in-the-loop              | 有 Coding Agent 协作                                  | 🟡 需要扩展到运行时 Agent     |
| Coding Agent Protocol          | 已设计                                                | ✅                            |
| Architecture Guardrails        | 已设计                                                | ✅                            |
| 增量式演进而非重写             | 核心原则                                              | ✅                            |
| 用户可感知的 Surprise          | 核心开发节奏                                          | ✅                            |

所以答案不是“之前的东西没有融进去”。

恰恰相反：

**产品层的改进已经融合得比较完整；现在缺的是把我们讨论过的现代 Agent Engineering / Harness Engineering 思想真正下沉到 Yuiro 的 Runtime 内核。**

------

# 二、尤其重要：我们之前的 Runtime 定义还需要再升级

我们之前说：

> Runtime = Session + State + Event + Lifecycle + Cancellation + Coordination

这个定义是正确的，但现在看来还不够。

如果 Yuiro 真正往 **Embodied Personal Agent** 发展，我建议把 Runtime 升级成：

```
                 YUIRO RUNTIME
                       │
       ┌───────────────┼────────────────┐
       │               │                │
    Session          Event           State
       │               │                │
       └───────────────┼────────────────┘
                       │
                  Lifecycle
                       │
                  Cancellation
                       │
                 Coordination
                       │
          ┌────────────┼────────────┐
          │            │            │
       Policy       Context       Trace
          │            │            │
       Approval     Compaction    Replay
          │            │            │
          └────────────┼────────────┘
                       │
                 Capability
                       │
            ┌──────────┼──────────┐
            │          │          │
          Tools      Tasks      Skills
```

也就是说：

> **Runtime 不是一个“运行 Agent 的模块”。**
>
> Runtime 是 Yuiro 的**操作系统层**。

------

# 三、这会直接改变我们之前的架构图

以前容易形成：

```
UI
 │
 ▼
AgentLoop
 │
 ├── LLM
 ├── Memory
 ├── Tools
 └── Live2D
```

这其实还是典型的“AI 应用”。

我们现在应该逐渐变成：

```
                         YUIRO
                           │
                    ┌──────▼──────┐
                    │   Runtime   │
                    │             │
                    │ Session     │
                    │ Event       │
                    │ State       │
                    │ Lifecycle   │
                    │ Cancellation│
                    │ Policy      │
                    │ Context     │
                    │ Trace       │
                    └──────┬──────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   Intelligence       Capabilities       Embodiment
        │                  │                  │
   ┌────┼────┐       ┌─────┼─────┐       ┌────┼────┐
   │    │    │       │     │     │       │    │    │
  LLM Memory Agent  Tools Tasks Skills  Voice Live2D Emotion
```

这才开始接近我们之前讨论 DSH / Codex / OpenCode / Claude Code 时发现的共同趋势：

> **核心不是 AgentLoop 有多复杂，而是 Agent 被放进了一个可观察、可控制、可恢复的 Runtime / Harness 中。**

------

# 四、之前没有充分融入的第一个东西：Agent Harness

这是我认为下一版必须增加的。

现在：

```
User
 ↓
AgentLoop
 ↓
LLM
 ↓
Tool
 ↓
LLM
```

看起来没问题。

但是实际运行时会出现：

```
LLM
 ↓
tool call
 ↓
tool failed
 ↓
retry?
 ↓
context changed
 ↓
user interrupts
 ↓
old generation still running?
 ↓
new generation
 ↓
old tool result arrives
```

如果没有 Harness，这些东西最终都会堆在 `AgentLoop` 里。

于是：

```
AgentLoop
 ├── LLM
 ├── Memory
 ├── Tool
 ├── Retry
 ├── Cancellation
 ├── Context
 ├── Logging
 ├── Error
 ├── Task
 ├── Streaming
 ├── Approval
 └── ...
```

最后变成“大泥球”。

所以应该明确：

```
Agent
  │
  ▼
Agent Harness
  │
  ├── Execution
  ├── Context
  ├── Tool Dispatch
  ├── Retry
  ├── Cancellation
  ├── Approval
  ├── Recovery
  ├── Trace
  └── Replay
```

而：

```
Agent
```

本身只负责：

> “决定下一步应该做什么。”

------

# 五、第二个缺口：Context Runtime

这是之前路线里明显缺的一块。

随着 Yuiro 变复杂：

```
System Prompt
+
Persona
+
Recent Conversation
+
Memory
+
Tool Definitions
+
Tool Results
+
Task State
+
User Preferences
+
Current Presence
+
Performance Intent
```

全部塞给 LLM 是不可持续的。

所以应该加入：

## Context Runtime

```
Context Sources
      │
      ├── Conversation
      ├── Memory
      ├── Task
      ├── Tools
      ├── User
      ├── Presence
      └── System
             │
             ▼
       Context Builder
             │
             ▼
       Context Budget
             │
      ┌──────┴──────┐
      │             │
   Compress      Retrieve
      │             │
      └──────┬──────┘
             ▼
          LLM
```

未来自然就能支持：

- context compaction
- memory retrieval
- task context
- tool result summarization
- conversation summarization
- token budget
- priority-based context

这比单纯“Memory 系统”重要得多。

------

# 六、第三个缺口：Trace / Replay

这一项我认为应该提升优先级。

因为我们之前已经提出：

> “智能测试不是简单 unit test，而是测试 Yuiro 有没有真的表现得像一个活着的桌宠。”

那么最好的基础设施其实就是：

**Trace。**

例如一次完整互动：

```
Session #182
│
├── user.speech_start
├── vad.detected
├── asr.partial
├── asr.final
│
├── agent.started
│
├── memory.retrieve
│
├── llm.started
├── llm.first_token
│
├── performance.intent
│
├── tts.started
├── tts.first_audio
│
├── live2d.expression
├── playback.started
│
└── response.completed
```

以后出现：

> “为什么 Yuiro 这次反应这么慢？”

不用猜。

直接：

```
Trace
 ↓
发现 ASR 1.2s
 ↓
Memory 0.3s
 ↓
LLM TTFT 1.8s
 ↓
TTS 0.7s
```

马上定位。

更重要的是：

## Trace 可以 Replay

例如保存：

```
Scenario: three_day_memory_001

Input:
"我下周要参加算法竞赛"

Memory:
...

LLM:
...

Tool:
...

Expected:
...

Actual:
...
```

以后代码改了，再跑：

```
Replay
 ↓
新的 Runtime
 ↓
新的 LLM
 ↓
比较结果
```

这就是我们之前所谓的：

> **Showcase Test + Regression Test**

真正工程化的基础。

------

# 七、第四个缺口：Policy / Approval

这一点在桌宠早期似乎“不重要”，但 Agent 能力增长以后非常重要。

例如：

```
Yuiro:
  我要执行 shell command
```

不能简单：

```
Agent → Tool → 执行
```

而应该：

```
Agent
 ↓
Capability Request
 ↓
Policy Engine
 ↓
┌───────────────┐
│ safe?         │
│ permission?   │
│ scope?        │
│ user approval?│
└───────┬───────┘
        │
   ┌────┴────┐
 allow     deny
```

以后：

- 文件操作
- Shell
- 网络
- Git
- 浏览器
- 自动发送消息
- 自动修改代码

都可以挂在这个体系下。

这也是 Coding Agent 世界里非常重要的一类思想：

> **Agent 能做什么，不应该由 Prompt 决定，而应该由 Runtime Capability / Policy 决定。**

------

# 八、第五个缺口：Skill 应该从 Tool 中独立出来

上一版虽然提到了：

```
Tools / Skills / Plugins
```

但是还没有把三者关系定义清楚。

建议：

```
Capability
│
├── Tool
│   └── 原子动作
│
├── Skill
│   └── 可复用能力流程
│
└── Task
    └── 有生命周期的目标
```

例如：

### Tool

```
get_weather()
read_file()
play_animation()
search_memory()
```

### Skill

```
help_user_debug_python()
prepare_meeting()
comfort_user()
analyze_git_progress()
```

Skill 可以组合 Tool：

```
Skill: analyze_git_progress

    git.status
       ↓
    git.log
       ↓
    git.diff
       ↓
    summarize
       ↓
    Performance Intent
```

### Task

则是：

```
Task #102

Goal:
分析 Yuiro 最近一周开发进度

Status:
RUNNING

Steps:
1. read git history
2. classify commits
3. summarize
4. generate report
```

这样：

> Tool ≠ Skill ≠ Task

就彻底清楚了。

------

# 九、而我们之前的 Live2D 架构改进，其实已经融得很好

这个部分上一版已经比较成熟。

以前：

```
LLM
 ↓
"播放xxx.motion"
 ↓
Live2D
```

现在应该：

```
LLM
 ↓
Performance Intent
 ↓
Performance Runtime
 ↓
Emotion / Motion / Gaze / Voice
 ↓
Live2D
```

例如 LLM 只表达：

```
{
  "emotion": "happy",
  "intensity": 0.7,
  "gaze": "user",
  "motion": "celebrate"
}
```

而不是知道：

```
Cubism Parameter ID
Motion Group
Expression File
Priority
Fade
```

这部分**应该坚定保留**。

因为这是 Yuiro 和纯 Agent 最大的差异之一：

> Agent 决定“想表达什么”，Embodiment Runtime 决定“怎么表现”。

------

# 十、Voice 也应该纳入同一个 Runtime

上一版的 Voice Pipeline 是：

```
VAD
 ↓
ASR
 ↓
LLM
 ↓
TTS
 ↓
Playback
```

下一版应该进一步升级成：

```
                  Runtime
                     │
          ┌──────────┴──────────┐
          │                     │
      Voice Session        Agent Session
          │                     │
          ▼                     ▼
         VAD                   LLM
          │                     │
         ASR                   Tool
          │                     │
          └──────────┬──────────┘
                     │
                 Cancellation
                     │
             ┌───────┴───────┐
             │               │
           Voice         Performance
             │               │
            TTS             Live2D
```

这样用户说：

> “等等！”

触发：

```
VAD
 ↓
Interrupt Event
 ↓
Runtime Cancellation
 ├── cancel LLM
 ├── cancel Tool
 ├── cancel TTS
 ├── stop Playback
 └── stop Performance
```

这就不是 Voice 自己实现的“打断”。

而是：

> **Runtime 级 cancellation。**

这个架构会漂亮很多。

------

# 十一、Memory 也已经融入，但我建议再增加一个非常重要的方向

之前已经确定：

```
Model ≠ Memory
```

而且上传的微调方案也明确强调：

> 微调解决的是行为风格、反应模式、工具调用习惯；长期知识和记忆仍然由 L2/L3 Memory 承担。 

这个原则应该直接成为 Yuiro 的**架构红线**。

进一步可以形成：

```
             Personal Brain
                   │
        ┌──────────┼──────────┐
        │          │          │
      Model      Memory     Experience
        │          │          │
     Who I am   What I know What happened
```

而不是：

```
Everything → Fine-tuning
```

上传方案本身也已经提出：

> Yuiro 引擎可以作为天然的数据工厂，L2 情景记忆以及后续工具调用日志都可以成为训练数据来源。 

所以这条路线可以直接保留。

------

# 十二、甚至可以把 Fine-tuning 放进 Runtime 的“数据闭环”

最终形成：

```
                 YUIRO RUNTIME
                       │
                       ▼
                  Interaction
                       │
          ┌────────────┼────────────┐
          │            │            │
       Memory       ToolCall     Trace
          │            │            │
          └────────────┼────────────┘
                       ▼
                 Data Factory
                       │
            Raw → Filter → Curate
                       │
                    Dataset
                       │
                    Evaluate
                       │
                    LoRA/SFT
                       │
                 Personal Model
                       │
                       ▼
                 Yuiro Runtime
```

这就是我们之前讨论的：

> **Yuiro Runtime → Interaction Data → Dataset → Evaluation → LoRA → Personal Model → Yuiro Runtime**

而且这里有一个很关键的工程原则：

**Runtime 产生数据，但 Runtime 不依赖 Fine-tuning 才能运行。**

也就是说：

```
Fine-tuning = optional improvement
```

而不是：

```
Fine-tuning = required architecture component
```

上传方案目前也明确把 0.6B 流程验证、4B/8B 正式训练、LoRA、OpenAI-compatible provider 等放在后续阶段，而不是当前既成能力。 

------

# 十三、所以我现在会重新定义 Yuiro 的总架构

这比上一版更完整：

```
┌────────────────────────────────────────────────────────────┐
│                        YUIRO EXPERIENCE                     │
│                                                            │
│  Chat UI   Desktop Pet   Voice   Live2D   Emotion         │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│                     YUIRO EMBODIMENT                       │
│                                                            │
│  Voice Runtime   Performance Runtime   Presence Runtime   │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│                     YUIRO INTELLIGENCE                     │
│                                                            │
│ Agent   Context   Memory   Planning   Personal Model       │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│                    CAPABILITY RUNTIME                       │
│                                                            │
│ Tools       Skills       Tasks       Plugins                │
│ Artifacts   External Services                              │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│                       YUIRO RUNTIME                         │
│                                                            │
│ Session │ Event │ State │ Lifecycle │ Cancellation          │
│ Policy  │ Context │ Trace │ Replay │ Recovery               │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│                     STABLE KERNEL                           │
│                                                            │
│ Event Contracts │ Interfaces │ Persistence │ Config         │
│ Provider Adapter │ Capability Registry │ Storage            │
└────────────────────────────────────────────────────────────┘
```

然后外面接：

```
                PLUGGABLE EDGE
                      │
      ┌───────────────┼────────────────┐
      │               │                │
   LLM Provider    TTS/ASR         Plugins
      │               │                │
 Qwen/OpenAI      Whisper/...     Git/Browser/OS
 Local Model      Cloud API       Custom Tools
```

------

# 十四、这时候 Stable Kernel + Pluggable Edge 才真正成立

这是我们之前提出的架构主轴，我建议下一版正式把它提升成：

## Stable Kernel

尽量稳定：

```
Runtime
Event
Session
State
Lifecycle
Cancellation
Capability
Trace
Persistence
Interfaces
```

## Pluggable Edge

可以不断变化：

```
LLM
ASR
TTS
Live2D Assets
Memory Backend
Tools
Plugins
Skills
Model
UI
```

这样以后你甚至可以：

```
Qwen Cloud
     ↓
Qwen Local
     ↓
Qwen3 LoRA
     ↓
其他 Model
```

而：

```
Runtime
Memory
Task
Performance
Tool
```

基本不用动。

这就是**真正值得 Coding Agent 长期维护的架构**。

------

# 十五、因此下一阶段不能再按“功能清单”推进

这一点我也建议修正上一版。

不要：

> Sprint 1 做 Memory
> Sprint 2 做 Live2D
> Sprint 3 做 Agent
> Sprint 4 做 Plugin

因为这样很容易重新走成“大模块堆叠”。

应该改成：

### 每个 Sprint = 一个用户体验 + 一个 Runtime 能力 + 一个工程指标

例如：

------

## Sprint 01

### Surprise

**Yuiro 三天后还记得我说过的话。**

### Runtime 增量

```
Memory Event
+
Memory Retrieval
+
Scenario Replay
```

### 工程指标

```
Memory recall accuracy
Retrieval latency
```

------

## Sprint 02

### Surprise

**我说“等等”，Yuiro 真的立刻闭嘴。**

### Runtime 增量

```
Cancellation Token
+
Interrupt Event
+
Cross-module cancellation
```

### 工程指标

```
Interrupt → Audio Stop latency
```

------

## Sprint 03

### Surprise

**Yuiro 根据我的情绪改变 Live2D 表现。**

### Runtime 增量

```
Performance Intent
+
Performance Runtime
```

### 工程指标

```
Intent → Animation latency
```

------

## Sprint 04

### Surprise

**Yuiro 帮我完成一个真正的任务。**

### Runtime 增量

```
Task
+
Tool
+
Agent Harness
+
Recovery
```

### 工程指标

```
Task success rate
Tool success rate
Recovery rate
```

------

## Sprint 05

### Surprise

**Yuiro 可以自己发现“今天值得跟我说句话”。**

### Runtime 增量

```
Presence Event
+
Attention Policy
+
Lifecycle
```

------

# 十六、而 Coding Agent 的角色也应该因此进一步升级

以前我们定义：

> Coding Agent = 主力程序员。

这个没有问题。

但现在应该变成：

```
                 HUMAN
                   │
        Product / Architecture
                   │
                   ▼
             DEVELOPMENT
                GOAL
                   │
                   ▼
          CODING AGENT
                   │
        ┌──────────┼──────────┐
        │          │          │
     Inspect     Plan       Implement
        │          │          │
        └──────────┼──────────┘
                   ▼
                Test
                   │
                   ▼
                Trace
                   │
                   ▼
               Scenario
                   │
                   ▼
              HUMAN REVIEW
```

也就是说：

**Coding Agent 不只是写代码，而是负责完成一个“可验证的架构增量”。**

------

# 十七、这也意味着我们之前的 Coding Agent Prompt 需要再加强

原来的：

> Inspect → Implement → Test → Report

还不够。

下一版应该强制它回答：

```
1. 当前 Runtime 边界在哪里？

2. 我要增加的能力属于：
   Runtime / Intelligence / Capability / Embodiment / UI？

3. 是否可以复用现有 abstraction？

4. 是否需要新增 Event？

5. 是否存在 Cancellation 生命周期问题？

6. 是否需要 Trace？

7. 是否可以 Replay？

8. 是否破坏 Provider / Tool / UI 解耦？

9. 是否需要 Scenario Test？

10. 这次修改是否扩大了 Stable Kernel？
```

最后这一条尤其重要。

------

# 十八、我现在对整个 Yuiro 路线的判断

经过这次回填，我反而认为我们之前的路线应该进一步收敛成：

```
                YUIRO EVOLUTION
                       │
                       ▼
                Stable Kernel
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
    Intelligence   Capability   Embodiment
         │             │             │
       Agent          Tool          Voice
       Memory         Skill         Live2D
       Model          Task          Emotion
         │             │             │
         └─────────────┼─────────────┘
                       ▼
                    Runtime
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
     Trace           Replay          Policy
       │               │                │
       └───────────────┼────────────────┘
                       ▼
                 Scenario Tests
                       │
                       ▼
                 User Experience
                       │
                       ▼
                  Interaction
                       │
                       ▼
                  Data Factory
                       │
                       ▼
                Personal Brain
```

最终不是：

> **“把 Yuiro 改造成一个更复杂的桌宠。”**

而是：

> **把 Yuiro 从“具有 AI 功能的桌宠程序”，逐步演化成一个拥有稳定 Runtime 内核、可插拔智能能力、可观察 Agent Harness、长期记忆和独特人格的 Embodied Personal Agent。**

------

## 还有一个重要的边界

目前我能从你上传的材料**确认**的是微调方案本身及其规划中的 Yuiro 落点；这个附件明确标注为“设想 / 参考路线图（未实施）”，所以我不会把其中的工具落库、Mac Provider、LoRA 等当成当前已经完成的代码。 llm-finetune-mac-persona.mdMD

对于 **Yuiro.zip 当前源码的具体文件/行号**，这一轮可检索附件结果没有返回源码内容，因此我不会凭之前讨论中的路径去假装确认当前实现。

**所以现在最合理的下一步，是把上述“架构审计结果”正式变成三份 repo-level 文档：**

1. `YUIRO_MASTER_ROADMAP.md` —— **总航标 + 架构演进树 + 阶段解锁条件**
2. `CODING_AGENT_PROTOCOL.md` —— **给 Coding Agent 的长期母提示词 + 架构护栏 + 实施/验收协议**
3. `SPRINT_TEMPLATE.md` —— **每一个增量功能如何从 Surprise → Architecture → Implementation → Test → Trace → Acceptance**

而且我建议这一次**不再只是写一个漂亮的路线图**，而是把刚才新增的 **Runtime / Agent Harness / Context / Trace / Replay / Policy / Capability / Skill / Task** 全部写进第一版正式架构规范中；否则后面 Coding Agent 很容易又把这些东西逐渐塞回 `AgentLoop`，最终重新形成我们最不希望看到的“大 AgentLoop”。