# Yuiro 统一架构与 Engineering Goal

版本：2026-10-23 / v1.2（增加双角色隔离前置项 C0，延续既有 Runtime）。当前优先完成 C0 的工程与实机验收，再续 G0 未验项及 G1–G5；不因 C0 已实现部分取消屏障就宣称 G1 完成。

用户新增优先级：**C0 Hiyori / Hotaru Shiomi 独立角色卡 → 补齐 G0 未验项 → G1 → G2 → G3 → G4 → G5**。C0 的配置/切换/调试台边界以 [角色卡契约](../spec/character-cards.md) 为准，交付见 [C0 报告](../plan/C0-character-isolation.md)。独立大脑配置、声音、人设、模型、表演与角色数据；设备、安全策略和通用工具共用。角色创建器、任意导入及多角色同时运行暂缓。

代码审阅基线：`97753e9b954f660a100c954573fda03e737638c1` + 当前未提交的 S53 Avatar/Live2D 工作区改动。此基线不是干净提交；实现前必须重新核对，保留用户已有改动。

## 1. 目标、范围与文档效力

交付一个可可靠打断、及时接话、能用现有 Live2D 资源自然表现的桌面角色。工具执行必须真实，声音与动作必须属于当前有效回合。架构增量以减少状态来源、排队等待、竞态和参数冲突为依据。

本文件整合 pi、AIRI、Project Waifu 的参考和前期 Yuiro 研究，替代 2026-10-22 研究文档中的阶段任务。本目录只维护这一套当前路线。历史研究继续作为来源证据，不再形成并行实施清单。

`docs/spec/` 仍是行为契约的落地位置。本次用户确定的新阶段顺序为 G0–G5；旧路线中的 Task 平台、Subagent、插件与训练能力不再是这一轮的前置工作。每阶段开始时：

1. 读取对应现行规范、实际入口和已有测试，列出代码/规范差异。
2. 按该阶段 Goal，把必要的最小规范增量同步到 `docs/spec/`，记录原因与兼容策略，再改代码。
3. 不削弱鉴权、Capability/Approval、文件域、事务和旧结果隔离等既有约束。发现目标与这些硬边界冲突时保留边界，提交具体冲突证据，而非绕过。

此次文档更新不启动实现、不提交代码、不改写历史四份研究、不改变运行配置。新增类型与文件名是建议职责位置，允许按实际结构合并；不允许创建只有名字、没有真实调用 ownership 的 Runtime。

**首要实施约束：延续现有 Runtime、局部重构、分阶段迁移。** Session、Generation、Cancellation、Lifecycle、Trace、Event/Intent 继续作为既有地基；新职责必须接入这些契约，不得建立第二套 Session 注册表、业务 generation、取消总线或相互独立的状态权威。暂缓扩展不等于删除已经落地的 Task、Memory、Capability 等能力。

## 2. 最终架构决策

### 2.1 保留的进程拓扑

```text
Electron main                         Python Engine
  窗口 / 文件路径 / manifest          Session + TurnCoordinator
          │                             ├─ Context / 原有 AgentLoop
Electron renderer ←── WS 协议 ────────┤   └─ ToolDispatcher → Policy/Approval → native / 可选 daemon
  PlaybackController                   └─ SpeechOutputScheduler → 语言渲染 / 原有 TTS provider
          │                                                       │
  PerformanceDirector                               独立本地 TTS 进程 / 云 TTS
          │
  ModelPerformanceProfile + 当前 Pixi/Cubism adapter
```

本地 TTS 保持进程隔离；native 是系统执行默认后端，C++ daemon 保持可选。记忆、Context、Task、Artifact、Presence 复用现有服务，后台工作受前台预算约束。

### 2.2 三个权威与一个输出调度器

| 组件 | 唯一决定 | 不承担的职责 |
|---|---|---|
| Session / TurnCoordinator（Engine） | 有效前台 turn、generation、任务归属、输入覆盖和取消 | 不逐帧控制模型，不决定客户端已经出声 |
| PlaybackController（renderer） | 音频源、播放队列、实际开始/结束和游标 | 不请求模型，不决定业务成功 |
| PerformanceDirector（renderer） | 当前身体的动作、表情、微动与参数交接 | 不另调导演 LLM，不执行系统工具 |
| SpeechOutputScheduler（Engine） | 不同来源输出的保序、预算、提供商调用和过期丢弃 | 不把合成完成或发送成功当作播放完成 |

一个 Session 同时只有一个前台 turn；一个显示中的角色同时只有一个可听前台输出。不同 Session 可以保存历史，但默认只有当前选中的 Session 获得该身体的输出权。换 Session、断线或 renderer 重建必须撤销旧输出绑定。

保留 AvatarRuntime 的语义意图与档案配置；实际动作选择、占用与完成状态统一归 renderer Director。Registry 负责依赖/健康/生命周期分发，引用必须始终对应实际服务对象。

### 2.3 复用、改良、暂缓

| 范围 | 决策 | 具体边界 |
|---|---|---|
| AgentLoop、ContextEngine、ToolRegistry/Dispatcher | 复用＋改良 | 增加真实 task owner、取消、工具执行模式；保持已有工具策略与预算 |
| Session、Generation、Trace、EventLog | 复用＋改良 | 统一身份与有限业务事件；保留可观测 stale 丢弃 |
| VAD、ASR、TTS provider、语言渲染 | 复用 | 保留内部中文/展示语言/朗读语言的现有约定；优化等待与预算 |
| TTSTaskManager、文字朗读、Presence 输出 | 收敛 | 共享一套 Scheduler，保留提供商；两条 WS 传输可渐进兼容 |
| Live2DCanvas、manifest、avatarSlots、performance/profile | 复用＋改良 | 审定资源、异步播放回执、model revision、Director 与效果归属 |
| 记忆检索/维护、关系、Task/Artifact | 保留＋限预算 | 修前台阻塞与 stale 提交，不借本轮扩建记忆算法或任务平台 |
| 鉴权、Capability、Approval、事务 | 必须保留并补齐取消绑定 | 安全底线不是暂缓项；新增请求和协议沿既有边界 |
| 通用 Plugin/Skill 平台、常驻多 Agent、复杂 Planner | 暂缓 | 实际使用场景、权限模型和预算明确后单独立项 |
| 微调/训练流水线、通用工作流引擎、消息中间件 | 暂缓 | 不进入当前实时体验主路径 |
| 新 Node Agent 服务、VTube Studio 执行链迁入 | 不引入 | 保持现有 Engine 与直接 Pixi/Cubism 渲染边界 |
| 全双工 AEC、词级对齐/viseme、跨进程耐久执行 | 条件扩展 | G5 后依据失败数据与资产能力选择；不预先承诺效果 |

