# 首块交付与双语输出实验

延续 `368c188` 和工作区已有 Runtime 改动。本轮分开测量 Fish 原始首包与本地出块等待，限制音频缓存与预解码，并加入默认关闭的双语句对实验。普通聊天继续使用现有 AgentLoop、Session、权限和记忆链路，没有另建 Runtime 或替换通信协议。

## 目标和边界

Goal：稳定交付首句，用数据决定是否省去独立翻译请求。Scenario：Hotaru 说日语、显示中文，首个完整句对即可交付；Hiyori 保持原中文音色，打断和换角后旧音频不得恢复。Architecture Increment：现有 provider 的细分计时/首块预算，既有 manager/播放器的缓冲预算，借用现有adapter与取消表的隔离实验。Tests：真实供应商同文交错采样、真实renderer音频图、双角色混合负载、格式/取消/容量专项、完整后端和前端检查。DoD：收益和限制有原始数据，实验默认关闭，首块可回退480ms，最终恢复Hotaru可用，用户修改不提交。

## 首包与冷路径

[480/240ms同文对照](2026-11-24-tts-packets-hotaru.json)共6对，[480/400ms对照](2026-11-24-tts-packets-hotaru-400.json)共4对；同对保持同文、音色、模型及参数，并交错正反顺序。该独立脚本不包含LLM、翻译、ASR或播放器；首个进程请求不等于供应商模型冷启动。

Fish WS 首个原始包均为40960字节，即44100Hz单声道PCM16约464.4ms。旧480ms阈值需要42336字节，因此多等下一包。仅将首块设400ms、后续仍480ms。PCM守恒、任意网络碎片和尾部保留已有回归。

| 400ms对照组，均n=4 | 原480ms首块 | 400ms首块 |
|---|---:|---:|
| flush后原始TTFB中位数 | 458.312ms | 508.962ms |
| 原始首包到可播放块中位数 | 115.492ms | 0.102ms |
| 该积累等待范围 | 114.340–164.253ms | 0.094–0.139ms |
| WAV封装CPU中位数 | 0.087ms | 0.089ms |
| PCM转换/RMS CPU中位数 | 0.410ms | 0.378ms |

另一组旧阈值等待85.149–203.055ms，240ms同样消除等待；正式采用储备更足的400ms。PCM未重采样或有损转码，`pcm_transcode_ms=0`表示该步骤不存在。HTTP raw首包指body首次到达，可能只有WAV头，不能与WS纯PCM首包混同。不同请求的原始TTFB仍受外部波动影响，不能把表中端到端差值全部称为分块收益。

历史“翻译完成→首可播放块10.5037s”只有汇总，没有原始包记录；本轮尚未复现同量级TTS区间。已证实本地额外等待约0.1–0.2秒，不能宣布10.50s已根治，也不能将剩余时间直接归因供应商。新增 `tts_timing` 记录连接任务调度、密钥读取、握手、首文本/flush、原始首包、可播放块及封装/RMS。

探索第12次还出现发送后慢样本：后端 `audio_sent=2489.5ms`，renderer首收包约7797.7ms。两进程入口起点有小偏差，约5.3秒差值不能精确等同网络耗时。该记录保留；后续补入同机发送wall-clock、renderer tick和独立health探测，不将界面投递延迟称为TTS慢。新增探针后尚未再次复现这项5秒异常。

冷路径另有证据：一次新引擎请求的WS任务约1924.074ms才获得调度，密钥读取仅0.619ms。[离线真实SDK三组独立进程对照](2026-11-24-llm-cold-resources.json)中，旧首轮聊天资源初始化1082.817–1116.677ms；在既有OpenAIProvider构造中预载后，首轮读取约0.001ms。构造成本从约108–110ms增加至1160–1194ms，成本移到装配阶段，不发网络请求，也不能将全部1.92秒归因于该资源。

## 双语实验的契约

