# Live2D自然交互交付审计

更新：2026-11-10。当前候选及六阶段缺口统一见[候选收敛报告](2026-11-10-avatar-delivery-candidate.md)。总体未完成；原目标继续。此表对应[原实施方案](live2d-expression-evolution.md)的六阶段，不增加新架构或替换Runtime。历史记录与失败仍保留，表内“通过”严格限定证据范围。

| 原要求 | 当前结论 | 权威证据与缺口 |
| --- | --- | --- |
| 两角色资源清单、缺失安全回退 | 清单和自动化通过；动态语义审定部分完成 | avatar-resource-inventory.json；80张实际缩略图及thumbnail-live-check.json。另补六段真实本地预览完整周期/18帧与头像裁剪修正（2026-11-10-avatar-dynamic-resource-review.md），哭泣/tear的安抚适配仍待验；不代表整套动作已审定 |
| 持续表情恢复、动作收尾/取消、待机去重 | 实现及分层测试通过；已有真实点击回落 | avatar-fixed-click-return-live.json；Hiyori资源Loop导致的逻辑/SDK脱节已修复；双角色Windows原生单击/回落已有avatar-native-fixed-click-live.json及avatar-native-click-hotaru-live.json；当前候选双角色自然语言greet落到Idle#6/Motion#4并回报started，见2026-11-10-avatar-dual-natural-current.md；全部动作衔接仍需综合观察 |
| Hiyori固定单一待机，单击池承担互动 | 最新用户要求已落地、短时实机通过 | avatar-fixed-idle-live.json；默认Idle#0，指定动作缺失安静暂停；avatar-delivery-candidate-idle-soak.json已补最终收敛候选300秒固定动作观察，主观自然度仍待确认 |
| 倾听/思考/真实播放四态 | Hotaru真实实录与听感通过；Hiyori实录待验 | avatar-microphone-hotaru-success.json；新增2026-11-10-avatar-dual-natural-current.md：双角色真实文本Agent/招呼/TTS/实际模型回执与说话回落通过；仍不替代Hiyori真人麦克风实录 |
| 真实打断、取消不吞、无旧语音/口型 | Hotaru最新真人打断听感通过；Hiyori独立实录待验 | 下发/播放占用已局部修复，avatar-barge-in-user-after-playback-fix.json及after-playback-summary：用户确认“打断效果已经很不错了”，转向首句TTS波动。不是物理停声P95或双角色全面通过 |
| 动作/表情/注视/口型仲裁 | 已实现主要仲裁；Hotaru注视真人通过；新增表情/自动眨眼顺序修复 | 用户确认Hotaru“衔接自然，未见明显抽搐”；当前表情/眨眼及动作/合成口型原生参数复验见2026-11-10-expression-blink-order.md；当前双角色原生移动/静止归还见avatar-native-gaze-*-live.json。Hiyori固定策略主观确认仍待验 |
| 角色/会话/generation隔离 | 多层证据通过，仍有协议审计范围 | 双向播放中正式换角旧记录及当前候选不刷新页面的真实文本TTS复验（2026-11-10-avatar-midplay-current.md，首轮Fish失败保留）；文字audio/end带身份；中间状态身份和转发等待后的复核已补（2026-11-10-speech-state-identity.md）；语音任务取消epoch继承已补，普通文本/统一取消与语音交接已补（2026-11-10-speech-turn-handoff.md）；辅助入口另见2026-11-10-diary-connection-ownership.md：独立日记连接/音频迟到结果已补护栏，官方媒体状态入口不引入语音中断；废弃builtin路径保持不启用 |
| 角色独立参数、实时预览 | 真实工作台与本地设置隔离通过 | appearance-studio.md，两个模型80缩略图；调试台/聊天坞双向语音设置回读已补，八次真实窗口变化及dirty标记保护通过（2026-11-10-speech-settings-live-sync.md）；本轮闭麦，已开麦期间的实际门控仍未人工验证 |
| 低延迟与指标 | 空知识库优化及本地播放状态分位数已记录；端到端语音分位数未完成 | avatar-memory-empty-kb-before/after.json，检索单样本4471→2345ms；不能当严格A/B或P50/P95。Fish首句长等待仍需进一步验证；avatar-local-playback-latency*.json仅本地状态延迟，不是TTFA |
| 实机持续运行、无空白/冻结 | 当前收敛候选双角色各300秒有界待机通过 | avatar-delivery-candidate-idle-summary.json及manifest：545个所列生产/构建/资源JSON文件哈希一致，双角色各300次可见/idle采样、画布持续非空且变化、眼睛0–1；Hiyori仅Idle#0，恢复Hotaru且采样器清理；旧候选记录均保留为历史；另补主语音dispose六个真实WebAudio实例closed（2026-11-10-voice-audio-context-lifecycle.md）；不推断多小时或语音压力稳定性 |
| 工程回归和交付文档 | 当前后端全量通过，前端相关专项与类型/构建通过 | 2026-11-10 engine目录pytest tests/：1000 passed，62.91秒；含首句入场、取消join、HTTP音频分块与句序新增测试。语音组件回执、生命周期和Avatar专项、前端最新长回复typecheck/build通过。不是全部lint通过，Agent既有22项保持基线 |

