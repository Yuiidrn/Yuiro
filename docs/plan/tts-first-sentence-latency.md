# 首句TTS延迟波动优化（进行中）

Goal：减少首句被后句抢占合成名额造成的本地等待，保持当前角色音色和朗读语言。Scenario：中文回复逐句转换为日语后，第一句即使翻译稍慢，也应先进入合成；标点/Markdown残片不应独立请求云端。

Architecture Increment：局部调整VoicePipeline现有投喂调度，翻译仍可并发，按原文序号取得合成入场顺序；保留TTSTaskManager的两路并发及保序输出、取消和占用回执。不另建Speech Runtime，不用填充语音掩盖延迟，不自动改Fish模型/音色/语言。

Tests：复现首句翻译落后、后两句先占满合成名额的场景；验证首句入场、输出顺序、翻译与合成并发、取消时无残留；验证空白/纯标点片段不请求服务。既有语音、Fish、角色隔离、打断测试继续通过。

Measure：同一确定性翻译/合成耗时fixture记录修复前后首句开始合成与首段交付；它只能度量本地排队增量，不替代Fish真实网络/服务端P95。现有真人日志中日语转换约0.9–2.9秒，Fish时延亦波动，后续独立核对连接与首字节/完整响应。

DoD：先交付有前后证据的调度修复和取消回归；整体首句体验仍需真实服务多样本验证，不以局部通过标记全部解决。HTTP连接复用必须配套provider生命周期与角色热切换资源释放后再引入，不能留下不关闭的常驻client。

## 2026-11-10 已实施：首句合成入场顺序

旧逻辑允许后句先译完、先占满两路合成名额，首句在自己的后句后排队。现保留并发翻译，增加按原文序号传递的入场事件链；事件在进入TTSTaskManager之前传给后继，因此合成仍可两路并发，而不变成整段串行。原有wait_next保序交付继续使用。

纯引号、Markdown符号等不含字母/数字/中日韩文字的片段不翻译、不发云端请求，仍放空序号占位，避免破坏句序。真实日志此前出现chars=1/2而只返回44字节WAV头，不能把这种无声响应算成有效首句。投喂日志新增seq、chars、render_ms、admission_wait_ms，不记录密钥或朗读正文。

取消时_feed现在取消并join已生成的翻译/合成子任务；_speak_impl等待_feed清理，防止在上游句流尚未结束时取消后留下孤儿翻译请求。CancelledError继续向调用方传播，旧manager所有权护栏保留。

确定性生产VoicePipeline场景（首句翻译40ms、后句1ms；首句合成10ms、后句150ms；各5次）中位数：

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| 首句开始合成 | 171.44ms | 46.40ms |
| 首段交付 | 186.90ms | 62.26ms |
| 全部片段交付 | 186.93ms | 218.51ms |

首句优先的代价是此fixture里全段完成稍晚；不隐瞒吞吐取舍，不把该结果外推成Fish真实提速比例。原始记录tts-first-queue-before/after.json及tts-first-queue-summary.json，脚本scripts/diag/tts_first_sentence_queue.py。

新增三项事件驱动回归验证首句入场、后句并发、提前交付、纯标点过滤、开放句流中取消join。语音/Fish/打断/所有权专项47 passed；在engine目录全量972 passed，81.54秒；新增测试Ruff与diff检查通过。本次仅改Python语音调度，前端沿用上一轮已通过的构建。已重启引擎加载该修复，角色与音色设置未改。

## 真实Fish有限采样与下一任务

使用Hotaru当前voice/model/latency/speed和安全存储key，固定短日语，最多六次计费请求，不出声、不采麦、不写入聊天。真实结果见[fish-http-latency-probe.json](fish-http-latency-probe.json)：六次均200；首个body chunk 501.0–1610.7ms，完整响应1786.1–5309.8ms。新连接三次complete 2218.7/5309.8/2250.3ms，共享连接冷样本1952.9ms、两次暖样本1837.9/1786.1ms；样本过少且服务端时间变化，不能据此给出连接复用因果改善比例或P95承诺。

生产Fish适配器当前仍是client.post收齐整句WAV后才交付，首个网络块不是有效可播放首音。因此下一增量验证HTTP音频分块提前交付：处理WAV头与不完整sample、按句与子段保序、统一RMS/口型、取消关闭响应、不重复播放、不串角色，并保留非流式路径用于比较。仅开stream读取或使用balanced参数不会自动让现有播放器提前出声；本次未假称此能力已实现。首句翻译和供应商波动也仍在实际首音之前。

