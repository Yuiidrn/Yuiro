# G0 — 当前 Runtime、回归与演出资源基线

日期：2026-10-23。对应统一 Goal v1.1；仅执行 G0，不授权进入 G1。

范围更新：本文件保留首轮采样事实，不覆写历史 JSON。用户随后指定资源重点为 `shell/src/renderer/public/live2d/hiyori` 与 `shell/src/renderer/public/live2d/Hotaru Shiomi`；当前验收对改为 **Hiyori + Hotaru casual**，稀疏能力用 Hotaru child still 补充，不再以 MaoPro/肥牛为前置。下文 8 份资源和 0/30 是首轮快照，后续实机进展见 [续记](G0-live-acceptance.md)，测试精简与各阶段效果见 [说明](G0-test-tiers-and-stage-effects.md)。续记中的未通过项仍须显式保留，不能据此自动放行 G1。

后续实机执行与当前资源范围见 [G0-live-acceptance.md](G0-live-acceptance.md)；本文以下数值保留为首轮离线基线。用户已将主要资源收敛为 Hiyori 与 Hotaru Shiomi，旧 MaoPro/肥牛验收选择已被后续记录替代。

## 1. 结论与验收状态

现有 Runtime 不是待推翻的原型：Session/Registry、AgentLoop、VoicePipeline、AvatarRuntime、Memory、Capability、Presence 已有实现与测试，应继续复用。当前主要差距在跨入口接线、异步结果归属、客户端播放事实和资源审定，而非缺少另一套 Runtime。

本轮重新执行：**772 个 Python 测试通过；前端类型检查、生产构建通过**。另用真实函数/AST 的隔离诊断复现播放取消竞态、关闭异常；通过的测试不能覆盖这些边界。

| 子任务 | 本轮交付 | 状态 |
|---|---|---|
| G0.1 | 当前提交、调用链、职责、已有测试、规范差异和缺陷复现 | 源码/隔离诊断完成；真实启动退出、WS 联调未验收 |
| G0.2 | 8 份 model3 的引用、时长、循环、曲线参数、哈希与当前 profile；主/稀疏验收对 | 静态盘点完成；视觉审定未完成 |
| G0.3 | 固定 30 次模拟依赖采样、阶段 trace、固定解码竞态、后续实机测量方案 | 部分完成；真实热启动样本 **0/30** |

**完整 G0 尚未通过。** 模拟回调耗时不能代替真实 TTFA；没有人工录屏评分、物理出声测量或 60 分钟稳定性证据。不调整 Goal 阈值，不先行实现 G1–G5。

## 2. 冻结对象与运行环境

- 实际仓库：`D:\Project\Yuii\desktop-pet\Yuiro`，不是聊天镜像目录。
- HEAD：`e2af077b03f204a4394b9eaedc530f4d337c4c9e`，提交时间 `2026-10-23 10:25:19 +0800`，`日记页风格调整，迭代前准备`。相较统一 Goal 原审阅的 `97753e9… + dirty S53`，当前必须以已提交的最新源码为准。
- 开始时已有未提交项：`docs/goal/README.md`、`docs/goal/2026-10-23-unified-architecture-engineering-goal.md`；保持原样。本轮只增加诊断脚本与 plan 记录，不修改生产实现、配置或模型素材。
- Windows 11 build 26200；Python 3.13.11；Node 20.18.0；pnpm 10.34.5。Ryzen 7 6800H、16 逻辑核、31.3 GiB RAM；RTX 3060 **Laptop GPU / 6144 MiB**，不是桌面版 12 GiB。
- 采集时 Engine 8200 无监听；5000/5005/9100 也无监听。配置的 TTS 是云端 SiliconFlow，因此本地 TTS 端口未监听不等于 TTS 故障。没有启动服务、调用云 API、读取密钥或写用户数据库。
- TOML：Qwen / `qwen3.8-flash`、Silero、SenseVoiceSmall CUDA、SiliconFlow、中文显示/发音、BGE-M3 + sqlite-vec、native system backend；`barge_in_enabled=false`。这些是文件值，不代表环境覆盖或服务可用性已验证。

原始证据：[环境](G0-baseline-artifacts/environment.json)、[版本](G0-baseline-artifacts/package-versions.json)、[236 个源文件哈希](G0-baseline-artifacts/source-hashes.json)、[源码完整性](G0-baseline-artifacts/source-integrity.json)。哈希覆盖已扫描 py/ts/vue/cpp/hpp，不等于全仓库所有二进制或 CSS 校验。

