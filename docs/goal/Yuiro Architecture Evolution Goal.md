有。并且我建议这次不要再给 IDE 一份“架构建议说明书”，而是给它一份**可执行的 Architecture Goal / Engineering Goal**。

核心思想是：

> **不推倒 Yuiro 当前代码，而是在现有 Electron + Python Engine + C++ SystemDaemon 基础上，把现有功能模块升级成具有统一生命周期、取消协议、事件/Intent 协议和持久化记忆生命周期的 Agent Runtime。**

下面这份可以直接作为编码 IDE 的长期 Goal。它不是“让 IDE 自己发挥”，而是明确**目标架构、改造原则、边界、优先级、验收标准以及禁止事项**。

# Yuiro Architecture Evolution Goal

## 0. Goal Definition

在不推翻当前 Yuiro 基础架构、不进行无必要的大规模重写的前提下，将 Yuiro 从：

> “功能较完整的 AI Desktop Pet”

逐步升级为：

> “具有统一 Session Runtime、Agent Runtime、Realtime Speech Runtime、Memory Runtime、Avatar Runtime、Capability Runtime 与安全 System Runtime 的本地 AI Agent Desktop Runtime”。

当前 Yuiro 已经具备：

- Electron Shell
- Python Engine
- C++ SystemDaemon
- Agent Tool Loop
- LLM
- VAD
- ASR
- TTS
- Barge-in
- Live2D
- Emotion
- Proactive Interaction
- Vector + FTS Memory
- RRF Retrieval
- Tool Registry
- Approval / Audit / Dry-run
- Plugin / Skill 架构骨架
- TOML + Pydantic 配置体系

因此，本次升级**不是增加大量新功能**。

核心目标是：

> **把已有功能从“彼此独立的模块”升级为“具有统一生命周期和运行时契约的协同 Runtime”。**

------

# 1. Non-Negotiable Architectural Principles

## 1.1 不推倒重来

必须优先复用当前代码。

禁止为了引入新架构而：

- 重写 AgentLoop
- 重写 Memory
- 重写 VoicePipeline
- 重写 Live2D
- 重写 SystemDaemon
- 引入重量级框架替换现有基础设施

除非现有代码明确无法满足目标。

优先采用：

```
existing implementation
        ↓
extract abstraction
        ↓
adapt existing implementation
        ↓
replace call path
```

而不是：

```
existing implementation
        ↓
delete
        ↓
rewrite
```

------

# 2. Target Architecture

最终目标：

```
                         YUIRO
                           │
                    YuiroRuntime
                           │
                 Session / Lifecycle
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
 AgentRuntime        SpeechRuntime       AvatarRuntime
        │                  │                  │
        │                  │                  │
   Context/LLM          VAD/ASR/TTS       Motion/Emotion
   ToolLoop             Playback          Live2D
   Generation           Interrupt         Expression
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                    MemoryRuntime
                           │
                 ┌─────────┼─────────┐
                 ▼         ▼         ▼
              Episode     Fact   Relationship
                 │         │         │
                 └─────────┼─────────┘
                           ▼
                    Retrieval / RRF
                           │
                           ▼
                    CapabilityRuntime
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          Builtin       Plugin        Skill
              │            │            │
              └────────────┼────────────┘
                           ▼
                    Security Policy
                           │
                           ▼
                    SystemDaemon
```

------

# 3. Runtime 的统一定义

这里的 Runtime 不是简单的 Python module。

每一个 Runtime 必须承担：

```
State
Lifecycle
Concurrency
Coordination
```

即：

### State

知道自己当前状态。

### Lifecycle

支持：

```
initialize
start
ready
run
interrupt
stop
shutdown
```

### Concurrency

明确：

- 当前 task
- task owner
- generation
- cancellation
- stale result

### Coordination

可以响应：

- user event
- system event
- session event
- interrupt
- shutdown
- capability change

------

# 4. 建立统一 Session Runtime

新增或逐步抽象：

```
YuiroRuntime
└── SessionManager
    └── AgentSession
```

建议 Session 至少拥有：

```
session_id
generation
abort_controller / cancellation_token
state
created_at
updated_at
active_tasks
```

最终所有 Agent / Speech / Avatar / Tool 任务都应该能够关联：

```
session_id
generation
task_id
```

