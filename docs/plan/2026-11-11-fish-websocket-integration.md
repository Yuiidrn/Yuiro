# Fish单轮WebSocket接入

Goal：将预连接/持续文本流接入现有Speech Runtime，而非仅保留实验脚本。Scenario：语音LLM尚在生成时启动单轮连接，翻译后的句子顺序发送，音频沿原播放队列提前交付；文字朗读同轮复用连接并与翻译重叠。Architecture Increment：Fish可选transport及单轮session适配，HTTP默认保留；不新增播放器/Runtime。Tests：协议流、提前握手、输入/网络失败、取消join、无文本、跨角色/generation、配置与调试台、全量回归及有界真实服务验证。DoD：明确可用范围和指标；出现错误不重复合成或暗切音色，默认HTTP可回退。

## 已实装的行为

- 调试台→声音→Fish配置增加“Fish传输方式”，支持HTTP/WebSocket。按角色保存，新回合生效；默认HTTP，当前Hotaru测试后也恢复HTTP，Hiyori保持原配置。
- WebSocket每轮建立独立连接，语音入口提前握手，已完成语言转换的句子依序发送，音频直接进入原TTSTaskManager和播放器。文本入口握手与Agent生成重叠；文本仍等待完整回复再朗读，不将其描述为LLM token直通音频。
- 持续文本流需要分段流式TTS开启；关闭时支持单次完整WAV合成，但没有单轮持续输入的收益。试听走完整音频合成，不播放返回音频的自动验证不等于听感验收。
- 沿用原有音色、模型、语速、出口语言、session/generation及播放归属。PCM转换为既有480ms WAV子块，一轮共享stream_id，沿用RMS口型与欠载处理。
- 打断、换代、换角色会取消并回收握手、输入任务、接收任务和socket；翻译前后复核归属。网络失败明确报错，不自动重试、不换音色、不暗切HTTP。用户可手动选择HTTP用于后续回合。
- 协议依赖在provider构造阶段加载，避免首句才导入阻塞关键路径。没有引入新的Runtime或播放器。

## 验证与证据

| 验证 | 结果与边界 |
| --- | --- |
| 后端全量 | 1032 passed，66.92秒；覆盖新增协议、取消与角色配置回归 |
| 前端 | pnpm typecheck / pnpm build通过，真实桌宠加载index-BPsrL3y6.js |
| 协议及运行时专项 | PCM分片/尾块无损、首块早于输入结束、统一stream_id、取消输入及连接、失败不重发、generation翻译竞态、预连接任务启动前后取消、非流式完整WAV均通过 |
| 真实LLM→翻译→WS | [fish-ws-pipeline-live.json](fish-ws-pipeline-live.json)：LLM首token2251.0ms、首句2369.3ms、生成结束2555.2ms、首块交付4283.9ms；调用真实生产VoicePipeline，固定ASR替身、捕获回调，不开麦、不播放、不写历史 |
| 实际配置/合成API | [fish-ws-config-live.json](fish-ws-config-live.json)：非法transport返回400；真实保存WS后实际TTS测试端点成功，44100Hz WAV共368684字节，完整合成2548.7ms；响应标记transport=websocket |
| 恢复与调试台 | 同一证据中全配置段恢复相等，Hiyori文件指纹不变；[fish-ws-ui-final-state.json](fish-ws-ui-final-state.json)确认控件有两种选项、当前http、Hotaru/idle/闭麦 |

真实流水线样本在“协议导入提前至provider构造”的最后调整前取得，证明贯通，不作为最终候选冷启动性能基线。4283.9ms是诊断开始至首块回调，包含LLM/翻译等；2548.7ms是另一次请求的整段合成时间。两者不能当作声学首音，也不能互相比较或与独立模拟预连接的520ms混用。保留全部样本，不据此宣称P95改善或供应商波动消失。

新增实现、测试和诊断文件Ruff通过；git diff --check通过。未宣称全仓历史lint清零。测试后已加载新引擎，刷新实际调试台与桌宠，未改变角色音色和模型，麦克风保持关闭。

## 验收结论与后续

本轮交付为“可选择、可取消、与既有Runtime整合的WS路径”，实现与自动验收完成。真实服务在两种入口通过，HTTP仍为默认，未擅自切换长期使用策略。其收益主要是握手与生成重叠、同轮后续分句省去重复请求连接，不能消除供应商排队和语言转换开销。

尚未完成：双角色WS真人听感/说话中打断、长时间稳定性、足量端到端P50/P95以及受控HTTP/WS对比。后续先做有界同文本、同音色、同网络的对照，分开记录首句就绪、翻译、连接、首音块与实际播放；再判断是否值得将Hotaru默认改为WS。不要用反复重试挑选快样本，不提前默认切换，不重启G1架构演进。

技术过程见[复盘](../tech_review/2026-11-11-fish-websocket-integration.md)。
