# Live2D表现管线实施复盘

现有AvatarRuntime、PerformanceResolver和语义槽位继续作为入口，未替换AgentLoop、VoicePipeline或渲染SDK。实现按本地即时反应与LLM语义演出分工：倾听/思考/实际播放/取消由已有事件推进；明显庆祝、打招呼等仍由Agent或用户显式触发。

主要修复来自实际SDK证据：

- SDK自身在motionFinish后立即续播Idle，绕过项目停顿/去重。以SDK选项隔离默认待机组，统一由现有startIdle调度。
- startMotion是异步Promise，原代码把请求当成成功。现在处理拒绝/异常、模型修订和请求替换，完成事件优先，时长仅作兜底。
- 一次性表演不再抹掉持续基础表情，期间收到的低优先级更新等待恢复；模型卸载清空基础表情、占用和回执。
- Cubism4没有原代码使用的setParamFloat。口型改在beforeModelUpdate阶段使用模型LipSync声明和setParameterValueById；实际模型参数采样验证开合与归零。
- 三份旧Hiyori Extra资源的CurveCount比实际数组多1，导致SDK解析失败；只修元数据，未重绘动作。

前端IntentLease和后端UUID回执各有边界：前端保护已开始的表演，后端只允许当前意图的回执释放占用。SDK完成优先加计时兜底，不能宣称每个平台都保证逐帧精确。当前generation字段仍未构成完整跨通道generation协议；会话过滤、角色切换取消和模型修订已有独立保护，完整generation补强仍待审计推进。

注视复用现有DIP/CSS鼠标坐标流，不启用SDK自动命中；focusController负责平滑，远离与显式表演时回正。两角色可分别热调注视幅度、说话动作冷却和时长上限，关闭后不再自动触发。没有新增云端调用来生成微反应。

验证已经覆盖真实SDK生命周期、真实TTS本地播放、双向播放中正式换角和自然话术触发greet；麦克风/ASR实录、整套资源视觉审定和长时间性能分位数仍有缺口。2026-10-31末轮帧采样count=0且画布为空，已确认页面visibilityState=hidden、rAF=0，不能提供有效帧率或视觉结论。完整记录与原始证据见[实施计划](../plan/live2d-expression-evolution.md)。

外部参考仅用于设计分工，不复制源码或资产：