------

# 5. Generation Protocol

当前 Agent 已经具有 generation 机制。

保留并扩大其作用。

统一定义：

```
generation = logical conversation generation
```

每当用户开始新的有效交互：

```
generation++
```

旧 generation 的异步结果：

```
MUST NOT mutate current state
MUST NOT enter current conversation
MUST NOT enter current memory
MUST NOT enter current TTS queue
MUST NOT trigger current avatar action
```

即：

```
generation mismatch
        ↓
stale result
        ↓
discard
```

------

# 6. Cancellation Protocol

Generation 不能代替真正的 cancellation。

必须形成：

```
Generation
+
Cancellation
```

双层机制。

目标：

```
User Barge-in
      │
      ▼
Session.cancel()
      │
      ├── cancel LLM
      ├── cancel Tool
      ├── cancel TTS
      ├── stop playback
      ├── cancel avatar action
      └── invalidate generation
```

其中：

### Cancellation

负责：

> 尽可能真正停止正在运行的任务。

### Generation

负责：

> 即使旧任务无法立即停止，其返回结果也绝不能污染当前状态。

------

# 7. AgentRuntime

当前 AgentLoop 是核心基础，不重写。

逐步演化：

```
AgentRuntime
├── Session
├── ContextBuilder
├── LLMClient
├── ToolLoop
├── GenerationController
├── CancellationController
├── OutputStream
└── MemoryBridge
```

AgentRuntime 负责：

```
user input
    ↓
context construction
    ↓
memory retrieval
    ↓
LLM
    ↓
tool calls
    ↓
tool results
    ↓
LLM continuation
    ↓
final response
```

------

# 8. 保留当前 AgentLoop 的优秀机制

必须保留：

- tool round limit
- tool failure limit
- successful tool deduplication
- parallel tool execution
- result ordering
- no-progress termination
- generation checking
- final summarization

不要为了 Runtime 抽象而削弱这些机制。

------

# 9. Agent Tool Loop 的最终状态模型

目标：

```
IDLE
 ↓
THINKING
 ↓
TOOL_CALLING
 ↓
TOOL_RESULT
 ↓
THINKING
 ↓
RESPONDING
 ↓
COMPLETED
```

任何阶段都允许：

```
INTERRUPTED
CANCELLED
FAILED
```

例如：

```
THINKING
   ↓
BARGE_IN
   ↓
CANCELLED
```

而不是：

```
TTS stopped
but LLM continues invisibly
```

------

# 10. SpeechRuntime

当前 VoicePipeline、VAD、ASR、TTS、TTSTaskManager 均保留。

最终统一：

```
SpeechRuntime
├── VAD
├── ASR
├── SpeechIntent
├── TTS
├── TTSTaskManager
├── Playback
└── InterruptController
```

------

# 11. Speech Pipeline

最终目标：

```
Microphone
    ↓
PCM
    ↓
VAD
    ↓
Speech Segment
    ↓
ASR
    ↓
User Utterance
    ↓
AgentRuntime
    ↓
Response Stream
    ↓
Sentence Segmenter
    ↓
TTSTaskManager
    ↓
Ordered Audio
    ↓
Playback
```

------

# 12. VAD

保留当前：

- Silero
- probability threshold
- dB threshold
- smoothing
- required hits
- required misses
- PCM buffering
- fixed model window

不要为了抽象 Runtime 重写 VAD。

VAD 只负责：

> 判断“用户是否正在讲话”。

不要让 VAD 直接负责：

- Agent
- Memory
- TTS
- Avatar

这些交由 SpeechRuntime 协调。

------

# 13. ASR

ASR 只负责：

```
audio
 ↓
transcription
```

必须携带：

```
session_id
generation
timestamp
```

ASR 不应该直接修改：

- Agent history
- Memory
- Emotion
- Avatar

由 Runtime 统一协调。

------

# 14. TTS

当前 TTSTaskManager 是重要基础设施。

必须真正接入当前 VoicePipeline 的核心执行路径。

目标：

```
Agent streaming output
        ↓
Sentence segmentation
        ↓
TTSTaskManager
        ↓
seq=0
seq=1
seq=2
...
        ↓
Ordered Playback
```

要求：

- 支持并行 synthesis
- 支持顺序 playback
- 支持 epoch invalidation
- 支持 cancellation
- 支持 stale audio suppression

