# 输出编排收口与延迟稳定性验证

后续进展见[首块交付与双语输出实验](2026-11-24-output-latency-experiment.md)：补原始包计时、首块/缓存预算、冷资源预载、默认关闭的双语同题实验与双角色验证。历史10.50s仍未同量级复现；新增renderer/音频时钟慢例独立保留。本文原始数据不回写为新候选结果。

## 本轮结论

基于 `368c188` 和开始时已有的 RuntimeRegistry、投喂窗口等未提交修改，完成三轮增量：文字首句进入现有朗读链路；句子、聊天和PCM队列的容量与退出预算；普通观测落盘隔离并保留关键事实的持久化完成边界。未新增总 Runtime、播放器或依赖，未更换角色、语言、音色、模型或供应商。

本轮可以证明等待全文的结构性阻塞被解除、排队任务有界、取消能回收、慢普通观测不再直接等待发布者。**不能宣称真实云端整体 P95 已下降**：两次较长提示的新实现首播放比旧实现慢，模型、检索、翻译等待及缓存/进程冷热状态不同。全部样本保留，不把受控对照冒充端到端加速。

## 第一轮 首句交付与共享输出

原文字路径 `_agent_reply` 返回全文后才 `_speak_reply`。现在使用已有 `on_sentence` 回调，借助 `audio/output.py` 的 ReplyStream 与 SentenceChannel 将完整句直接交给朗读；WS握手仍可与Agent生成重叠。完整文字答复不再触发第二次朗读。现有文字任务表仍拥有输出任务，新加的文字Agent任务表供原取消路径回收，不建立平行生命周期系统。

文字HTTP/WS与语音WS复用正文清洗、翻译前后身份检查和provider句子流协调。VoicePipeline与Presence继续复用原TTS manager及4项投喂窗口；并未声称所有历史日记/媒体适配调用都已删除。保留整段适配入口供既有调用，后续可逐项迁移，不一次重写。

前端增加带session/generation的 `tts:reply_start`，防止完整答复到来时重置已经开始的播放时钟；若声音先结束，迟到文字不再重新进入无限等待。Agent reset取消剩余声音，旧代翻译不能启动provider。已经真正播放的内容不能撤回。

实机迭代发现的竞态与修复：一次本地stop后，网络中尚在途的两个旧片段再次入队，出现late_starts=2（[失败证据](architecture-live-compatible-ui.json)）。epoch只能保护已经在解码/排期的旧回调，不能拦截stop之后才入队的旧帧。因此新增有界PlaybackAdmission，取消后拒收同会话旧代，并为文字请求增加可选reply_request_id：本地stop立即作废活动请求，即使首音频尚未到达也不能由旧响应恢复；后继请求和无ID旧客户端保持兼容。

权威session:ready先停止旧排期再重置播放器代际准入，允许后端重启后的低generation；旧连接仍由既有socket归属检查隔离。控制连接尚未获得权威session时，界面明确提示未就绪而不发送请求。Node诊断实际执行useVoiceInput（音频设备受控），验证迟到网络帧/解码、后继代、会话重置和未就绪发送门控，证据见 [播放器诊断](playback-admission-probe.json)。

点选媒体播放也属于新用户意图，官方/内置两分支进入执行前推进Session generation，避免客户端停止旧朗读后误拦新播放确认。test_media_output_generation在真实worker中用替身验证，不播放真实音乐、不调用系统媒体后端。

同轮 TraceContext 记录首句、翻译起止、TTS首块与发送，并在音频帧携带trace_id及阶段快照。renderer在自己的performance时钟记录接收、decode、start/ended；只通过trace_id关联，不直接相减跨进程单调时间。发送时刻是应用提交WS，不是网卡或扬声器事实。

## 第二轮 有界队列与归属

- SentenceChannel：默认4句、put等待5秒、单句最多16000字符；满载结束靠条件通知，不塞可能永远入不了队的哨兵。文字朗读超时可停止声音、明确结束并继续文字，不重发已经播出的句子。
- VoicePipeline：复用该通道，保留上一切片4项翻译/合成在途窗口。不是只限制provider semaphore而继续无限创建翻译任务。
- control待处理聊天4条：满载返回chat:busy，不在receive循环等待容量，因此审批与interrupt仍可处理。已接收的请求不静默丢弃；新请求会明确被拒绝。
- PCM待处理32帧、单帧64000字节：超限分别关闭1013/1009，不静默删帧拼接错误语音。超载路径取消/等待该会话语音生产者，断线cancel/join worker，不在满队列等待结束哨兵。
- control interrupt先使generation失效，再取消/等待文字Agent及朗读；回收完成给出interrupt:complete和服务端settle_ms。单轮取消不终止接收后续聊天的worker，控制取消期间暂停下一队列项。仍不把取消称为工具副作用回滚。

