# 语音中间状态身份与旧帧隔离

Goal：旧回合的结束、打断、ASR/LLM状态不能改变新角色/新回合的播放与表演。

Scenario：新声音正在播放时收到旧tts:end或tts:interrupted；或状态回调等待Avatar期间发生换角/代际变化。旧事件应被丢弃，不能提前收气泡、关闭新口型。

Architecture Increment：沿用Session generation，在现有语音事件转发边界冻结session/character/generation，并在异步等待后复核；前端对语音状态与音频采用同一身份下限。pipeline加载通知保持连接级事件。没有另建Speech Runtime，也不宣称这能追溯所有旧生产者任务。

Tests：转发等待期间换代/换角色/更换会话对象不下发；正常状态身份完整；前端旧/跨角色/缺身份状态无副作用，新状态正常收尾；原播放租约、缓冲、取消、类型/构建回归。

DoD：局部边界实现和生产函数/组件场景通过，当前结果与仍未覆盖的生产者任务身份记入本报告；真实麦克风和主观自然度仍按总体审计单独验收。

## 已实施与证据

`engine/yuiro/main.py::_emit_event`在进入时冻结Session对象、generation及角色ID，等待Avatar回调后复核，再用冻结身份下发，不能把等待前事件重新标成新回合。`useVoiceInput.ts`在改变VAD/ASR/LLM/TTS状态之前检查身份和单调代际下限；音频另保留playback_id检查，坏音频帧不提前抬高代际下限。连接级pipeline加载事件保留既有处理。

新增`engine/tests/test_speech_state_identity.py`直接执行生产转发函数：正常身份、payload不能覆盖权威身份、等待期间换代/换角色/替换会话、会话缺失。生产组件测试额外注入旧/跨角色/跨会话/缺身份打断与旧结束帧，证明不能停止当前播放；旧ASR收尾不能清掉新回合busy。原播放回执、分块连续排期、重新缓冲、生命周期专项继续通过。

真实Electron/WebAudio复验见`avatar-http-stream-browser-live.json`：Hiyori/Hotaru隔离夹具各自然结束和VAD触发取消四场景通过。fixture发送状态已按新契约带身份；这是生产组件+实际WebAudio/localhost WS的组合，不是两个真实角色的真人麦克风听感，也未覆盖正式模型切换。

最新engine目录全量988 passed，64.46秒；前端typecheck/build通过，新增测试Ruff和git diff --check通过。重启引擎并刷新单个已有桌宠到最新构建，读回Hotaru、idle、麦克风关闭。本轮未请求供应商、未开麦或改角色配置。

## 范围限制与后续

这次堵住的是“转发期间变更”和“前端收到旧身份帧”，并未证明每个生产任务均从创建时冻结权威Session generation。如果旧任务在新回合建立后才首次进入_emit_event，现转发器仍无法仅靠当前状态辨认其来源；下一增量应将生产者身份/取消作用域从任务入口传递到状态与音频回调，不可把当前generation事后贴到旧结果上。旧tts:interrupted的延迟任务派发也须在该审计范围中。

真实麦克风Hiyori、主观自然度与供应商慢响应分位数保持待验；本次局部通过不满足整个Live2D自然交互Goal的完成条件。

## 下一增量：任务创建时的取消epoch作用域

场景：ASR/展示翻译仍在await时interrupt，或延迟interrupt通知尚未调度即再次interrupt。沿用VoicePipeline已有_turn_gen，任务入口冻结epoch，子任务继承作用域；中间事件和音频交付前核对，旧任务不能到转发器后重新取得当前身份。interrupt通知在同步调用处捕获新epoch，不在通知任务启动时重新捕获。验证真实VoicePipeline阻塞ASR/翻译后取消和延迟通知；保持CancelledError传播。此增量针对取消epoch，不冒充完整Session generation统一（AgentLoop会在自身入口推进generation，不能直接冻结ASR前generation并误丢该轮合法回复）。

### 已实施的生产任务护栏

新增`audio/ownership.py`只封装已有_turn_gen的不可变任务owner与ContextVar作用域。on_speech_end、_speak、_speak_stream、_speak_impl入口复用继承owner，事件回调和音频下发前核对；旧子任务不能在自己的子入口重取新epoch。ASR线程返回（含空值和异常）后先检查，再允许写_speaking或发状态。on_sentence也先检查再入队。失效抛CancelledError，不能当普通合成失败继续。

interrupt通知在同步interrupt调用处显式冻结owner；连续两次interrupt而通知尚未调度时，前一次通知自行失效，只发送最新通知。正常VAD连接事件没有回合owner，继续沿用上轮转发身份护栏。

另外修复延迟trace汇总按session盲目pop的问题：旧播放结束后的延时任务原先可能移走新回合trace，导致首音指标丢失或错误提前结算。现在显式传入原trace并按对象所有权移除，只输出自己的记录；此项是可观测性正确性修复，不是延迟提速。

新增`test_speech_task_owner.py`验证真实VoicePipeline的ASR迟到正常/空值/异常、展示转换迟到、重复延迟interrupt，以及trace正常收尾/不误移新trace。组件、播放租约和现有语音专项继续复验；双角色真实WebAudio自然结束与取消四场景继续通过，范围仍为隔离静音fixture。

仍需说明：取消epoch与权威Session generation有不同推进时机。本轮没有把二者合并或保证所有跨Runtime新文本回合都已触发voice取消；该编排边界以及主动任务/全部事件来源仍须独立审计。真人Hiyori麦克风、主观自然度与服务端延迟分位数未由这些测试替代。

本增量最终回归：engine目录995 passed，59.44秒；新ownership模块和测试Ruff、git diff --check通过。前端源码本增量未改，沿用上一轮已通过类型/构建的配套壳。已重启引擎加载；结束状态见avatar-speech-owner-final-state.json。本轮无新供应商请求、无麦克风采集，也不把静音WebAudio夹具记为真人自然度通过。