## 3. 当前运行链路与职责归属

下列行号对应本轮 HEAD；完整符号表见 [source-landmarks.json](G0-baseline-artifacts/source-landmarks.json)。

| 现有落点 | 当前真实职责与调用入口 | 继续复用 / 当前缺口 |
|---|---|---|
| `engine/yuiro/main.py:750` lifespan | 创建 Memory/backend、重建 Agent、启动预热/维护/Presence；模块底部组装接口 | 保留 composition root；关闭和热更新引用需补证，不增加第二套总控 |
| `runtime/session.py:55,224` | Session、generation、连接关联、cancel 失效 | 统一身份基础已在；`active_tasks` 不是完整 task owner |
| `runtime/contract.py:67`、`adapters.py:17,83` | Registry 顺序广播取消；适配已有 Agent/Voice | 不把适配器存在等同于所有实际入口引用一致 |
| `agent/__init__.py:376,755` | AgentLoop、上下文组装、memory.retrieve、LLM/tool loop、预算/收尾/历史 | 复用循环，不另写 Agent；异步提交边界需逐个检查 |
| `agent/tool_dispatch.py:58` | 工具策略/执行与 batch gather | 安全检查保留；共享写资源并发不应直接视作安全 |
| `audio/__init__.py:774,1208` | VoicePipeline：VAD/ASR 后进入 Agent，分句 TTS、发送、speech task 取消 | 复用；句子队列和上游 enqueue task 尚非端到端有界 |
| `audio/__init__.py:705` | TTSTaskManager：并发 2、序号、有序回调、epoch | 合成顺序已实现；不能保证 renderer 迟到解码不再启动 |
| `avatar/runtime.py:32,172` | 语义意图、优先级、状态与 broadcast | 保留；真实 motion 播放成功/结束、参数控制在 renderer |
| `memory/__init__.py:1196` 及 store/retriever | 检索、显式记忆、遗忘/衰减/归纳、异步写入 | 不新建 Memory Runtime；turn reset 后提交与 session 隔离需专项证明 |
| Capability / Policy / Approval / transaction | 工具准入、参数域、审批与副作用恢复 | 稳定性优化不得绕过；取消不是副作用回滚 |
| Presence / TaskRuntime | 主动互动、跨回合任务、日记/关系入口 | 复用但限制对当前用户输出的竞争；此轮不扩建插件平台 |

### 3.1 进程与入口

Electron main/preload/renderer → Python Engine（control/audio WS 与 API）→ provider。系统工具默认 Python native；C++ SystemDaemon 可选，不是默认必需进程。Embedder 有独立工作边界；TTS provider 可以是远端，不能按架构图臆造固定本地 TTS 进程。

文字链：`main.py:1595` control → `:1626` chat queue → `:1675` `_agent_reply` → AgentLoop → 显示消息；`main.py:1224` `_speak_reply` 是独立文字回复朗读路径，不能只审 VoicePipeline 后宣布所有输出已统一。

语音链：`main.py:1744` audio WS → `:1787` PCM queue → `audio/__init__.py:1003` on_audio → VAD/`spawn_speech_end:1037` → `on_speech_end:1208` ASR → Agent streaming → 分句队列 `:1340` → `_speak_impl:1507` / TTS manager → `main.py:483` `_play_audio` → renderer `useVoiceInput.ts:208` playOne → decode/start。Presence 另走 `main.py:1199` → `pipe.speak_text`。

取消链：audio WS `main.py:1817` interrupt → `_schedule_cancel:1397` → `_cancel_turn:1372` → Session generation 失效、Registry 广播；Voice `interrupt:1669` 取消 speech/LLM/TTS 任务。前端 `App.vue` sendText 会按 turnBusy 条件发送音频通道 interrupt 并 stopPlayback，**不等于后端 control WS 自身拥有统一 interrupt 协议**。断线、纯文字、新旧入口的组合尚未端到端验收。

### 3.2 当前接线风险与规范差异

