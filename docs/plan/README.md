[表情与眨眼顺序修复](2026-11-10-expression-blink-order.md)：实际闭眼笑被SDK后写眨眼覆盖，现已修复；双角色中性/表情/回落原生参数与动作+合成口型组合通过，类型/构建通过。用户暂不方便人工验收，继续自动验证。

[语音设置双向同步](2026-11-10-speech-settings-live-sync.md)：调试台/聊天坞开关双向回读、角色与乱序保护已补；八次真实窗口变化和dirty标记保护通过，配置完整恢复，实际开麦门控仍待人工复验。

[主语音完整释放](2026-11-10-voice-audio-context-lifecycle.md)：dispose幂等关闭AudioContext，停麦仍保留输出；生产专项与类型/构建通过，真实WebAudio六实例均closed。人工Hiyori准备答复尚待，麦克风保持关闭。

[日记连接与迟到音频隔离](2026-11-10-diary-connection-ownership.md)：异步建连epoch/socket归属与旧play失败提示隔离已修复；三个生产专项、类型/构建和实际双角色日记连接通过，临时窗口关闭、恢复Hotaru。

[当前候选说话中无刷新换角](2026-11-10-avatar-midplay-current.md)：真实文字TTS播放中两方向清理通过，保留首次Fish连接失败、只读检查及独立反向补测；恢复Hotaru，配置未变，人工听感未新增确认。

[当前候选双角色自然语言实测](2026-11-10-avatar-dual-natural-current.md)：正式切换、真实Agent招呼和TTS，两角色实际动作/回执/语音身份/口型绑定/结束回落通过；配置一致，恢复Hotaru。真人麦克风与主观自然度仍待验。

[动态资源与头像预览](2026-11-10-avatar-dynamic-resource-review.md)：六段本地真实预览完整周期与18帧已补；修正Hotaru表情头像留白，前端类型/构建通过，角色配置未变，整套语义审定仍未完成。

[文本与语音输出交接](2026-11-10-speech-turn-handoff.md)：新文本停止并join旧语音/文字朗读，统一打断覆盖文字朗读请求；最新1000项后端测试通过，媒体/日记入口及真人自然度继续验收。

[语音中间状态隔离](2026-11-10-speech-state-identity.md)：状态帧身份、异步转发复核、任务取消epoch继承与旧trace所有权已补；最新995项后端回归通过，前端沿用已通过构建；跨Runtime generation编排与真人验收仍待完成。

# Sprint 索引与进展（Yuiro Runtime 演进）

## 当前优先项：C0 双角色隔离

[Fish单轮WebSocket实装](2026-11-11-fish-websocket-integration.md)：可选角色级传输、提前握手和持续分句输入已接现有Runtime，取消与换代回收覆盖；1032项后端全量、前端类型/构建、真实LLM/翻译/WS和实际配置/合成API通过。测试后恢复Hotaru HTTP，Hiyori未变、闭麦；真人听感与端到端P95仍待验，不宣称供应商波动消失。

[首句交付与WS提前握手](2026-11-11-tts-sentence-admission.md)：修复短“嗯。”阻塞后续完整句直到EOF，已部署；生产函数模拟交付343→42ms，非声学指标。独立WS提前连接实验文本就绪后首480ms约541/520ms，未接生产LLM。1021项后端全量通过。

[Fish传输优化](2026-11-10-fish-transport-iteration.md)：HTTP连接池已部署，真实暖请求0次TCP/TLS；直连失败保留原路径。独立WS双向文本流验证通过，但本轮未快过暖HTTP，暂不替换生产。1014项后端全量通过，延迟稳定性仍待验。

[Agent互动新一轮](2026-11-10-agent-reaction-iteration.md)：真实工具阶段/结果驱动短反应，身份隔离、去重/冷却、用户优先级及角色独立调参已补；1011项后端全量、前端类型/构建和双角色本地整合通过。此新候选接续此前冻结候选，TTS波动仍未解决。

**当前Live2D候选与剩余验收统一入口：[候选收敛报告](2026-11-10-avatar-delivery-candidate.md)。** 545文件指纹一致、九个相关专项与双角色各300秒待机通过；六阶段缺口明确保留，真人/声学验收尚未完成。以下链接为分项过程与证据。

[安抚动作语义收敛](2026-11-10-avatar-comfort-semantics.md)：撤销sad/cry/tear自动映射comfort；Hotaru七个资源保留并可明确试播，Hiyori不受影响。真实主进程清单、预览、类型/构建通过，壳已重启生效。

[首段等待主窗口整合](2026-11-10-avatar-tts-waiting-integrated.md)：正式Hiyori→Hotaru→Hiyori，真实App/SDK/WebAudio本地入站回放六场景、双向旧会话帧拒收通过；恢复Hotaru并移除钩子。无云端/麦克风，不代表真人声学验收。

[语音首段等待表现](2026-11-10-avatar-tts-waiting.md)：补齐首段等待与空音频的presence收尾，保留文字阅读时间；生产专项、双角色真实WebAudio四场景、类型/构建通过，不代表供应商TTFA改善。

[真实SDK重叠回放](2026-11-10-avatar-overlap-replay.md)：双角色高优先级表演/低优先级基础表情延后恢复、取消及换模型旧计时器隔离通过；当前构建本地预览证据，不代替正式角色服务或真人验收。

[动作启动请求归属](2026-11-10-motion-start-ownership.md)：修复旧异步启动失败清空新动作状态；生产函数竞态专项、双角色真实动作结束/取消四场景、类型与构建通过。

[表情异步加载取消](2026-11-10-expression-request-cancellation.md)：修复默认回落/选择当前表情后旧加载重新覆盖；实际SDK原始类竞态回归、双角色六阶段真实参数、类型与构建通过。

[最新表情/眨眼构建待机验证](2026-11-10-blink-order-idle-soak.md)：双角色各300秒通过有界自动验证，Hiyori固定Idle#0，绘制/眼睛更新持续；恢复Hotaru并关闭采样器。用户暂不方便人工验收，麦克风保持关闭。

