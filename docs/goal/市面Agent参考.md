需要，而且把参照系扩展到 **DSH（DeepSeek Harness）、Codex、OpenCode、Claude Code** 之后，我认为对 Yuiro 的判断会发生一个重要变化：

> 前面的 Open-LLM-VTuber / my-neuro / airi，主要告诉我们“桌宠应该怎样做实时语音、角色呈现、记忆和桌面交互”；而 Codex / Claude Code / OpenCode / DSH 更能告诉我们：**一个真正成熟的 Agent Harness 应该怎样组织 Session、Context、Tool、Permission、Subagent、Skill、Checkpoint、Event Log 和长任务生命周期。**

我核实了你说的 DSH，这里按 **DeepSeek Harness** 理解。它在 2026 年 8 月才进入 developer preview，因此架构思想很有参考价值，但不应该像 Codex/Claude Code 那样直接视为经过长期生产验证的成熟范式。它最突出的特点是“Everything is a Plugin”，Harness 自身都高度插件化。[dshbase](https://dshbase.com/blog/deepseek-harness-architecture/?utm_source=chatgpt.com)

------

# 一、先重新定义 Yuiro 应该对标什么

过去我们把目标画成：

```
                  Yuiro
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
        Agent     Speech    Avatar
          │
        Memory
          │
        Tools
```

现在看，这还少了一层。

真正成熟的 Agent 产品通常是：

```
                       PRODUCT SURFACE
              Desktop / CLI / IDE / Web / Voice
                             │
                             ▼
                    ┌─────────────────┐
                    │  AGENT HARNESS  │
                    └────────┬────────┘
                             │
             ┌───────────────┼────────────────┐
             │               │                │
             ▼               ▼                ▼
          Session          Context           Agent
          Runtime          Engine            Loop
             │               │                │
             │               │         ┌──────┴──────┐
             │               │         ▼             ▼
             │               │       Tools       Subagents
             │               │         │
             │               │      Permission
             │               │         │
             └───────────────┼─────────┘
                             │
                         Event Log
                             │
                    Persistence / Replay
```

对桌宠 Yuiro 来说，还要在 Harness 外增加：

```
Speech Runtime
Avatar Runtime
Emotion / Relationship Runtime
Proactive Runtime
```

所以更准确的 Yuiro 目标已经不是简单的：

> **Agent Runtime**

而是：

> **General Agent Harness + Embodied Desktop Runtime**

也就是一个通用 Agent Harness，再加上桌宠特有的语音、身体、情绪、主动性。

------

# 二、四个主流 Agent 最值得研究的不是“模型”，而是 Harness

OpenAI 自己对 Codex 的描述就很明确：

> Codex 的核心是一个 harness，它负责在用户、模型和工具之间执行 agent loop。

OpenAI 公开的 Codex agent-loop 分析表明，它每轮并不是简单把聊天历史发给模型，而是动态组合 sandbox 权限、developer instructions、项目级 `AGENTS.md` 等上下文，再执行模型—工具—模型循环。[OpenAI](https://openai.com/zh-Hans-CN/index/unrolling-the-codex-agent-loop/?utm_source=chatgpt.com)

所以：

```
Model ≠ Agent
```

更准确地说：

```
              Model
                +
        Agent Harness
                =
              Agent
```

Harness 包含：

```
Session
Context
Tools
Permissions
Execution
Persistence
Cancellation
Observability
Skills
Subagents
```

这正是 Yuiro 下一阶段最需要补的一层。

------

# 三、Codex：最值得 Yuiro 学习的是“Thread as Runtime”

Codex 目前对 Yuiro 最有价值的架构不是 coding 能力，而是：

> **Thread 不是聊天记录，而是一个可持续运行、可恢复、可 fork、可持久化的 Agent execution unit。**

OpenAI 的 App Server 架构文章明确指出，Codex thread 可以：

```
create
resume
fork
archive
```

并持久保存 event history，使客户端断线后重新连接仍然能够恢复一致 timeline。Codex core 本身既是 library，也是可以启动起来管理单个 thread 的 runtime。[OpenAI](https://openai.com/index/unlocking-the-codex-harness/?utm_source=chatgpt.com)

这对 Yuiro 非常重要。

------

# 四、Yuiro 当前 Session 还偏“conversation session”

你现在的 Agent 已经有：

```
session_id
generation
history
state_notes
```

这是很好的基础。

但 Codex 给我们的启示是：

```
Session
```

不应该只意味着：

> “这是一段聊天。”

而应该意味着：

> **这是 Agent 从开始到结束的一条完整执行轨迹。**

所以建议 Yuiro 未来把：

```
ConversationSession
```

提升为：

```
AgentSession
├── session_id
├── generation
├── parent_session_id
├── state
├── events
├── active_tasks
├── context_snapshot
├── permissions
├── created_at
├── last_active_at
└── lifecycle
```

------

# 五、这会直接解决 Yuiro 一个长期问题：会话恢复

假设用户昨天让 Yuiro：

```
帮我整理这个项目
```

Agent 做过：

```
read files
tool calls
memory lookup
reasoning
system operations
```

第二天重新打开。

目前典型桌宠会恢复：

```
chat history
```

而一个 Codex-style Session 应恢复：

```
User Request
      ↓
Agent Started
      ↓
Memory Retrieved
      ↓
Tool A Called
      ↓
Tool A Completed
      ↓
Tool B Called
      ↓
Approval Required
      ↓
Approved
      ↓
Agent Responded
```

即：

> **Event trajectory。**

这是比普通聊天记录高一个层级的能力。

------

# 六、因此我现在非常建议 Yuiro 增加 Event Log

不是传统日志：

```
INFO ...
ERROR ...
```

而是**Agent-native event log**：

```
AgentEvent
{
    event_id
    session_id
    generation
    trace_id
    type
    source
    timestamp
    payload
}
```

事件可能包括：

```
session.started
user.message
speech.started
asr.completed
agent.started
llm.started
llm.token
tool.requested
tool.approval_required
tool.started
tool.completed
memory.retrieved
speech.intent_created
tts.started
avatar.motion_started
agent.cancelled
session.completed
```

这一个改造会同时改善：

**恢复、调试、UI timeline、Memory、主动行为、长期任务和审计。**

Codex 对 agent-native telemetry 和审计的强调也说明这一层已经成为成熟 Agent 系统的重要组成部分。[OpenAI](https://openai.com/index/running-codex-safely/?utm_source=chatgpt.com)

------

# 七、Claude Code：最值得学的是“Plan → Execute”双模态

Claude Code 有一个对桌宠极有价值、但我们之前没充分讨论的架构：

```
Plan Mode
      ↓
Execution Mode
```

Anthropic 对其描述是：

> 与其让 Agent 每一步都申请权限，不如先展示整体策略，用户批准计划后，再允许 Agent 在执行过程中自主完成大量步骤。[Anthropic](https://www.anthropic.com/research/trustworthy-agents?utm_source=chatgpt.com)

这非常适合 Yuiro。

------

# 八、Yuiro 不能把所有任务都当成同一种 Chat Turn

例如：

```
“打开网易云音乐”
```

是：

```
Immediate Action
```

而：

```
“帮我整理一下电脑里的毕业设计资料”
```

是：

```
Long-running Task
```

目前如果统一：

```
User input
 ↓
AgentLoop
```

长期会吃亏。

建议引入：

```
InteractionMode

CHAT
ACTION
PLAN
TASK
BACKGROUND
```

然后：

```
简单问题
→ CHAT

简单工具操作
→ ACTION

复杂敏感任务
→ PLAN → APPROVAL → TASK

独立耗时任务
→ BACKGROUND TASK
```

------

# 九、Plan 本身应该成为一种数据结构

不要只是让 LLM 输出一段 Markdown：

```
1. 做什么
2. 做什么
3. 做什么
```

应该形成：

```
TaskPlan
├── goal
├── assumptions
├── steps[]
├── required_capabilities
├── risk_level
├── approval_requirement
└── completion_criteria
```

例如：

```
Goal:
整理下载目录中的论文

Step 1:
扫描 PDF

Step 2:
抽取元数据

Step 3:
按主题分类

Step 4:
移动文件

Capabilities:
filesystem.read
filesystem.write

Risk:
medium

Approval:
required before write
```

------

# 十、这会让 Yuiro 的 Approval 系统真正升级

目前 Yuiro：

```
Tool
 ↓
Approval
 ↓
SystemDaemon
```

已经不错。

Claude Code / Codex 给出的进一步启示是：

> **审批不应该只有 Tool-level，还应该有 Plan-level。**

因此：

```
LEVEL 1

read_file
→ 自动

LEVEL 2

open_application
→ 自动/策略

LEVEL 3

delete_file
→ tool approval

LEVEL 4

批量整理用户文件
→ plan approval
```

这比每移动一个文件都问一次：

> “可以吗？”

体验会好得多。

------

# 十一、Codex + Claude Code：Sandbox 应该升级成 Yuiro 的重点

这是我现在认为 Yuiro **SystemDaemon 下一阶段最值得增强的地方之一**。

Codex 将：

```
Sandbox
```

和：

```
Approval
```

视作两个不同维度：

```
Sandbox:
技术上能碰哪里？

Approval:
什么时候需要用户允许？
```

Codex 有文件系统、网络访问等技术边界；高风险越界动作再进入审批。[OpenAI](https://openai.com/index/running-codex-safely/?utm_source=chatgpt.com)

Claude Code 同样强调 filesystem isolation + network isolation，并指出仅有 permission prompt 并不足够。[Anthropic](https://www.anthropic.com/engineering/claude-code-sandboxing?utm_source=chatgpt.com)

------

# 十二、Yuiro 当前 Security 已经很好，但还是“Policy-oriented”

现在大致：

```
Agent
 ↓
Tool
 ↓
Policy
 ↓
Approval
 ↓
SystemDaemon
```

应该逐步升级：

```
Agent
 ↓
Capability
 ↓
Permission
 ↓
Sandbox
 ↓
Approval
 ↓
Execution
```

区别是：

### Policy

```
“不允许访问 ../”
```

### Sandbox

```
“即使 Agent 想访问，也在操作系统层面访问不到。”
```

这是完全不同的安全强度。

------

# 十三、Yuiro 特别适合做“桌面 Agent 权限域”

可以借鉴手机操作系统：

```
Capability Scope

filesystem:
  ~/Documents/Yuiro/**

network:
  api.openai.com
  music.163.com

process:
  whitelist applications

media:
  unrestricted

clipboard:
  read/ask

screen:
  ask
```

然后 AgentSession 创建时带：

```
PermissionProfile
```

例如：

```
NORMAL
TRUSTED
READ_ONLY
PRIVACY
```

OpenCode 也越来越明确地把 permission 做成独立 policy system，而不是简单的 `tool=true/false`；当前 V2 甚至是 ordered resource rules。[OpenCode](https://opencode.ai/v2/docs/permissions?utm_source=chatgpt.com)

------

# 十四、OpenCode：最值得 Yuiro 借鉴的是“Agent Profile”

OpenCode 的 Agent 定义很有启发性：

> 一个 Agent = system prompt + model preference + tool permissions + metadata。

并明确区分：

```
Primary Agent
Subagent
```

以及：

```
Build
Plan
General
Explore
```

不同 Agent 拥有不同的工具访问范围。[OpenCode](https://opencode.ai/v2/docs/agents?utm_source=chatgpt.com)

这对 Yuiro 很适合。

------

# 十五、Yuiro 现在 Persona 和 Agent 基本还是绑在一起

目前比较接近：

```
Yuiro
 ↓
Persona
 ↓
AgentLoop
```

但是以后可以解耦成：

```
Character
    ≠
Agent Role
```

例如仍然都是 Yuiro 这个人格，但内部可以出现：

```
Yuiro / Conversation
Yuiro / Research
Yuiro / System
Yuiro / Memory
Yuiro / Vision
```

这不是人格分裂。

用户始终看到：

> **Yuiro。**

内部却可以采用不同：

```
prompt
model
toolset
permission
context policy
```

------

# 十六、这直接通向 Subagent

现在 Yuiro 已经有 `SubagentTool` 的代码基础。

所以这不是凭空增加。

建议真正把它发展为：

```
Main Agent
     │
     ├── ResearchAgent
     │       └── read/web/search
     │
     ├── SystemAgent
     │       └── system capabilities
     │
     ├── MemoryAgent
     │       └── retrieve/consolidate
     │
     └── VisionAgent
             └── screen/image
```

但必须非常克制。

------

# 十七、Claude Code / OpenCode 给我们的教训：Subagent 不是“多 Agent 越多越好”

Anthropic 自己目前强调的 multi-agent 获益场景主要是：

```
Context isolation
Parallel execution
Specialization
```

而不是所有任务都拆 agent。[Anthropic](https://www.anthropic.com/events/anthropic-at-google-cloud-next-2026?utm_source=chatgpt.com)

所以 Yuiro 只有在下面情况才应该 delegation：

```
上下文太大
任务可并行
需要不同能力/权限
需要独立验证
```

不要：

```
聊天 Agent
 ↓
先叫 planning agent
 ↓
再叫 research agent
 ↓
再叫 tool agent
 ↓
再叫 response agent
```

这种“Agent 套娃”。

------

# 十八、我特别推荐 Yuiro 增加 Verification Agent，但不是默认启用

这是 coding agent 给桌宠一个非常好的启发。

对于高风险操作：

```
“删除所有重复文件”
```

可以：

```
Main Agent
     ↓
Produce Plan
     ↓
Verification Agent
     ↓
Check:
  scope?
  irreversible?
  suspicious?
  mismatch?
     ↓
Approval
```

对于普通：

```
“今天星期几？”
```

当然完全不需要。

------

# 十九、Claude Code：Hooks 是 Yuiro Plugin 系统很值得吸收的一层

Claude Code Hooks 可以在：

```
PreToolUse
PostToolUse
UserPromptSubmit
SessionStart
...
```

等生命周期节点触发外部逻辑。[资源](https://resources.anthropic.com/hubfs/Claude Code Advanced Patterns_ Subagents%2C MCP%2C and Scaling to Real Codebases.pdf?utm_source=chatgpt.com)

这个设计特别适合 Yuiro。

因为目前你在考虑：

```
Plugin
Skill
Tool
Event
Runtime
```

很容易变复杂。

Hooks 可以成为非常薄的 extension boundary。

------

# 二十、例如 Yuiro 可以定义这些 Hook

```
on_session_start
on_user_input
before_context_build
after_memory_retrieval
before_llm
after_llm
before_tool
after_tool
before_speech
after_speech
on_barge_in
on_avatar_action
on_session_end
```

Plugin 就可以：

```
Plugin
 ↓
subscribe hooks
```

而不需要直接依赖：

```
AgentRuntime internals
```

这会比 my-neuro 的 `global.pluginManager` 健康很多。

------

# 二十一、但是 Hook 和 Event 不一样

建议明确：

```
Event
= 系统事实广播

Hook
= 扩展点

Intent
= 要执行的动作
```

例如：

```
tool.completed
```

是 Event。

```
after_tool()
```

是 Hook。

```
SpeakIntent
```

是 Intent。

不要把三种东西混成一个 EventBus。

------

# 二十二、Claude Skills：Yuiro 当前 Skill 骨架应该重做定位

Anthropic 对 Agent Skills 的定义非常值得采用：

> Skill 是一个包含 instructions、scripts、resources 的可发现能力包，Agent 在需要时加载，而不是所有知识始终塞入 system prompt。[Anthropic](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills?utm_source=chatgpt.com)

这基本就是 Yuiro Skill 应该走的方向。

------

# 二十三、Yuiro Skill 不应该只是 Prompt 文件

建议：

```
skills/
└── research-paper/
    ├── SKILL.md
    ├── scripts/
    │   ├── parse_pdf.py
    │   └── search_refs.py
    ├── templates/
    └── resources/
```

然后：

```
Agent
 ↓
Skill Metadata
 ↓
Need?
 ↓ yes
Load SKILL.md
 ↓
Grant required capabilities
 ↓
Execute workflow
```

这叫：

> **Progressive disclosure of capability/context**

非常重要。

------

# 二十四、为什么不要启动时加载所有 Skill？

因为成熟 coding agents 有一个共同压力：

> **Context 是稀缺资源。**

几十个 Tool、几十个 Skill、几十页 persona 全塞进去：

```
Prompt
├── Persona
├── Memory
├── 80 tools
├── 30 skills
├── history
└── state
```

模型反而变差。

所以应该：

```
Metadata always available
       ↓
Relevant Skill selected
       ↓
Skill body loaded lazily
```

这对 Yuiro 非常值得实现。

------

# 二十五、Codex 的 AGENTS.md 也给 Yuiro 一个很重要的 Context 思路

Codex 会按目录层级聚合：

```
AGENTS.md
AGENTS.override.md
```

并让更具体路径的 instruction 具有更高局部性。[OpenAI](https://openai.com/index/unrolling-the-codex-agent-loop/?utm_source=chatgpt.com)

对 Yuiro 不一定要照搬文件名。

但是应该学习：

> **Context 不是一个大 prompt，而是有 scope 的 Context Sources。**

------

# 二十六、所以我现在建议给 Yuiro 正式建立 Context Engine

这是上一版 Goal 中不够突出的部分。

目标：

```
                   ContextEngine
                        │
       ┌────────────────┼────────────────┐
       ▼                ▼                ▼
    Persona          Session          Runtime
       │                │                │
       ▼                ▼                ▼
 Character         Conversation       Environment
       │
       ├──────────────┐
       ▼              ▼
    Memory          Skills
       │              │
       ▼              ▼
 Retrieval       Lazy Load
       │
       └──────────────┐
                      ▼
                   Tools
                      │
                      ▼
                Final Context
```

ContextBuilder 不应该只是：

```
messages = system + memory + history
```

------

# 二十七、每个 Context Source 应该带 metadata

例如：

```
ContextItem
{
    source
    scope
    priority
    token_cost
    freshness
    relevance
    mandatory
}
```

这样 Context Engine 才能决定：

```
哪些必须保留？
哪些可以摘要？
哪些动态检索？
哪些可以丢弃？
```

这是现代 Agent Architecture 一个非常关键但容易被忽略的部分。

------

# 二十八、Context Budget 应成为 Runtime 的一等公民

例如：

```
context budget = 64K
```

可以分配：

```
system/persona       8K
active task          8K
recent conversation 16K
memory retrieval     8K
tools                8K
skill                 8K
reserve               8K
```

不一定硬编码这些数字。

关键是：

> **预算应该被管理。**

------

# 二十九、Claude Code 的 Long-running Agent 给 Yuiro 另一个非常重要的启示

Anthropic 在 long-running agent 实验中发现：

> 长任务不能依赖模型“记得之前做过什么”，而应该留下外部 artifact，让下一 context window 能恢复进度。[Anthropic](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents?utm_source=chatgpt.com)

这正好对应 Yuiro 未来主动任务。

------

# 三十、因此 Yuiro 应该增加 Task Journal

不是 Memory。

而是：

```
TaskState
├── goal
├── plan
├── completed_steps
├── current_step
├── artifacts
├── blockers
├── next_actions
└── status
```

比如：

```
用户：
“帮我整理整个 Yuiro 架构。”

Task:
architecture-review

Completed:
✓ inspect agent
✓ inspect speech
✓ inspect memory

Current:
plugin architecture

Next:
compare capability model
```

这和“用户记忆”完全不是一回事。

------

# 三十一、所以必须区分三个东西

```
Conversation Memory
用户和我聊了什么

Relationship Memory
我们之间发生过什么

Task State
我正在做什么
```

当前很多 Agent 系统把这三个混在一起。

Yuiro 应该从一开始避免。

------

# 三十二、Claude Code Checkpoint：非常值得桌面 Agent 吸收

Claude Code 已经提供 checkpoint / rewind，在重要修改之前保存状态，可恢复 code、conversation 或二者。[Anthropic](https://www.anthropic.com/news/enabling-claude-code-to-work-more-autonomously?utm_source=chatgpt.com)

对 Yuiro 来说不应该照搬：

```
Git checkpoint
```

而应该发展：

> **Action Checkpoint / Undo Model**

例如：

```
Tool Operation
      ↓
CanUndo?
      ↓
Checkpoint
      ↓
Execute
```

------

# 三十三、具体可实现为 Tool Transaction

```
ToolExecution
├── dry_run()
├── execute()
├── verify()
└── rollback()
```

例如移动文件：

```
move_files
    ↓
dry_run
    ↓
record original paths
    ↓
execute
    ↓
rollback token
```

用户说：

```
“恢复刚才的操作。”
```

Yuiro：

```
rollback(transaction_id)
```

这比“Approval”又高一个层级。

------

# 三十四、对于 Desktop Agent，这甚至比 coding agent 更重要

因为 Coding Agent 很多修改可以：

```
git diff
git reset
```

桌面 Agent 可能：

```
移动文件
关闭程序
改系统设置
删除数据
修改配置
```

所以 Yuiro 应该有：

```
Approval
+
Checkpoint
+
Rollback
```

三层。

------

# 三十五、OpenCode 给 Yuiro 的另一个价值：Agent Tool Permission 应和 Agent Role 绑定

OpenCode 明确：

```
Build
Plan
General
Explore
```

拥有不同权限；工具权限由 permission system 控制，而不是简单靠 primary/subagent 类型决定。[GitHub](https://github.com/anomalyco/opencode/issues/9297?utm_source=chatgpt.com)

因此未来：

```
ResearchAgent
```

根本不应该拥有：

```
shutdown_process
delete_file
```

即使全局存在这些 Tool。

------

# 三十六、所以 Yuiro Capability Runtime 应该进一步升级成 Agent Capability View

现在我们设计：

```
CapabilityRuntime
      ↓
Tools
```

更准确应该是：

```
Global Tool Registry
         │
         ▼
Capability Policy
         │
      ┌──┴───┐
      ▼      ▼
    Role   Session
      │      │
      └──┬───┘
         ▼
Agent Capability View
         │
         ▼
      LLM Tools
```

因此 Tool discovery 变成动态的。

------

# 三十七、这还解决一个非常现实的问题：Tool Context Explosion

几十个 MCP：

```
filesystem
browser
music
calendar
weather
shell
memory
vision
email
...
```

全部暴露给模型，会浪费大量 context。

OpenCode 近期甚至有专门关于 per-agent MCP tool filtering 和工具上限的讨论，这说明“工具太多”已经是现实工程问题。[GitHub](https://github.com/anomalyco/opencode/issues/28662?utm_source=chatgpt.com)

所以 Yuiro 必须：

```
Tool Registry
 ↓
filter by:
  agent
  capability
  current task
  availability
  permission
 ↓
LLM
```

------

# 三十八、DSH：最值得借鉴的是“Everything is a Plugin”，但只能借一半

DeepSeek Harness 最激进的地方是：

```
Model
Tool
Storage
Agent
UI
Session
...
```

都可以通过插件组合，底层使用 Cordis 构建。第三方资料和当前 DSH 文档均将其核心概括为“一切皆插件”。[dshbase](https://dshbase.com/blog/deepseek-harness-architecture/?utm_source=chatgpt.com)

这很有吸引力。

但 Yuiro **绝不能完全照抄**。

------

# 三十九、为什么？

如果 Yuiro 也做到：

```
AgentLoop = plugin
Session = plugin
Memory = plugin
Speech = plugin
Avatar = plugin
```

你会得到：

> 一个非常灵活的框架。

同时也可能得到：

> 一个难以保证一致生命周期的桌宠。

尤其 Speech：

```
Barge-in
generation
TTS
audio playback
```

要求非常强的一致性。

------

# 四十、所以对 DSH 应该采用“Stable Kernel + Pluggable Edge”

我现在最推荐 Yuiro 的总原则：

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

不能插件化的核心：

```
Session semantics
Generation semantics
Cancellation semantics
Event schema
Security policy
```

其他尽量插件化。

这比 DSH 的“Everything is Plugin”更适合桌宠。

------

# 四十一、DSH 另一个值得借鉴的是 Profile

DSH 当前有：

```
profile = bundle stack + patch layer
```

也就是不同运行环境可以组合不同能力。[GitHub](https://github.com/Electricitysheep/dsh-handbook/blob/main/README.en.md?utm_source=chatgpt.com)

Yuiro 很适合做：

```
Yuiro Profile
```

例如：

```
Normal
Privacy
Study
Coding
Companion
Minimal
```

------

# 四十二、Profile 不只是配置主题

例如：

```
Privacy Profile

network        restricted
screen         denied
memory write   temporary only
system tools   ask
proactive      disabled
```

Coding：

```
filesystem     workspace
shell          sandboxed
memory         project context
subagent       enabled
voice          optional
```

Companion：

```
relationship memory   enabled
proactive interaction enabled
system tools           limited
voice                  enabled
```

这非常有产品价值。

------

# 四十三、现在把七个项目放到同一个维度里

我们现在有：

```
Open-LLM-VTuber
my-neuro
airi
Codex
Claude Code
OpenCode
DSH
```

不要问：

> 谁最好？

应该问：

> 每一个在哪一个 subsystem 上最值得 Yuiro 借鉴？

| 架构问题      | 最有价值参考                | Yuiro 应吸收                             |
| ------------- | --------------------------- | ---------------------------------------- |
| Agent Loop    | Codex / Open-LLM-VTuber     | Harness-managed loop                     |
| Session       | Codex                       | create/resume/fork/event persistence     |
| Plan          | Claude Code                 | Plan → approve → execute                 |
| Cancellation  | airi / Codex                | generation + abort                       |
| Speech        | airi / my-neuro             | intent + barge-in                        |
| Tool Registry | OpenCode / airi             | filtered capability view                 |
| Permission    | Codex / OpenCode            | resource-scoped policy                   |
| Sandbox       | Codex / Claude Code         | filesystem/network containment           |
| Plugin        | DSH / my-neuro              | stable kernel + pluggable edge           |
| Skill         | Claude Code                 | lazy-discovered instruction package      |
| Context       | Codex / Claude Code         | scoped, layered context                  |
| Subagent      | Claude Code / OpenCode      | isolation/parallel/specialization        |
| Long Task     | Claude Code                 | task artifacts/journal                   |
| Checkpoint    | Claude Code                 | reversible effects                       |
| Memory        | airi                        | episodic/semantic/relationship lifecycle |
| Avatar        | airi / my-neuro             | intent + desktop interaction             |
| Security      | Codex / Claude Code + Yuiro | sandbox + approval + audit               |
| Observability | Codex                       | agent-native event timeline              |

这张表其实已经告诉我们：

> **Yuiro 的目标架构不应该是“桌宠项目的加强版”，而应该是“现代 Agent Harness 的具身化版本”。**

------

# 四十四、所以我会重新设计之前的 Yuiro Goal

之前：

```
YuiroRuntime
├── AgentRuntime
├── SpeechRuntime
├── MemoryRuntime
├── AvatarRuntime
└── CapabilityRuntime
```

现在我会升级成：

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

**Harness 应该成为真正的中心。**

------

# 四十五、Harness 负责什么？

非常具体：

```
用户说了一句话
       ↓
SessionRuntime
       ↓
记录 user.message Event
       ↓
TaskClassifier
       ↓
CHAT / ACTION / PLAN / TASK
       ↓
ContextEngine
       ↓
选择 Persona / Memory / Skill / Tool View
       ↓
AgentLoop
       ↓
Tool / Subagent
       ↓
Events
       ↓
Response
       ↓
SpeechIntent
       ↓
AvatarIntent
```

这才是整个 Yuiro 的“大脑周围神经系统”。

------

# 四十六、一个新组件：Task Runtime

这是扩展参照系之后我认为**必须补进 Goal** 的。

现在 Yuiro：

```
AgentRuntime
```

主要适合 turn-level interaction。

未来必须有：

```
TaskRuntime
```

负责跨多个 Agent Turn 的任务。

------

# 四十七、Task 应有自己的状态机

```
CREATED
  ↓
PLANNING
  ↓
WAITING_APPROVAL
  ↓
RUNNING
  ↓
PAUSED
  ↓
VERIFYING
  ↓
COMPLETED
```

异常：

```
CANCELLED
FAILED
BLOCKED
```

这样：

```
“帮我整理 500 个文件”
```

就不会和：

```
“你好”
```

共享同一种生命周期。

------

# 四十八、Task Runtime 和 Agent Runtime 区别

```
AgentRuntime
=
怎么思考和执行一步

TaskRuntime
=
为什么执行、执行到哪里、下一步是什么
```

这和我们前面：

```
Module vs Runtime
```

的区分类似。

------

# 四十九、Subagent 应该挂在 TaskRuntime，而不是随便由 LLM spawn

推荐：

```
TaskRuntime
      │
      ├── Main Agent
      │
      ├── Research Subtask
      │       ↓
      │   ResearchAgent
      │
      └── Verification Subtask
              ↓
          VerifyAgent
```

而不是：

```
LLM:
“我想叫个 Agent。”
 ↓
随便 spawn
```

这样才能控制：

```
预算
权限
并发
取消
上下文
```

------

# 五十、Background Task 值得做，但要晚一点

OpenCode 当前甚至已经支持 subagent background job，而 Claude Code 也将 background tasks 用于长运行进程。[GitHub](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/task.ts?utm_source=chatgpt.com)

Yuiro 未来也非常适合：

```
“你帮我慢慢整理这个文件夹，我先干别的。”
```

Yuiro：

```
Foreground conversation
          │
          │
          └───────────────┐
                          ▼
                   Background Task
                          │
                      Progress
                          │
                     Notification
```

这是桌宠比 coding CLI 更天然的场景。

------

# 五十一、这也是 Yuiro 真正“主动性”的正确实现方式

Proactive 不应该只是：

```
定时随机说句话
```

真正的 Proactive Runtime 应该消费：

```
Task Events
Memory Events
System Events
Calendar Events
User Presence
```

然后决定：

```
是否值得主动打扰用户？
```

------

# 五十二、未来可以有 Attention / Notification Policy

例如：

```
ProactiveIntent

urgency = low
interruptibility = no
channel = avatar
```

Yuiro 只是：

```
抬头
显示气泡
```

而：

```
urgency = high
```

才：

```
TTS
notification
```

这同样可以借用 airi 的 Intent/Priority 思路。

------

# 五十三、Context Compaction 也必须正式化

coding agent 面临的最大工程问题之一就是：

> 长任务 context 会无限增长。

Claude Code 长运行 harness 通过外部 artifacts 跨 context 维持工作进度；Codex 也将 thread persistence 与 event history 独立于单次模型上下文。[Anthropic](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents?utm_source=chatgpt.com)

因此 Yuiro 不应该：

```
session = ever-growing messages
```

------

# 五十四、建议 Context 分成 Cold / Warm / Hot 三层

```
Cold Context
    ↓
Database / event log / memory
    不直接喂模型

Warm Context
    ↓
Task state / summaries / relevant memory
    按需加载

Hot Context
    ↓
当前模型调用真正使用的 prompt
```

也就是：

```
Long-term state
      ≠
LLM context
```

这是一个非常重要的架构原则。

------

# 五十五、Yuiro 的 Memory 系统也应该和 ContextEngine 解耦

现在：

```
Memory.retrieve()
     ↓
Agent prompt
```

以后更理想：

```
MemoryRuntime
     ↓
MemoryCandidates
     ↓
ContextEngine
     ↓
Budget / relevance / scope
     ↓
ContextItems
     ↓
Agent
```

这样 Memory 只负责：

> 找。

ContextEngine 负责：

> 用不用、用多少、放哪里。

------

# 五十六、Tool Result 同样应该 Context-aware

例如工具返回：

```
500 KB JSON
```

绝对不能直接全部塞回 LLM。

应该：

```
Tool Result
    ↓
Artifact Store
    ↓
Result Summary
    ↓
LLM Context
```

需要详细内容时：

```
read artifact slice
```

这会让未来复杂工具调用能力明显增强。

------

# 五十七、Artifact 应成为 Yuiro 新的一等实体

建议增加：

```
Artifact
{
    artifact_id
    type
    source
    task_id
    path/reference
    summary
    metadata
}
```

例如：

```
PDF
Screenshot
Tool output
Generated document
Plan
Report
Code result
```

Agent 不需要一直把 artifact 全内容放在 context 里。

------

# 五十八、因此 Yuiro 最终应该有六个“一等实体”

如果这次要进一步收敛整个架构，我建议围绕：

```
Session
Task
Event
Intent
Artifact
Capability
```

六个实体建模。

这是非常强的架构骨架。

它们分别回答：

| 实体       | 回答的问题                 |
| ---------- | -------------------------- |
| Session    | 我们这次交互属于谁？       |
| Task       | 我正在完成什么目标？       |
| Event      | 已经发生了什么？           |
| Intent     | 下一步想做什么？           |
| Artifact   | 产生/使用了什么对象？      |
| Capability | 我能做什么、被允许做什么？ |

然后：

```
Memory
```

变成长期知识系统。

```
Agent
```

变成决策执行器。

```
Speech / Avatar
```

变成具身输出。

整个架构会非常干净。

------

# 五十九、还有一件我认为 Yuiro 非常应该借 Codex 的东西：App Server 思维

Codex App Server 的意义是：

> 核心 Agent Harness 不应该绑定某一个 UI；CLI、IDE、其他客户端都应该调用同一个 core/runtime。[OpenAI](https://openai.com/index/unlocking-the-codex-harness/?utm_source=chatgpt.com)

Yuiro现在其实已经有这个天然优势：

```
Electron
 ↓ WebSocket
Python Engine
```

所以你完全可以继续坚持：

```
Yuiro Engine
≠
Yuiro Desktop UI
```

------

# 六十、未来甚至可以自然支持

```
Yuiro Desktop
       │
Yuiro CLI
       │
Mobile Remote
       │
Web Control Panel
       │
       ▼
 Yuiro Harness
```

不要求现在做。

但架构上不要堵死。

这也是为什么 Python Engine 应该继续保持 UI-independent。

------

# 六十一、对 DSH 的 UI Plugin 思路也可以适度吸收

DSH 比较特殊的一点是 host/client plugin 可以同时扩展后端能力和前端 UI。[GitHub](https://github.com/Electricitysheep/dsh-handbook/blob/main/README.en.md?utm_source=chatgpt.com)

Yuiro Plugin 以后也可以：

```
Plugin Package
├── engine/
│   └── tools
└── shell/
    └── widget
```

例如音乐插件：

```
engine:
search_song
play_song
pause

shell:
mini-player
album art
lyrics
```

这个非常适合桌宠。

------

# 六十二、但绝对不能让 Plugin 随便注入任意 UI/系统权限

应该：

```
Plugin Manifest
├── capabilities
├── engine entry
├── UI contributions
├── permissions
└── configuration schema
```

例如：

```
permissions:
  network:
    - music.163.com

capabilities:
  - music.search
  - music.play

ui:
  widgets:
    - player
```

由 Runtime 控制。

------

# 六十三、最终我会把原来的 Yuiro Goal 增加 10 个新能力

如果只说最值得实现的，不做无限扩张，就是：

1. **Persistent AgentSession + Event Log**
2. **TaskRuntime / Plan Mode**
3. **Plan-level Approval**
4. **Sandbox + Resource-scoped Permissions**
5. **Agent Profiles + Subagents**
6. **Hooks**
7. **Lazy Agent Skills**
8. **ContextEngine + Context Budget**
9. **Artifact Store + Checkpoint/Rollback**
10. **Background Task + Task Journal**

其中最优先的其实不是 Subagent。

而是：

```
Session/Event
Context
Task
Sandbox
```

------

# 六十四、我现在会重新调整 Yuiro 的开发优先级

过去我说：

```
P0 Cancellation
P1 Agent/Speech
P2 Memory
P3 Plugin
```

现在应该变成：

```
                            当前 Yuiro
                                │
                                ▼
               P0 Harness Foundation
               Session / Event / Cancellation
                                │
                                ▼
                  P1 Context Engine
               context source / budget / skill
                                │
                                ▼
                    P1 Task Runtime
               plan / state / checkpoint
                                │
                                ▼
          P1 Speech + Avatar Runtime 接入 Harness
                                │
                                ▼
                   P2 Security Runtime
             sandbox / permissions / capability
                                │
                                ▼
                   P2 Memory Lifecycle
                episode / semantic / relationship
                                │
                                ▼
                    P2 Subagent
           parallel / isolation / verification
                                │
                                ▼
                    P3 Plugin / Hooks
                                │
                                ▼
                 P3 Background Agent
```

------

# 六十五、这里要特别防止一个误区

看 Claude Code、Codex、DSH 很容易产生一种感觉：

> “Yuiro 也应该有多 Agent、后台 Agent、十几个 Skill、插件平台。”

不是。

这些都是：

```
Capability
```

而不是：

```
Architecture
```

真正应该优先复制的是这些产品背后的**控制结构**：

```
Session ownership
Context ownership
Task ownership
Permission ownership
Cancellation ownership
```

谁拥有这些，才是真正决定系统能否扩展的东西。

------

# 六十六、所以最终 Yuiro 可以被重新定义为四层

```
┌──────────────────────────────────────────────┐
│ EXPERIENCE LAYER                             │
│ Desktop / Chat / Voice / Live2D / Proactive │
├──────────────────────────────────────────────┤
│ EMBODIMENT RUNTIME                           │
│ Speech / Avatar / Emotion / Presence         │
├──────────────────────────────────────────────┤
│ AGENT HARNESS                                │
│ Session / Task / Event / Context / Agent     │
│ Skill / Subagent / Artifact / Cancellation   │
├──────────────────────────────────────────────┤
│ CAPABILITY & EXECUTION                       │
│ Tools / Plugins / MCP / Sandbox / Policy     │
│ SystemDaemon / Providers / Storage           │
└──────────────────────────────────────────────┘
```

这比之前：

```
AgentRuntime
SpeechRuntime
MemoryRuntime
...
```

更高一个抽象层次。

------

# 六十七、桌宠项目和 Coding Agent 两组参考其实正好互补

现在终于可以把它们完整地对应起来：

```
               CODING AGENTS
               ─────────────
Codex            Session / Harness / Security
Claude Code      Plan / Skill / Hook / Checkpoint
OpenCode         Agent Role / Permission / Subagent
DSH              Plugin Composition / Profiles
                         │
                         │
                         ▼
                   YUIRO HARNESS
                         ▲
                         │
                         │
              DESKTOP AGENTS
              ──────────────
airi              Speech Intent / Memory / Runtime
my-neuro          Barge-in / Live2D / Plugin UX
Open-LLM-VTuber   Tool Loop / MCP / TTS queue
```

上面一组回答：

> **Agent 怎样可靠工作。**

下面一组回答：

> **Agent 怎样像角色一样生活。**

而 Yuiro 的差异化恰恰就在二者结合。

------

# 六十八、如果最后只保留一个总目标

我会把之前的 Goal 中：

> “建立多个 Runtime”

升级成：

> **Build Yuiro as an embodied agent harness.**

翻成具体架构语言就是：

```
一个具有：

Persistent Session
Task Lifecycle
Event Sourcing
Context Management
Agent Loop
Tool / Capability
Permission / Sandbox
Skill / Plugin
Memory Lifecycle
Cancellation

的 Agent Harness

+

具有：

Realtime Voice
Barge-in
Speech Intent
Avatar Intent
Emotion
Relationship
Proactive Presence

的 Embodiment Runtime。
```

这比单纯“做一个 airi 加强版”要有前景得多。

------

# 六十九、基于当前 Yuiro，我建议真正落地的第一轮改造

不是一下实现所有这些。

第一轮只做：

```
                    SessionRuntime
                          │
                ┌─────────┼─────────┐
                ▼         ▼         ▼
              Event     Task    Cancellation
                │         │         │
                └─────────┼─────────┘
                          ▼
                    ContextEngine
                          │
                          ▼
                     AgentLoop
```

同时保留当前：

```
VoicePipeline
Memory
ToolRegistry
SystemDaemon
Live2D
```

只通过 Adapter 接进来。

这样是**增量升级**，不是大改重构。

第二轮再做：

```
Plan
Artifact
Checkpoint
Skill
Capability View
```

第三轮：

```
Subagent
Background Task
Plugin hooks
Relationship consolidation
```

------

# 七十、对四个新参照系的最终取舍

**Codex：强烈借鉴。** 特别是 Thread/Session、App Server/Core 边界、Event persistence、Sandbox + Approval、Agent-native telemetry。Codex 的公开架构资料是目前四者里对 Yuiro 核心 Harness 最直接的参考。[OpenAI](https://openai.com/index/unrolling-the-codex-agent-loop/?utm_source=chatgpt.com)

**Claude Code：强烈借鉴。** 特别是 Plan Mode、Checkpoint、Hooks、Skills、Subagents、长任务 artifact，以及安全 sandbox。不要照搬 coding-specific Git/worktree 语义，要转换成 Desktop Task/Transaction 语义。[Anthropic](https://www.anthropic.com/engineering/claude-code-sandboxing?utm_source=chatgpt.com)

**OpenCode：选择性强烈借鉴。** Agent Profile、Primary/Subagent、权限和 Tool 可见性分离、LLM Runtime adapter 边界很适合 Yuiro；但其产品核心仍是 coding session，不应该照抄 Build/Plan 等具体角色。[GitHub](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/llm/AGENTS.md?utm_source=chatgpt.com)

**DeepSeek Harness：借思想，不追实现。** 它的 plugin composition、profile、host/client extension 非常适合启发 Yuiro 的插件生态，但截至 2026 年 9 月仍很新，第三方实测也明确标注其 developer-preview / breaking-change 风险，所以现在不建议把 Cordis 或“一切皆插件”作为 Yuiro 核心依赖。[GitHub](https://github.com/Electricitysheep/dsh-handbook/blob/main/README.en.md?utm_source=chatgpt.com)

------

如果把这次扩展后的架构判断压缩成一句话：

> **Yuiro 下一阶段真正应该建设的，不再是“更多 Agent 功能”，而是一个 Codex/Claude Code 级别的 Harness Kernel，再把 airi/my-neuro 级别的语音、Avatar、Memory 和关系能力挂在这个 Kernel 上。**

也就是说，Yuiro 的长期路线最好从：

```
AI Desktop Pet
```

升级为：

```
Embodied Personal Agent
        =
General Agent Harness
        +
Realtime Embodiment Runtime
        +
Long-term Relationship Memory
        +
Safe Desktop Capabilities
```

这个定位也会直接改变我上一轮那份 `ARCHITECTURE_GOAL.md`：**应该把 Session/Event/Task/Context/Artifact/Capability 六个一等实体，以及 Plan、Checkpoint、Sandbox、Hooks、Skills、Subagent 纳入正式 Goal，而不仅仅围绕几个 Runtime 做模块重构。**