1. `main.py:1037` 模块级 AgentLoop 先创建，`:1338` AgentRuntimeAdapter 捕获它；lifespan `:784` 随后替换 AgentLoop。诊断证实 adapter 持有旧对象时 cancel 只改变旧对象。实际 main lifespan 未运行，静态接线与适配器行为分别作为证据，不声称做过完整启动回归。
2. `debug_api.py:139,168` 重建 responder 与 main factory 参数不等价，search/diary/events/event_log/agent_config 等接线未同等传入，Registry 也未同步引用。旧 Sprint 中“Runtime consolidation 完成”不能证明当前热更新路径正确。
3. `agent/tool_dispatch.py:72` gather 批次；`agent/__init__.py:1070` await 后处理工具结果至历史/记忆提交处，没有统一紧邻 await 的旧代屏障。存在需要确定时序测试的风险，**未动态证明每一种污染都已发生**。
4. `audio/__init__.py:1340,1578` 的无界句子队列与 enqueue task 列表：合成 semaphore 不等于翻译/待发送/预解码全链路背压。
5. `main.py:483` 音频消息无统一 generation/segment/trace 身份；`:1821` playback_started 不是完整 completed/interrupted/failed 回执。服务端 `tts_end` 不是客户端实际播完。
6. 旧 spec/Sprint 的“已完成”保留为历史记录；当前 native 默认、独立朗读入口、真实连接和本次诊断优先作为事实。此轮不为匹配旧文档改代码，也不改行为规范。

## 4. 已有测试与本轮回归

| 检查 | 本次结果 | 证据与限制 |
|---|---|---|
| Python `tests/` 全集 | **772 passed，87.53s**，65 个测试文件，0 failure/error/skip | [JUnit](G0-baseline-artifacts/pytest.xml)、[汇总](G0-baseline-artifacts/regression-summary.json)；包含本地 BGE 相关工作，不是会话延迟 |
| shell `pnpm typecheck` | exit 0 | 类型正确不代表 motion/音频时序正确 |
| shell `pnpm build` | exit 0 | renderer 665 modules / 8.64s；最大产物 MicDevicePicker 约 6.07 MB、index 约 1.59 MB；未等同首屏或语音耗时 |
| main.py scoped F821 | exit 1，2 项 | [诊断](G0-baseline-artifacts/main-f821.json)；不是全仓 lint |
| 迟到 decode 的 stopPlayback 诊断 | 复现已知缺陷：lateStarts=1，安全期望=0 | [真实函数隔离证据](G0-baseline-artifacts/frontend-race.json)；非浏览器 E2E |
| lifespan teardown AST | `NameError: daemon is not defined` | [关闭诊断](G0-baseline-artifacts/shutdown-characterization.json)；真实 AST + fake app state，非服务实启 |
| C++、真实 WS、音频设备、视觉/长稳 | 本轮未运行 | 默认 native，未改 C++；不引用历史结果冒充本轮通过 |

已有覆盖包括 `test_runtime_contract.py`、`test_session_lifecycle.py`、`test_audio.py`、`test_voice_trace.py`、`test_presence_voice.py`、`test_avatar_action.py`、`test_performance.py`、`test_motion_mapping.py`、多组 memory/capability/transaction 测试。`test_debug_api_panels.py` 使用最小 app/router，不是完整 main lifespan；全绿不覆盖本轮关闭缺陷。

统一 Goal R01–R12 当前证据：Session/voice 单元测试提供部分取消、隔离、失败路径证据；本轮额外覆盖 R02 类 decode 迟到反例。R06–R08 的真实 SDK Promise/循环/模型切换/口型争抢、R10 stale 写入、R11 全部热更新/关闭交错、R12 同资源写并发均仍需确定时序与集成验收。不得将“存在同名测试”写成整条 R 场景已通过。

### 4.1 缺陷分级（登记，不修复）

- **P0 阶段门禁：**真实 30 热样本与视觉证据缺失，G0 不放行；这不是要求换模型/扩服务。
- **P1：**`main.py:860` teardown 未定义 daemon，隔离可复现；影响有序退出。另 `:130` MemorySystem 注解未定义，受 deferred annotations 影响，不直接宣称启动必崩。
- **P1：**`useVoiceInput.ts:208,250` 解码挂起时 stop，恢复后旧 source 仍 start；本次仅记录失败，没有修复成绿。
- **P1：**Agent adapter 陈旧引用/热更新 factory 不一致，取消路径真实性存疑；需 G1 既有边界内修接线而非另建 Runtime。
- **P2：**全链路无界缓冲、消息身份/完整播放回执、真实工具 await 后 stale 提交、参数 ownership 与资源版本缓存需分别进入既定 G1–G4，不能在 G0 顺手重构。