[首句TTS延迟波动](tts-first-sentence-latency.md)（进行中）：首句入场、HTTP音频分块及有限重新缓冲已实现；983项后端测试及前端类型/构建通过。三次真实请求首段提前约1秒，但整合实机仍有供应商慢样本和欠载风险，连续听感与波动优化尚未通过。

[长回复隐藏滚动修复](2026-11-10-long-reply-scroll.md)：隔离对白曲线全局pointer-events污染，正文独立滚动、花饰留位，真实独立窗滚轮与末段可达验证通过。

[Live2D统一交付审计](live2d-acceptance-audit.md)（2026-11-10，整体未完成）：原六阶段要求、当前证据和待验范围；当前后端全量969项通过，Hotaru播放占用修复后真人打断听感通过，Hiyori实录与最终自然度仍待验。播放占用技术过程见[复盘](../tech_review/2026-11-10-speech-playback-ownership.md)。

[可视化角色演出工作台](appearance-studio.md)（2026-11-01）：两模型图卡、左右实时舞台、动作/表情/Agent分类预览、缩略图与收藏、单击池联动、Agent重复演出合并；真实构建UI验证与956项Python回归通过。

[桌宠单击反馈动作池](avatar-click-feedback.md)（2026-11-01）：角色/模型独立动作池、调试台增删/推荐/清空、轮廓内短按随机播放、拖动排除；真实构建renderer和调试台入口验证通过。

[Live2D自然交互持续实施](live2d-expression-evolution.md)（2026-10-31，进行中）：待机去重、持续表情恢复、本地倾听/思考/真实播放/取消状态联动；代码检查通过，分层仲裁与实机验收仍在推进。

[日记标题、多媒体与历史修订](diary-title-media-revisions.md)（2026-10-29）：语音栏同排保存、标题、图片/音视频本地附件、历史编辑与版本恢复、共享记忆联动；自动回归通过，截图启动被自动审批拒绝，实机视觉验收待补。

[日记陪伴独立会话方案](diary-companion-session-design.md)（2026-10-29）：Enter短回应/Ctrl+Enter段落回应、独立上下文与只读角色记忆、侧栏与独立TTS归属；替代停笔自动旁注的目标，D0–D3待实施。本轮已实施成功status轮询访问日志过滤，专项测试通过。

[日记自然插话与低延迟](diary-quip-natural-latency.md)（2026-10-27）：未提交片段的真实停笔触发、2/3/5秒节奏、继续输入即取消、插话不阻塞保存、首句收束与4秒预算；含实际窗口云端样本和935项回归。

[聊天坞自定义与博客式日记](dock-and-blog-diary.md)（2026-10-27）：位置/圆角/字号热更新；日记列表与清爽记录页、原文直存、草稿恢复与防重复，附两套配色截图及929项回归。后续视觉 Tab 见[调研与阶段验收方案](vision-tab-evaluation.md)，尚未实施摄像头。

[窗口/聊天坞高度与角花修复](window-height-dock-and-corners.md)（2026-10-27）：解除90%硬上限、保留手动几何及分数DPI稳定读回；输入条高度热更新，角花独立页脚与可调透明度。

[气泡调试台左右对照](ui-preview-side-by-side.md)（2026-10-27）：左预览/右参数独立滚动，模型与对白同尺度缩放，窄窗口回退；实机布局与热更新检查通过。

[模型优先与双角色真实桌面验收](model-first-desktop-acceptance.md)（2026-10-27，当前）：模型放大、头部右上紧凑对白、Alpha留白靠近、长文+真实选歌卡、边缘与换肤；含前后截图及正常捕获保护恢复证据。

[双角色漫画UI与自然语言音乐验收](manga-skins-and-natural-music.md)（2026-10-26，当前）：连续漫画轮廓、奶油/白花自动换肤、自然话术收藏/取消/推荐、卡片同步和原收藏恢复。

[短曲线与客户端喜欢/随机推荐](curve-and-client-favorites.md)（2026-10-26，当前）：曲线距离/弯曲热更新；双角色 Monody 结果卡喜欢、Agent取消并恢复收藏，客户端日推随机候选与隔离通过。

[极简单曲线与客户端原生搜歌](minimal-dialogue-and-client-search.md)（2026-10-26，当前）：无背景文字/开放曲线/字体颜色排版，单曲搜索与选歌脱离 ncm-cli/网易云 API；双角色 Max 自然语言搜歌、Monody 原版播放/暂停及清理通过。含喜欢/随机模式调查边界。

[Markdown、漫画气泡与网易云客户端入口](ui-comic-and-client-only.md)（2026-10-26）：安全 Markdown、真实模型相对预览、曲线气泡/功能岛自定义、旧形象移除、客户端唯一播放入口与工具约束；含随机候选及收藏/个性化能力边界。

[三面板并存与双角色 UI 验收](ui-multi-panel-acceptance.md)（2026-10-26）：歌曲/来源独立显示、三窗空位选择、四角/原生拖动/热更新与切换清理；真实检索和显式长文压力样本分开记录。见 [技术复盘](../tech_review/2026-10-26-ui-multi-panel-review.md)。

[调试台 UI 自定义补齐](ui-customization-refresh.md)（2026-10-24，最新）：独立回复/音乐/来源面板的排版、主题、来源独立样式、时长和安全预览；保留旧偏好，实际跨窗热更新、重载、分组重置、设置页卸载后同步与双角色清理通过。见 [技术复盘](../tech_review/2026-10-24-ui-customization-refresh.md)。

[Windows 官方客户端精确选歌与显式播放器选择](netease-exact-client-selection.md)（2026-10-24，最新）：编码命令 + 客户端独立 ID 读回，Monody 原版冷/暖启动与双角色真实点选/播放/暂停/切换清理通过；结果卡明确选择桌宠或网易云客户端，官方仅显示“暂停/继续”，不换版、不静默回退。Python 904 项通过。技术复盘见 [此处](../tech_review/2026-10-24-netease-exact-client-selection-review.md)。