服务端 `YUIRO_BILINGUAL_EXPERIMENT=1` 和单次请求 `bilingual_order=ja_first|zh_first` 必须同时存在，且角色原朗读语言须为ja。默认关闭。实验只借用当前LLM adapter/persona，不注入历史、检索和工具，不执行操作，不写history/Memory。`baseline`使用相同只读上下文、中文分句及现有OutputRenderer独立翻译，仅该实验实例禁用翻译缓存；普通聊天缓存保留。因此结果不能直接当成完整Agent工具回合的收益。

解析只接收严格有序ja/zh字符串对象，拒绝重复/未知字段、残句、语言错误、围栏、前缀、动作/表情/工具标签和tool_call chunk。对象闭合即交付，不等下一换行。日语字段闭合仅观测，完整句对校验后才显示中文并送日语TTS。每对象4096字符、总32768字符、最多16对、生成60秒。测试覆盖逐字符切分、转义引号、多句、容量、取消、旧代和工具chunk；每轮新建parser，失败关流并停掉本轮声音，不把错误或结构标签作为日语兜底朗读。

最终匹配对照采用Hotaru、同题同配置，轮转三种顺序，覆盖疲惫安抚、完成事情后的夸奖、四句雨夜陪伴。按真实usage分别统计生成与翻译token；冷请求单列，不能用冷基线对热双语宣称普遍提速。表中“首音”只是实际AudioBufferSourceNode的start调用/计划起点，含流式解码后约20ms储备；后续发现音频图停顿，因此不能把这些数值当成实际音频图进度或物理声卡/扬声器首音，真正图时钟进度另有交接样本。

Hiyori为SiliconFlow中文，Hotaru为Fish日语，两者配置和模型保留。探索中的Hiyori日语实验不参与该角色自然度或翻译性能结论；最终候选拒绝在该中文配置下启用日语实验。句对可按保存文本审阅语义；声线、语气和Live2D动作是否自然仍须听看实际产物，不能以自动评分冒充人工听感。

### 最终同题对照结果

[最终匹配对照](2026-11-24-output-controlled-final.json)每方案3次，全部完整播放完成、角色身份正确、内部pending归零；[统计脚本输出](2026-11-24-output-summary.json)保留原始usage与分阶段计算。样本很小，表中的范围比标成“总体P95”更诚实。

| 中位数，括号为首音范围 | 中文生成→独立翻译 | 单轮日语先 | 单轮中文先 |
|---|---:|---:|---:|
| 首个可朗读日语文本 | 1835.7ms | 1099.3ms | 1277.4ms |
| 完整句对可交付 | 不适用 | 1293.6ms | 1277.4ms |
| start调用/计划起点 | 2325.3ms（2295.2–2887.4） | 1798.6ms（1717.0–1891.4） | 1723.5ms（1635.3–2660.3） |
| 本轮主体生成耗时 | 1424.9ms | 2109.5ms | 2829.2ms |
| 首句独立翻译 | 974.0ms | 无 | 无 |
| 主体生成completion tokens | 24 | 62 | 83 |
| 含全部翻译completion tokens | 61 | 62 | 83 |
| 含全部翻译prompt tokens | 462 | 154 | 154 |
| 三个场景各自的模型请求次数 | 3 / 3 / 5 | 1 / 1 / 1 | 1 / 1 / 1 |
| 请求到实际整轮播放结束 | 15014.3ms | 14153.8ms | 14585.7ms |

主体生成变慢、单次输出token增加是真实成本；省掉独立翻译后，这组样本首音仍较早。日语先的首字段较早，但等完整句对后优势可能被中文字段生成抵消；本组中文先的中位首音更早、最大值却更晚，不能仅靠字段顺序选最终默认。总播放耗时受实际话术长度/供应商音频时长影响，不是等长音频的吞吐对照。