### 2.4 局部重构与迁移的硬边界

1. 优先顺序固定为：确认当前实现 → 补缺陷/契约 → 必要时提取小接口或适配器 → 迁移一个真实入口 → 回归验收 → 清理被替代的重复路径。不得先新建完整目标目录，再整体搬迁或替换。
2. TurnCoordinator、PlaybackController、PerformanceDirector、SpeechOutputScheduler 是职责名称，可以先作为既有类的方法或小协作者实现。新增类/文件须说明现有落点为何不足、状态由谁迁入，以及谁调用它；不能要求每个名字都对应独立 Runtime、进程或框架。
3. 每个迁移切片仅有一个有效写入者和一条实际执行路径。适配期间允许旧接口转发到新实现，但禁止新旧两套同时执行工具、写记忆、播音或驱动同一参数。只读影子比较可以保留，必须与副作用执行隔离。
4. 先保存可复现的行为和数据基线，再修改调用关系。Session 恢复、数据库/配置兼容、协议与 UI 设置不能因为抽象提取丢失。业务代际迁移沿用 Session 权威，本地 TTS epoch、播放 epoch 等资源屏障保留各自限定语义。
5. `main.py` 的组合根按实际迁移逐步提取，不作为全文件拆分任务；AgentLoop、VoicePipeline、MemorySystem、Live2D 渲染和执行后端均不整体重写。禁止为此引入 pi 的完整运行框架或第二个 Agent 服务。
6. 新路径通过当前切片的回归后才替换默认入口并删除旧重复编排。报告必须列出迁移入口、唯一 owner、兼容适配器、回退方式和适配器删除条件；回退不能撤销既有安全检查或已确认的 stale 防护，也不能恢复已取消的旧副作用。
7. 若某局部确实不能满足目标，先交付具体失败证据、最小替换范围、契约兼容和数据迁移方案。此 Goal 不构成大规模重构授权；涉及更换进程拓扑、整体重写核心或不可逆数据迁移时，报告具体范围并另行取得方向确认。

### 2.5 现有模块 → 目标职责的接续映射

下表以仓库相对路径定位，执行前按真实代码重新核对。表中的“收敛”指迁移已有状态/调用责任，不是在旁边新建平行系统。

| 现有模块/路径 | 必须复用的已有能力 | 目标职责与局部改动 | 需要避免的误解 |
|---|---|---|---|
| `engine/yuiro/runtime/session.py` | Session 身份、代际、通道绑定、恢复/挂起 | 在同一 Session 服务中集中前台 turn、task owner、覆盖策略；必要时提取小型 TurnCoordinator | 不新建另一套 SessionManager；不由 Agent/Voice 各自推进业务代际 |
| `engine/yuiro/runtime/contract.py`、`adapters.py` | RuntimeRegistry、生命周期分发、状态快照 | 更新实际服务引用，补真实取消与有界收敛；Adapter 转发现有对象 | 不把 Adapter 外再套一套无真实调用的 Runtime |
| `engine/yuiro/main.py`、`debug_api.py` | 启动装配、WS 入口、热更新 | 先统一工厂/替换入口与注册；业务随迁移渐进提取，传输保留兼容 | 不先重写整个 main 或另起 Engine |
| `engine/yuiro/agent/__init__.py`、`agent/tool_dispatch.py` | 原有 LLM/tool loop、上下文、预算与工具结果 | 保持执行算法，补 task 取消、结果身份、提交边界和副作用批次顺序 | 不用 pi 替换 AgentLoop；不丢成功去重/失败限流等策略 |
| `engine/yuiro/audio/__init__.py` | VAD/ASR/VoicePipeline、分句、TTSTaskManager 保序与 epoch | 语音输入继续复用；从已有输出编排收敛 Scheduler，并接入文字与 Presence | 不再写一条全新 VAD→ASR→LLM→TTS 管线 |
| `engine/yuiro/main.py` 的 `_speak_reply`、Presence 输出入口 | 文字朗读与主动发言的现有功能 | 逐条变为统一输出服务的适配调用，验收后删除重复合成循环 | 不同时维护两套 TTS 编排，不移除功能来宣称已统一 |
| `engine/yuiro/audio/providers.py`、`render.py`、`tts_server/` | 多提供商、语言解耦、本地推理隔离 | 在既有边界补超时、连接复用与预算 | 不更换提供商来掩盖调度问题，不把推理并入主进程 |
| `shell/src/renderer/src/composables/useVoiceInput.ts` | FIFO 播放、RMS、设备/音频接入与停播 | 先原位补 epoch；再按需要提取 PlaybackController，让文字/语音共用实际播放器 | 不增加第二个 AudioContext/播放队列作为平行声音权威 |
| `engine/yuiro/avatar/runtime.py`、`intent.py`、`performance.py` | 语义 Intent、表演库、配置与事件接入 | 保留语义请求与业务限制，携带身份；实际渲染占用/完成裁决交给同一 Director | 不删除 AvatarRuntime，也不让两端各自宣称动画已完成 |
| `shell/src/renderer/src/components/Live2DCanvas.vue`、`avatar/avatarSlots.ts` | Pixi/Cubism 加载、播放、槽位解析与预览 | 先改现有唯一入口，再必要时提取 Director；补异步回执、参数归属、效果清理 | 不另建渲染器、动画服务或导演 LLM |
| `shell/src/main/live2dManifest.ts`、`shell/src/shared/live2d.ts`、`live2dInfer.ts`、`engine/yuiro/config.py` | 资产清单、类型、模型档案和热更新 | 扩展版本/缓存失效/人工审定字段，兼容既有映射和配置 | 不改原模型素材；不重建独立且互相漂移的档案来源 |
| `engine/yuiro/context/`、`memory/`、`task/`、`artifact/`、`presence/` | 已实现检索、维护、关系、任务与产物能力 | 沿原入口补前台预算、stale 提交检查、输出 TTL；保持持久化兼容 | “暂缓平台扩展”不等于删除现有实现或迁移数据库后端 |
| `engine/yuiro/approval.py`、`capability/`、`native/`、`transaction/`、`systemd/`、`system-daemon/` | 审批、权限、文件域、执行/回滚与后端切换 | 审批绑定 turn，取消后拒绝旧批准；复用安全链和结果契约 | 不在新协调器/工具里直接绕过后端执行 OS 操作 |
| `engine/yuiro/runtime/events.py`、`event_log.py`、`trace.py`、`shell/src/shared/events.ts` | 事件/日志/计时与既有 IPC | 扩展现有事件身份；Engine WS 类型渐进归并到 engine-protocol，IPC 职责保持 | 不另起消息总线，不把每帧数据写入业务日志 |