## 5. Live2D 资源基线

[完整清单](G0-baseline-artifacts/live2d-inventory.json) 含引用路径、存在性、model3/motion JSON 哈希、Duration、Loop、曲线参数 ID。[实际 TS 推断候选](G0-baseline-artifacts/live2d-slot-candidates.json) 与 [当前生效 profile](G0-baseline-artifacts/effective-avatar-profile.json) 分开保存，避免把候选推断当作现行映射。

| 资源 | 表情引用 | 动作引用 | Loop=true | 精确 `ParamMouthOpenY` 动作数 | 时长范围 s |
|---|---:|---:|---:|---:|---|
| Hiyori | 8 | 13 | 13 | 10 | 1.10–8.57 |
| Hotaru casual | 46 | 67 | 0 | 58 | 2–6 |
| Hotaru child still | 10 | 3 | 0 | 0 | 6 |
| Hotaru live-mode | 0 | 9 | 0 | 9 | 3.983–10.65 |
| Hotaru live-mode low | 0 | 9 | 0 | 9 | 3.983–10.65 |
| Hotaru live | 46 | 67 | 0 | 0 | 2–6 |
| MaoPro | 8 | 7 | 7 | 0 | 3.47–9.37 |
| 肥牛 | 7 | 14 | 14 | 0 | 1.10–8.57 |

扫描引用均存在；这不保证解码/SDK/视觉有效。曲线计数是精确参数名匹配，0 不能推断模型没有其他命名的嘴参数。每个资源均标记 `reviewed=false`，没有伪造人工批准。

验收对选择：**Hiyori 主模型**（当前 TOML `/live2d/hiyori/Hiyori.model3.json`）+ **MaoPro 稀疏映射模型**；Hotaru casual 作为丰富资源比较样本，不擅自切换默认角色。

Hiyori 当前 profile 已显式提供 greet=`happy, Idle#6`、comfort=`sad, Idle#2`、celebrate=`playful, Idle#4`、thinking=`think, Extra#0` 等，故不能因自动推断缺少 greet 就说实际功能不存在。但显式配置仍须视觉审定。Hiyori 13 个 motion 均标记 Loop，且 10 个涉及标准嘴参数，释放策略/口型争抢是高价值实机检查项，不可仅凭 Duration 自动认定已经结束。

Hotaru 候选含 `mtn_bye01_C` → greet、`mtn_cry01_C` → comfort；是现有关键词推断产物，不是通过审定的“迎接/安慰”。MaoPro 8 个表情均未由当前自动规则推断到槽位，适合验证 fallback；不等于素材不可用。Hotaru idle 候选 6s 可在 max4500 筛选无结果后 fallback 被选中，当前上限不是硬限。

Renderer 风险：`shell/src/renderer/src/components/Live2DCanvas.vue:485,502` motion 启动返回 Promise，但当前状态更新未以成功回执为准；`:262,281` 异步装载缺少明确 revision 屏障；`:541,557` 意图/释放 timer 未带统一身份；`:220–226` 参数写入与 SDK update 顺序需实际 API/视觉验证。`shell/src/main/live2dManifest.ts:68` 缓存以 model3 mtime 为主，不足以覆盖被引用资源/profile 改变。此处均不直接更改 SDK 调用或素材。

## 6. 延迟基线：已测与未测

[synthetic-latency.json](G0-baseline-artifacts/synthetic-latency.json) 使用真实 AgentLoop + VoicePipeline + TTSTaskManager，依赖替换为 fake ASR、空 Memory、LLM 两句、fake TTS；直接调用 on_speech_end，**绕过 VAD**。LLM chunk 与合成各含名义 5ms 等待，返回文字字节而非真实 WAV；sink 是 Python 回调。

| 指标 | 样本 | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|---:|
| on_speech_end → 首个发送回调（模拟） | 30 | 31.300 | 32.157 | 32.450 |
| on_speech_end → 管线回调全部结束（模拟） | 30 | 46.839 | 48.014 | 48.134 |
| 真实语音热启动 TTFA | 0 | 未测 | 未测 | 未测 |
| 客户端本地停播/视觉反馈/声画同步 | 0 | 未测 | 未测 | 未测 |

