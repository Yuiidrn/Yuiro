是的。把前面 **Open-LLM-VTuber、my-neuro、airi、Yuiro 本身，以及我们进一步抽象出的 DSH / Codex / OpenCode / Claude Code 类 Agent Harness 思路**放在一起后，我认为最终不应该“照搬某一个项目”，而应该形成一套**平衡型目标架构**。

核心不是“功能最多”，而是：

> **吸收各参考项目的长处，同时严格控制桌宠场景下的复杂度，让 Yuiro 逐步从桌宠 → AI Companion → Embodied Personal Agent。**

------

# 一、最终的总目标

我会把 Yuiro 的目标架构定义为：

# **Runtime-Centric Embodied Personal Agent**

也就是：

> **以 Runtime 为核心，以 Agent / Memory / Capability 为智能中枢，以 Voice / Live2D / UI 为具身表现，以 Provider / Plugin 为可替换边界，以 Trace / Replay / Scenario 为工程保障，以 Personal Brain 为长期进化机制。**

最终结构：

```
┌──────────────────────────────────────────────────────────────────┐
│                         YUIRO EXPERIENCE                         │
│                                                                  │
│       Chat UI        Desktop Pet       Voice       Live2D        │
│          │                │              │           │            │
│          └────────────────┴──────────────┴───────────┘            │
│                           │                                      │
├───────────────────────────▼──────────────────────────────────────┤
│                       EMBODIMENT LAYER                            │
│                                                                  │
│   Voice Runtime       Performance Runtime       Presence Runtime │
│   VAD / ASR / TTS     Emotion / Motion / Gaze   Attention Policy │
│                                                                  │
├───────────────────────────▼──────────────────────────────────────┤
│                     INTELLIGENCE LAYER                           │
│                                                                  │
│       Agent             Context             Memory               │
│        │                  │                   │                   │
│     Planning          Retrieval          Recall/Relation         │
│     Reasoning         Compaction         Preference              │
│                                                                  │
├───────────────────────────▼──────────────────────────────────────┤
│                    CAPABILITY / ACTION LAYER                     │
│                                                                  │
│        Tools              Skills              Tasks               │
│          │                  │                   │                  │
│       Atomic             Reusable            Long-running         │
│       actions            workflows           objectives            │
│                                                                  │
├───────────────────────────▼──────────────────────────────────────┤
│                         YUIRO RUNTIME                             │
│                                                                  │
│ Session │ State │ Event │ Lifecycle │ Cancellation │ Context      │
│ Policy  │ Approval │ Recovery │ Trace │ Replay │ Coordination      │
│                                                                  │
├───────────────────────────▼──────────────────────────────────────┤
│                         STABLE KERNEL                             │
│                                                                  │
│ Interfaces │ Event Contracts │ Persistence │ Config │ Registry   │
│ Provider Abstraction │ Capability Boundary │ Storage             │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
             │                  │                  │
             ▼                  ▼                  ▼
       LLM Providers       Voice Providers      External Plugins
       Cloud / Local       ASR / TTS             Git / OS / Web
```

这就是我认为我们目前所有讨论最终应该收敛到的**目标蓝图**。

------

# 二、为什么不是直接复制 airi？

因为三个项目的优势实际上不同。

可以把它们粗略归纳成：

| 项目                                     | 最值得借鉴的核心                                             |
| ---------------------------------------- | ------------------------------------------------------------ |
| **Open-LLM-VTuber**                      | 语音交互链路、桌宠交互、实时体验                             |
| **my-neuro**                             | 角色化、Live2D、人格与陪伴感                                 |
| **airi**                                 | 更完整的 Agent / Memory / Runtime / 工程化方向               |
| **DSH / Codex / OpenCode / Claude Code** | Agent Harness、Tool、Task、Context、Permission、Trace、Recovery |
| **Yuiro**                                | 把以上能力整合成“真正的个人桌面 AI Companion”                |

所以最终不是：

```
Yuiro = airi + VTuber + Claude Code
```

而是：

```
Yuiro
=
VTuber Embodiment
+
Agent Runtime
+
Personal Memory
+
Capability System
+
Personal Brain
```

------

# 三、第一条总原则：Stable Kernel + Pluggable Edge

这是整个架构最重要的平衡点。

## Kernel

尽量稳定：

```
Runtime
Session
Event
State
Lifecycle
Cancellation
Context
Trace
Policy
Capability
Persistence
```

## Edge

允许不断变化：