两组进程冷首请求另列：[预载前](2026-11-24-output-controlled-before-prewarm.json)首音4374.5ms、WS任务调度1924.074ms；预载后首音2887.4ms、调度4.2ms。后者拆解为首句1172.9ms、翻译完成2338.3ms、TTS首块2823.9ms；供应商flush后首包483.046ms，本地积累0.163ms，PCM/RMS1.221ms，音频发送前约4.6ms；同机消息投递约22.96ms，最后还含解码与20ms排期储备。仅一组重启冷请求，不能据此宣布总体冷/热P95改善。首轮原有冷检索另见[480ms原流程](2026-11-24-live-baseline-480.json)：检索约590.2ms，LLM首token等待约5953ms，两者在翻译前，不属于10.50s TTS区间。

文本审阅发现真实取舍：日语先的夸奖/安抚基本语义对齐，但雨夜回复混用礼貌体和亲昵口吻；中文先的雨夜例加入“这里没法帮你做什么”，尽管中日对应，仍破坏陪伴氛围。采用结论：首块400ms和SDK装配预载可保留；双语保留默认关闭的实验，不替换完整AgentLoop。后续须在真实角色人格、检索/工具回合和人工听感都通过后再谈默认开启。

## 缓冲预算

| 位置 | 满载策略 | 释放与验证 |
|---|---|---|
| TTSTaskManager | 默认2个序号窗口，每序号4项/2MiB排队WAV；窗口不超过并发槽，后句不能挤掉队头 | 消费唤醒；interrupt清空并唤醒；超大单段按原失败占位跳过并记录；慢消费、乱序、取消测试通过 |
| renderer待播 | base64/音量估算上限16MiB；超限显式报错并control取消整轮 | 停播/消费释放；受控真实composable验证溢出和迟到拒收 |
| renderer预解码 | 排期超过2秒即等待时钟，容许2秒加当前一块的峰值 | 停播立即唤醒等待者，避免无限提前解码 |
| 跨回合音频复用 | 当前不存在，本轮不新建 | 热句仍可用原256项翻译LRU，不借用旧角色音色换命中 |

4MiB仅限制manager排队WAV，不包括provider当前包、生产者持有段和模型内存；16MiB是播放器负载估算，不等于renderer RSS。生产者和消费者必须并行；原先等待所有enqueue再消费的三句测试已改为并行消费，避免有界背压下自锁。设置 `fish_first_chunk_ms=480` 可回退首块，关闭环境变量即可禁用实验，不做全仓reset。

## 连续负载的限制

[探索批次](2026-11-24-output-matrix.json)运行约21分钟，54次双角色短/长句、普通/实验、首音前/播放中打断和切换。期间有开发热更新与完整回归，属于混合负载探索。早期第4次标Hiyori，但实录模型仍是Hotaru，已从角色结论排除；最终采样器等待预期模型并记录帧character_id。

早期采样器在Hiyori整段音频句间交接时，可能把当前source结束误当整轮播完；内部pending/queue非空的行不算完整播放验收。已修为同时等待内部pending/queue/scheduled/decode-waiters归零，超时记错，原始批次保留。因此54次不能全称完整播放成功，最终Hiyori原配置播放另测。

探索Engine RSS约1870→2795MiB，有一次约810MiB阶跃，末次private commit约4.58GB；renderer末段V8约33–42MB并回落。不能把阶跃确定为音频泄漏，也不能证明整进程无泄漏。后续应同步剖析private/RSS、Python堆和native分配，不靠定时重启或强制GC掩盖。

补充：新引擎对照的private从约2.80GB升至4.55GB，随后第2–9次仅在约4.545–4.549GB内波动；同一次启动日志也记录了SenseVoice模型装配。模型启动成本与工作集需要单列，但时间相关性仍不能证明之前RSS阶跃的根因，不能用重复重启当长期治理。

该批次12次取消的迟到start均0，服务端settle范围4.2–138.6ms；这是control取消，不是实录麦克风VAD或声学停播。播放缓存估算峰值2593848字节（约2.47MiB），预解码峰值2.479秒符合“2秒+一个480ms块”的预算；观察到的流式欠载0次，整段播放不适用该欠载计数。后段863次独立health探测中位6.12ms、P95 11.48ms、最大42.64ms；observer末态pending0、peak1、failures0。原始54次不等同无干扰的24小时长稳验收。