------

# 15. TTS Epoch

保留当前 epoch 思路。

每次 interrupt：

```
epoch++
buffer.clear()
cancel current task
```

旧 epoch 的音频：

```
MUST NEVER PLAY
```

------

# 16. SpeechIntent

引入统一的 SpeechIntent 概念。

例如：

```
SpeechIntent(
    session_id=...,
    generation=...,
    text=...,
    priority=...,
    interruptible=True,
)
```

SpeechRuntime 不再只是：

```
tts.synthesize(text)
```

而是：

```
SpeechIntent
    ↓
SpeechRuntime
    ↓
TTS Task
    ↓
Playback
```

------

# 17. Barge-in

Barge-in 必须成为跨 Runtime 操作。

目标：

```
User starts speaking
        ↓
SpeechRuntime detects VAD
        ↓
Session interrupt
        ↓
AgentRuntime.cancel()
        ↓
SpeechRuntime.stop_tts()
        ↓
Playback.stop()
        ↓
AvatarRuntime.cancel_speech_action()
        ↓
generation++
        ↓
new user turn
```

禁止只调用：

```
voice_pipeline.interrupt()
```

然后让 Agent 在后台继续运行。

------

# 18. AvatarRuntime

当前 Live2DCanvas 不需要重写。

新增 Runtime abstraction：

```
AvatarRuntime
├── AvatarIntent
├── Expression
├── Motion
├── LipSync
├── Priority
└── Cancellation
```

Renderer 只负责：

```
AvatarIntent
    ↓
Live2D
```

而不是由 Agent 直接控制 Live2D API。

------

# 19. AvatarIntent

统一：

```
AvatarIntent(
    source="agent|emotion|speech|system",
    generation=...,
    emotion=...,
    expression=...,
    motion=...,
    priority=...,
    duration=...
)
```

来源包括：

```
Agent
Emotion
Speech
System
User Interaction
```

------

# 20. Avatar Priority

至少支持：

```
SYSTEM
USER_INTERACTION
SPEECH
EMOTION
IDLE
```

高优先级可以打断低优先级。

例如：

```
IDLE animation
       ↓
USER interaction
       ↓
override
```

Barge-in：

```
Speaking animation
       ↓
cancel
       ↓
Listening animation
```

------

# 21. MemoryRuntime

当前 Memory Retrieval 基础必须保留：

- Vector
- FTS
- RRF
- Recency
- Salience
- Facts
- BGE-M3

不要推倒。

真正需要升级的是：

> Memory Lifecycle。

------

# 22. Memory Lifecycle

最终目标：

```
Current Turn
    ↓
Short-Term Memory
    ↓
Episode
    ↓
Consolidation
    ↓
Semantic Memory
    ↓
Fact Memory
    ↓
Relationship Memory
```

不要让每次 conversation 都直接等价于长期 Memory。

------

# 23. Memory 类型

至少形成：

### Short-Term

当前上下文。

### Episodic

发生过的具体事件。

例如：

```
2026-09-08
用户完成毕业论文
```

### Semantic

长期稳定知识。

例如：

```
用户长期使用 C++
```

### Fact

结构化事实。

### Relationship

人与 Agent 之间形成的经历和关系。

例如：

```
共同讨论过某个项目
用户曾经遇到某个问题
某个事件对用户意义重大
```

------

# 24. Memory Consolidation

不要每轮都复杂化。

建议异步：

```
Conversation
    ↓
Short-term
    ↓
async consolidation
    ↓
Episode / Fact / Relationship
```

Consolidation 不能阻塞用户正常聊天。

------

# 25. Memory Retrieval

当前 RRF 继续保留：

```
Vector
FTS
Recent
Salience
```

最终：

```
query
 ↓
parallel retrieval
 ├── vector
 ├── FTS
 ├── recency
 └── salience
        ↓
      RRF
        ↓
  reranking/filter
        ↓
      context
```

------

# 26. Memory Write Safety

只有：

```
current generation
```

允许写入当前 Memory。

旧 generation 的：

- LLM result
- tool result
- TTS result
- summary

不能进入当前 Memory。

------

# 27. Relationship + Emotion

当前 Emotion 中的：

```
affinity
xp
level
attributes
```

