# Hotaru 真人打断验收：路径成立，拖音未验收通过

> 本标题描述修复前轮次。后续已经完成播放占用局部修复，Hotaru复验反馈“打断效果已经很不错了”；见文末追加结果。原始失败记录保留。

## 本轮目标与范围

在现有Voice/Avatar Runtime上验证真人说话中打断；不调整模型、音色、角色配置架构。用户已同意临时开启打断并自行开关麦克风。观察器只记录事件、PCM帧计数/峰值及口型输入，不保存麦克风音频。

本轮用户先说“请讲一个稍长的小故事”，在实际出声后尝试打断。最终反馈：“总体效果还不错，但还是有些瑕疵和反应延迟”；进一步明确为“说‘停一下’后，旧声音仍拖了一会儿”。因此不能签收低延迟停声。

## 证据与结果

- 原始记录：[avatar-barge-in-user-live.json](avatar-barge-in-user-live.json)；摘要：[avatar-barge-in-user-summary.json](avatar-barge-in-user-summary.json)。Hotaru实际采音2863帧，8508836字节，最大帧RMS约0.328。
- 四次当轮`local:interrupt_logged`前均已有`audio:playback_started`，并收到`tts:interrupted`。证明本轮确实进入播放后打断路径，区别于之前只有ASR阶段取消的尝试。
- 四次打断日志前的口型输入均非零；下一次闭口采样分别38.0、10.8、49.4、41.0ms，presence为idle。这是约50ms采样的renderer props观测，不是SDK最终嘴部参数、物理停声或用户开口到停声的耗时。
- Runtime.enable重放了两条历史console打断记录，已在摘要中按当轮采样时间范围排除，原始文件保留。原始Network的ms为观察器收包时间，受CDP轮询/积压影响，不能直接计算准确VAD→停声P95。后续探针已保留CDP单调时间、过滤历史日志，不能把新探针能力倒算成旧样本精度。
- ASR存在“感一下.”、“给一下。”、“等明签。”等转写。没有原始声音逐句对照，不能把所有短句认定为误识别或自听；但用户的停止意图与转写偏差值得后续独立复验。

## 源码发现与下一增量

`engine/yuiro/audio/__init__.py`的`_speak_impl`在manager下发完成的finally清除`_speaking[session_id]`并发送`tts:end`；`_process_audio_chunk`仅在`SpeechStart`且`_speaking`为真时触发自动打断。`mark_playback_started`当前只标trace。

`shell/src/renderer/src/composables/useVoiceInput.ts`明确区分引擎`tts:end`与本地`tts:playback_end`，音频在串行队列中逐段播放。记录也存在`tts:end`之后继续发送播放开始回执的时段。因此“已下发完，但还在出声”是当前代码确实存在的判定空档，可解释部分漏打断/拖延；尚不能证明全部主观延迟都源于此，也不能排除VAD确认、能量二次门槛、音频设备缓冲的贡献。

后续最小修复任务（本轮未冒充已实现）：

1. **Goal/Scenario**：当最后一段已下发、桌宠仍在实际播放时，用户开口仍能取消本角色的旧输出。
2. **Architecture Increment**：延续VoiceRuntime，分离生成/下发状态与实际播放占用；播放开始、自然结束、取消回执携带session/generation/角色身份；旧回合结束回执不得清掉新回合占用。连接关闭、换角和取消必须释放占用；不采用无限等待结束回执的锁。
3. **Tests**：覆盖“tts:end后队列未空→VAD开口”、旧回执晚到、新回合替换、开关关闭、断连/换角、解码失败与重复取消；正常播放/真实打断分别测试。保留能量防自听边界，不用单纯降低阈值掩盖生命周期问题。
4. **Measure**：下一次记录连续接收的CDP单调时间与PCM窗口时间，分解输入采集→VAD确认→取消发出→前端停止；物理停声仍需真人/声学验证。前后样本口径一致，不把当前50ms口型采样宣称为输入到停声延迟。
5. **DoD**：分层测试通过，双角色不串音/不串占用，用户确认停止后旧声音及时消失；测试结束读回原设置、关闭麦克风。

## 恢复与工程检查

本轮结束已实际读回Hotaru、barge_in_enabled=false、microphone=false；临时采样timer和window探针已移除。当前没有继续采音。Hiyori固定Idle#0、两角色声音和模型配置保持原方案。

本轮只调整诊断脚本及验收文档，两个脚本py_compile通过；未改产品实现，未重复运行此前963项后端全量。后端/前端整体交付状态继续以[live2d-acceptance-audit.md](live2d-acceptance-audit.md)为准。

## 后续修复与真人复验

已按上述局部边界引入逐片段播放占用，详见[技术复盘](../tech_review/2026-11-10-speech-playback-ownership.md)。实际engine目录pytest全量969项通过，前端typecheck/build及语音组件专项通过。隔离配置下真实WebAudio/localhost WS四场通过，不代替真人听感。

用户再次自行开麦复验，原始记录独立保存为[修复后实录](avatar-barge-in-user-after-playback-fix.json)，未覆盖修复前证据。六次tts:interrupted中第一轮发生于生成阶段，随后已有播放；其中可见tts:end后仍在播放时收到新的打断，补到了原先空档。CDP同一单调时钟下，VAD active到收到interrupted约10.95–18.97ms；这不是开口到物理停声耗时。

用户明确反馈：“打断效果已经很不错了！现在的主要问题还是tts的首句返回延迟不稳定问题（时快时慢）”。据此本轮Hotaru打断听感通过，Hiyori真人链路和端到端声学测量不外推。finally已读回Hotaru、barge=false、麦克风关闭，探针清理。摘要见[修复后摘要](avatar-barge-in-after-playback-summary.json)。