## 验证和源码状态

### 音频图与双角色收口

[Hiyori时钟复查](2026-11-24-hiyori-clock-check.json)复现旧音频图 `state=running` 但currentTime停顿约5278ms，JS最大tick间隔仅34.4ms。首段2.56秒WAV的ended回调约7.85秒后到达，第二句已到却只能等待。独立新建Context播放同一真实WAV两次（中间空闲8秒），[实际2720ms音频分别约2738/2716ms结束且无时钟停顿](2026-11-24-device-clock.json)。这是音频图/设备路径证据，不是TTS慢，也不能确定具体驱动根因。

局部处理：权威Session交接且没有采音节点时，stop旧播放、关闭旧Context，后续输出等待关闭完成再新建；普通stop输入和普通回合更替仍保留输出，完整dispose等待所有关闭，迟到解码不得重建资源。[生产composable测试](../../scripts/diag/playback_admission_probe.cjs)覆盖等待关闭期间dispose；[原有生命周期专项](../../scripts/diag/voice_input_lifecycle_test.cjs)更新为加载实际PlaybackAdmission后仍通过停麦/自然结束/卸载场景。

不能称所有卡顿已消失：[更新后Hiyori两次复查](2026-11-24-hiyori-clock-after.json)图时钟最大停顿约25/55ms，但首次发生JS tick约5350ms、消息投递约5324ms的独立停顿；第二次JS最大间隔约47ms。此异常与“旧Context时钟停顿”分开保留，仍需renderer/native性能剖析。

Hiyori按原配置完整播放2句均starts=ended=received=2、最终内部pending0；冷检索样本约2287ms，热检索约54ms，首start分别约5219/2972ms，不能将这个差值全归为TTS或翻译。两个播放中control打断late_starts均0，settle约4.7/3.4ms；[中文角色日语实验门禁](2026-11-24-hiyori-language-gate.json)实际拒绝。Hotaru补测中文分句翻译/单轮双语各完整播放一次，两个四句实验在首音前取消均无start、settle约130ms，见[补测](2026-11-24-hotaru-bilingual-cancel-final.json)。WAV导出首次失败只涉及诊断导出头部参数，播放原记录保留，修复后已另存有效素材。

听感素材保留在忽略目录：`.env-local/diag-audio/hiyori-zh.wav`（中文5.68s）、`hotaru-baseline-ja.wav`（翻译日语8.071s）、`hotaru-bilingual-ja.wav`（直接日语7.802s）。它们是实际供应商输出，不包含原始克隆参考音频；拼接WAV不保留实时网络/图停顿，不能替代实时听感。未进行真人日语母语盲听或麦克风barge-in声学验收。

### 测试与最终交接

- 完整后端 **1091 passed / 77.09s / 0 skip**，见[最终JUnit](2026-11-24-output-final-regression.xml)。测试适配有界背压后按engine工作目录执行；旧“先gather所有生产者再消费”不再作为合法调用方式。
- 最终前端typecheck和production build均通过；实际composable容量/迟到/Session重置和音频生命周期两个Node专项通过。新增Python模块/诊断及限定范围Ruff通过；[与HEAD比较](2026-11-24-output-lint-delta.json)main/agent/audio/config没有新增code+message，历史lint仍在，不宣称全仓清零。
- 已重新加载最终Engine，服务端实验设为0，[实际门禁](2026-11-24-default-off-gate.json)拒绝实验请求；普通Hotaru完整两句播放及打断通过，见[最终交接](2026-11-24-final-handoff.json)。另[图进度复查](2026-11-24-final-clock-handoff.json)记录音频时钟跨过首段起点后的进度，停止发生在图进度之后，late_starts0、settle106.9ms，图时钟停顿0。该进度仍不是物理扬声器测量。
- [最终状态](2026-11-24-final-state.json)：8200 health200，Hotaru casual模型ready、control已连、闭麦、turn不忙、队列/排期/等待者/pending均0；observer pending0、peak1、failures0。HEAD仍 `368c188`，没有commit/push。用户原有改动和另一路gaze/Live2DCanvas改动全部保留，未改写；没有为指标换音色、模型、语言或记忆后端。