```
LLM
ASR
TTS
Live2D Model
Animation Assets
Memory Backend
Tools
Plugins
Skills
UI
Local Models
Cloud Models
```

因此：

```
             Stable Kernel
                  │
       ┌──────────┼──────────┐
       │          │          │
      LLM       Voice      Avatar
       │          │          │
    Qwen/...   Whisper/... Cubism/...
```

换模型不会重写 Runtime。

换 Live2D 不会重写 Agent。

换 TTS 不会重写 Memory。

换 Memory backend 不会影响 Voice。

**这就是我们从几个项目中真正应该抽象出来的架构价值。**

------

# 四、第二条原则：Runtime 是真正的“骨架”

前面我们讨论 Runtime 很久，现在可以最终定稿：

> **Runtime 不是 Agent，也不是一个普通 service。**
>
> **Runtime 是整个 Yuiro 中负责“让状态持续存在、事件持续流动、能力安全执行、任务可以取消和恢复”的运行时骨架。**

它至少负责：

```
Session
State
Event
Lifecycle
Cancellation
Context
Coordination
Policy
Recovery
Trace
Replay
```

所以：

```
Agent
Voice
Memory
Live2D
Task
Tool
Presence
```

都运行在 Runtime 之上。

而不是彼此互相调用。

------

# 五、第三条原则：Agent 必须从 Runtime 中解耦

这是借鉴现代 Agent Harness 最重要的东西之一。

不要：

```
AgentLoop
 ├── Memory
 ├── Tool
 ├── TTS
 ├── Live2D
 ├── Retry
 ├── Cancellation
 ├── Context
 └── UI
```

最终一定会爆炸。

应该：

```
                 Runtime
                    │
          ┌─────────┴─────────┐
          │                   │
     Agent Harness        Other Runtime
          │
    ┌─────┼─────┐
    │     │     │
  Agent Context Tool
```

Agent 只负责：

> **下一步应该做什么。**

Harness 负责：

> **让这个决定可靠、安全、可观察地执行。**

------

# 六、Tool / Skill / Task 三层也最终确定

这个是我们之前逐渐收敛出来的，非常值得保留。

```
Capability
│
├── Tool
│     原子动作
│
├── Skill
│     多 Tool 组合出的能力
│
└── Task
      有生命周期的目标
```

例如：

```
Tool:
read_file()

Skill:
analyze_project()

Task:
“分析 Yuiro 最近一周开发进度”
```

于是：

```
Task
 ↓
Skill
 ↓
Tools
 ↓
Artifacts
```

这比“所有东西都是 Tool”强很多。

------

# 七、第四条原则：Context 是 Agent 的独立基础设施

这一点是我们前几轮讨论中逐渐发现的。

Memory 并不能解决所有 Context 问题。

Yuiro 实际需要组合：

```
System
+
Persona
+
Conversation
+
Memory
+
Task
+
Tool
+
User
+
Presence
+
Runtime State
```

所以：

```
Context Sources
      │
      ▼
Context Builder
      │
      ├── Retrieval
      ├── Ranking
      ├── Summarization
      ├── Compaction
      └── Token Budget
      │
      ▼
     LLM
```

最终：

> **Memory 提供信息，Context 决定当前哪些信息应该进入模型。**

这是两个不同的问题。

------

# 八、第五条原则：Memory 不等于数据库，也不等于训练模型

最终建议采用：

```
                 Personal Memory
                       │
          ┌────────────┼────────────┐
          │            │            │
        Recent       Episodic    Semantic
        Context      Events      Relations
          │            │            │
          └────────────┼────────────┘
                       │
                  Retrieval
                       │
                  Context
```

然后再形成：

```
Memory
  ↓
Behavior
```

例如：

> 用户喜欢直接的表达方式。

不是每次把：

```
“用户喜欢直接表达”
```

硬塞进 Prompt。

而是让它最终影响：

```
Response Style
Decision
Emotion
Interaction
```

这才是真正的 Personal Companion。

------

# 九、而 Fine-tuning 放在哪里？

不是 Runtime 核心。

而是：

# **Personal Brain Evolution Pipeline**

```
             Yuiro Runtime
                  │
             Interactions
                  │
      ┌───────────┼───────────┐
      │           │           │
 Conversation   Memory     Tool Calls
      │           │           │
      └───────────┼───────────┘
                  ▼
             Data Factory
                  │
         Raw → Curate → Eval
                  │
                  ▼
              Dataset
                  │
                  ▼
             LoRA / SFT
                  │
                  ▼
           Personal Model
                  │
                  ▼
             LLM Provider
```