## 下一轮顺序

1. Hotaru播放占用修复后，真人确认打断效果已好；长回复真实滚轮也已修复。首句排队和纯标点请求已修复，后续后端当前1000项回归通过，HTTP音频分块已接入并有双角色静音fixture取消/句序/隔离证据；Hotaru整合实机仍遇Fish首片6.8秒、块间欠载风险，连续听感未判通过，详见tts-first-sentence-latency.md。有限重新缓冲与新句边界已实现，真实WebAudio六场景和最新Hotaru短句连续排期通过；继续实测供应商断供自然听感及端到端分位数；不把本地fixture中位数当作真实服务P95。
2. 独立补Hiyori实录，保持固定Idle#0与独立声音；自然度由用户明确确认，不能外推Hotaru结果。
3. 当前收敛候选持续待机300秒/角色已复验，545文件哈希一致（2026-11-10-avatar-delivery-candidate.md）；当前候选两方向文字TTS原页面换角已复验；输入/播放解耦与麦克风语音换角继续结合实录验证。对延迟记录真实起止和多次样本，再计算P50/P95，不把rAF分位数当作语音延迟。
4. 继续审计ws/audio生产者任务入口到回调的冻结身份传播及队列边界，补动态资源语义审定；仅对有证据的问题局部修复，不凭“更生动”增加随机待机或重写Agent。

## 收尾规则

没有真人反馈、原始记录或对应生产调用链测试的项目保持待验。待全部原要求都有相称证据后，再更新Goal为完成。暂未收到真人配合答复不等于授权开麦、不等于测试失败，也不自动满足blocked条件；能继续推进的独立工程工作继续执行。

[最新眨眼适配构建待机](2026-11-10-blink-order-idle-soak.md)：双角色各300秒、全程可见、画布持续变化、眼睛正常开合、Hiyori固定Idle#0；30个文件哈希一致，恢复Hotaru并清理采样器。仅有界自动验证，不代替真人自然度或语音压力测试。

[表情加载预约取消](2026-11-10-expression-request-cancellation.md)：本机SDK原始类复现reset/current遗留预约；生产实例适配补齐，reset/current/newer/dispose专项及双角色六阶段真实参数回归、类型/构建通过。最新主窗口已加载，Hotaru/idle/闭麦。该次新构建未重新进行300秒待机，不挪用上一构建证据。

[动作启动回调归属](2026-11-10-motion-start-ownership.md)：底层状态修改前核对模型/表演/单次播放身份，防止旧失败清空新动作；生产函数控制Promise专项、真实双角色动作结束与显式取消四场景、类型/构建通过。最新主窗口Hotaru/idle/闭麦，长时记录仍归属于此前候选。

[真实SDK重叠意图回放](2026-11-10-avatar-overlap-replay.md)：当前构建双角色高优先级保持、低优先级基础表情延后恢复、取消原计时器无迟到副作用及换预览模型旧计时器隔离通过；首轮诊断清理错误及重跑说明保留。无生产修改、闭麦，不代替正式角色服务切换或自然度评分。

[首段等待与空音频收尾](2026-11-10-avatar-tts-waiting.md)：文字朗读开始、语音合成及晚到最终文本维持等待表现，真实播放器启动才说话；空结果独立结束等待、不冒充播完收气泡。生产处理器专项、双角色真实WebAudio四场景、类型/构建通过。当前主窗口已更新闭麦，不代表主模型整合自然度或供应商TTFA改善。

[首段等待真实主窗口整合](2026-11-10-avatar-tts-waiting-integrated.md)：实际App控制处理器、模型presence/口型props与WebAudio回放，正式Hiyori→Hotaru→Hiyori六场景通过；双向旧会话音频及结束帧未改变新等待状态。恢复Hotaru、钩子清理、闭麦。事件与静音音频为本地fixture，不代表ASR/LLM/TTS真实整链路或声学评分。

[安抚动作默认推断收敛](2026-11-10-avatar-comfort-semantics.md)：sad/cry/tear不再自动等同comfort，Hotaru七项退出默认安抚但资产/具体试播保留；重启后真实主进程清单和双模型具体试播/取消通过，类型/构建通过。未审定表情/其他语义保持待验；最新新构建未重跑300秒。

[当前候选收敛](2026-11-10-avatar-delivery-candidate.md)：545文件指纹前后一致、九个相关专项及双角色各300秒持续可见待机通过；原六阶段逐项保留人工/端到端/语义缺口，整体不标完成。

[当前候选真实Fish供给](2026-11-10-fish-current-candidate-sampling.md)：同配置三次实际短句首块1.72–3.32秒，第三次13.75秒收齐3.39秒音频，最长相邻yield间隔3.25秒。没有播放/采麦，不能当声学断续或端到端P95；低延迟稳定性保持未验收。545候选指纹未变。

[用户新一轮Agent互动迭代](2026-11-10-agent-reaction-iteration.md)：补真实工具结果分阶段反应、session/generation/角色身份、低优先级短动作、去重/冷却与调试台独立参数；1011项后端全量和前端类型/构建通过，双角色真实主窗口本地回放通过。新候选接续冻结版本，未新做300秒待机或真人自然度；TTS供应商波动保持未解决。