## 核心源码落点

| 文件和行号 | 本轮职责 |
|---|---|
| [agent/__init__.py:143](../../engine/yuiro/agent/__init__.py#L143) | SDK公有资源在原provider构造中准备，无网络预热 |
| [audio/fish_websocket.py:44](../../engine/yuiro/audio/fish_websocket.py#L44)、[fish.py:112](../../engine/yuiro/audio/fish.py#L112) | 调度/密钥/握手/原始首包/本地出块计时，HTTP与WS各自保留语义 |
| [audio/wav_stream.py:9](../../engine/yuiro/audio/wav_stream.py#L9)、[config.py:140](../../engine/yuiro/config.py#L140) | 首块400ms、后续480ms，角色参数与回退 |
| [audio/__init__.py:710](../../engine/yuiro/audio/__init__.py#L710) | 现有TTS manager的序号窗口、字节/项数背压和唤醒 |
| [audio/bilingual.py:45](../../engine/yuiro/audio/bilingual.py#L45)、[main.py:2160](../../engine/yuiro/main.py#L2160) | 隔离parser/同上下文实验，接现有reply输出/取消任务；失败发送明确终态 |
| [useVoiceInput.ts:99](../../shell/src/renderer/src/composables/useVoiceInput.ts#L99)、[Session重置:492](../../shell/src/renderer/src/composables/useVoiceInput.ts#L492) | 待播字节、预解码、停止唤醒、Session输出图释放 |
| [App.vue:650](../../shell/src/renderer/src/App.vue#L650)、[engine-protocol.ts](../../shell/src/shared/engine-protocol.ts) | 中文句对显示、request/Session护栏、显式实验参数及帧契约 |

## 后续可执行任务

1. **P0 尾延迟取证**：保持现有链路，围绕>2s原始TTFB、>250ms界面投递/图停顿保留有界元数据，禁止录入密钥/原始用户音频。对5.3s renderer停顿做主线程/音频服务trace，至少把三个慢例归到明确阶段；两角色各复验完整播放、换角、取消和旧代迟到，不能以强制重启或更换供应商算修复。历史10.50s仍待同量级样本。
2. **P1 内存与长稳**：在ASR/嵌入均ready后固定基线，采集RSS/private/Python堆/native分配和任务数量；至少60分钟、100轮含长句与角色切换，结束队列/任务回到基线。发现阶跃要以分配证据解释；当前21分钟探索不足以承诺多小时稳定。
3. **P1 双语人格验收**：实验继续关闭默认。扩展至少30个不同场景、同人格同上下文且翻译无缓存的对照，按真实usage统计总tokens和请求数；检查日中语义、礼貌体一致、无无故能力免责声明。工具回合只在现有AgentLoop内做适配且沿用permission/reset，不另建Agent；至少覆盖工具chunk/重试/取消/换角全套后，才能考虑可选产品开关，仍需真人听感。
4. **P2 声学与演出**：经明确选择设备，用固定生成夹具或回环测实际扬声器首音/停播，和图进度分列；在既有Hiyori/Hotaru资源上审听声线、口型和动作语义。延迟与人格尚不稳时，不增加导演LLM、全局音频缓存或新的总Runtime。

## 复跑入口

先在根目录加载 `. .\config\env.ps1`，使用 `.env-local/engine-venv2/Scripts/python.exe`。`tts_packet_probe.py`做同文首块；`llm_cold_probe.py`离线测SDK；`output_matrix_live.py --controlled --roles hotaru --duration-seconds 0 --rounds 3`做隔离对照；`runtime_renderer_live.py --expected-role hotaru`做普通链路；`output_evidence_summary.py`重算统计。实验需由启动Engine的进程显式设环境变量1，结束恢复0并实测门禁。真实runner会调用当前云服务并播放，不能并发运行；换输出名保留原始证据。声学首音与真实麦克风不在这些脚本的覆盖范围内。
