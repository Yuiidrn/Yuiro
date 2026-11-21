# Yuiro：小内核、低延迟与资产驱动演出 — 架构决策及下一阶段 Goal

> 文档状态（2026-10-23）：保留为调研与源码证据。当前执行入口为 [统一架构与 Engineering Goal](2026-10-23-unified-architecture-engineering-goal.md)；本文旧阶段清单已被替代，不再独立推进。

日期：2026-10-22。工作区基线：`97753e9` + 当前未提交的 S53 Avatar/Live2D 改动。

本文是本次架构研究的交付及下一阶段实施建议。四份历史调研原文保持原样；本文没有修改现行 `docs/spec/`，也不表示下列行为已经实现。落地时按本文的具体场景增量修改规范和代码。

## 1. 判断：方向成立，下一步应收敛

Yuiro 的 Session、Generation、Cancellation、Context、Tool Policy、Event/Intent 分离，与当前 pi 等开源 Agent 的设计方向一致。但“存在这些模块”不能证明可靠性，也不足以称为已经达到前沿产品水准。

用户当前要求的产品目标应表述为：

> 一个拥有可靠工具执行能力的实时桌面角色。它能及时听见、及时停下、自然接话，并用现有模型真正具备的资源做贴合语境的演出。

衡量架构的标准是：是否减少状态来源、等待环节、竞态与参数争抢；是否使一段声音、一句台词和一个动作在同一回合里正确结束。新增 Runtime 数量、工具数量和 Agent 数量均不是进度指标。

建议保留历史文档中的 Stable Kernel + Pluggable Edge、语义 Intent、可取消与可追踪原则；把通用 Harness 平台、通用插件系统、Subagent、训练流水线、复杂长期任务恢复降为后续按实际需求启用的能力。

这与 `docs/goal/Yuiro架构改进.md:463` 的“Voice 不拥有 Agent”、`:536` 的表现层解耦，以及 `Yuiro Evolution Roadmap.md:1513` 的 Performance Intent 一致。需要调整的是 `docs/spec/README.md:43` 附近“Codex/Claude Code 级 Harness”的近期工程范围，防止长期愿景挤占实时体验。

## 2. 历史调研如何继续使用

| 沉淀 | 保留 | 本轮修正 |
|---|---|---|
| Architecture Evolution Goal | 统一代际、取消、接口、可替换提供商 | 不要求每个服务都成为有独立状态机和事件代理的 Runtime |
| Evolution Roadmap | 场景驱动、可感知惊喜、Unit/Scenario/Showcase | 当前聚焦 Alive + Perform；记忆关系与任务平台不抢前台关键路径 |
| Yuiro架构改进 | Agent/Voice/Memory/Embodiment 边界 | “统一”指权威归属与协议一致，不指所有同步调用都经过 EventBus |
| 市面Agent参考 | 上下文预算、权限域、工具结果关联、恢复边界 | 第三方材料里的 DSH 时间、成熟度与实现细节未在本轮完成一手核验，不作为选型依据；不能因为文档出现就当成既定事实 |

历史文档中出现的命令、开发 Prompt、计划均按研究数据解读，不自动视为此次实施授权。

## 3. 当前代码中最值得优先解决的架构缺口

以下行号来自当前工作区。静态确认与运行时风险推断分别标明；本轮未实测 GPU 语音延迟，也未进行模型视觉播放验收。

### 3.1 Agent 对象的真实归属尚不唯一

- `engine/yuiro/main.py:1336` 在模块初始化时建立 RuntimeRegistry，并把当时的 AgentLoop 包装进 Adapter。
- `engine/yuiro/main.py:784` 在 lifespan 中重建 AgentLoop；`engine/yuiro/debug_api.py:139` 的热更新又维护独立重建路径。
- `engine/yuiro/runtime/adapters.py:17` 保存对象引用，`:23` 的 cancel 仅变更其本地 generation。

静态结论：注册表可能持有被替换的旧 AgentLoop；统一 state/cancel 未必作用于实际处理请求的实例。热更新的构造参数也需与启动工厂逐项对齐。