## 3. 开源参考：机制、改良与引入依据

沿用前轮已核验的固定快照，本文件不声称这些是各项目最新版本。来源详见 [研究文档 §4](2026-10-22-small-kernel-realtime-performance-goal.md#4-可核验的开源参考与接入方式)。

| 参考与定位 | 采用的机制 | Yuiro 改良 | 不照搬 |
|---|---|---|---|
| pi `58c0b02…`：[agent.ts](https://github.com/earendil-works/pi/blob/58c0b02ce552adab76014e7ed712ab7981359aa8/packages/agent/src/agent.ts#L307) | abort + 可等待结束；steer/followUp；上下文与模型消息分离 | asyncio task owner + Session generation；硬中断和排队补充明确分开 | TypeScript 整套 Agent 替换 Python；把 steer 当成立即停播 |
| pi 同快照：[agent-loop.ts](https://github.com/earendil-works/pi/blob/58c0b02ce552adab76014e7ed712ab7981359aa8/packages/agent/src/agent-loop.ts#L518) | 选择顺序/并发工具执行 | 独立只读可并行；写操作和共享媒体资源默认串行，保持结果 ID/顺序 | 无条件 gather 所有副作用工具 |
| AIRI `448ada1…`：[speech-pipeline](https://github.com/moeru-ai/airi/blob/448ada1a41c29d84b3975a73ee732f7bdcd13c27/packages/pipelines-audio/src/speech-pipeline.ts)、[playback-manager](https://github.com/moeru-ai/airi/blob/448ada1a41c29d84b3975a73ee732f7bdcd13c27/packages/pipelines-audio/src/managers/playback-manager.ts) | Intent、owner、播放回执、queue/replace/interrupt | 单角色输出、有界缓冲、Python 合成与 renderer 播放分权 | 上游整个 monorepo 依赖、默认并发配置、多角色调度复杂度 |
| AIRI 同快照：[motion-manager](https://github.com/moeru-ai/airi/blob/448ada1a41c29d84b3975a73ee732f7bdcd13c27/packages/stage-ui-live2d/src/composables/live2d/motion-manager.ts#L751) | 口型说话状态、释放尾段、参数交接 | 适配当前安装 API 和具体模型通道，不复制未知帧更新顺序 | 固定常量直接当作本模型最佳参数 |
| Project Waifu ZIP：`llm/novelai_runtime.py:12` | provider 资源 ownership、连接复用、优先级排队 | 前台/后台预算、超时和防饥饿；在已有 provider 边界实现 | 全局单例承担所有 Session；声称非抢占队列可以立即抢占 |
| 同 ZIP：`tts/sentence_pipeline.py:23` | 当前句播放、下一句有界预取；迟到合成不能自行播放 | 原有 TTS manager 上比较 lookahead=1/2，保留中文分句 | 线程体系、要求标点后空白的分句规则、等完整 LLM 回复再说 |
| 同 ZIP：`vtube_studio/advanced.py:46`、`idle_animations.py:516` | talking/idle/reset、owned effects、配置快照、低强度微动 | cue/model revision 绑定；renderer 本地 tick；仅清自己占用的效果 | VTS hotkey 协议、长等待占全局锁、固定 15 FPS 参数传输 |

Project Waifu 来源：`D:/Project/Yuii/desktop-pet/_pack/Project_Waifu-main.zip`，SHA256 `C9CF0DAACDECB0854417C949A958F7E69C2450A6C2614C24B29AA825F769E7C9`。路径行号指包内 `Project_Waifu-main/`；没有可确认 Git commit。其 Runtime 是具体资源管理范例，不等于完整 Agent Harness，也没有足够历史证据认定它是 Yuiro 整体蓝图的唯一来源。

引入方式：固定快照 → 读依赖/许可 → 提取必要机制或最小纯逻辑 → Yuiro adapter → 契约测试 → 本机前后对比。记录原文件/版本、保留 attribution、改动原因、测试和撤回方式。代码许可与模型资源许可分别登记。不要为复用十行规则引入完整框架。

## 4. 必须先统一的运行契约

### 4.1 身份与状态归属

Engine 权威身份：`engine_instance_id + session_id + generation + turn_id`。重启后换 engine_instance_id，避免恢复旧 session 时 generation 重置与旧消息碰撞。generation 仅由 Session/TurnCoordinator 增加，AgentLoop/VoicePipeline 不再分别推进业务代际。

输出增加 `output_id`、`segment_id/seq`；cue 增加 `cue_id` 与模型绑定版本。renderer 的本地 `playback_epoch` 是解码/回调取消屏障，不是新的业务 generation。模型装载/切换递增 `model_revision`，异步结果只能更新同 revision 的实例。

短时状态：turn = RUNNING/CANCELLING/COMPLETED/CANCELLED/FAILED；输出 = PRODUCING/QUEUED/PLAYING/COMPLETED/INTERRUPTED/FAILED。业务生成结束与输出结束分开，不强迫 LLM task 一直等声音播完。

消息至少包含 `protocol_version + identity + trace_id + event_id/seq`。增量协议以建议的 `shell/src/shared/engine-protocol.ts` 为 TS 来源，Engine 对称校验；序列化 fixture 做跨端契约测试。旧客户端兼容只在传输适配器处理且有删除条件；不可同时维护两套长期业务解释器。

### 4.2 输入、并发与取消

| 输入 | 默认行为 |
|---|---|
| 显式 stop | 立即本地静音并取消当前前台 turn；不自动开始新任务 |
| 新文字发送 | 默认 replace 旧前台 turn；若后续增加排队按钮则明确区分 queue |
| 确认有效的 speech_start | 按现有 barge_in_enabled 开关决定是否 interrupt；保留用于打断的新一句音频 |
| Presence | 用户前台工作优先；不打断用户或任务，忙时跳过或有限延后且有 TTL |
| 新 Session/断线重连 | 撤销旧绑定；恢复业务历史不自动重播旧声音或旧演出 |

取消分两条并发路径：

```text
renderer：playback_epoch++ → 停声音/清缓冲/收口/撤销旧 cue → silenced
Engine：generation 作废 → cancel LLM/等待工具/审批/输出 → bounded settle → settled 或 pending/unknown
```

silenced 不等待 settled。每个异步 await 后、外部副作用提交前、history/memory/state 提交前，检查 owner 与身份；真正的数据库写入须避免“检查后再 await、之后无检查提交”的竞态。

审批绑定 session/turn/generation/request，取消后旧批准无效。已经进入不可取消线程或外部副作用不谎报停止；记录完成/未知状态，必要时经原事务机制补偿。取消不等于回滚。

工具结果始终关联原 tool_call_id。先采用“含副作用工具的一批顺序执行”的保守策略；只读批次允许并行。等有实测需求再细化资源锁，锁内不执行等待动作或网络闲置计时。

### 4.3 单一语音输出路径与预算

文字、语音、Presence 经一个 Scheduler 使用原有分句、语言渲染与 provider；首句流式送 TTS。输出开关关闭时仍正确结束文本/演出状态，不能等永远不会出现的 audio:end。

首版默认预取下一句、合成并发 1，作为保守起点；G2 对比当前并发 2 与 lookahead=1/2 后确定默认值。翻译、合成、待发送、预解码都须有界，至少限制 item 数和估计音频时长/字节；达到预算时向上游施加 backpressure，不丢用户确认文本，Presence 可过期丢弃。

建议初值：未开始播放的输出最多预取 2 段，预解码最多 1 段。单段/单回复上限与 timeout 在 G0 根据实测冻结。长期等待允许显式截断并向用户说明，禁止无限创建后台 task。

renderer 使用 AudioContext 时间关联音频和 RMS，处理 suspend/resume。解码前后、预加载后、start 前、onended 和错误恢复均检查 identity/epoch。旧回调只能释放旧资源，不得清空新 source 或递减新轮计数。

PlaybackReceipt 分 started/completed/interrupted/failed，携带 segment_id、played_ms。无词级对齐时只确认完整播出的句子；当前半句记录进度，不伪造逐字 heard text。记忆/历史区分生成结果与播出事实，工具已执行的真实结果仍必须记录。

### 4.4 轻量资源管理与后台工作

provider 连接由既有工厂生命周期拥有；启动、热更新、shutdown 共用入口，注册表引用与实际服务一致。热更新先构建校验新配置，在安全边界切换；当前 turn 保持配置快照，输出互斥切换，失败可保留旧配置。

前台检索设独立 deadline，超时走明确降级；后台整理/摘要不能占满前台所需的模型连接或 GPU。前台活跃时优先暂停新后台任务，已运行的非抢占工作如实计入等待。仅在测出争用后扩展 provider admission control，避免先建通用资源调度框架。

幂等 shutdown：停止接入 → 立即停输出 → 取消并有界等待自有任务 → 关闭后台任务、连接、worker 与 store。关不掉的外部请求单列，不无限等待。

## 5. Live2D：资产、微动与演出统一

### 5.1 资产是能力边界

当前资源重点（2026-10-23 用户指定）：`shell/src/renderer/public/live2d/hiyori` 与 `shell/src/renderer/public/live2d/Hotaru Shiomi`。Hiyori 与 Hotaru casual 为两套主要验收资源；Hotaru child still 可补充稀疏能力 fallback 检查。MaoPro/肥牛不再作为本轮前置验收对象。前轮引用基线 Hiyori 8 表情/13 动作、Hotaru casual 46/67，须以 G0 本轮扫描和实机结果为准。引用数量不等于可用、独立或已审定的语义动作。

复用 manifest 扫描真实文件、Duration、Loop、曲线参数和模型能力；文件名推断仅产生候选。profile 以模型身份/资源版本绑定，记录实际 group/index、适用语义、强度、方向、参数影响、循环/停止策略、fade、是否允许打断、冷却、权重与 reviewed 证据。

greet/farewell、角色悲伤/安慰用户分别审定；不能自动把 bye 归迎接、cry 归安抚。仅 reviewed 资源进入自动池；未知资源在调试预览可见，生产自动演出关闭。缓存失效覆盖 model3、被引用 motion/expression 和 profile 版本，不能只看 model3 mtime。

### 5.2 一个 Director、受限演出配方

每个配方描述 prepare/talking/release/reset，附带语义 cue 的 immediate/segment_start/segment_end 锚点、TTL、优先级和 fallback。沿原有 performance 配置扩展，不创建完整 DSL。

Director 记录 owned effects、实际播放句柄、配置快照及 model_revision。只回收当前配方拥有的效果；不可清掉新回合或用户手动设置的效果。手动预览退出后正确恢复；异常清理有截止时间，不占用全局调度锁等待长序列。

运动优先级固定：interrupt/显式停止 > 用户手动交互 > 当前语音/业务表演 > Presence > idle。普通演出使用适当优先级，FORCE 只用于明确停止/调试等限定操作。新 cue 需要经过抢占策略，不直接互相覆盖。

异步 startMotion 确认成功后才发 started；失败发 failed/fallback。完成回调为主，watchdog 兜底；循环资源由适配器明确退出策略。禁止仅按资源 Duration 宣称动画已完成。

### 5.3 参数控制权与自然微动

| 通道 | 说话/表演时的归属 | 结束交接 |
|---|---|---|
| MouthOpen | 语音优先；body motion 不覆盖其可听时序 | 收口短尾段后平滑交还模型基线 |
| Expression/脸部 | 当前审定配方；只占声明参数 | 撤销自有效果并恢复当前有效基线 |
| EyeBlink/Gaze | 角色本地控制，尊重闭眼表情和显式动作 | 防止叠加眨眼与凝视驱动争抢 |
| Head/Body/Breath | 显式 motion 优先，微动只作用于空闲通道 | 平滑回落，避免两套呼吸叠加 |

验证当前安装 SDK 的 API、更新阶段和参数 min/max，不依靠可选链无报错证明写入成功。没有相应参数/资源时不强造能力。

借鉴 Project Waifu 的低幅度头部、视线、呼吸与稀有小手势，在 renderer 本地 tick；默认低强度，有冷却、seed 与最近使用记录。整段 motion 期间让位，背景行为不按每帧发送 Engine 事件。

六个场景统一：自然迎接、倾听、短暂思考、轻微得意、克制安慰、真实成功后的庆祝。每个配方都有正例/禁止场景/fallback；任务失败不庆祝，普通“好的”不连续大幅摆动。LLM 情绪提示若后续引入，只附带在原响应，解析失败不阻塞首句；本轮不加逐句情绪/导演模型请求。

## 6. 测量与验收标准

以下数值是目标，不是已达成成绩。先冻结基线，再比较同硬件、同 provider/model、同语言与语料的结果。冷启动单列；工具长任务与纯聊天分组；云网络波动、错误与超时单独统计且不可丢弃。

| 指标 | 边界 | 目标/门槛 |
|---|---|---|
| 可见响应 | renderer 接受输入/收到确认 speech_start → 状态首帧 | p95 ≤150ms |
| 本地静音 | renderer 接受 stop/interrupt → 活跃 source 停止 | p95 ≤100ms；另测检测到用户说话至静音总耗时 |
| 协作取消 | Engine 接受 cancel → 自有协作 task 结束 | p95 ≤500ms；不可取消外部计算报告 pending/unknown |
| 纯聊天首音频 | VAD speech_end → renderer 首段开始 | 热启动目标 p50 ≤1.5s、p95 ≤3s；达不到必须保留分段瓶颈与下一任务，不能标全部通过 |
| 端到端首音频 | 测试音频标注的语音终点 → 首段开始 | 额外报告，包含 VAD 端点等待，不能只报较短内部 TTFA |
| 动作同步 | AudioContext 锚点 → adapter 确认开始 | 预热资源 p95 绝对偏差 ≤100ms；另记录人工可见起效偏差 |
| 主线程帧耗时 | 目标显示帧率对应预算 | 60Hz 下 p95 ≤16.7ms；其他帧率按预算报告 |
| stale 污染 | 解码/工具/审批/写入/动作/换模型的确定性竞态 | 测试中旧输出进入新状态 0 次 |
| 持续稳定 | 固定交互脚本持续运行 | ≥60分钟，无崩溃/死锁/重播；结束后 turn-owned task/句柄/队列归零，缓存按预算保留 |

G0 至少完成 30 个热启动样本用于诊断；G5 每个正式支持的 provider+语言验收组合至少 100 个热启动样本，冷启动至少 3 次，报告样本数、p50/p95/max、失败率、配置与资源峰值。基线冻结后改变阈值必须有原因，不能为通过验收临时放宽。超出依赖能力的目标标记未通过，不等于自动要求换模型或扩建服务。

跨进程计时使用 trace 关联并在各进程记录单调时钟；测总时长通过同一测试时钟或校准方法，不直接相减未经校准的单调时间。AudioContext 启动表示应用播放事实，不能伪称物理扬声器实测；需要物理端到端时另加 loopback/录音证据。

人工演出验收：固定六场景，主模型至少每场景 5 次；另测一个资源较少模型的 fallback。录屏由实际评审者按语义贴合、节奏、口型/动作冲突、角色一致性四项 1–5 分评分。建议平均 ≥4 且无反向语义、旧动作重播、持续张嘴等严重违和；审定者/证据/待修项可追溯。Agent 无法访问模型预览或用户反馈时，只标“工程通过、视觉待验”，不能自行填写 reviewed=true。

## 7. IDE Agent 分阶段任务

依赖顺序：G0 → G1 → G2 → G3 → G4 → G5。每个子任务一个可审查增量；每阶段必须交付 Goal / Scenario / Architecture Increment / Tests / DoD 对照。已通过的功能以测试证据复用，不重复实现。

### 7.1 每阶段改动边界与累计回归门槛

以下边界适用于后文所有子任务。验收采用“切片定向回归＋阶段累计回归”：切片先测触及的契约和故障；切换默认路径或宣布阶段完成前，执行引擎完整测试、shell typecheck/build 与已落地的跨端场景。只有触及 daemon 时才要求其构建/契约回归。指标同条件比较，未测项不得当通过。

| 阶段 | 允许改动与迁移顺序 | 本阶段不扩大的范围 | 阶段切换前必须证明 |
|---|---|---|---|
| G0 | 观测、固定时序 fixture、资源清单、基线报告；记录既有公开接口与配置 | 不切换业务默认路径，不清理用户代码，不批量移动文件 | 文字/语音/工具审批/已有任务记忆/模型切换的现状可复现；测量不改变行为；记录已有失败而非要求掩盖 |
| G1 | 原位修工厂引用 → Session 内 task owner → 两个输入入口统一取消 → 播放 epoch → 工具/提交 guard | 不重写 AgentLoop、VoicePipeline，不迁移数据库，不改变人设/语言与系统后端 | Session 恢复/通道绑定、工具结果/审批/事务、TTS 开关和 barge-in 设置均保留；R01/R02/R04/R05/R10/R12 通过；无双重副作用 |
| G2 | 从现有语音输出提取共享编排 → 迁移文字朗读 → 迁移 Presence → 验收后清除重复循环 | 不更换 ASR/TTS/语言协议，不新建推理服务，不顺手重做 Memory/Task | 三种来源逐项功能等价；保序/首句/口型/字幕/取消/错误终态保持；R03/R09 和 G1 场景通过；默认路径单一，延迟与缓冲有对比 |
| G3 | 扩展已有 profile/manifest → 改现有 Avatar 入口 → 归并真实播放裁决 → 清除重复状态/计时裁决 | 不替换 Pixi/Cubism，不删除 AvatarRuntime，不修改原始资产或重建调试 UI | 原表情/动作映射、手动预览、模型/档案热更新和口型保持可用；R06/R07/R08 通过；无法自动迁入的旧映射显式提示，不能静默变空 |
| G4 | 在 G3 的同一 Director 内加 cue 锚点/配方、空闲通道微动与冷却；先单个配方再扩到六个 | 不新建第二套动作/参数循环，不加导演模型，不扩大工具或训练平台 | 前三阶段回归保持；六场景有正反例和 fallback；稀疏模型自然降级；相对 G2 首音频不恶化，人工审定状态真实 |
| G5 | 固化已实现路径的 runner/自动检查、性能/持续稳定测量和文档证据 | 不把发布验收变成额外重构阶段，不顺手启动 G5 之后的扩展 | 全部 R01–R12、阶段累计回归与 §6 实机/视觉门槛有证据；兼容适配器有删除结论，旧副作用执行路径已退出 |

回归失败必须对照 G0 区分“既有失败”“本次回归”“测量环境变化”。本次回归在当前切片修复或撤回切片；既有失败保留可复现证据并按严重性处理，不以基线存在为理由忽略阻断级污染/死锁/安全缺陷。

任何接口迁移都需核对原调用者、配置字段、事件消费者与异常终态；不得只验证新类的孤立单元测试。临时兼容适配器需注明对应入口、唯一执行 owner、终止条件和目标删除阶段。

### G0 — 固定事实与基线（P0，入口阶段）

本轮资源与测试执行补充：资源主线限定为 Hiyori + Hotaru Shiomi，优先完成 Hiyori 与 Hotaru casual 两套独立档案，不共享未经审定的动作索引/参数假设；Hotaru 其他外观按独立 model3 验证，不因同角色名自动批准。日常测试精简运行范围而非删除契约：局部关联测试 → 常规快测 → 真实模型集成/完整回归 → 实机体验。真实 BGE 语义测试可从日常快测单列，但 Memory/embedding/检索改动、阶段交付和发布前必须补跑；skip 不算通过。不得把快测标为全量。具体命令、已核验耗时与 G0–G5 体验收益见 [测试分层与阶段效果](../plan/G0-test-tiers-and-stage-effects.md)。本补充不改变各阶段门禁。

**Goal / Scenario：** 能复现一轮文字、一轮语音、一次打断、一次换模型，知道等待与违和发生在哪。

**Architecture Increment：** 旁路计时、场景 fixture 和资产盘点；只加必要观测，不改原行为。

任务：

- G0.1 记录 HEAD、dirty 文件、实际启动/热更新/取消/播放调用链。核对当前 spec，写最小差异说明；不根据旧报告假定功能仍缺失。
- G0.2 生成模型能力表并标记候选/审定/不支持；记录资源版本。Hiyori 与 Hotaru Shiomi casual 均为主要验收对象，Hotaru child still 补充稀疏能力 fallback；不为验收重新引入已移除的 MaoPro/肥牛资源。
- G0.3 分解端点/VAD、ASR、Context/Memory、LLM 首句、翻译、TTS、传输/解码/播放；固定测量脚本、语料、provider 和六个 Showcase。

**代码入口：** `engine/yuiro/main.py`、`runtime/trace.py`、`audio/__init__.py`、`shell/src/renderer/src/composables/useVoiceInput.ts`、`shell/src/main/live2dManifest.ts`。

**Tests：** 测量字段与 trace 对应；错误/超时不遗漏；model3 引用与文件存在校验；30 次热启动诊断。

**DoD：** `docs/plan/` 提交带 G0 ID 的基线报告和可复现实验命令；明确未测项与配置。交付实际证据，不能引用以前的“772 passed”当作本轮验收。

### G1 — 回合、对象与取消归属（P0）

**Goal / Scenario：** 在 LLM、工具、审批或音频解码中停止，都不会让旧结果恢复输出。

**Architecture Increment：** Session 内 TurnCoordinator、最小身份 envelope、renderer epoch 和统一工厂。

任务：

- G1.1 统一启动/热更新的 AgentLoop 工厂，保持 Registry 与实际请求对象一致，当前 turn 固定配置快照；规范和协议 fixture 同步。
- G1.2 control/audio/stop 接同一 TurnCoordinator。保存活跃 task、作废 generation、取消审批与子任务；保留 barge-in 开关和新录音。
- G1.3 为前端解码/播放/回调补 identity+epoch 屏障，实现立即本地静音与有界后台 settle；处理 Session/连接切换。
- G1.4 将副作用批次顺序执行；各 tool_call_id、执行状态与 late result 可追踪；history/memory 提交有 stale gate。

**代码入口：** `main.py:784/:1336/:1372/:1711`、`debug_api.py:139`、`runtime/session.py`、`runtime/adapters.py:23`、`agent/tool_dispatch.py:58`、`approval.py`、`useVoiceInput.ts:208/:250`。行号仅为基线定位，执行时重定位。

**Tests：** 延迟 decode 后 stop；旧 onended 晚于新 source；文字/语音竞争；取消后批准旧 request；工具晚返回；重启/resume 身份；热更新与 Registry；输入开关回归。复用 `test_barge_in.py`、`test_session.py`、`test_runtime_contract.py`、`test_transaction.py`，新增真实调用链场景。

**DoD：** stale 自动化测试全部通过，本地静音与协作取消达到 §6；工具状态真实，无权限回退；无法停止的外部副作用单独报告。

### G2 — 一个语音输出调度与播放事实（P0/P1）

**Goal / Scenario：** 文字、语音和 Presence 共用输出链路；首句先说，长回复保序且不会互相抢声音。

**Architecture Increment：** Scheduler、segment/PlaybackReceipt、有界预算和客户端音频时钟。

任务：

- G2.1 逐个迁移原语音回复、文字 `_speak_reply`、Presence，复用 provider 与 manager；迁移完成删除重复编排，不保留长期双实现。
- G2.2 翻译/合成/发送/预解码限制容量与 deadline，分别比较 lookahead=1/2 和并发=1/2；后台摘要/整理避免与前台争用，先用简单准入策略。
- G2.3 按 AudioContext 时间播放并回传 segment 生命周期，输出关闭/断线/失败也有终态；区分生成记录与播出记录。

**代码入口：** `main.py:1224`、`audio/__init__.py:705/:1559`、`audio/providers.py`、`audio/render.py`、`presence/runtime.py`、`useVoiceInput.ts`。

**Tests：** 乱序完成、有空段、解码失败、翻译 timeout、网络断线、TTS 开关、Presence 与用户同时输出、长文本预算、取消后迟到结果。复用 `test_reply_tts.py`、`test_tts_streaming.py`、`test_output_renderer.py`、`test_presence_voice.py`。

**DoD：** 三种来源一个 Scheduler；用户输入不被 Presence 打断；所有队列有预算且可清理；给出选定默认并发的本机对比，纯聊天首音频不退化。

### G3 — 模型档案与单一演出裁决（P1）

**Goal / Scenario：** 模型切换后只演当前模型支持的内容，动作失败/循环/结束都有真实状态。

**Architecture Increment：** 扩展既有 manifest/profile + Director + PerformanceReceipt。

任务：

- G3.1 为资源生成候选档案和预览入口，拆分 greet/farewell、sad/comfort；审定记录绑定资源版本，未知能力降级。
- G3.2 等待 startMotion 的成功结果，注册完成回执与 watchdog，落实 Loop 退出和 model_revision；配置缓存随引用资源变化失效。
- G3.3 每个配方保存 owned effects、配置快照和句柄，结束/取消/异常只清理自己的效果；手动预览、旧模型加载/回调竞态都受控。
- G3.4 验证 SDK 参数 API 与帧更新顺序，建立 mouth/eyes/gaze/body 通道归属，移除普通演出的默认 FORCE。

**代码入口：** `avatar/runtime.py`、`avatar/intent.py`、`avatar/performance.py`、`config.py`、`Live2DCanvas.vue:220/:485/:541`、`avatar/avatarSlots.ts`、`shared/live2d.ts`、`shared/live2dInfer.ts`、`main/live2dManifest.ts`。

**Tests：** 启动 Promise 失败/迟到、旧结束覆盖新动作、换模型、资源被替换、循环无法结束、嘴眼参数争抢、无资源/无参数、用户手动效果保护。复用 `test_motion_mapping.py`、`test_performance.py`、`test_avatar_action.py`；前端纯逻辑加最小测试入口，测试运行器是否新增由 G0 工程环境决定。

**DoD：** 自动池只有 reviewed 项，启动/完成/失败/取消可区分；旧 revision 不影响新模型；主模型及稀疏模型通过工程回归，视觉审定证据齐全后才开启自动演出。

### G4 — 自然演出与六个惊喜场景（P1）

**Goal / Scenario：** 倾听、思考、回应、安慰与成功反馈在适合的时刻发生，动作克制且有变化。

**Architecture Increment：** 轻量 cue anchor、通道内微动、冷却与可重放选择。

任务：

- G4.1 实现六个受限配方，每个写正例/反例/fallback；说话与动作锚定实际 segment 播放。
- G4.2 在空闲参数通道加入低幅度微动，显式 motion 到来让位；嘴部不被 idle 再次撑开。
- G4.3 按权重、冷却、近期使用和 seed 选择审定变体，过期 cue 丢弃；任务完成只接受真实成功事件。

**Tests：** 固定种子回放；慢 TTS 下 cue 不提前/补播；连续“好的”无密集大动作；失败不庆祝；打断立即收口；同配方热更新不改变正在执行的快照；六场景人工评分。

**DoD：** 无额外导演/情绪 LLM 往返；预热动作同步达标；六场景通过 §6 人工验收，首音频 p95 不比 G2 恶化，缺少素材的 fallback 仍贴合。

### G5 — 发布候选与证据闭环（P1）

**Goal / Scenario：** 长时间陪伴和连续输入仍稳定，能够复现故障并有界关闭。

**Architecture Increment：** 跨端场景 runner、有限事件复盘、持续回归门槛；不做任意外部副作用重放。

任务：

- G5.1 固化 §8 竞态矩阵，接入现有自动化；工程无 CI 时补最小自动检查入口，覆盖引擎测试与 shell 类型/构建。
- G5.2 每个支持配置完成正式延迟采样、60分钟交互 soak、冷启动/重连/关闭；记录峰值与基线对比。
- G5.3 记录错误分类、降级原因、资源预算和六场景录屏评分；同步 spec/当前架构与执行报告。

**Tests / DoD：** §6–§8 必须提供实测结果和待办，严重违和/污染/死锁为阻断项。云依赖、设备与视觉待验项明确标记，不宣称全绿。未达目标只能提交阶段进度，不能标记整个 Goal 完成。

阶段完成后，按失败数据只选择一项后续扩展：AEC、可用对齐数据驱动的词级 cue、记忆驱动的稀有表现、按需 Skill 或长任务恢复。扩展须新增独立 Goal，不在本轮顺手引入。

## 8. 最小竞态与故障验收矩阵

| ID | 故障注入 | 必须证明 |
|---|---|---|
| R01 | LLM 流、工具/审批等待期间 stop | 先静音、旧批准失效、后端如实收敛 |
| R02 | decode Promise 完成前 stop，随后返回旧音频 | 旧段不 start，不改新队列/计数 |
| R03 | 第二段合成迟到，新 turn 已播放 | 旧段被丢弃，新段正常结束 |
| R04 | 文字与语音同 Session 交叉输入 | 唯一有效前台 turn，开关行为保持 |
| R05 | 换 Session/重启/reconnect，旧 WS 消息到达 | 绑定/engine instance 身份隔离，不重播 |
| R06 | motion 启动失败、完成回调迟到、Loop 不自然结束 | 成功状态真实、旧回调不重置新状态、watchdog 有界 |
| R07 | 换模型/替换资源/编辑 profile 时异步结果返回 | revision/cache 正确，当前配方快照稳定 |
| R08 | 语音与 motion/idle 同写嘴眼参数 | 通道 ownership 生效，结束后不持续张嘴 |
| R09 | 翻译/检索/TTS timeout、空音频、输出开关关闭 | 终态与 fallback 可见，无无限等待/重复播报 |
| R10 | memory/summary 在 turn reset 后完成 | 无 stale history/state/memory 提交；真实工具执行审计保留 |
| R11 | Presence 到达与热更新/shutdown 交错 | 不抢用户输出，Registry 无旧引用，任务与句柄有界释放 |
| R12 | 工具批次含同资源写入/媒体控制 | 顺序与结果关联正确，取消不伪装成回滚 |

优先使用手动可控 Promise、Event、fake clock/adapter 构造时序，避免依赖随机 sleep。场景 runner 在无 GPU/外部 API 时仍可证明身份和终态；真正延迟与演出另做实机验收。

## 9. IDE Agent 启动指令与报告模板

开始执行时按下列约束工作：

1. 读取本文件、根 AGENTS、当前 `docs/spec/` 与相关源码/测试。先核对 G0 报告和工作区变化；从首个未验收的阶段开始。
2. 先完成该阶段一个最小子任务及其契约/回归验证，提交可审查 diff。完成一个阶段再进入下一阶段；不把多个新框架一次性铺开。
   每次实现前按 §2.5 列出现有落点，按 §2.4/§7.1 列出本切片允许变更、保持不变、迁移入口及回退方式。目标职责已有实现时直接复用，不为匹配架构图新增平行类。
3. 保留所有用户未提交改动；可在相邻位置增量接入，重叠无法安全处理时明确报告具体文件与冲突。
4. 只读入相关源码/资源；不运行参考 ZIP 的安装器、不读取其中凭证、不复制模型权重或整个工程。模型原素材保持不改，扩展档案单独存储。
5. 修改行为时同步最小 spec；保留安全检查、语言约定、独立 TTS 进程和真实取消语义。
6. 每个阶段报告：变更/复用项、删掉的重复路径、测试命令结果、同条件指标、视觉审定状态、剩余风险与下一任务 ID。源码存在或测试数量不是完成证据。

验证命令：引擎在 `engine/` 使用 `..\.env-local\engine-venv2\Scripts\python.exe -m pytest tests/ -q`；shell 在 `shell/` 使用 `pnpm typecheck` 与 `pnpm build`。按 AGENTS 先加载项目环境，不安装无关依赖。触及 C++ 后端再执行该后端构建/契约测试。前端若新增测试脚本，须在报告提供确切可运行命令；不得引用当前不存在的 `pnpm test`。

建议阶段报告路径：`docs/plan/G0-realtime-baseline.md` 至 `G5-realtime-acceptance.md`，仅完成对应工作时创建。报告包含：

```text
阶段 / 子任务 ID / 基线 commit + dirty 摘要 / 配置与设备
Goal / Scenario / Architecture Increment
实现与兼容方式 / 开源来源及改良点 / 回退策略
现有模块→目标职责 / 唯一 owner / 本切片改动边界
迁移入口与旧路径退出 / 临时适配器删除条件 / 既有失败与新增回归
Unit + 跨端场景结果 / p50 p95 max + 失败率 / 视觉证据
DoD：通过、未通过、待人工验收（分别列出）
已知问题与下一任务 ID
```

最终完成条件：取消后旧输出不再出现；所有前台输出共用一个调度；播放事实驱动演出时机；模型只使用审定且适配的资源；六个场景自然可复现；正式延迟与长时间稳定证据齐备。此时再启动能力扩展。