interrupt还清理未执行的排队请求，并推进队列epoch；已经取出、但仍在等待语音交接的旧项也不能在取消完成后启动。新旧客户端及“交接期间取消后，下一新项仍能服务”有实际worker测试。

队列限制不等于全链路内存已经封顶：provider输出、TTS manager已合成音频、renderer预解码与系统网络缓冲仍需独立容量/时长预算。

## 第三轮 普通观测隔离与持久化

EventBus业务订阅保持原顺序，不把审批/行为订阅批量fire-and-forget。仅EventLog普通观测进入128项单消费者队列，深复制事件并冻结当时角色的sink，防止切角后串库。满载施加背压，不静默丢事实；正常关闭drain/join。

`turn/task/session/approval/transaction`事件仍在有序队列中等待本条写入完成，保留既有回合恢复和审批事实的完成边界。普通观测的publish返回仅表示已入队，强杀前尚未写入的普通观测可能丢失；这不是崩溃安全队列，也未增加fsync保证。关键写失败保留原错误隔离，但计数和日志可见。

EventLog.sink在线程写盘并串行加锁，正常取消等待当前写完成后才释放锁，避免轮转并发。事件查询API先flush；runtime API增加待写数量、峰值和失败数。同步append接口保留，不能把需要立即完成的审计调用迁移成普通入队。

## 受控前后对照

证据：[共享输出与观测对照](architecture-consolidation-probe.json)，5次固定依赖实验。模拟后文生成等待150ms、合成等待20ms；慢观测/慢写边界为50ms，不是实际供应商耗时。

| 指标中位数 | 原行为 | 新行为 | 解释 |
|---|---:|---:|---|
| 首音频回调 | 207.51ms | 46.30ms | 不再等待后文生成结束，非真实声学首音 |
| 慢普通观测的publish返回 | 61.98ms | 0.28ms | 写入仍执行，正常关闭等待完成；关键事件不使用此提前返回语义 |
| 慢写期间事件循环tick | 50.37ms | 10.99ms | 写盘离开事件循环；含Windows定时器/调度噪声 |

另做真实本地磁盘实验：项目D盘临时目录、100条普通观测、3轮，结束后清理本轮临时文件。批量入队/同步写入耗时中位84.44→2.76ms，事件循环tick中位99.00→2.82ms；100条记录的generation顺序均完全一致。**全部写完**耗时中位84.46→121.30ms，说明收益是释放控制循环，不是磁盘吞吐变快。不能用入队时间替代持久化时间。

上一切片的64句受控翻译峰值64→4仍保留，不把同一成果重复计为本轮新实现。新增回归还验证滚动补位、首句先交付、流式/整段取消、满载结束、溢出拒绝、切角冻结、关键写入完成、单句HTTP失败不重试且后句仍可继续。

## 实际运行与测量口径

Engine和Electron均已实际启动，当前Hotaru casual真实加载。样本经真实界面sendText→Memory/LLM→当前朗读语言转换→Fish WS→既有renderer队列与AudioContext，不打开麦克风、不自动批准工具。使用当前角色与会话数据目录；正常测试聊天会产生会话历史、关系计数和事件记录，不宣称这些运行数据完全不变。

较长提示保持相同文字与角色：

- [旧路径两次](architecture-live-before.json)：首播放约4109.8/2204.6ms。
- [首轮新路径两次](architecture-live-after.json)：约5645.1/5174.8ms，其中一次首播放早于完整文字约43.5ms。它们不构成受控提速证明，也不应从两个样本外推P95。重启、供应商波动、输出措辞与翻译缓存均影响可比性。
- [控制通道取消](architecture-live-cancel.json)：一次local stop至ended约6ms；服务端settle约140.5ms；观察1.5秒晚到start为0。这不是物理声学停播，也不覆盖所有取消竞态。
- [最终流式路径连续采样](architecture-live-accepted.json)：第一轮单列预热，后30轮用于诊断分位数。最终统计与阶段拆解由 [汇总](architecture-consolidation-summary.json) 计算；前一候选的热样本单独保留在architecture-live-hot.json、architecture-live-hot-final.json，不混入本组。最后媒体generation接线只影响media:play，未改变此组验证的文字路径。