[网易云通道权益与 Windows 官方客户端桥接验证](netease-channel-client-bridge.md)（2026-10-24，当前策略）：修正通道不可播与会员/版权的混淆；保留指定原版，禁止静默换版和空闲转控其他播放器。官方客户端 Monody 播放/暂停及人工听感通过；按 ID 自动定位、Stop 与进度仍有限制，未启用默认官方后端。技术复盘见 [此处](../tech_review/2026-10-24-netease-channel-client-bridge-review.md)。

[网易云扫码后真实搜歌/播放/停止补验](netease-real-playback-acceptance.md)（2026-10-24）：双角色隔离回合真实搜索、卡片点选/拖动、mpv 播放与停止、双向切换清理通过，人工听感确认正常；修复 IPC 状态误判导致的错误外部转控，858 项 Python 全量通过。同会话重搜不调工具仍单列 P1。

[独立回复/结果窗口实施与双角色验收](detached-ui-windows.md)（2026-10-24）：移除常驻“⋮”，回复/选歌/来源移到独立轻量窗口，原生拖动跟随、屏幕边缘避让、偏好热更新与切换清理；首轮因登录失效未验真实播放，现已完成上方隔离回合补验。技术过程见 [docs/tech_review](../tech_review/2026-10-24-detached-ui-windows-review.md)。

[动态轮廓命中 MVP 与原生点击验收](contour-hit-mvp.md)（2026-10-24，历史轮次）：Hiyori/Hotaru Alpha 遮罩、透明区域提前穿透与调试台热更新。后续拆窗、常驻入口移除及坐标修订以本页上方独立窗口报告为准。

[联网来源卡分流与语音正文双角色验收](search-presentation-acceptance.md)：资料/来源查询展示标题、摘要和日期，普通答案不默认弹卡；朗读去链接，双向切换清卡及旧身份拒收已实测。

[DeepSeek 联网检索替换与验收](deepseek-search-acceptance.md)：旧后端移除，独立安全密钥与调试台真实搜索接通；实际 Agent 调用并返回官网来源；827 项回归通过。

[Fish Audio HTTP 接入与充值后实机验收](C0-fish-audio-acceptance.md)：Hotaru 公共音色真实合成与调试台播放成功；说话中切换、合成取消、配置恢复已有证据。809 项回归通过。当前窗口后续聚焦前后端功能与体验调整，不推进 G1。

[C0 实机续验与 Hotaru 独立 SiliconFlow 音色](C0-live-acceptance.md)：真实切换、配置恢复与语音证据；793 项回归通过。声音听感及完整演出仍待人工审定，未进入 G1。

[C0 工程实现与验收报告](C0-character-isolation.md)：Hiyori / Hotaru Shiomi 独立配置、角色状态与调试台切换；全量 790 项通过。先做双角色实机验收，再续 G0 未验项及 G1–G5；不以自动化全绿代替声音/视觉与切换体验验收。

## 当前统一 Goal：G0 基线

当前资源重点为 **Hiyori + Hotaru Shiomi**；补充阅读：[实机续记](G0-live-acceptance.md)、[测试分层与 G0–G5 体验改善](G0-test-tiers-and-stage-effects.md)。下面首轮基线的样本状态是历史快照，最新进展请对照续记，不以单项通过替代整阶段验收。

[G0 当前源码、Runtime、Live2D 与延迟/回归基线](G0-realtime-baseline.md)（2026-10-23）：本轮 Python 772 项通过，前端类型检查/构建通过；静态资源与隔离时序证据已归档。真实热启动 0/30、视觉审定未完成，**G0 尚未整体验收，未进入 G1**。以下 Sprint 为历史记录，不替代本轮验收。

> 本目录是**执行层**记录：每个 Sprint 的计划、改动清单、冒烟证据、DoD 对照与遗留。
> 规范层（目标架构与协议）在 `docs/spec/`；两者冲突时以 `docs/spec/` 为准。
> 最近更新：2026-09-17。

## 1. Sprint 一览