继续保留。

但不要让 affinity 单独代表关系记忆。

目标：

```
Experience
    ├── semantic importance
    ├── emotional intensity
    ├── relationship relevance
    ├── novelty
    └── recurrence
             ↓
        Memory Runtime
```

最终让：

```
Emotion
+
Memory
+
Relationship
```

形成闭环。

------

# 28. CapabilityRuntime

当前 Tool Registry 和 SystemDaemon 保留。

最终统一：

```
CapabilityRuntime
├── Builtin Tools
├── SystemDaemon Tools
├── Plugins
└── Skills
```

Tool 是具体能力。

Capability 是：

> Agent 在当前环境中“允许并可用”的能力集合。

------

# 29. Capability Schema

建议形成：

```
Capability(
    name,
    tools,
    permissions,
    required_env,
    approval_required,
    availability
)
```

例如：

```
filesystem
    ├── read_file
    ├── write_file
    └── list_directory

system
    ├── open_app
    ├── process_control
    └── media_control
```

------

# 30. Security Boundary

必须保持：

```
Agent
 ↓
Tool
 ↓
Capability
 ↓
Policy
 ↓
Approval
 ↓
SystemDaemon
```

禁止：

```
LLM
 ↓
arbitrary OS command
```

SystemDaemon 继续作为：

> OS capability security boundary。

------

# 31. Approval

继续保留：

- approval
- dry-run
- trace_id
- audit
- sensitive tool policy
- path traversal protection

未来所有高风险 Capability 都必须经过统一 Policy。

------

# 32. Plugin Runtime

当前 Plugin Manager / JSON-RPC Bridge 为基础。

第一阶段只实现稳定生命周期：

```
Plugin
 ↓
load
 ↓
initialize
 ↓
ready
 ↓
execute
 ↓
shutdown
```

插件必须具备：

```
plugin_id
version
capabilities
tools
configuration
health
```

------

# 33. Plugin 与 Tool 的关系

不要形成：

```
Plugin system
Tool system
Skill system
```

三套互相平行的生态。

统一：

```
Plugin
   ↓
Capability
   ↓
Tool
```

------

# 34. Skill Runtime

Skill 的定位不是 Plugin。

Skill 是：

> Agent workflow / instruction / behavior package。

目标：

```
Skill
 ↓
Instructions
 ↓
Capability / Tools
 ↓
Agent execution
```

例如：

```
research.skill
coding.skill
music.skill
system-management.skill
```

------

# 35. Skill 不应拥有自己的 Tool Runtime

Skill 应调用：

```
CapabilityRuntime
```

而不是自行维护另一套 Tool Registry。

------

# 36. Configuration Architecture

当前：

```
AppConfig
```

继续作为配置入口。

短期不要重构。

随着系统扩大，可以逻辑分组：

```
RuntimeConfig
├── AgentConfig
├── SpeechConfig
├── MemoryConfig
├── AvatarConfig
├── ToolConfig
├── SystemConfig
└── ProactiveConfig
```

保持：

```
Pydantic
+
TOML
+
frontend schema
```

------

# 37. Composition Root

当前 `main.py` 的：

```
_build_agent()
_build_memory()
_build_voice()
_build_daemon()
```

属于正确方向。

最终将其明确为：

```
YuiroRuntime.create(config)
```

负责：

```
configuration
 ↓
dependency construction
 ↓
runtime initialization
```

而不是让 `main.py` 承担业务逻辑。

------

# 38. Event / Intent Architecture

不要让所有模块互相直接调用。

推荐：

```
User Event
     ↓
Runtime
     ↓
Intent
     ↓
Capability / Effect
```

例如：

```
User starts speaking
        ↓
SpeechEvent
        ↓
SpeechRuntime
        ↓
InterruptIntent
        ↓
SessionRuntime
```

------

# 39. Event 与 Intent 的区别

Event：

> 已经发生的事情。

例如：

```
UserSpeechStarted
TTSStarted
ToolCompleted
BargeInDetected
```

Intent：

> 系统希望执行的动作。

例如：

```
CancelAgent
SpeakText
PlayMotion
RetrieveMemory
ExecuteTool
```

不要混用。

------

# 40. Runtime Communication

优先：

```
explicit interface
+
typed event / intent
```