最终组31次尝试均无失败；首轮预热首播放2020.7ms（不是冷启动）。后30次应用首播放P50 **1796.1ms**、P95 **2290.8ms**、max **2387.6ms**。语料固定为“请只回复你好呀，不要调用工具”，重复短句命中了翻译/前缀缓存；不是不同语料、不同角色的体验分布，也不能与两次长提示直接比较。前一组1.62/2.17秒仍作为原始候选数据保留，不挑较快的一组当最终成绩。

以下阶段耗时逐样本在同轮Engine时钟内求差，再计算分位数，单位ms；各分位数不可直接相加等于总分位数，完整累计时间线保留在JSON：

| 阶段 | P50 | P95 |
|---|---:|---:|
| 检索 | 59.3 | 79.3 |
| LLM请求到首token | 907.8 | 1203.9 |
| 首token到完整首句 | 68.5 | 83.0 |
| 首句翻译（重复短句缓存命中） | 0.1 | 0.1 |
| 翻译完成到TTS首音块 | 649.6 | 752.7 |
| 首音块到提交WS | 3.4 | 4.6 |

renderer自己的接收到decode完成P50/P95为7.6/13.7ms；AudioContext首start的总体分位数见上（记录start调用，不是扬声器声学起点）。传输延迟没有跨时钟硬减，未知网络/调度差额不强行归因。短句未形成句子队列积压；真实高压队列等待时长尚未单独采样，容量、等待超时及满载关闭由确定时序测试验证。

最终候选另一次 [控制打断](architecture-live-cancel-final.json)：服务端settle **135.7ms**，本地stop至ended约 **8.9ms**，观察1.5秒late_starts=0。早期140.5ms样本保留，不与最终样本混淆。[真实PCM预算验证](architecture-transport-live.json)返回1009；runtime API为200，观测pending=0、peak=1、failures=0。最终界面Hotaru已加载且turnBusy/replyTtsBusy均false。

最终代码重新启动后的 [交付确认](architecture-live-handoff.json)：一次完整播放和一次control停止均贯通，真实旧WAV重放新增start=0。但首个重启后样本首播放 **15287.4ms**，其中翻译完成到首可播放块约 **10503.7ms**；第二次首播放2325.1ms、取消settle236.4ms。冷/远端长尾仍未解决，此样本不混入热启动分布，也不因完整播放成功就称延迟验收通过。当前阶段只能定位到TTS/传输/首块积累边界，尚未分开首个原始音频包与480ms可播放块，不把10.5秒全部归因供应商计算。

首次旧实测曾有约4.56秒冷检索；本轮取消样本也有约3.98秒检索阶段等待。该现象仍需单独冷启动/嵌入worker诊断，不能用热样本掩盖，也不通过把BGE改成md5来制造低延迟。语音VAD/ASR、扬声器loopback、Hiyori/Hotaru双角色真人听感和60分钟稳定性均不是本次文字播放采样的验收范围。

## 测试与复现

全量回归与最终专项见本轮最终汇总；新增模块、测试和诊断执行限定范围Ruff，保留main/audio历史lint问题，不宣称全仓清零。前端typecheck和生产build通过，仍在实际开发界面运行验证，不冒充安装包验收。

最终完整后端回归 **1061 passed / 65.59s / 无skip**，见 [JUnit](architecture-consolidation-final-regression.xml)。迭代中一轮曾有真实BGE语义测试未在60秒内就绪而跳过（原因状态仍为“未启动”），[单独复查](architecture-bge-recheck.xml)1 passed / 29.33s，最终全量也通过；首次就绪波动的根因仍未定位，不能因为复跑通过就删除这一风险。worker内输出回调trace/speech/request ID绑定为本轮快照，防止后续循环变量重绑定。main/audio的Ruff诊断按code+message与HEAD比较没有新增；新增输出/观测模块、测试、诊断均通过限定范围Ruff，diff空白检查通过。

最后重新加载当前Engine并通过 [部署确认](architecture-live-delivery-confirmed.json)：一次正常完整播放和一次control停止均成功，晚到start为0，第二次服务端settle为71.6ms。该确认不混入30个热样本。前一次 [启动采样预检](architecture-live-delivery-smoke.json) 含一条连接尚未ready、消息未发送的60秒等待失败，原始记录保留；采样器现会等待控制连接、会话和模型就绪，不把此失败算入供应商时延。30热样本在此预检前已完成且均有实际收音频/解码/start证据。