| # | Sprint | Wave / 主题 | 状态 | 一句话交付 |
|---|---|---|---|---|
| S01 | Voice Latency Observatory | W0 Trace | ✅ 完成 | 全链路阶段时间戳 + 统一 trace id（只观测不改行为） |
| S02 | Session & Generation 统一 | W0 内核 | ✅ 完成 | `runtime/` 包：Session / Generation / EventBus 统一契约 |
| S03 | Real Barge-in | W1 Speech | ✅ 完成 | 打断真正传播（取消 LLM/工具/TTS，而非只停播放） |
| S04 | Streaming TTS | W1 Speech | ✅ 完成 | TTS 分段流式 + 有序播放（TTSTaskManager 接线） |
| S05 | AvatarIntent 通道 | W2 Avatar | ✅ 完成 | 表情随情绪变化 + LLM 等待期"思考"表情 + Alt+E 预览 |
| S06 | ContextEngine | W3 Context | ✅ 完成 | Context 受预算管理（ContextItem/裁剪/可观测），`_build_messages` 等价替换 |
| S07 | Explicit Memory | W4 Memory | ✅ 完成 | 说"记住 X"就真的记住（立即写入 + 常驻注入通道） |
| S08 | TaskRuntime | W5 Task | ✅ 完成 | 跨多轮目标（状态机 + Journal 落盘 + 重启恢复 + 4 个工具） |
| S09 | Artifact Store | W6 Artifact | ✅ 完成 | 超长工具结果落盘可回查（`artifact_read` 分片回读） |
| S10 | 系统工具 Python 化 | Capability 层 | ✅ 完成 | `native` 后端（默认，无需 C++ 工具链）+ `[systemd].backend` 可切换；daemon 降级为可选；spec 约束 9 修订 |
| S11 | Capability 层 | W6 Security | ✅ 完成 | `capability/`：RiskLevel × 四档 PermissionProfile → ALLOW/ASK/DENY；CapabilityView 可见性过滤；DENY 为硬边界 |
| S12 | Event Log | W0/Harness | ✅ 完成 | `runtime/event_log.py`：事件 JSONL 落盘 + 回放 + 轮转；EventBus 全局订阅；`GET /api/events` |
| S13 | Memory Lifecycle | W4 Memory | ✅ 完成 | 事实衰减生效 + `forget()` 遗忘 + 显式记忆管理 API + 每 6h 维护循环 |
| S14 | Wave 2 动作通道 | W2 Avatar | ✅ 完成 | AvatarIntent 动作通道（motion/push_action/playMotion）+ Alt+M 预览 13 个动作 |
| S15 | Runtime Consolidation | Harness 收敛 | ✅ 完成 | `runtime/contract.py`+`adapters.py`：RuntimeContract/Registry；4 个 Runtime 共享生命周期；`_cancel_turn` 改统一广播；`/api/runtime` |
| S16 | Agent Harness Extraction | Harness 收敛 | ✅ 完成 | 抽离 `agent/tool_dispatch.py`（ToolDispatcher）+ `agent/tool_events.py`（StateNotes）；AgentLoop 1151 → 1049 行 |
| S16b | 大文件收敛 | Harness 收敛 | ✅ 完成 | 抽离 `audio/providers.py`（TTS 实现层）：audio 1501 → 1154 行；memory 抽离按约束 2 有意延后 |
| S17 | Memory Showcase | Era 2 验收 | ✅ 完成 | 5 个端到端场景（200 天后仍记得 / 琐事淡忘但显式保留 / 重启仍在 / 注入链 / Replay）+ `GET /api/memory/showcase` |
| S18 | Performance（表演） | Era 1 收尾 | ✅ 完成 | 表演库（11 语义名）+ `PerformanceResolver` + `AvatarRuntime.perform` + `avatar_perform` 工具 + `task.completed`→celebrate 事件驱动；顺带修复 ACTION 永久压制 EMOTION、TaskRuntime 事件从未发布两个静默 bug |
| S19 | Capability Scope | Wave 6 后半 | ✅ 完成 | 参数级资源域（filesystem/network/process/media/clipboard/screen）+ 越界拦截（ToolDispatcher 单点）+ 系统目录硬红线（默认生效）；`GET /capability/scope` + `/capability/check` |
| S20 | Presence（存在感） | Wave 7 | ✅ 完成 | `presence/` 包：`ProactiveIntent{urgency,channel}` + `AttentionPolicy`（Quiet Hours / Cooldown / 偏好 / 上下文 / 置信度）+ 事件驱动 `PresenceRuntime` + "降级而非丢弃" |
| S22 | Presence 深化 | Wave 7 补全 | ✅ 完成 | `VoicePipeline.speak_text()`（主动说话，忙时跳过）+ `Channel.VOICE` 真出声（失败退化气泡）+ `system.*` 事件入口 + Intervention quality（`useful_rate`） |
| S23 | 收敛 + Gallery | 遗留清理 | ✅ 完成 | `memory/store.py` 抽离（`__init__.py` 1278 → 1070 行）+ `memory/constants.py` + 前端 Performance Gallery（Alt+G 列表/现场触发） |
| S25 | 回合策略抽离 | 收敛收尾 | ✅ 完成 | `agent/turn_policy.py`（成功去重 / 失败限流 / 无进展早停）；三条实测约束从"长函数注释"变成 11 个独立护栏用例 |
| S26 | Relationship Memory | Era 3 起步 | ✅ 完成 | `memory/relationship.py`（认识天数 / 互动数 / 一起做成过什么 / 里程碑）+ ContextEngine【我们的关系】(P_RELATION=72) + `GET /memory/relationship` |
| S28 | Memory Consolidation | Wave 4 收尾 | ✅ 完成 | `memory/consolidation.py`：Episode → **支持度驱动**归纳为稳定画像（规则复用 + LLM 可选）+ 安全阀（不降级已有 / 跳过显式 / 推断衰减更快）+ 6h 维护循环 + `POST /memory/consolidate` |
| S29 | Plan 审批 + 失败恢复 | Era 4 深化 | ✅ 完成 | `PENDING_APPROVAL` 状态 + `plan/approve(可改写 steps)/reject` + `retry`（attempts → 超限判失败）+ 摘要恢复线索 + `task_plan`/`task_retry` 工具 + 壳层**计划审批卡片** + `GET /task/list` & `/approve` `/reject` `/retry` |
| S30 | Personality Baseline（PB0） | Personal Brain 起步 | ✅ 完成 | `eval/`：10 类 24 条固定场景 + 规则判定（纯函数可离线测）+ 可对比报告（`model`/`prompt_hash`）+ CLI（`python -m yuiro.eval [--live]`）+ `GET/POST /api/eval/personality`；默认跳过工具类场景（无副作用） |
| S31 | 管理 UI（调试台） | 可见性收尾 | ✅ 完成 | 新增「人格基线」「任务」两个 tab + 记忆页追加「记忆洞察」（三通道/关系/显式记忆/归纳）；api.ts 补 11 个接口；**顺带修两个真 bug**：桌宠窗口 API 前缀误写 `/debug`（表演库与计划审批全部 404）、任务视图 `status` 覆盖外层 `ok`（改 `task_status`）；新增 10 个 API 契约测试 |
| S32 | 场景集扩充 + LLM-judge | PB0 深化 | ✅ 完成 | 场景 24 → **60** 条（10 类每类 ≥5）+ `eval/judge.py`：四维主观评分（人格一致性/情绪贴合/自然度/简洁，含**评分锚点**）+ 严格解析（非法即跳过，不污染均分）+ 只评通过规则者（成本控制）+ CLI `--judge`（独立"严格评审" prompt，避免自评自夸） |
| S33 | Tool Transaction | Era 4 深化 / v1 收口 | ✅ 完成 | 文件写操作（create/write/**move**/**delete**）自动事务化：写前备份 → 落盘 → **逆序回滚**（"恢复刚才的操作"）；补 `file_move`/`file_delete` 原语 + `transaction_list`/`transaction_rollback` 工具；`GET /api/transaction/list` |
| S34 | 动作映射 + 输出净化 | 实测反馈修复 | ✅ 完成 | 动作语义**自动推断**（扫描 motion 曲线 + cdi3 中文参数名）→ 索引写死不再随机 + 时长跟随动作真实时长；`（本轮操作：…）`被 TTS 念出 → 源头（history 改 system 备注）+ 出口（`text_hygiene`）双层修复；另诊断 3 项见 [S34](S34-motion-and-output-hygiene.md) |
| S35 | 任务续跑 + 结果可见性 | 实测反馈修复 | ✅ 完成 | 任务工具调用后注入「任务续跑」system 提示（上限 2 次）—— 多步任务真的会往下跑；修正"每轮 messages 重建"导致的注入失效；artifact 失效文案引导"重调原工具"；`tool_result_max_chars` 2000 → 3500（治"歌单被截成半截 JSON → 反复重拉 18 秒"） |
| S36 | 音乐媒体 | 实测反馈修复 | ✅ 完成 | 歌名经 `force-media-title` 传给 mpv（此前 `media-title` 是哈希 `.mp3` 文件名，用户与 LLM 都不知道在放什么）+ 老版本 mpv 自动降级；`get_state` 新增 `ready`；`state` 补查 `volume`；`_brief_song` 精简 |
| S37 | 延迟 | 实测反馈修复 | ✅ 完成 | `_speak` 改由调用方传 trace —— 修"连续说话时 TTS 打点落到新一轮 trace"（实测 `tts_start=75ms` 早于 `speech_end`）；首段超 28 字再切一刀（TTFA 由首段合成耗时决定）。另：VAD 尾静音给出建议值，流式流水线列为遗留 |
| S38 | 整理能力 | 真实目录验收 | ✅ 完成 | 新增 `file_list`（此前**没有列目录能力**，"整理文件夹"无从起步）；**工具结果解包**（不再二次 JSON 转义：长度减半、一层可读）；**本轮工具结果注入下一轮**（修"看不到结果 → 重复调同一个工具 → 被去重挡死"）；**写操作后续跑**（修"移完一批就说'剩下的也分一下'然后停住"）；**`_plan_moves` 语义修复**（无扩展名 dest = 目录，此前把 `.xls` 变成叫「表格文件」的无扩展名文件）。真实验收 6 轮迭代，最终 `表格/图片/PDF文档` 三类归位；期间用**事务回滚**撤销了两次误操作 |
| S39 | 反馈体系 + 任务驱动 v2 | P0（用户指定） | ✅ 完成 | **F4**：任务驱动判据从"猜"换成**任务状态**（注入 `0/2｜扫描文件` 真实进度；进度不变即停，防空转）。**G4–G6**：新模块 `agent/activity.py`（工具→「正在读取目录…」）+ 工具执行前发 `agent.activity` → 前端**状态行**（呼吸点 + `3/7` 进度）+ 按工具类型播动作（**6 秒节流**）。消除"工具在跑但界面静默"的**空壳感主因** |
| S40 | 架构审视 + 事实卫生 | 用户质疑驱动 | ✅ 审视完成/已修 | 审视结论：**主干通了，接缝系统性薄弱**（9 个断点全在层间）；实测 history 占上下文 **1/3**、facts 全量常驻；**事实记忆实测污染**（`名字: 什么名字`、`歌曲偏好: 《谁》Live版`）→ 加**四道闸门**（值过滤 / LLM 触发门槛 / prompt 收紧 / 二次确认仅对粗规则）；新增 `scripts/inspect_memory.py` 记忆库诊断工具。详见 [S40](S40-architecture-review-and-fact-hygiene.md) |