不要过早引入 Kafka / Redis / message broker。

当前单机桌宠没有必要。

Python Engine 内部可以先采用：

```
asyncio
typed dataclass
queue
event dispatcher
```

------

# 41. Observability

所有跨 Runtime 操作尽可能具备：

```
trace_id
session_id
generation
task_id
runtime
event
duration
status
```

例如：

```
trace=abc123
session=s001
generation=42
runtime=AgentRuntime
event=tool_call
tool=read_file
status=success
duration=34ms
```

这会极大提高后期调试能力。

------

# 42. State Machine

不要让状态散落在：

```
boolean
None
magic string
```

例如：

```
speaking=True
recording=False
locked=True
```

逐步统一成显式状态。

Speech：

```
IDLE
LISTENING
TRANSCRIBING
THINKING
SPEAKING
INTERRUPTED
```

Agent：

```
IDLE
THINKING
TOOL_CALLING
RESPONDING
CANCELLED
COMPLETED
FAILED
```

Avatar：

```
IDLE
LISTENING
THINKING
SPEAKING
INTERACTING
INTERRUPTED
```

------

# 43. Error Handling

Runtime 必须区分：

```
Cancelled
Timeout
ToolFailure
LLMFailure
SpeechFailure
StaleResult
ConfigurationError
SecurityDenied
```

禁止：

```
except Exception:
    pass
```

尤其不能吞掉 cancellation。

------

# 44. Cancellation Exception

Cancellation 必须是正常控制流，不应该被当作系统错误。

例如：

```
User Barge-in
 ↓
Cancelled
```

不是：

```
ERROR
 ↓
stack trace
```

日志级别应该能够区分：

```
expected cancellation
vs
unexpected failure
```

------

# 45. Testing Goal

架构升级不能只测试函数。

必须加入 Runtime-level tests。

至少测试：

### Agent

```
LLM
Tool
Tool loop
generation
cancel
stale result
```

### Speech

```
VAD
ASR
TTS
interrupt
epoch
ordered playback
```

### Memory

```
write
retrieve
consolidation
stale generation
```

### Avatar

```
intent
priority
interrupt
```

------

# 46. 必须测试最重要的 Race Conditions

例如：

```
LLM response arrives
while user starts speaking
TTS segment 2 arrives
after interrupt
Tool returns
after Agent cancellation
Memory consolidation finishes
after session reset
Avatar animation callback
after generation invalidation
```

所有这些都必须：

```
NOT corrupt current state
```

------

# 47. Runtime Contract

每个 Runtime 最终至少应该满足：

```
initialize()
start()
state()
handle_event()
cancel()
shutdown()
```

不要求所有 Runtime 完全相同实现，但生命周期语义必须一致。

------

# 48. Implementation Priority

严格按照以下顺序执行。

## P0 — Runtime Foundation

1. Session
2. generation
3. cancellation
4. task ownership
5. lifecycle
6. trace_id

这是整个升级最重要的基础。

------

## P1 — Agent Runtime

1. 将现有 AgentLoop 纳入 AgentRuntime
2. 统一 generation
3. 引入真正的 cancellation
4. Tool cancellation
5. stale-result protection
6. memory write protection

------

## P1 — Speech Runtime

1. 统一 VoicePipeline
2. 真正接入 TTSTaskManager
3. SpeechIntent
4. TTS epoch
5. ordered playback
6. Barge-in
7. Agent cancellation linkage

------

## P1 — Avatar Runtime

1. AvatarIntent
2. motion priority
3. speech lip-sync
4. emotion integration
5. interrupt
6. Live2D adapter

------

## P2 — Memory Runtime

1. Short-term
2. Episode
3. Fact
4. Semantic
5. Relationship
6. async consolidation
7. retrieval pipeline

------

## P2 — Capability Runtime

1. Capability abstraction
2. Tool grouping
3. permission
4. availability
5. approval
6. SystemDaemon integration

------

## P3 — Plugin Runtime

1. lifecycle
2. JSON-RPC bridge
3. capability registration
4. tool registration
5. health
6. configuration
7. hot reload only if necessary

------

## P3 — Skill Runtime

1. SKILL metadata
2. instruction loading
3. workflow
4. capability access
5. script execution
6. isolation

------

# 49. Explicitly DO NOT Do