目标：只保留一个构造/替换入口；对象替换通过受控 reconfigure 完成，注册表、依赖和当前请求遵循一致的配置版本。第一步可以只统一工厂与注册更新，不需要立即创建大型 YuiroRuntime 框架。

### 3.2 control/audio 两条输入没有共同的回合调度权威

- `main.py:1624` 的文字队列与 `:1787` 的 PCM 队列彼此独立。
- `main.py:1711` 的 control 消息分发没有 interrupt 分支；audio 在 `:1817` 有。
- `runtime/adapters.py:23` 没有持有 Agent task 并真正取消的实现。

风险：同一 Session 的文字/语音可争抢代际；新文字输入排队不等于旧回合立即作废；仅在返回结果时检查 stale，不能阻止已经开始的工具副作用。

目标：Session 的 TurnCoordinator 拥有唯一 active foreground turn；文字、语音、UI stop 使用同一套 supersede/interrupt/queue 策略。仍保留原 AgentLoop 和 VoicePipeline 的具体实现。

### 3.3 前端 stopPlayback 仍有解码竞态

- `shell/src/renderer/src/composables/useVoiceInput.ts:208` 的 playOne 在 `:214` 等待 decodeAudioData，然后创建播放源并在 `:231` 启动。
- `:250` 的 stopPlayback 清队列和 currentSource，但解码中的这一段还没有 currentSource；解码返回后没有再次校验 epoch。

静态风险：用户按停止时若正处于解码，旧音频仍可能在停止之后启动。测试应通过延迟 decodeAudioData 的 Promise 确定性复现，再确认实际结果。

目标：播放项携带 turn/generation/output_epoch/segment_id；每次异步解码、预加载、渲染完成后检查身份；开始播放和 onended 回调也必须校验当前 owner。

### 3.4 文本朗读和语音回复复用提供商，却没有统一输出编排

- `main.py:1224` 的 _speak_reply 直接取 `pipe._tts`，整轮文字回复结束后逐句翻译/合成。
- `audio/__init__.py:705` 的 TTSTaskManager 是语音回复的保序/并发/epoch 管理器。
- `audio/__init__.py:1559` 在逐句渲染后入 TTS，但 `:1578`、`:1582` 可创建多个渲染 task；TTS 信号量只约束合成，并不自动约束翻译等上游 task。

目标：文字、语音、Presence 共享 SpeechOutputScheduler；传输通道可暂时保留两条。一个输出项只有一套取消、顺序、缓冲和播放回执语义。给整条输出管线设置有界缓冲，不能只限制 TTS 同时运行数量。

### 3.5 现有 Avatar 映射尚不能保证“贴切”

- `shell/src/shared/live2dInfer.ts:40` 把 bye 与 hello 合并为 greet；`:44` 把 cry/tear/sad 与 comfort 合并。
- `shell/src/renderer/src/avatar/avatarSlots.ts:90` 选择槽位候选；自动识别和资源存在校验不能代替艺术语义确认。
- `shell/src/renderer/src/components/Live2DCanvas.vue:485` 默认 FORCE；`:502` 调用异步 startMotion 而未等待结果，立即更新“播放中”状态。安装版本声明见 `shell/node_modules/pixi-live2d-display/types/index.d.ts:795`，返回类型为 Promise<boolean>。
- `:541` 的 applyAvatarIntent 没有接收/检查 turn、generation、intent_id、model_revision；`:557` 主要按时长排回落。
- `engine/yuiro/avatar/runtime.py:172` 以引擎本地优先级/时间裁决；`:197` 取消只清引擎记录，没有向 renderer 发取消动作命令。

风险：打招呼选到告别，安慰用户却选到角色哭泣；新动作打断旧动作；加载失败被记成成功；旧回调覆盖新模型或新回合。上述语义不适配需要视觉验证，文件名本身只构成审查线索。

目标：模型档案经人工审定后成为演出权威；引擎只提语义建议，renderer Director 决定实际动作与完成状态。

### 3.6 动作、口型与呼吸需要参数归属