参考：[Fish TTS API](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech.md)、[实时流指南](https://docs.fish.audio/developer-guide/best-practices/real-time-streaming.md)。先读取官方llms.txt索引；浏览工具不支持页面text/markdown时通过HTTP读取原文。保留已有balanced、s2.1-pro及公共音色，不以切换low模式/其他声音替代实现。

## 2026-11-10 HTTP音频分块已实现，稳定性仍待收尾

上述“待实施”为前一轮状态。现已在同一Fish HTTP请求内解析PCM16 WAV，按480ms封装可独立解码的WAV，尾块保持真实长度；不会每块重复请求或重复合成原句。TTSTaskManager按句序、句内子块顺序提前交付；语音主链和文字回复朗读均已接入。非Fish路径、关闭segment_streaming的整句路径保留；日记专用合成与调试试听尚未改为音频分块。

前端使用AudioContext.currentTime提前解码、连续排期，口型按当前真正播放的子块采样；语音播放回执在排期到达时上报，取消停止当前和未来全部已排期节点。HTTP读流和生成器在取消、换代退出时关闭，部分内容已经交付后不重发整句、不自动切换音色。

三次真实短日语请求（无翻译/无播放，保持Hotaru参数）见[fish-stream-first-audio-probe.json](fish-stream-first-audio-probe.json)：

| 样本 | 首段可播放 | HTTP完成 | 同一次请求提前量 |
| --- | --- | --- | --- |
| 1 | 1580.9ms | 2555.0ms | 974.1ms |
| 2 | 855.9ms | 1983.8ms | 1127.9ms |
| 3 | 1112.6ms | 2128.0ms | 1015.4ms |

这证明不必等待整句下载，不代表供应商P95下降，也不是新旧实现的受控A/B。保留第一个冷样本及安全凭证加载时间，没有只取暖请求。

实际重启引擎并启动单个最新构建壳后，Hotaru真实LLM→语言转换→Fish→播放→idle见[avatar-reply-http-stream-live.json](avatar-reply-http-stream-live.json)。11个audio均streaming=true、session/generation匹配、最终idle、麦克风未开启。然而此次真实Fish首片6795.9ms、完整16768.4ms；回复提交至首片11454.7ms，包含LLM约3680ms及出口翻译825ms等。这是必须保留的慢样本，不能用前面三个快样本覆盖。子块到达间隔最长约2.65秒，超过480ms音频长度，存在网络供给不足引起断续的风险；本次仅确认链路与身份，不将自然连续听感判为通过，待用户反馈和播放时间线复核。

回归：engine目录pytest tests/为983 passed，72.19秒；前端typecheck/build通过。新增解析器分片/占位长度/元数据/截断、首块早于EOF、取消关闭响应、子块句序、旧generation丢弃；生产组件专项验证提前排期、到点回执、分块口型、全部节点取消和迟到解码拒绝。实际Electron WebAudio双角色自然结束/取消四场景见[avatar-http-stream-browser-live.json](avatar-http-stream-browser-live.json)，使用合成静音fixture，不能替代双角色真实服务听感。新Python文件Ruff和git diff --check通过；未声明全仓lint通过。

下一项：记录实际播放时间线及欠载，评估首段启动缓冲与欠载后的重新缓冲，在首音速度和连续自然朗读之间明确取舍；继续核对供应商/网络慢样本和翻译耗时。真人听感未确认前，首句波动优化仍进行中，整体Live2D原目标仍未完成。

## 断供后的有限重新缓冲与最新整合验证

Goal/Scenario：首段仍尽早播放，网络中途断供时减少逐块断续；无声等待期间闭嘴，取消立即结束等待。Architecture Increment：在现有播放器增加回合内重新缓冲等待及每句stream_id，保留原Runtime、播放所有权及角色/generation护栏。

首块不增加启动等待。流式队列播空且尚未收到结束时，后续积累约960ms音频再续读；再次欠载时目标递增480ms，上限1920ms。每次等待最多1500ms，结束消息立即释放不足目标的尾块，取消清定时器和等待者。分句stream_id由一次Fish请求生成并随子块传递；新句首块不继承上一句欠载等待，前句已排期音频仍严格先播。等待期间mouth=0，presence映射从speaking转thinking，恢复实际播放再回speaking，不用补零/重复音频掩盖停顿。

代价明确：第一次首音不因该策略等待，已经断供后的续读可能额外等待0–1500ms；它降低碎片式续读风险，无法保证极慢供应商持续实时供给。目标缓冲量按RMS切片估算，尾块长度仍以实际WAV为准。不是“完全消除停顿”的承诺。

Tests/DoD：生产组件专项覆盖缓冲阈值、结束释放、最长等待释放、取消无迟到播放、新句不受旧句阻塞；presence映射专项通过。真实Electron/WebAudio六场景（两角色隔离夹具×阈值/尾块/取消）见[avatar-stream-rebuffer-browser-live.json](avatar-stream-rebuffer-browser-live.json)：等待时口型均为0、成组续读相邻块连续排期、尾块正常结束、取消后无迟到source；另双角色播放租约自然结束/取消四场景复验通过。它们是静音夹具，不冒充实际模型切换或声学听感。

重新启动最新引擎、刷新原桌宠后，Hotaru真实LLM→出口翻译→Fish→播放器新样本见[avatar-reply-http-rebuffer-live.json](avatar-reply-http-rebuffer-live.json)：6块均带stream_id和正确session/generation，最终idle；音频图5处相邻排期间隙均0ms，无本次欠载日志。此样本Fish首片804.5ms、完整1759.8ms；LLM回复1019ms、翻译1102ms。调试器观察到首帧8259.7ms包含前序上下文等环节和采样影响，不能把804.5ms当成端到端首音。此样本没有触发重新缓冲，重新缓冲行为由上述受控真实WebAudio断供场景证明；实际供应商断供下的自然听感仍待用户确认。

测量修正：CDP轮询收到消息的时间有观测延迟，旧样本中约2.65秒消息间隔不能单独证明声学断续；风险仍保留，最新用实际AudioBufferSource排期直接核对音频图。Runtime.enable会回放历史console，诊断已在请求前清除历史记录，避免把先前夹具欠载误记到本次朗读；原6.8秒Fish慢响应样本保持不覆盖。

最新engine目录全量983 passed（64.33秒），专项24 passed，前端typecheck/build和播放/Avatar专项通过；新Python实现和新增诊断Ruff通过。providers.py有既有未用httpx导入告警，未称全仓lint无告警。当前运行角色Hotaru，测试未开启麦克风。整体首句稳定性、多样本P50/P95、Hiyori真实麦克风与用户自然度验收继续保留未完成。

## 冻结候选后的真实供给复测

[本次三次有限采样](2026-11-10-fish-current-candidate-sampling.md)：首个可播放块2976.4/1721.6/3324.5ms，第三次完整接收13754.0ms、音频3390.1ms，最大相邻yield间隔3246.5ms；无播放/麦克风/配置改动，慢样本保留。545候选文件哈希一致。本地新进程keychain冷读506.7ms、后续约0.1–0.24ms，不能外推成运行中每句开销，不据此缓存旧key。供应商供给稳定性及声学/端到端指标仍未验收。

## HTTP连接复用与WS验证

[本轮实现/实验](2026-11-10-fish-transport-iteration.md)：同循环HTTP池已部署，暖请求实测0次TCP/TLS、首块745/902ms；直连约5秒连接失败，保留现路径。两次WS协议验证成功，冷连接首480ms音频约2.24/2.01秒，本轮没有优于暖HTTP，不立即替换。1014项后端全量通过；样本少、不宣称服务P95或彻底解决波动。

## 2026-11-11 首句文本交付与WS预连接

[本轮](2026-11-11-tts-sentence-admission.md)修复流式短前缀卡在最早句界、直到EOF才交付的问题；模拟token节奏各5次，短前缀首句文本交付中位343→42ms，普通首句约21ms不变。新增7项与全量1021项通过，修复已部署。两次独立WS预连接在模拟文本就绪后约541/520ms凑足480ms音频，握手已与1.5秒模拟生成等待重叠；不是实际LLM/翻译/播放链路或P95。生产继续HTTP连接池，供应商波动未宣称解决。

## 2026-11-11 WS接入现有Runtime

[可选WS已实装](2026-11-11-fish-websocket-integration.md)：真实VoicePipeline、文字朗读、角色配置及调试台均已接入，复用原队列/播放器/打断隔离；提前握手与生成重叠，同轮持续发送转换后的句子，无隐式重试或传输回退。1032项后端全量、前端typecheck/build通过。

真实LLM→翻译→WS生产流水线的捕获回调首块4283.9ms（含生成与翻译，固定ASR替身，无播放）；实际配置热更新后，测试API用WS整段合成2548.7ms。这两个观测范围不同，既非声学首音，也非受控HTTP/WS对比；流水线样本在协议预导入最终修正前取得。尚不足以宣称P95改善。Hotaru已恢复原HTTP，Hiyori未变、麦克风保持关闭；后续以同文本/音色/网络有界对照及实际播放时间线评估默认值。