禁止以下行为：

## 49.1 不要为了架构而架构

不要：

```
100 个 interface
50 个 abstract class
```

却没有解决：

```
cancellation
lifecycle
race condition
```

------

## 49.2 不要过早微服务化

不要拆成：

```
Agent Service
Speech Service
Memory Service
Avatar Service
```

然后通过网络通信。

当前桌宠是单机应用，没有必要。

------

## 49.3 不要引入重量级 Message Broker

不要为了 Event Architecture 引入：

```
Kafka
RabbitMQ
Redis Streams
```

当前：

```
asyncio Queue
Event Dispatcher
```

足够。

------

## 49.4 不要推倒 Memory

当前：

```
Vector + FTS + RRF
```

是正确基础。

升级生命周期，而不是重写检索。

------

## 49.5 不要推倒 AgentLoop

当前 Tool Loop 已经比较成熟。

主要增加：

```
Runtime
Cancellation
Lifecycle
```

而不是重新设计 ReAct。

------

## 49.6 不要把所有东西都 Event 化

例如：

```
Agent → Tool
```

明确同步调用完全可以。

只有：

```
跨 Runtime
生命周期
用户事件
异步状态变化
```

才优先使用 Event / Intent。

------

# 50. Target Directory Direction

不要求一次性完成目录重构。

长期可以逐步形成：

```
engine/yuiro/
│
├── runtime/
│   ├── __init__.py
│   ├── session.py
│   ├── lifecycle.py
│   ├── cancellation.py
│   └── events.py
│
├── agent/
│   ├── runtime.py
│   ├── loop.py
│   ├── context.py
│   └── ...
│
├── speech/
│   ├── runtime.py
│   ├── vad.py
│   ├── asr.py
│   ├── tts.py
│   ├── playback.py
│   └── intent.py
│
├── avatar/
│   ├── runtime.py
│   ├── intent.py
│   └── ...
│
├── memory/
│   ├── runtime.py
│   ├── retrieval.py
│   ├── consolidation.py
│   ├── episode.py
│   ├── facts.py
│   └── relationship.py
│
├── capability/
│   ├── runtime.py
│   ├── registry.py
│   ├── policy.py
│   └── ...
│
├── plugins/
├── skill/
└── systemd/
```

但是：

> **目录结构不是第一目标。Runtime Contract 才是第一目标。**

如果现有目录结构可以实现目标，则不要为了“看起来漂亮”而移动大量文件。

------

# 51. Definition of Done

一个阶段只有在满足以下条件后才算完成。

## Agent

能够：

```
用户输入
 ↓
Agent
 ↓
LLM
 ↓
Tool
 ↓
LLM
 ↓
Response
```

同时：

```
用户打断
 ↓
Agent cancellation
 ↓
旧 LLM 不再污染状态
```

------

## Speech

能够：

```
VAD
 ↓
ASR
 ↓
Agent
 ↓
TTS
 ↓
Playback
```

同时：

```
用户开始讲话
 ↓
Barge-in
 ↓
TTS stop
 ↓
Agent cancel
 ↓
旧音频全部 invalid
```

------

## Memory

能够：

```
conversation
 ↓
short-term
 ↓
episode
 ↓
consolidation
 ↓
long-term
```

并且：

```
旧 generation
 ↓
不能写当前 Memory
```

------

## Avatar

能够：

```
Agent
 ↓
AvatarIntent
 ↓
Live2D
```

并且：

```
Speaking
 ↓
Barge-in
 ↓
Speaking animation cancelled
 ↓
Listening animation
```

------

## Tools

能够：

```
Agent
 ↓
Capability
 ↓
Policy
 ↓
Approval
 ↓
Tool
 ↓
SystemDaemon
```

并具备：

```
trace_id
audit
permission
cancellation
```

------

# 52. Final Architectural Goal

最终 Yuiro 不应该只是：

```
Electron
 +
Python
 +
LLM
 +
TTS
 +
Live2D
```

而应该成为：

```
                  YUIRO AGENT RUNTIME

                         Session
                           │
                    Lifecycle / Cancel
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
     AgentRuntime     SpeechRuntime    AvatarRuntime
          │                │                │
          └────────────────┼────────────────┘
                           │
                     MemoryRuntime
                           │
                     CapabilityRuntime
                           │
                      Security Policy
                           │
                     SystemDaemon
```