- `Live2DCanvas.vue:220` 的 ticker 在 model.update 前通过可选 setParamFloat 写入口型，需验证当前 Cubism4 模型实际 API 与更新顺序；可选链无异常不等于写入生效。
- 实际检查 Hiyori 和 Hotaru 的动作 JSON，均存在大量与口部/眼睛/身体重叠的曲线。例如 Hotaru `mtn_thinking01_C.motion3.json` 与 Hiyori `Hiyori_m01.motion3.json` 包含 ParamMouthOpenY。

目标：每个渲染帧按明确顺序混合；说话期间 mouth-open 由语音拥有，结束后短暂收口再平滑交还动作；expression、blink、gaze、body 各有规则。先做通道级归属，避免过早建设通用动画图。

## 4. 可核验的开源参考与接入方式

调研时固定上游 commit，避免后续 main 分支变化导致引用漂移。以下代码均通过 GitHub raw 源文件读取核验；采用前应核验引入文件的依赖与许可证。

### 4.1 pi：借执行语义，不替换现有 Python Engine

仓库旧地址 badlogic/pi-mono 当前重定向至 earendil-works/pi。本轮 commit：`58c0b02ce552adab76014e7ed712ab7981359aa8`。

- [agent.ts](https://github.com/earendil-works/pi/blob/58c0b02ce552adab76014e7ed712ab7981359aa8/packages/agent/src/agent.ts#L307)：steer/followUp 队列；`:350` abort；`:359` waitForIdle。
- [agent-loop.ts](https://github.com/earendil-works/pi/blob/58c0b02ce552adab76014e7ed712ab7981359aa8/packages/agent/src/agent-loop.ts#L518)：可选择 sequential/parallel；存在 sequential 工具时整批按顺序执行；上下文转换接口位于同文件约 `:400`。
- [agent README](https://github.com/earendil-works/pi/blob/58c0b02ce552adab76014e7ed712ab7981359aa8/packages/agent/README.md)：应用消息与模型消息分离、请求准备、事件生命周期与可等待结束。

Yuiro 改良：

1. 将 abort + await settlement 的契约用 asyncio 实现，绑定 Session generation；不为使用 TypeScript 包额外启动一个 Agent Node 进程。
2. 不把 steer 当作实时打断：pi 的 steer 是在调度检查点注入输入；Yuiro 的停播必须立即发生，不能等待工具轮结束。
3. 工具按副作用分级调度：独立只读可并行；相同目录写入、播放器控制、同资源事务默认串行。当前 ToolDispatcher.run_batch 的 gather 需要这一约束。
4. 业务状态、UI 事件、模型上下文分开；角色表情不会成为大段 tool history。

### 4.2 AIRI：借语音/播放职责与渲染混合方法

commit：`448ada1a41c29d84b3975a73ee732f7bdcd13c27`。

- [speech-pipeline.ts](https://github.com/moeru-ai/airi/blob/448ada1a41c29d84b3975a73ee732f7bdcd13c27/packages/pipelines-audio/src/speech-pipeline.ts)：Intent、并发合成、播放 timeline、queue/interrupt/replace。
- [playback-manager.ts](https://github.com/moeru-ai/airi/blob/448ada1a41c29d84b3975a73ee732f7bdcd13c27/packages/pipelines-audio/src/managers/playback-manager.ts)：按 owner/intent 停播、播放 start/end/interrupt/reject、旧异步完成的身份检查。
- [voice/interruption.ts](https://github.com/moeru-ai/airi/blob/448ada1a41c29d84b3975a73ee732f7bdcd13c27/packages/core-agent/src/voice/interruption.ts)：silenced 与 durable notification 的 done 分别建模。
- [motion-manager.ts](https://github.com/moeru-ai/airi/blob/448ada1a41c29d84b3975a73ee732f7bdcd13c27/packages/stage-ui-live2d/src/composables/live2d/motion-manager.ts#L751)：说话标志、口型释放尾段和交接，避免 idle 曲线重新撑嘴。

Yuiro 改良：移植前端纯逻辑和测试场景时保留 attribution，用本项目接口适配。首版只支持一个角色声音，采用更少的队列策略与依赖；上游默认并发数不能直接用于本机 RTX 3060，需实测 1/2 并发的延迟和显存竞争。Python 仍拥有 TTS 生产，Electron renderer 拥有最终播放事实。

### 4.3 Open-LLM-VTuber：借中断与“真正听到的内容”

commit：`992309c0aa19845960228f880013d4685fde93b5`。

- [conversation_handler.py](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/conversations/conversation_handler.py#L112)：中断取消会话任务，并把 heard_response 传回 Agent/历史。
- [tts_manager.py](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/conversations/tts_manager.py)：TTS 并行生产与有序下发。Yuiro 已有同类管理器，优先修补既有路径。

Yuiro 改良：PlaybackReceipt 记录 completed_segment_ids 和当前 segment 的 played_ms；已合成、已下发、已开始、已播完分别标记。没有词级对齐时，仅确定已完整播出的句子，当前句只记录时间进度，不假装能从音频秒数精确推断用户听到了哪个字。语言转换后用 segment_id 关联内部文本、展示文本、朗读文本。

### 4.4 Cubism：遵循动画资源与 SDK 的边界

[官方 Motion 文档](https://docs.live2d.com/en/cubism-sdk-manual/motion/)用于核对 motion 的播放、淡入淡出、管理与回调。以安装的 pixi-live2d-display API 为具体适配依据，不能直接把原生 Cubism 示例函数名复制进 Vue。

代码许可与模型资源分开登记。pi、AIRI 本轮仓库许可为 MIT；Open-LLM-VTuber 的 LICENSE 正文为 MIT，并明确 Live2D 样例另受 LICENSE-Live2D.md 约束。真正移植的文件记录 upstream URL、commit、license、依赖、修改点与对应测试；现有模型不因来源项目开源就自动获得相同分发许可。

### 4.5 补充参考：Project Waifu 本地源码包

依据：`D:/Project/Yuii/desktop-pet/_pack/Project_Waifu-main.zip`；SHA256：`C9CF0DAACDECB0854417C949A958F7E69C2450A6C2614C24B29AA825F769E7C9`。以下路径、行号均指压缩包 `Project_Waifu-main/` 内的文件。本次直接读取源码，未运行包内程序，未读取凭证配置。它不含可确认的 Git commit，不能把文件夹 main 当作版本号。

定位修正：这是具体运行机制与角色演出的重要参考，但本包未见统一的 SessionManager/RuntimeRegistry/Agent 工具循环。不能凭 Runtime 命名推断它已经实现 Yuiro 目标里的完整执行内核；现有调研文档也未检索到 Project Waifu 的明确溯源记录。

**优先借鉴的五个机制：**

1. `llm/novelai_runtime.py:12` 的 NovelRuntime：拥有生成排队、HTTP/client session、close；`:31` 用优先级堆分配生成执行权，`:69` 按 asyncio loop 隔离实例。它是具体 provider 的资源运行管理器。Yuiro 可把前台生成与后台摘要放入同一资源预算管理，复用连接并记录 queue wait。需要补充超时、aging 和独立取消；这是非抢占队列，已运行的后台请求不会因为前台到来就立刻让出执行权。
2. `tts/sentence_pipeline.py:23`：一个准备 worker，播放当前句时只预取下一句。`:55` 明确迟到的阻塞 SDK 只允许准备音频，不能自行播放。这是“有界预取＋生产和播放分权”的精简示例。Yuiro 应保留现有异步 TTS manager，增加可配置 lookahead/缓冲上限，实测 1 与 2 的收益；不复制线程体系。其分句正则要求标点后有空白，不适合直接用于中文连续句。
3. `vtube_studio/advanced.py:46` 的 AdvancedActions：talking/idle/reset 生命周期；`:53`、`:100` 跟踪并只清理自己激活的表情，`:110` 防止跨模型清理；`:144` 固定当前配置快照，异常通过 shield 清理。Yuiro Director 应吸收“效果归属＋配方快照＋结束回收”，用 cue_id/model_revision 表达；不复制 VTube Studio hotkey 协议。其 run 在 manager 锁内包含 wait，Yuiro 不应让长等待占用全局控制锁。
4. `vtube_studio/idle_animations.py:269` 的参数通道与配置，`:516` 的情绪幅度/速度调节，`:667` 的本地 tick，`:820` 的低频手势和权重选择。Yuiro 可在 Electron renderer 本地实现低强度微动层；服从真实模型参数边界、口型和 motion 的 ownership。已有动作、呼吸、眨眼驱动时避免重复写入；不沿用它默认 15 FPS 的 VTS 参数传输方式。
5. `speech_to_text/utterance_capture.py:158` 的有界队列、`:295` 的 audio epoch 检查和 `:302` 的暂停/恢复重置，是设备切换和旧音频丢弃的可用参照。`tts/overlapped.py:44` 的逐句字幕/音频绑定与 `:94` 的首音频写入计时，也可映射到 Yuiro segment/PlaybackReceipt；音频写入仍不等于用户实际听见。

**不应沿用的主链路限制：**

- `main_loop/turn_control.py:8` 是进程全局 interrupt/pause Event；`main_loop/main_loop.py:503` 在新轮清标志。Yuiro 已有 Session/generation，继续使用每轮取消身份；不可回退到全局布尔标记。
- `main_loop/main_loop.py:604` 等待完整生成后，`:721` 才 speak(response)。TTS 的句间重叠不等于 LLM 首句到达即可开播；Yuiro 应保留已有流式 LLM→首句 TTS。
- `main_loop/main_loop.py:647` 与 `:669` 在播放前写记忆/完成对话记录；不能据此证明内容已经被用户听到。Yuiro 需要分别记录 generated、played、interrupted。
- `main_loop/main_loop.py:684` 启动情绪推断，`:397` 的路径允许独立推断等待；这是并发旁路，不是整轮必然增加六秒。Yuiro 仍需限制过期情绪影响，首版优先已有语义事件和本地规则。
- 本包未发现测试目录或常见 test 文件；本轮仅做静态审阅，不宣称其低延迟、稳定性或视觉效果已得到实测证明。

**对阶段 Goal 的具体补充：** G1 增加旧 epoch 音频与前台/后台排队测试；G2 对比单句 lookahead 和现有并发策略；G3 增加 owned effects、配方配置快照与跨模型清理测试；G4 在审定资源之上添加低强度、受情绪调节的本地微动。无需为这五项再新增一个常驻服务或通用框架。

## 5. 目标架构：三个权威，两个时间域

```text
Electron 输入适配器（文字 / 麦克风 / UI stop）
                    │
Python Session + TurnCoordinator
    ├── AgentLoop ← Context / Memory / Tools / Policy
    └── SpeechOutputScheduler ← 原有 TTS provider / 语言渲染
                    │
        语义 cue + 带身份的音频 segment
                    │
Electron PlaybackController ── 播放游标与回执 ── PerformanceDirector
                                                   │
                                 已审定 ModelPerformanceProfile
                                                   │
                                      当前 Pixi/Cubism adapter
```

三个权威：

1. Session/TurnCoordinator 决定哪个回合有效、输入如何覆盖、任务由谁取消。
2. PlaybackController 决定哪段声音真正开始/结束、播放进度到哪里。
3. PerformanceDirector 决定此刻这个身体能演什么、资源冲突如何处理。

两个时间域：引擎业务顺序依赖 turn/generation/seq；本地声音与演出依赖 AudioContext 播放时间。跨进程通过 ID 与 ACK 关联，不用服务器时间戳直接驱动客户端口型。

Director 是现有 AvatarRuntime/Live2DCanvas 的职责收敛，不是增加一个会调用 LLM 的导演 Agent。AvatarRuntime 可以保留语义意图生产与配置，移除重复的实际播放裁决；文件是否拆分由调用关系决定。

### 5.1 最小契约

所有前台输出关联 session_id、generation、turn_id、output_epoch；音频增加 segment_id/seq，演出增加 cue_id/model_revision。使用同一个 Envelope 避免各接口复制不一致字段。

```text
SpeechSegment
  identity + seq + audio + internal_text_ref + display_text + speak_text

PerformanceCue
  identity + cue_id + semantic + intensity + anchor + ttl_ms
  anchor = immediate | segment_start | segment_end

PlaybackReceipt
  identity + segment_id + status + played_ms
  status = started | completed | interrupted | failed

PerformanceReceipt
  identity + cue_id + model_revision + actual_asset + status + fallback_reason
```

不要给每帧 RMS 创建可靠业务事件；口型、眨眼与视线在 renderer 本地更新。持久化回合/工具/播放边界和少量演出结果即可。

### 5.2 中断有两个完成边界

用户打断 → renderer 立即递增输出 epoch、停音、停止口型及旧演出；同时发送 cancel → Engine 作废 generation、取消 LLM/工具/审批/TTS，并在限定时间内报告收敛状态。

`silenced` 不等待 `settled`。非协作线程/外部 HTTP 推理可能继续运行，不能把丢弃结果谎报为底层计算已停止；副作用工具记录 running/cancel_requested/completed/unknown 等真实状态。已提交的操作需要补偿或回滚，Cancellation 本身不等于撤销。

## 6. 现有模型足够，缺少的是可验证的演出档案

本轮直接遍历 model3.json 得到：

| 模型 | 表情引用 | 动作引用 | 当前使用重点 |
|---|---:|---:|---|
| Hiyori | 8 | 13 | 安静陪伴、倾听/思考/短回应；动作组名不能决定动作语义 |
| 肥牛 | 7 | 14 | 编号表情/动作需逐条审定，不共享 Hiyori 的索引假设 |
| Mao Pro | 8 | 7 | 精简模型，验证缺少语义槽位时的表达降级 |
| Hotaru casual | 46 | 67 | 表现力主样本，验证丰富资源的选择、节奏和参数冲突 |
| Hotaru child still | 10 | 3 | 极少动作样本；能力不足应自然静态表达 |

Hotaru live 另有 46/67；两个 live-mode 变体各 0/9。上述为引用数，不等于独立且已审定的演出数量，也不证明视觉质量。

Hiyori 多个 motion 的 Meta.Loop=true，时长约 1.1–8.57s。一次性“点头/庆祝”不能只按 Duration 估计结束，还需确认库运行时如何处理 Loop；不能直接修改原始资源来规避调度问题。

### 6.1 ModelPerformanceProfile 最小内容

每个可选动作/表情记录：asset_id、reviewed、语义、强度、方向、真实时长、循环策略、可否打断、fade、口/眼/头/身体影响范围、适用场景、禁止场景、冷却和选择权重。

自动扫描负责读取 Duration、Loop、曲线参数和资源有效性；文件名推断只产生未审定候选。人工预览确认语义和强度后才进入自动演出池，区分 `farewell/greet`、`sad/comfort`、`celebrate/sing`。优先单独档案覆盖，不重命名原素材。

时长不等于动作幅度。现有 idleCandidates 的时长过滤可保留作辅助，但“短”不能证明适合静态待机。默认只启用已审定的低强度 idle，缺少时使用呼吸/眨眼。

### 6.2 Director 先实现六条规则

1. 安全与显式 interrupt 最高；用户互动高于主动搭话；idle 不抢占前台动作。
2. 说话期间语音拥有 mouth-open，body motion 不覆盖口型；眨眼和表情按参数规则协调。
3. motion 等待实际启动结果；完成回调为主，计时器仅作 watchdog；无法确认结束时发出明确结果。
4. cue 超过 TTL、generation 作废、model_revision 改变就丢弃；绝不补播已经过时的庆祝。
5. 同语义候选加冷却、最近使用惩罚、有限权重随机；复盘时记录 seed/实际选择。
6. 资源不支持时降级到已审定表情或静态；不要用“最像的文件名”填满所有语义。

### 6.3 惊喜来自时机和克制

建立 6 个短演出配方：自然迎接、侧耳倾听、短暂思考、轻微得意、克制安慰、任务完成庆祝。配方调用实际已审定资源；缺少资源时使用对应低强度表达。无需另造完整 DSL，先用受类型检查的配置。

例如：安慰时轻表情＋温和视线；任务失败不庆祝；任务真的成功且相关音频开始时短庆祝；用户打断时立即收口并回到倾听。只有较高置信度、上下文合适且冷却允许时触发稀有变体。普通“好的”不反复大幅摆动。

LLM 若提供情绪 cue，沿原流式输出附带紧凑可忽略标签，采用增量解析；解析不完整也不能卡住正文。首版由真实任务事件和状态驱动已足够，禁止为每句再调用一个模型决定演出。

## 7. 低延迟设计与验收预算

以下是建议验收目标，不是当前实测成绩。首先固定本机硬件、TTS provider、语言配置、网络与语料，测至少 100 个热启动样本；冷启动单独报告。不同 provider 不混为一个 p95。

| 指标 | 计时边界 | 首阶段目标 |
|---|---|---|
| 可见响应 | 已接受输入/确认 speech_start → 倾听状态可见 | p95 ≤150ms |
| 本地静音 | renderer 收到 stop/interrupt → 音频停止 | p95 ≤100ms |
| 协作任务取消收敛 | Engine 接受 cancel → 自有可取消任务结束 | p95 ≤500ms；外部不可取消计算单列 |
| 首音频 | speech_end → renderer 实际首段开始 | 热启动纯聊天争取 p50 ≤1.5s、p95 ≤3s |
| 演出同步 | cue 锚点对应播放开始 → 实际动作开始 | 预热资产 p95 绝对偏差 ≤100ms |
| 旧结果污染 | 取消/换模型后旧音频、旧 cue、旧回调进入当前状态 | 确定性竞态测试 0 次 |

首音频应拆为端点等待、ASR、context/memory、LLM 首个可播句、语言渲染、TTS、传输/解码/播放。超过目标时据分段数据优化；工具长任务不要求在 3 秒内完成。

具体策略：

- 控制关键路径仅有必要的 ASR/模型/TTS 调用；首句不等完整回复、全部工具解释或全部记忆维护。
- 不阻塞的本地倾听/思考表现先出现，但不伪装为已经完成任务。
- 前台检索给短预算；未按时完成的结果只作用于后续请求或安全降级，不插入已提交的旧回合。
- 保留目前内部中文与展示/朗读语言分离的用户约定；跨语言渲染单独计时，限制并发、复用缓存并设置超时。不能为追求延迟擅自改变内部语言协议。
- 单独本地 TTS 进程保留；用数据决定 TTS 并发与 BGE/ASR 的 CPU/GPU 资源分配。
- 音频只预解码有限数量段，用 AudioContext 时间调度播放；异常恢复必须经过 epoch 检查。
- 表现规划、记忆写入/整理、日志存盘不与首句串行等待；关键事务审计仍需保留可靠记录，区分 durable 与 best-effort。

## 8. 可直接执行的阶段任务

### G0：建立基线与模型能力样本

Goal：固定可复现基线；Scenario：一段文字、一段语音、一次打断、一次换模型都有同一组记录。

Architecture Increment：增加统一 ID 记录与资产审查数据，不扩建 Runtime。

任务：记录 commit/dirty diff；列出双输入和三种输出链路；做 Hiyori、Hotaru casual、Mao 资源表；测各阶段延迟；选 6 个 Showcase。

Tests：固定时序模拟、资源清单与引用校验；真实本机延迟测量。

DoD：提交基线报告、可复现实验条件、未审定资源列表；不以既有单元测试通过代替语音/视觉验收。

### G1：统一回合归属与立即静音（P0）

Goal：文字/语音都能可靠打断。Scenario：解码未结束、工具等待、审批未决时打断，旧结果均无法恢复输出。

Architecture Increment：Session 内 TurnCoordinator + 前端 output_epoch，统一工厂注册。

任务：保存 Agent task；control interrupt 接线；音频解码与回调身份 guard；审批绑定 turn/generation；替换 AgentLoop 时同步注册；副作用工具执行分类。

Tests：延迟 decode 后 stop；旧 onended 晚到；文字/语音同 Session 竞争；工具取消后晚批准；启动/热更新的 registry 对象与请求对象一致。

DoD：本地静音不等后台收敛；所有状态如实报告；原工具/语音回归测试通过。

### G2：统一语音输出与播放回执（P0/P1）

Goal：文字、语音、主动发言共用输出协议。Scenario：长回复边生成边说，打断后旧 segment 不再播放。

Architecture Increment：SpeechOutputScheduler、segment ID、PlaybackReceipt；保留原提供商。

任务：合并 _speak_reply 与语音输出编排；限制翻译/合成/预解码缓冲；AudioContext 主时钟；记录实际播出与未播出；Presence 忙时丢弃或延后且有 TTL。

Tests：乱序合成、单段失败、解码失败、交叉输入、播放 end/interrupt 区分；跨语言 segment 关联。

DoD：任何来源不会同时抢同一个角色声音；可从 trace 看出延迟发生在哪一段。

### G3：模型档案与渲染裁决（P1）

Goal：每个自动动作都贴合且可解释。Scenario：Hiyori、Hotaru、Mao 切换后各用自己的能力，旧动作不影响新模型。

Architecture Increment：扩展现有 manifest/profile + 单一 PerformanceDirector。

任务：区分 greet/farewell 与 sad/comfort；人工审定候选；等待 motion 启动/完成；model_revision；循环策略；通道归属；FORCE 仅留明确紧急/调试用途。

Tests：异步动作启动失败、旧完成回调、循环 motion、mouth/eye 冲突、无资源 fallback；选定场景人工录屏复核。

DoD：自动池全部 reviewed；不再以时长/文件名作为语义正确性的唯一证据。

### G4：六个带节奏的演出配方（P1）

Goal：自然且偶有惊喜。Scenario：倾听/回应/安慰/成功庆祝的动作在正确的语音时刻发生。

Architecture Increment：轻量 cue anchor + 冷却/近期历史，优先复用现有 performance 配置。

任务：6 个配方；已预热动作；失败不庆祝；被打断后恢复倾听；对普通回应减少大幅动作；有限随机带 seed。

Tests：固定种子回放、 cue 过期、先快后慢的 LLM/TTS、连续同类回应；人工评审节奏与角色一致性。

DoD：每个配方有正例、反例、fallback；没有额外导演 LLM 往返；首音频 p95 相对 G0 不恶化。

### G5：完成体验后再扩展（P2）

基于实测决定下一项：AEC/turn-taking、模型支持的 phoneme/viseme、记忆驱动的稀有个性化回应、按需 Skill、长任务恢复。每次仅选择一个有明确场景与预算的增量。

高精度词级动作锚定依赖真实对齐数据；未具备时使用 segment 边界。全双工 AEC 也要先证明误打断/回声是主要瓶颈，不能用新增服务掩盖播放身份竞态。

## 9. 执行约束与最终完成条件

- 保留 Electron + Python Engine + 独立本地 TTS；native 默认、C++ 可选的系统执行边界继续复用。
- 不引入通用工作流引擎、消息中间件、常驻多 Agent、完整行为树或新的 Agent 服务进程。
- Registry 管依赖/健康；直接调用承载有返回值的同步业务；Event 承载已发生事实；Cue/Intent 承载表演请求。
- 任一新队列必须有容量、owner、取消和超时/过期策略；任一新状态必须指定唯一写入者。
- 每个阶段包含 Goal / Scenario / Architecture Increment / Tests / DoD；行为规范随对应实现更新，不先批量改写全部 spec。
- 开源复用采用“固定版本 → 提取最小模块或移植机制 → Yuiro adapter → 契约测试 → 本机对比”。没有证据证明收益的依赖不进入主路径。

本阶段完成意味着：可真实取消、旧结果不污染；文字/语音/Presence 共享一个输出调度；声音的实际播放决定演出时机；现有模型的审定资源可靠运行；六个小场景带来可复现且不违和的惊喜。

本轮仅添加此研究文档；不重跑前次 772 测试来包装成本轮运行时验证，也不将本文目标数字作为已达成结果。