这与你附件中的微调路线是吻合的：先 Prompt baseline，再用 0.6B 验证流程，之后再进入 4B/8B；LoRA 负责行为风格与工具使用倾向，而长期事实记忆仍然由 Memory 负责。llm-finetune-mac-persona.mdMD

所以最终：

> **Memory 让 Yuiro 记得你。**
>
> **Fine-tuning 让 Yuiro 越来越像“这个 Yuiro”。**

这是非常漂亮的职责划分。

------

# 十、Voice 系统则采用“实时管线 + Runtime 控制”

最终：

```
User Speech
    │
    ▼
   VAD
    │
    ▼
   ASR
    │
    ▼
Runtime Session
    │
    ▼
 Context
    │
    ▼
 Agent / LLM
    │
    ├─────────────┐
    │             │
    ▼             ▼
   TTS       Performance
    │             │
    ▼             ▼
Playback        Live2D
```

重点是：

**Voice 不拥有 Agent。**

Voice 是 Runtime 的一种输入/输出通道。

------

# 十一、Barge-in 最终也应该成为 Runtime 能力

例如：

```
User says:
“等等！”
```

↓

```
VAD
 ↓
Interrupt Event
 ↓
Runtime Cancellation
 ├── LLM
 ├── Tool
 ├── TTS
 ├── Playback
 └── Performance
```

因此：

> **打断机制不是 Voice Feature，而是 Runtime Capability。**

Voice 只是最常见的触发来源。

未来 UI 点击“停止”、用户输入新消息、Task 被取消，都可以使用同一个 Cancellation 模型。

------

# 十二、Live2D 最终成为 Embodiment Runtime

这一点 Yuiro 必须区别于传统 Agent。

LLM：

```
“我有点惊讶。”
```

↓

```
Performance Intent
```

↓

```
Performance Runtime
```

↓

```
Emotion
Motion
Gaze
Expression
Timing
```

↓

```
Live2D
```

因此 Agent 永远不直接操作 Cubism 参数。

这既吸收了桌宠项目的优点，也解决了耦合问题。

------

# 十三、Presence 是 Yuiro 与普通 Coding Agent 最大的区别

Claude Code / Codex / OpenCode 这些 Agent 很强，但它们通常是：

> **User invokes → Agent acts**

Yuiro 最终应该多一个：

> **World changes → Yuiro notices → Yuiro decides whether to act**

例如：

```
User enters room
       ↓
Presence Event
       ↓
Attention Policy
       ↓
Should act?
   │         │
  No        Yes
             ↓
           Agent
             ↓
         Performance
```

但这里必须非常克制。

**主动 ≠ 高频打扰。**

所以 Presence 必须建立：

```
Attention Policy
+
Cooldown
+
User Preference
+
Context Awareness
+
Quiet Hours
+
Confidence
```

------

# 十四、这就是桌宠和 Coding Agent 真正的分叉点

可以把两者看成：

```
Coding Agent:

User
 ↓
Task
 ↓
Agent
 ↓
Tool
 ↓
Result


Yuiro:

World / User
 ↓
Event
 ↓
Attention
 ↓
Context
 ↓
Agent
 ↓
Capability
 ↓
Performance
 ↓
Memory
 ↓
Future Behavior
```

所以：

> **Codex / Claude Code 是很好的 Agent Engine 参考，但不是 Yuiro 的完整产品范式。**

我们真正应该吸收的是它们的：

- Harness
- Tool execution
- Task
- Context
- Permission
- Recovery
- Trace

而不是照搬它们的产品交互。

------

# 十五、插件体系最终应该采用“Capability Registry”

不要让插件直接：

```
import everything
```

而是：

```
Plugin
 ↓
Registration
 ↓
Capability Registry
 ↓
Policy
 ↓
Agent
```

例如：

```
Git Plugin
 ├── git.status
 ├── git.diff
 └── git.log

System Plugin
 ├── system.notify
 └── system.open_app
```

Agent 看到的是：

```
Available Capabilities
```

而不是整个插件内部结构。

------

# 十六、配置体系也要统一

最终：

```
Config
│
├── Runtime
├── LLM
├── Voice
├── Avatar
├── Memory
├── Agent
├── Tools
├── Plugins
├── Policy
└── UI
```

同时支持：

```
defaults
↓
environment
↓
config file
↓
profile
↓
runtime override
```

最重要的是：

> **业务代码不能到处读取环境变量。**

应该：

```
Config
 ↓
Typed Config
 ↓
Runtime / Components
```