- [AIRI Live2D Model.vue](https://github.com/moeru-ai/airi/blob/main/packages/stage-ui-live2d/src/components/scenes/live2d/Model.vue)
- [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)

后续首先保证实际窗口持续绘制，再完成资源视觉标注、性能开关对照和主观自然度确认；不以绿色单元测试替代这些结果。

2026-11-01补充：普通桌面恢复后已采到有效开关对照帧数据和非空模型画面；用户授权改为qwen3.8-max-0902后，进一步发现并修复角色bundle构造遗漏generation查询的问题。两角色真实意图现均携带generation=1并被前端应用，工厂级隔离测试已补。详见实施计划最新段落，旧“generation仍待补强”和“画布为空”描述仅代表此前阶段。

单击反馈增量：把原先按下立即拖动改为按位移阈值启动拖动，短按释放才进入独立动作池。配置按角色+模型分区，当前清单校验过滤旧资源；动作仍走统一applyAvatarIntent和USER优先级，避免点击另起播放器。事件处理与存储隔离回归、真实renderer鼠标分发及调试台入口通过，见[验收](../plan/avatar-click-feedback.md)。


2026-11-09实际桌宠续验：唯一最新构建实例下正式双角色切换，各150秒rAF与像素采样有效，最终恢复Hotaru且idle/until=0。该结果补上优先级修订后的持续绘制证据，不等同用户自然度认可；rAF间隔非GPU完成时间，Hotaru90.8ms最大离群仍需后续观察。状态存储是变化触发，不是逐帧心跳，重复同动作时at不刷新，不能据此误判冻结。原始记录见计划最新段落及avatar-current-idle-soak.json。


本轮用户明确确认当前Hotaru鼠标移动→停住约3秒时「衔接自然，未见明显抽搐」，该场景可记录主观验收通过。Hiyori需独立确认，完整Goal仍有ASR实录和全素材动态审定等缺口。


2026-11-09用户将Hiyori风格收敛为“固定单一待机＋单击动作池互动”。新增角色独立fixedMotion，Hiyori默认Idle#0、Hotaru保留空值轮换；固定动作缺失不随机替代，热更不抢显式表演。真实调试台Idle#1试选12秒不出现其他动作，再恢复Idle#0并切回Hotaru，隔离读回通过。此前Hiyori随机待机的150秒样本不能证明新策略长期稳定。详见计划本轮证据。


固定待机续验暴露底层Loop动作与逻辑租期脱节：只清状态不足以停止SDK循环。completeAppearance现失效请求后显式停止motionManager，再做回执和待机恢复。当前SFC函数级回归及实际renderer轮廓内点击→Idle#6→固定Idle#0验证通过；临时池恢复、Hotaru恢复。该证据不替代原生鼠标及完整自然度审定，详情见计划最新记录。


真实麦克风首轮仅出现管线ready，无VAD/ASR/TTS事件，已关闭录音并等待用户说明实际说话情况，不能判通过。排查同时发现随机micLevel是假观测，已替换为真实PCM RMS经显示增益归一化，停止时归零；纯函数专项与类型/构建通过。后续采样按上行PCM帧、字节与RMS聚合区分采音/传输/VAD阶段，不保存原始音频；尚未获得第二轮实录证据。详见计划新增段落。


实录进展：用户说明首轮未说话后，ASR-only参考音频测试成功；第二轮真实Hotaru麦克风585帧上行，VAD/ASR/LLM/TTS与实际播放、四态表现齐备，用户确认声音正常。当前barge_in_enabled=false且未尝试打断，该项仍待验。CDP接收归档出现批量时间戳，样本提示等待偏长但不能直接当服务端耗时或分位数，后续须原始Network timestamp+Trace定位。成功样本另存avatar-microphone-hotaru-success.json，避免后续探针覆盖唯一证据。


延迟审查发现旧Trace把管线LLM入口与真正provider请求混在一段，记忆也只有完成点。新增检索开始、provider请求开始及provider首正文token阶段，保持原字段兼容，以便区分journal/检索/上下文与外部等待。真实样本Fish首句13.37秒、ASR167ms；单样本不足以得出普遍归因，不通过乱序播放或跳过显式记忆换取表面速度。52项Agent/Trace回归通过，新增文件lint通过、Agent既有22项lint未增加。实际新计时与优化收益仍需重启后复验。


2026-11-10计时落地发现确定浪费：知识库0片段仍编码BGE查询。KnowledgeStore.retrieve新增无缓存的SELECT 1 LIMIT 1快速空返回，避免重复推理，导入/清除立即可见；未绕过其他记忆通道。39项专项通过，两次真实短文本采样检索4471ms→2345ms，provider等待2396ms→3448ms，说明外部波动须单独看。单样本不当作分位数或严格因果收益；原始JSON与重启加载状态已记入计划。


2026-11-10取消隔离增量：文字TTS帧以前缺session/generation，只靠任务取消不足以防已发送旧音频。现在任务创建时冻结权威代际，合成前后验证，audio/end共同绑定身份；前端队列与结束标记之前校验并抬高接受下限。29项后端回归、实际App分支测试及配对实例正常朗读冒烟通过。旧无身份TTS帧被拒，须配对更新，当前已重启/重载。真麦克风barge-in与真实竞态注入仍另验，详见计划。


2026-11-10音频所有权修正：stop采音不应无条件停止正在输出语音的口型，mic:stop也不应将speaking/thinking直接判idle；现在输出由实际播放结束/取消拥有，dispose则明确停止两端。生产composable适配桩测试覆盖输入关闭、自然结束和卸载，start前读取最新barge配置防陈旧镜像。前端专项、类型和构建通过，当前Hotaru未开麦，真人播放中关麦/打断待验。


语音流收尾修复：finally按session pop会在旧清理与新合成重叠时取消后继manager。现以局部mgr对象拥有清理权，每次状态/锁更新前确认映射，取消不发正常end；受控asyncio交错验证生产VoicePipeline，31项专项/963项全量通过，后端已加载。该修复不能替代ws/audio全帧身份传递或真人barge-in。见实施记录及avatar-speech-cleanup-regression.json。


当前候选持续性补验已完成：最新固定待机、收尾与输入生命周期构建下，两角色正式切换各300秒，画布每秒非空且变化，Hiyori未切换其他idle，最后恢复Hotaru/麦克风关闭。对22个实现/构建入口与147个模型资源做前后SHA核对均一致，范围不扩到整个仓库。rAF仅页面调度，非GPU或逐帧SDK计数；证据与限制见计划末段及avatar-final-candidate-idle-summary.json。


本地20次/角色无声WAV处理器探针补充状态延迟分位数，并发现首AudioContext的图时钟与墙钟启动进度不同；口型原按墙钟消费音量片，现统一为图时钟currentTime。生产composable时钟分离测试及真实Live2DCanvas口型props探针通过，不能扩展为物理音画完全同步。首次结束长尾保留，未用定时器强行截尾；设备outputLatency未校准。详见计划本轮数据与限制。


原生点击补验：通过Windows真实SendInput而非JS MouseEvent，结合DPI/client坐标、production hitContour与WindowFromPoint归属检查，在Hiyori/Hotaru触发指定单击动作并回原待机。临时池/角色/鼠标恢复，Hotaru原池文本读回一致。动态browser PID避免旧探针硬编码进程误操作。失败防护分支只做语法审查未伪造实测，详见计划原始JSON。


原生注视续验：当前角色偏好下分别2200/2800ms租期，Win32移动后生产Gaze owns=true/weight约.99946，静止后owns=false/weight约.001，Hiyori回Idle#0、Hotaru回Motion#19。未改参数或点击池，鼠标/角色恢复，临时VNode引用清除。该证据仅状态与SDK focusController，不等于逐帧核心参数或真人自然度认可。