排除 1 次预热，30 次有效采样、0 失败；保留每次 trace 与阶段 mark。Windows 定时器粒度影响 fake sleep，不能扣除名义等待后声称测得“纯编排开销”。`tts_first_audio` 是 Engine 回调，`tts_end` 是管线终点，不是 renderer start/end 或扬声器出声。

现有 trace 可拆 ASR final、memory retrieve、LLM start/first token/final、lang render、TTS first/end；当前未建立 VAD 实际端点、真实翻译/远端服务、网络、decode、播放结束的同链实测。跨进程单调时间不可直接相减；客户端应在同一测试时钟记录发送/回执，总体 trace 只用于关联。

不据模拟数值冻结单段字数、句数、超时或队列时长限制；这些仍是 Goal 的建议值，待真实数据后决定。

## 7. 固定实机补测方案（仍属 G0）

条件：可访问真实 renderer/麦克风/播放设备、Engine 和配置 provider；使用隔离测试会话/数据目录，确认不向用户长期记忆写测试内容。当前未自动启动可能重置端口/修改用户状态的启动器。服务未监听及无法视觉评审时，不假造通过。

固定中文语料与六场景：

| 场景 | 固定输入/操作 | 观察点 |
|---|---|---|
| S1 迎接 | “早上好，今天也请多关照。” | 不使用告别语义，轻量及时回应 |
| S2 思考与回答 | “请用两句话解释什么是运行时。” | 首句及时，等待动作可释放 |
| S3 安慰 | “今天有点累，先陪我安静一会儿。” | 安抚用户而非角色哭泣/夸张庆祝 |
| S4 成功/失败 | 只读测试工具固定 success / failure fixture | 成功状态真实，失败不庆祝，不调用真实写工具 |
| S5 打断替换 | 两句输出期间：“停一下，改成一句话。”；另固定 decode 未完成时 stop | 旧声音/旧动作/旧 history 不重新提交；记录本地与服务端延迟 |
| S6 fallback/切模型 | 同一 greet/comfort 切到 MaoPro，再切回 Hiyori | 无映射时中性退化，旧 load/motion 回调不污染新模型 |

每个样本记录：case/trace/session/generation、配置与 profile/model 版本、冷热、输入时长、端点、ASR、检索、LLM 首 token/首句、翻译、TTS 首块、发送、decode 起止、AudioContext start/ended、取消发出/本地停播/任务结束、失败原因、队列与任务峰值。真实热样本至少 30，冷启动单独报告；不得混合 fake 数据。记录 p50/p95/max/失败率，时间基准写清。物理出声另需 loopback/录音，AudioContext start 只代表应用播放事实。

主模型每场景至少 5 次录屏；稀疏模型另测 fallback。评审者按语义、节奏、通道冲突、角色一致性 1–5 分打分，记录 reviewed 证据；无人评审时继续标未完成。30 次采样/30 次场景播放不必互相冒充，完整六场景覆盖、失败样本也要保留。

## 8. 可复现命令、回退与下一步

仓库根 PowerShell（仅使用现有依赖）：

```powershell
. .\config\env.ps1
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/g0_baseline.py --samples 30
node scripts/diag/g0_frontend_probe.cjs
```

全量 Python 回归（在 `engine/`）：

```powershell
. ..\config\env.ps1
& ..\.env-local\engine-venv2\Scripts\python.exe -m pytest tests/ -q --disable-warnings -p no:cacheprovider --junitxml=../docs/plan/G0-baseline-artifacts/pytest.xml
```

随后在根目录执行静态/关闭诊断（依赖上述 XML）：

```powershell
. .\config\env.ps1
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/g0_source_checks.py
```

前端（在 `shell/`）：加载 `..\config\env.ps1`，依次 `pnpm typecheck`、`pnpm build`。没有假设不存在的 `pnpm test`。

注意：诊断脚本会覆写同名 G0 JSON/XML；比较新结果前先归档本轮文件。诊断 exit 0 只表示诊断执行完毕，不表示被诊断竞态安全。本轮新增脚本不被生产启动路径引用；回退只需撤下本轮脚本/报告，不触碰用户源码、数据库或模型。

下一步仅补 G0 实机证据、确认复现与测试 fixture；完成阶段评审后再请求/依既定流程进入 G1 最小接线修复。后续职责仍落在现有 Session/Adapter/AgentLoop/VoicePipeline/Avatar/renderer，不创建平行 Runtime，不合并重写所有入口，不借 G0 扩建插件、任务或多 Agent 平台。