核心改动落点：

| 模块 | 改动 |
|---|---|
| audio/output.py | 共享句子通道、清洗/翻译/身份检查、provider句子流与文字输出桥 |
| main.py | 按句接线、同轮trace、聊天/PCM准入、文字Agent任务归属、control取消与回执 |
| audio/__init__.py | VoicePipeline句子通道、既有投喂窗口、语音WS共享协调 |
| runtime/observation.py 与 event_log.py | 有序有界观测、关键写入屏障、线程写盘、失败可见 |
| debug_api.py 与 runtime/trace.py | 观测队列状态、事件读取flush、阶段字段 |
| App.vue 与 engine-protocol.ts、playback-admission.ts、useVoiceInput.ts | 早到音频启动、迟到入队屏障、请求ID、权威会话重置、满载提示及control改口 |

新UI显式发送stream_reply=true；旧客户端未声明时，后端保持全文先发、声音后发，避免旧renderer重置早到音频。30热样本验证的是同一流式执行路径；补入可选协议标记后，已另测新旧两分支，并再次部署确认。

[实际兼容协议验证](architecture-compat-live.json)均通过：旧请求无stream_reply时先chat:assistant后音频，新请求允许tts:reply_start先于完整文字。初版界面确认中出现的late_starts=2已登记为失败，不计为通过；加入客户端准入后，[首批5次打断](architecture-live-cancel-fixed.json)和[最终3次打断](architecture-live-cancel-guarded.json)均late_starts=0，后者另用真实旧WAV直接重放到实际renderer，新增start也为0。[首音前取消3次](architecture-live-cancel-before-audio.json)均未启动音频，其中一次服务端settle为554.8ms，不能宣称所有取消低于500ms。此前曾在仓库根目录误跑依赖engine相对路径的专项，已终止该误跑并按engine目录重新执行，不把执行目录错误当作业务回归。

根目录先加载 `. .\config\env.ps1`，使用 `.env-local/engine-venv2/Scripts/python.exe`：

```powershell
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/architecture_consolidation_probe.py
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/runtime_renderer_live.py --samples 31 --output architecture-live-accepted.json
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/runtime_renderer_live.py --samples 3 --cancel-all --cancel-before-audio --output architecture-live-cancel-before-audio.json
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/runtime_renderer_live.py --samples 3 --cancel-all --replay-after-stop --output architecture-live-cancel-guarded.json
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/architecture_transport_live.py
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/architecture_summary.py
node scripts/diag/playback_admission_probe.cjs
```

实机脚本依赖8200 Engine和9222 CDP、使用当前供应商且会计费；勿并发启动采样runner。复跑会覆盖同名文件，比较前先归档。诊断恢复临时WebAudio钩子并移除自己的WS监听，不修改生产音色或语言。长提示与默认短句语料分开保存。

测试在engine目录先加载环境，再执行 `python -m pytest tests/ -q -ra --disable-warnings -p no:cacheprovider`；重点文件为test_output_consolidation、test_reply_generation、test_transport_budgets、test_ordered_observation、test_speech_turn_handoff及原有Fish/voice/trace测试。

## 遗留风险与后续优先级

1. 优先拆开TTS首个原始包与480ms可播放块，定位已观察到的10.5秒等待；同文同音色交错对比HTTP/WS并评审首音等待预算。并行定位冷检索与嵌入worker就绪/排队，保持真实语义检索能力，不靠改成md5或更换音色伪造提速。
2. 下一切片再收紧合成完成音频和renderer预解码的字节/时长预算；当前句子窗口不代表这些缓存已有限。
3. 慢业务订阅仍可阻塞publish；普通观测队列饱和也会背压。先按订阅者测量，不将所有订阅改异步。磁盘永久卡住、反复强制取消、系统强杀仍不是可靠关闭保证。
4. 本次共享的是句子输出边界及取消归属，main仍承担角色/媒体/日记适配；保留旧兼容辅助函数，不为文件行数漂亮而批量迁移。后续按入口逐项移除已无消费者的适配。
5. 保留用户未提交修改，不commit/push。输出桥、队列预算、普通观测隔离为可分开回退的切片；回退时同步协议/前端及对应测试，不用全仓重置覆盖用户改动。