| S41 | 歌单语义匹配 + 卡片点选 | 用户诉求 | ✅ 完成 | `netease_play(playlist_name=…)`：**字面 → 语义**两级匹配账号歌单（实测「助眠」→《做个好梦.》0.67、「跑步」→**《运动》**0.73 = 泛化）；"我的歌单"扩到**四个入口**（订阅/创建/收藏/**红心**）；修 ID 类型 bug（明文 `originalId` ≠ 加密 id）；结果卡**可点选**（点一下=播放）。不确定时**返回候选绝不猜** |
| S42 | **架构收口（P0-A/B + P1）** | 用户质疑"打地鼠" | ✅ 完成 | **P0-A `TurnState`**：`send()` 里 9 个平铺状态变量 → 3 个显式推进策略（任务续跑/写操作续跑/幻觉纠错），判据移入可单测模块（`agent/turn_state.py`）；**P0-B `PendingInteraction`**：裸字符串 pending → 结构化（**选项可点** + **TTL 按类型**）；**P1 工具返回规约**（`tools/result.py`：status/message/options/artifacts）；**提示词三份副本 → 一份**（`config.py` 那份甚至还在教废弃的 `media_control`）；**BGE-M3 权重补齐** + **嵌入器启动自检**。详见 [S42](S42-architecture-consolidation.md) |

| S43 | 会话生命周期 | Session ownership 补完 | ✅ 完成 | 修"会话只增不减"（`SessionManager.close()` 全项目**零调用**，`_sessions` 无限增长）：**`sweep` 超时回收 + `revive` 从事件日志复活 + `archive` 主动归档**，`get_or_create` 改为**内存 → 复活 → 新建**；前端 `sessionId` **持久化 localStorage**（刷新不再丢上下文）+ **会话列表面板（Alt+S）**；`GET /api/sessions`；lifespan 5 分钟定时回收。**六项 ownership 至此全部达成**。详见 [S43](S43-session-lifecycle.md) |

| S44 | Live2D 表现层调研 | 用户提问 | ✅ 完成 | **★ 表情语义可直接从 `cdi3.json` 的中文参数名读出**，不必靠 Alt+E 肉眼确认：据此修正 `[persona].expression_map` —— 此前**除 happy 外全部错位**（sad 配成了生气、angry 配成了害羞…）；梳理资源可改性分层（`moc3` 需 Cubism Editor **不可手改**；`exp3.json` / `motion3.json` **纯 JSON 可手写** → "加 json"零成本、"加 asset"需重制）；对比 3 个现成模型（肥牛 77 参数·13 动作 / **mao_pro 128 参数·8 表情** / shizuku 45 参数·无表情）。前端调试面板记为**暂停**（见 [PAUSED-frontend-avatar-debug.md](PAUSED-frontend-avatar-debug.md)） |
| S45 | **媒体链路彻查** | 用户反馈"点歌很不稳定" | ✅ 完成 | 实测定位 **5 个根因**（诊断脚本 `engine/scripts/media_probe.py`）：① **静默串歌** —— 原唱无版权时 `_pick_best` 静默返回**同名曲**（证据：点《LIFE》(Neuro-sama, `playFlag=False`) 播成了 Life(Tobu)）→ 改为**多候选交给用户选**；② **明文 `song_id` 无法播放**（实测接口 400），而原实现用"把 ID 当关键词搜"解析（搜索匹配歌名/歌手，必然搜不到），最终报**误导性**错误"请给 song_id" → 只用歌名解析 + 如实提示；③ **`pause` 残留** —— `pause` 是 mpv **全局属性**、`loadfile` **不会重置**，只要暂停过一次，之后每次播放都停在 paused（**"日志完整却没声音"的真凶**）→ `play_urls` 先清 pause；④ **确定性意图被交给 LLM 二次解释** —— 点选只发歌名，引擎只能重新模糊搜索 → 改为**结构化直连**（`media:play`，绕过 LLM）；⑤ **history 上限 40 条**使工具摘要累积、压低新请求的工具触发率 → 收紧到 12 条 + 提示词补"已成功的事不要再调一次去确认"。详见 [S45](S45-media-pipeline-audit.md) |

| S46 | **InteractionMode** | 蓝图最后缺口 | ✅ 完成 | 落地 `architecture-goal.md` §3.5「**不能把所有输入当成同一种 Chat Turn**」：新增 `agent/interaction_mode.py` 显式识别五种形态（CHAT / ACTION / PLAN / TASK / BACKGROUND），并以两级安全原则约束（**不确定倾向 CHAT**、**分类只用于加速与约束、绝不削减能力**）。唯一的路径分化在 **ACTION 的 "Immediate Action"** —— 收尾轮传 `tools=None`，**结构上不可能再重复调用同一个工具**（实测日志：第 1 轮 `played=true`、第 2 轮又调一次被去重挡回 `{"status":"done"}`）。CHAT/PLAN/TASK 保持现状，BACKGROUND 仅识别、未实现。详见 [S46](S46-interaction-mode.md) |

## v1.0 之后（体验驱动阶段）

> 工作方式已切换为「**只有真实体验反馈才触发新 Sprint**」（`V1-acceptance.md` §9）。
> 下面两个 Sprint 均为**用户明确指定**触发，不属于 v1.0 冻结范围。

| # | Sprint | 主题 | 状态 | 一句话交付 |
|---|---|---|---|---|
| S47 | **引擎端优化审视（延迟/架构）** | 用户指定 | ✅ 完成 | 三件"把已有的接起来"：**① 缓存观测 + 上下文排序**（`usage` → trace 跨 provider 归一；稳定前缀 + 变化后缀；情绪提示移出 persona 段；`tool_results`/`nudges` 收进 ContextEngine）—— **顺带修掉一个真 bug：工具轮走旧 `_build_messages`，从第 2 轮起绕过预算与组装日志**；**② 流式 TTS**（`_speak_impl` 统一两条路径，句子一到就合成，**首句提前 1–3 秒**）；**③ turn 级预算**（`TurnBudget` 时间/token/轮数 + **渐进收尾**，`[agent]` 可配）。**实测该 provider 前缀缓存命中 99%**（`scripts/cache_probe.py`）。另交付 **B4 turn Journal**（`turn.started/step/completed` + **replay boundary**）。详见 [S47](S47-engine-optimization-audit.md) |
| S48 | **崩溃恢复的副作用分级（方案 D）** | S47 B4 续作 | ✅ 完成 | 工具**自描述副作用**（`BaseTool.effect`：read / local / external）+ **保守推断**（认不出当 external）；`ResumePlan` 按步骤分级 —— **只读/本地写可安全重放，对外影响必须问用户**，否掉三个"一律"（重放会重复 / 跳过白做 / 全问=唠叨到没人看）；`GET /api/turns` 暴露回合视图与恢复建议。**实测抓到"判太严"的 bug**（未注册工具被当危险 → 读文件也要问）→ 双向测试补齐。详见 [S48](S48-turn-recovery-policy.md) |
| S49 | **回归修复 + 测试压缩** | 用户实测反馈 | ✅ 完成 | 修三处 bug 并配**防再犯护栏**：① TTS 无声音（0B）—— S47 流式 `_feed` fire-and-forget enqueue + 立即 finish 的竞态 → gather 后再 finish，带延迟 fake TTS 测试钉住；② 语音回复不显示气泡 → `llm:text` 触发 `showSpeech`；③ 媒体撒谎"已经放起来了" → `netease_play` 的 `played:false` 误用 `status:ok` + 去重 `done` 占位误导收尾总结 → 状态语义 + note 文案双修。**顺带把测试 172s 压缩到 22s（7.8 倍）**：`Embedder` 把字符串 `"md5"` 当模型名去 spawn（每次白耗 3s）→ 归一。详见 [S49](S49-regression-fixes.md) |
| S51 | **长线实施：联网检索 + 日记** | 用户需求 | ✅ 完成 | 见 [S51](S51-websearch-diary-implementation.md)。**两功能端到端交付**（净增 71 个测试，692 passed）：① 联网检索 —— `SearchConfig` + keychain + `web_search`（Tavily，摘要级/条数克制）+ **补上 `requires_env` 消费者**（此前是死字段）+ `Policy` 风险登记 + **会话级开关→工具按需注入**（聊天坞发送键左侧）+ **来源卡**（点击经主进程 `openExternal`，仅 http/https）+ **结果二次提炼**（URL 不走模型以防编造）；② 日记 —— 独立库（`diaries`/`diary_tags`/`diary_fts`）+ 解构 + **三档隐私与记忆联动**（改档位真的删/补记忆）+ 总评 + 回顾工具（`local_only` 只给存在性）+ 吐槽门控（**情绪安全阀**）+ **日记模式**（草稿/审阅态"就这样·存原文"/处置三选/吐槽开关，独立 `diary:*` 通道**不经 AgentLoop**）+ 调试台「日记」页签。**第四轮（用户实测反馈）**：① 日记主入口移入**悬浮功能岛右列**（取代「日志」）→ 打开**独立编辑窗口**（多入口构建 + IPC；与聊天坞入口**共用同一份草稿**）；② **语音日记** —— 新增 `POST /api/diary/transcribe` 直调**常驻 ASR**，**不复用 `/ws/audio`**（那条链路是对话链路，日记正文走它会触发预路由工具/进 history/出声）；③ 修联网开关**图标名无效**（`solar:glob-bold` 不存在 → `global-bold`）与**不可用时静默**（`disabled` → 可点并说明原因）；④ **录音设备的检测与切换** —— 三处语音入口（聊天坞 / 日记窗口 / 调试台）此前都**不指定设备**（只能用系统默认麦）→ 新增 `useAudioDevices`（权限探测取真名、拔插监听、选中设备失效**自动回退**、跨窗口同步、错误分类翻译）+ `MicDevicePicker` 复用组件；⑤ 调试台「日记」页封面化 + 「纸感扩散」入场（**教训：`prefers-reduced-motion` 一刀切 `animation: none` 会让渐显永不播出 → 关键效果改由 WAAPI 驱动**） |
| S52 | **空闲期记忆整理** | 用户需求 | ✅ 完成 | **会话间隙 / 会话结束时**异步整理（`MemoryIdleScheduler`：单飞 + 最小间隔 + 失败静默；`note_activity()` 同步 O(1)，**不占回复时间**）。内容：**语义重复归一**（vec 最近邻距离 < 0.06；归一 = 只删不写 ⇒ **保留原话、零幻觉**）+ **冷门压缩**（≥45 天 **且** `access_count==0` **且** ≥3 条 → LLM 压成 1 条摘要、沿用最早 ts）。**关键前置**：`messages` 表此前**没有访问计数**（"无人回顾"无数据可依）→ 新增迁移 + `retrieve` 命中回写；**四表齐删**直接做进 `store.delete_messages()`（S50 教训）。既有分工保持不变：`forget`(时间) / `consolidate`(L2→L3) / `_apply_facts`(L3 冲突以新替旧，**早已实现**)。**同轮另修**：知识库实测装的竟是 `docs/init/milestones.md`（里程碑路线图，每轮注入 286 tokens，她会冒出"M4→M5 阶段"——出戏）；`KnowledgeStore.clear()` **第二次犯 S50 同款错**（漏删 `knowledge_vec`）→ 修 + 补测试（此前知识库零测试）；根因是"**后端有、界面没有**"→ 新增 `sources()` 来源清单 + `KnowledgePanel`（可见可控）+ **导入防线**（开发文档默认拦住）；「记忆」页重排为"先看→再看你给的→再管→最后调参"，并把 L2/L3/RRF/支持度等**内部术语全部换成说法**。详见 [S52](S52-memory-idle-tidy.md) |
| S50 | **BGE 嵌入真相 + 记忆删除排查** | 用户提问 | ✅ 完成 | ① **BGE 生产载入成功**（本地目录 19.2s 握手、余弦 0.59），失败的是测试里的 HF 缓存路径（快照缺 onnx_data + 无网）—— 解释了 roundtrip 测试失败；降级从静默改为 warning。② "删除没落库"实为**已落库但有真 bug**：`messages_vec`/FTS 从不跟随删除（实测 152 条孤儿向量；全清后新 rowid 会与旧向量错位关联）→ 四表齐删 + 返回 deleted 数量 + 孤儿清理 + 契约测试钉死。详见 [S50](S50-bge-and-memory-delete.md) |

## v1.0 范围（2026-09-13 冻结）

**v1.0 包含** —— 六个 Era 全部可达：

| Era | 能力 | 落点 |
|---|---|---|
| 0 Alive | 语音 + 真打断 + 分段流式 | S01–S04 |
| 1 Perform | 表情 + 动作 + 11 个表演包 | S05 / S14 / S18 |
| 2 Remember | 显式记忆 + 衰减遗忘 + 三通道 Showcase | S07 / S13 / S17 |
| 3 Relate | 关系记忆 + 归纳（Consolidation） | S26 / S28 |
| 4 Act | 任务 / 计划审批 / 产物 / **文件可回滚** | S08 / S09 / S29 / **S33** |
| 5 Exist | 存在感（注意力策略）+ 主动说话 | S20 / S22 |
| 支撑层 | Trace · EventLog · Context · Capability · Scope · 人格基线 | S01 · S12 · S06 · S11 · S19 · S30–S32 |

**v1.0 明确不做**（不是"没做完"，是"现在不做"）：

| 项 | 为什么不做 |
|---|---|
| Sandbox（OS 层隔离） | 需 SystemDaemon/C++ 侧兜底；配置层拒绝（S19）已覆盖实际风险，等真实需求 |
| Wave 8（Hooks / Lazy Skill / Plugin / Subagent） | 用户 2026-09-13 决定暂缓 —— 扩展性应由真实插件需求驱动，而非 spec 完备性 |
| Personal Brain PB1–PB4（数据工厂 / 微调 / 本地推理） | **需真实使用数据**；没有数据的人格微调是赌博 |
| Gaze（视线跟随）/ Voice style | 属"表演加深"，等你验收时说"表演还不够活" |

**触发原则**：v1.0 之后新增 Sprint 必须由**一次真实使用体验**触发
（清单见 [`V1-acceptance.md`](V1-acceptance.md) §9）—— 不再为对齐 spec 清单而开 Sprint。

## 2. 全局验证状态

- 全量回归：**514 passed / 5 failed**（失败集自 S01 起**从未变化**，均为既有问题）；
- 既有失败（与各 Sprint 无关）：
  - `tests/test_audio.py` 等 5 个（VAD/barge-in 相关，S01 前即存在）；
  - `tests/test_memory.py::test_migrations_idempotent` 的 `PermissionError`——本机
    `C:\Windows\Temp` 权限问题（WinError 5/32），**非代码问题**；
- 新增测试累计：S05 +8、S06 +10、S07 +8、S08 +19、S09 +10、S10 +15、S11 +14、S12 +10、S13 +8、S14 +3、S15 +8、S16 +10、S16b +0（纯搬运）、S17 +5、S18 +12、S19 +14、S20 +21、S22 +11、S23 +0（搬运 + UI）、S25 +11、S26 +12、S28 +16、S29 +17、S30 +17、S31 +10、S32 +17、S33 +20、S34 +16、S35–S37 +7、S38 +12、S39 +7、S40 +13；
- 每个 Sprint 的护栏（等价性 / 兼容性 / 容错）都保留在全量测试中。

## 3. 架构落点（已就位的新包）

```
engine/yuiro/
├── runtime/     # S01–S03：Session · Generation · EventBus · Trace
├── avatar/      # S05：AvatarIntent · AvatarPriority · AvatarRuntime
├── context/     # S06：ContextItem · ContextBudget · ContextEngine
├── task/        # S08：TaskStatus · Task · TaskRuntime（Journal 落盘）
├── artifact/    # S09：Artifact · ArtifactStore（LRU + 磁盘）
└── tools/       # S08/S09：task_*.py · artifact_tool.py
```

新增配置段：`[context]`（`budget_tokens` / `tool_result_max_chars`，调试台可改）。

## 4. 待人工验收（需要你本人做的）

> **能力验收台**：[`Agent-test-matrix.md`](Agent-test-matrix.md) —— 按能力域列出场景 /
> 怎么说 / 判据 / 当前状态（✅🟡⛔），**增量开发从这里挑 ⛔ 行**。
> **人工观察清单**：[`V1-acceptance.md`](V1-acceptance.md) —— 延迟 / 交互 / 记忆 / 任务 /
> 安全 / 存在感六类观察项与记录模板。下面只列**必须你本人动手**的几条：

1. **Alt+M** 逐个预览 13 个 TapBody 动作，确认语义后回填 `engine/config.toml` 的
   `[persona.motion_map]`（例如 `greet = "TapBody"`）—— 这是唯一还缺你输入的地方；
2. **S33（新增）**：说「把下载文件夹里的图片移到"图片"子文件夹」→ 批准 →
   说「恢复刚才的操作」→ 预期文件全部移回、**"图片"目录（若原本不存在）也消失**；
3. **S18**：说「我终于把那个 bug 修好了！」→ 预期它主动调 `avatar_perform(celebrate)` 并做动作；
4. **S07**：说「记住：我下周要参加算法竞赛」→ 隔天问「我下周要干什么」→ 应答得出来；
5. **S19**：让它操作 `C:\Windows` 下的文件 → 应明确说明越界（不是报错崩溃）；
6. 其余按 `V1-acceptance.md` 逐类走一遍即可（**记关键词就行，不用写报告**）。

## 5. 遗留与下一步建议

**已知遗留**（各 Sprint 报告末尾有完整列表）：

- **Wave 2**：13 个 Hiyori 动作的语义确认（通道已通；`[persona.motion_map]` 待 Alt+M 确认后回填）；
- **Wave 5**：LLM 自动规划（PLAN 模式）—— 当前是"LLM 语义判断 + 用户批准"（S29），非全自动规划；
- **Wave 6**：Sandbox（OS 层）与 C++ 侧 `transaction.cpp` —— **v1.0 不做**；
  配置层拒绝（S19）+ Python 侧事务（S33）已覆盖实际风险；
- **Wave 7**：已落地（S20 / S22）；剩余：系统事件源需外部集成、`useful_rate` 为近似指标；
- **Wave 8**：Subagent / Lazy Skills / Plugin —— **v1.0 不做**（用户 2026-09-13 决定）；
- **Era 3+**：Relationship（S26）与 Consolidation（S28）已落地；Personal Brain Track（PB1–PB4）等真实使用数据；
- **S33 自身**：daemon 后端无事务能力（native 为默认后端，不影响使用）；整文件备份（超大文件占等量磁盘）；
- **技术债**：`main.py` 拆分、`memory/__init__.py` 存储层（S16b 有意延后）。

**建议下一步（v1.0 之后：由体验驱动，不再按 spec 清单排期）**：

1. **按 [`V1-acceptance.md`](V1-acceptance.md) 实际用 2–3 次**，记下别扭的地方；
2. 把记录贴给 Coding Agent → 它据此**只开必要的那一个 Sprint**；
3. 候选池（按"什么信号触发"排序，**不是**按 spec 完备性）：

| 触发信号 | 候选 Sprint | 内容 |
|---|---|---|
| 你实测发现某段卡 | 延迟专项 | 用 trace 定位（ASR / LLM / TTS / 尾段）后针对性优化 |
| 你觉得"表演还不够活" | Gaze + Voice style | 视线跟随 + 语气风格（表演包补齐） |
| 你想手动管记忆 | 记忆管理 UI | 前端增删改显式记忆 / 查看归纳结果 |
| 你觉得"它不够在场" | 系统事件源 | 前台应用 / 剪贴板变化 → 主动意图 |
| 你愿意花 2–3 小时标注 | PB1 数据工厂 | 60 场景 → 真人标注 → 训练集（微调前置） |
| 你有真实扩展需求 | Wave 8 起步 | Hooks（before_tool / after_tool）→ Lazy Skill |

**待人工验收**：见 [`V1-acceptance.md`](V1-acceptance.md)——含延迟 / 交互 / 记忆 / 任务 / 安全 /
存在感六类观察清单与记录模板。

## 6. 如何继续（给 Coding Agent）

1. 读 `docs/spec/coding-agent-protocol.md`（七步流程 + 护栏）；
2. 从本表挑一个 Sprint 或让 Human 指定；
3. 先把 **Plan 落盘到本目录**（`S<NN>-<slug>.md`），再动代码；
4. 每个 Sprint 必须闭环：实现 → 测试（新增 + 全量回归对比基线）→ 冒烟证据 → 报告 → 清理临时脚本。