------

# 十七、可观测性最终必须成为一等公民

这是我们从现代 Agent 架构里应该狠狠吸收的东西。

一次互动：

```
Trace #10291
│
├── Session
├── VAD
├── ASR
├── Memory
├── Context
├── LLM
│    ├── TTFT
│    └── tokens
├── Tool
│    ├── latency
│    └── result
├── TTS
├── Performance
└── Playback
```

最终可以回答：

> “为什么 Yuiro 这句话花了 4.2 秒？”

而不是靠猜。

------

# 十八、再加上 Replay，就形成非常强的开发闭环

```
Interaction
 ↓
Trace
 ↓
Save
 ↓
Replay
 ↓
New Runtime
 ↓
Compare
```

于是你可以真正建立：

# **Scenario-driven development**

例如：

```
scenario/memory/three_day_recall.yaml
scenario/voice/barge_in.yaml
scenario/agent/tool_failure.yaml
scenario/avatar/emotion.yaml
```

这些不是普通单元测试。

它们是：

> **Yuiro 的“人格行为测试”。**

------

# 十九、于是我们之前提出的“惊喜式测试”就真正有了工程基础

例如：

### Memory Surprise

> 三天后记住用户说过的事情。

### Voice Surprise

> 用户说“等等”后 200ms 内停止说话。

### Avatar Surprise

> Yuiro 说出惊讶内容时同步表现惊讶。

### Agent Surprise

> 工具失败以后自己换方案。

### Personalization Surprise

> 用户说过喜欢直接表达，以后真的改变说话方式。

### Presence Surprise

> 用户长时间工作后，Yuiro 合适地提醒休息。

这些都可以变成：

```
Scenario
+
Trace
+
Replay
+
Human Acceptance
```

------

# 二十、这也是我们最终对四类参考架构的平衡

我会这样归纳：

```
Open-LLM-VTuber
       │
       ├── Voice
       ├── Realtime
       └── Desktop Interaction
             │
             ▼

my-neuro
       │
       ├── Character
       ├── Live2D
       └── Companion Experience
             │
             ▼

airi
       │
       ├── Agent
       ├── Memory
       ├── Runtime
       └── Extensibility
             │
             ▼

Codex / Claude Code / OpenCode / DSH
       │
       ├── Harness
       ├── Tool
       ├── Task
       ├── Context
       ├── Policy
       ├── Recovery
       └── Trace
             │
             ▼
           
          YUIRO
             │
       ┌─────┴─────┐
       │           │
 Intelligence   Embodiment
       │           │
 Agent          Voice
 Memory         Live2D
 Capability     Emotion
       │           │
       └─────┬─────┘
             │
          Runtime
             │
        Personal Brain
```

------

# 二十一、哪些东西明确“不借鉴”？

这同样重要。

## 1. 不追求 Agent 能力无限膨胀

Yuiro 不是：

> “什么都能干的超级 Agent。”

它首先是：

> **Personal Companion。**

能力增长应该服从陪伴体验。

------

## 2. 不把 Live2D 做成 Agent API

Agent：

```
emotion = surprised
```

而不是：

```
set_parameter("ParamEyeLOpen", ...)
```

------

## 3. 不把所有聊天都塞进 Memory

必须有：

```
Ephemeral
vs
Episodic
vs
Semantic
```

------

## 4. 不用 Fine-tuning 替代 Memory

这是红线。

------

## 5. 不因为“现代 Agent 都有”就加入复杂 Planner

如果：

```
LLM → Tool → Result
```

已经足够，就不要：

```
Planner → Planner → Planner → Executor
```

------

## 6. 不过早微服务化

Yuiro 是桌面应用。

在很长一段时间内：

```
Single Process
+
Modular Runtime
```

比：

```
10 Services
+
Message Queue
+
RPC
```

更加合理。

------

# 二十二、所以我认为最终的“理想程度”应该停在这个位置

不是：

```
                  Super Agent
                       │
      ┌────────────────┼────────────────┐
      │                │                │
 Planner            Browser          Coding
 Browser            Computer         Terminal
 Memory             Research         Deploy
 ...
```

而是：

```
                 PERSONAL COMPANION
                         │
             ┌───────────┴───────────┐
             │                       │
       Intelligence              Embodiment
             │                       │
       Agent / Memory           Voice / Live2D
       Capability / Task        Emotion / Presence
             │                       │
             └───────────┬───────────┘
                         │
                    YUIRO RUNTIME
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
      Context          Policy            Trace
      State            Recovery          Replay
      Event            Cancellation      Lifecycle
                         │
                   Stable Kernel
                         │
             Pluggable Providers
```

