# 文本与语音回合的输出交接

Goal：新文本回合开始时，旧语音/主动发言和旧文本朗读必须停止；语音打断也须取消文字朗读HTTP任务。

Scenario：旧VoicePipeline仍合成时输入文字，或文字朗读在途时触发统一取消。旧请求不能继续占服务或给新回合补旧声音；停止通知不能在新播放启动后误停新声音。

Architecture Increment：复用现有pipe.interrupt和统一_cancel_turn，补齐_reply_speak_tasks的取消/join；文本worker入口只交接语音输出，不取消用户持久Task/Plan。等待已派发停止通知后才进入新Agent回合。保持原Session generation推进和RuntimeRegistry职责，不另建调度架构。

Tests：生产交接函数与worker入口的顺序、在途旧任务取消释放、其他会话不受影响、父任务取消传播；实际WebAudio身份/取消回归。DoD：局部修复及调用链测试通过，记录实际范围；不以无麦克风夹具宣称真人验收全部完成。

## 实现与场景验证

新文本worker原来只cancel上一轮_reply_speak_tasks，未处理VoicePipeline里尚在生成的语音/主动发言。现进入Agent之前调用_prepare_text_turn：取消旧文本朗读，快照该会话的语音producer任务，调用既有interrupt，等待停止通知与这些任务清理后进入新Agent。只交接语音输出，不广播TaskRuntime取消、不重置用户持久Plan、不额外推进Session generation。

统一_cancel_turn也补齐文字朗读任务：先作废Session generation，立即发出旧文字朗读取消，再按原RuntimeRegistry传播取消，最后join文字朗读清理。不会在发出语音停止之前先等待HTTP关闭，保持打断响应优先。既有VoicePipeline.interrupt的副作用不变，只增加返回已派发停止通知任务，旧同步调用者仍可忽略；文本交接入口可等待通知完成，避免新Agent generation建立后迟到的停止通知误停新播放。

test_speech_turn_handoff.py直接执行生产交接/统一取消函数与真实嵌套chat_worker：

- 真VoicePipeline主动发言阻塞合成时，新文本交接同时取消旧语音和旧文本朗读，等待资源释放；其他会话的朗读保持运行。
- 统一取消在RuntimeRegistry+SpeechRuntimeAdapter和旧fallback两种装配下均先派发voice-stop，后等待文本请求释放，再发布session.cancelled。
- 真实chat_worker在停止通知门闩释放前不调用Agent；释放后才进入Agent调用边界（测试在该处取消，不请求供应商）。
- 父任务取消继续传播CancelledError，并取消正在等待的停止通知。

双角色Electron/WebAudio自然结束与VAD取消四夹具继续通过，证据仍为avatar-http-stream-browser-live.json；没有把这些静音夹具称为真实服务重叠说话/换角的听感证明。本轮前端源码未变，沿用前一轮配套构建。

## 限制

交接等待依赖provider及回调遵守取消契约；故意吞掉CancelledError并永久不返回的第三方实现不在本次通过范围。这里没有静默越过未释放的旧producer开始新播放。入口包括普通文本和统一取消；媒体直达/日记各自队列及所有主动后台来源的同类边界仍需逐个审计，不能把本轮修复外推到全部路径。

真人麦克风Hiyori、资源动态语义审定与主观自然度仍按总体审计保留。当前局部完成不等于整个Live2D自然交互Goal完成。

## 最终检查

engine目录pytest tests/：1000 passed，62.91秒；五项新增交接场景和其余语音/角色测试均在内。新增测试Ruff通过，git diff --check无错误。本轮未改前端，沿用已通过的配套壳。引擎已重启，结束状态见avatar-speech-handoff-final-state.json（Hotaru、idle、麦克风关闭）。本轮无真实供应商请求或麦克风采集；不将工作树测试等同于真实服务交叠说话听感验收。