其核心运行模型：

```
Event
  ↓
Session
  ↓
Runtime
  ↓
Intent
  ↓
Task
  ↓
Effect
  ↓
Event
```

同时所有异步工作必须具备：

```
session_id
generation
task_id
cancellation
trace_id
```

最终形成：

> **可运行、可取消、可追踪、可恢复、可扩展、可组合的本地 Agent Runtime。**

------

# 53. Implementation Philosophy

在任何具体编码任务中，IDE Agent 必须遵循以下判断顺序：

```
1. 当前代码是否已经解决这个问题？
        ↓
2. 能否抽象现有实现？
        ↓
3. 能否通过 Adapter 接入新 Runtime？
        ↓
4. 能否增量迁移？
        ↓
5. 最后才考虑重写。
```

每次修改前必须回答：

```
这个修改解决的是：
A. 功能缺失？
B. Runtime 生命周期问题？
C. 并发 / cancellation 问题？
D. 架构耦合问题？
E. 安全问题？
F. 可维护性问题？
```

如果只是为了“让代码看起来更高级”，不要修改。

------

# 54. Highest Priority Principle

如果实现过程中资源有限，不要平均分配精力。

优先级必须是：

```
P0
统一 Session / Generation / Cancellation
        ↓
P1
Agent + Speech Runtime
        ↓
P1
Barge-in / Race Condition
        ↓
P1
AvatarIntent
        ↓
P2
Memory Lifecycle
        ↓
P2
Capability
        ↓
P3
Plugin / Skill
```

**不要先开发 Plugin，再解决 Cancellation。**

**不要先增加 Live2D 动作，再解决 Agent stale result。**

**不要先增加 Memory Retrieval 算法，再解决 Memory Lifecycle。**

------

# 55. Ultimate Success Criterion

当 Yuiro 最终可以自然地处理下面这个场景时，说明本次架构升级真正成功：

```
用户：
“帮我查一下今天的天气。”

        ↓

Agent
        ↓
Memory / Context
        ↓
Tool Call
        ↓
System / External Capability
        ↓
LLM
        ↓
开始流式回答
        ↓
TTS
        ↓
Live2D Speaking
        ↓
用户突然开始讲话
        ↓
VAD
        ↓
Barge-in
        ↓
Session.cancel()
        ├── LLM cancel
        ├── Tool cancel
        ├── TTS cancel
        ├── Playback stop
        ├── Avatar cancel
        └── generation++
        ↓
旧结果全部失效
        ↓
ASR
        ↓
新的 Agent Turn
        ↓
Memory 正确记录
        ↓
Avatar 根据新的 Intent 行动
```

整个过程中：

> **不存在旧 LLM 结果污染新对话、旧音频继续播放、旧 Tool 修改当前状态、旧 Avatar 动作覆盖新状态、旧 Memory 写入当前会话等问题。**

这才是 Yuiro Runtime Architecture 升级完成的最终标准。

这套 Goal **最适合放在 IDE 项目的根目录**，例如：

```
Yuiro/
├── ARCHITECTURE_GOAL.md      ← 上面这份
├── ARCHITECTURE.md           ← 当前架构说明
├── engine/
├── shell/
└── system-daemon/
```

然后编码 IDE 每次接到具体任务时，应该先以 `ARCHITECTURE_GOAL.md` 判断“**这个改动最终要把系统往哪里推**”，而不是每次重新从零理解 Yuiro。

尤其我建议你把整个升级计划理解成一条主线，而不是几十个独立任务：

```
当前 Yuiro
    │
    ▼
① Session / Generation / Cancellation
    │
    ▼
② AgentRuntime
    │
    ▼
③ SpeechRuntime
    │
    ▼
④ AvatarRuntime
    │
    ▼
⑤ MemoryRuntime
    │
    ▼
⑥ CapabilityRuntime
    │
    ▼
⑦ Plugin / Skill Runtime
    │
    ▼
最终 Yuiro Agent Runtime
```

**真正的“主轴”只有一个：统一 Runtime Contract。**
Agent、语音、记忆、Live2D、插件并不是五个平行的大改造项目，而是围绕这个 Contract 逐步接入。这样 IDE 才不会越改越散。