这就是我认为的**平衡点**。

------

# 二十三、如果把它压缩成一句架构宣言

我会把 Yuiro 的最终 Architecture Principle 写成：

> **Yuiro is a Runtime-centric embodied personal agent: a stable execution kernel coordinates intelligence, memory, capabilities, voice, avatar, and presence through explicit state, events, lifecycle, cancellation, policy, context, and observability, while external models, providers, tools, skills, plugins, and embodiment assets remain replaceable.**

中文就是：

> **Yuiro 是一个以 Runtime 为核心的具身个人智能体：通过显式的状态、事件、生命周期、取消、策略、上下文和可观测机制，统一协调 Agent、Memory、Capability、Voice、Live2D 与 Presence；模型、服务商、工具、技能、插件及表现资产则保持可替换。**

我认为这句话已经可以作为我们后续所有架构决策的**最高层锚点**。

------

# 二十四、最终的完整心智模型

最后可以用一张图记住整个东西：

```
                         ┌───────────────┐
                         │    HUMAN      │
                         │ Personality   │
                         │ Preferences   │
                         │ Custom Assets │
                         └───────┬───────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────┐
│                         YUIRO                                 │
│                                                              │
│   ┌───────────────┐                 ┌────────────────────┐   │
│   │ Intelligence  │                 │    Embodiment      │   │
│   │               │                 │                    │   │
│   │ Agent         │                 │ Voice              │   │
│   │ Memory        │                 │ Live2D             │   │
│   │ Context       │                 │ Emotion            │   │
│   │ Personal Model│                 │ Presence           │   │
│   └───────┬───────┘                 └─────────┬──────────┘   │
│           │                                   │              │
│           └──────────────┬────────────────────┘              │
│                          ▼                                   │
│                  ┌───────────────┐                           │
│                  │ YUIRO RUNTIME │                           │
│                  │               │                           │
│                  │ Session       │                           │
│                  │ State         │                           │
│                  │ Event         │                           │
│                  │ Lifecycle     │                           │
│                  │ Cancellation  │                           │
│                  │ Context       │                           │
│                  │ Policy        │                           │
│                  │ Recovery      │                           │
│                  │ Trace         │                           │
│                  │ Replay        │                           │
│                  └───────┬───────┘                           │
│                          │                                   │
│                  ┌───────▼───────┐                           │
│                  │ CAPABILITIES  │                           │
│                  │               │                           │
│                  │ Tools         │                           │
│                  │ Skills        │                           │
│                  │ Tasks         │                           │
│                  │ Plugins       │                           │
│                  └───────┬───────┘                           │
│                          │                                   │
│                  ┌───────▼───────┐                           │
│                  │ STABLE KERNEL │                           │
│                  └───────┬───────┘                           │
└──────────────────────────┼───────────────────────────────────┘
                           │
             ┌─────────────┼──────────────┐
             ▼             ▼              ▼
           Cloud         Local         External
           Models        Models        Services
             │             │              │
             └─────────────┼──────────────┘
                           ▼
                     EXPERIENCE
                           │
                           ▼
                    Interaction Data
                           │
                           ▼
                     Data Factory
                           │
                           ▼
                    Personal Brain
                           │
                           └──────────────→ YUIRO
```

**这就是我们从目前所有参考项目、现代 Agent 架构、你自己的 Yuiro 基础，以及你附件中的 Personal Brain / LoRA 设想共同归纳出来的最终目标架构。**

而最重要的是：**它不是要求你现在就把整张图实现出来。**

整张图是**方向**；真正的工程路线仍然应该是：

> **先把 Runtime 骨架长出来 → 再逐步把 Voice / Agent / Memory / Capability / Embodiment 接上去 → 用 Trace / Replay / Scenario 固化每次进化 → 最后让 Interaction Data 反过来训练 Personal Brain。**

这样“万丈高楼平地起”才真正成立：**目标架构可以一步到位地想清楚，代码却必须一层一层长出来。**

我建议下一步把这张“最终目标架构”进一步做成一份**Architecture Decision Matrix**：逐项标出 Open-LLM-VTuber / my-neuro / airi / Codex / Claude Code / OpenCode 各自贡献了什么、Yuiro 最终采纳什么、为什么不采纳什么，以及每项应该在哪个 Sprint 落地。这样以后 Coding Agent 面对架构选择时，就有一张真正的“裁判表”。