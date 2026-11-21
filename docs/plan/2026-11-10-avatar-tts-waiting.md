# 语音首段等待与空结果的表现状态

Goal：TTS首段慢时保持等待表现，真实播放才进入说话；没有音频时正确收尾且保留文字可读时间。Scenario：文字回复朗读已开启但首段未到、语音LLM最终文本晚于合成开始、关闭/失败导致零音频。Architecture Increment：沿用前端presence及播放器事实，增加本地waiting/empty通知；不改引擎协议或调用供应商。Tests：生产presence与useVoiceInput受控回放，真实WebAudio专项，类型/构建。DoD：等待、播放、空结果、取消和结束顺序均有断言；不把状态表现修正称为降低供应商TTFA。

当前源码：presenceAfter在chat:assistant/llm:text后回idle；beginReplyPlayback只清计数、不发等待通知；tts:start/synthesize未驱动presence。零音频不能发playback_end（否则气泡过早收起），但也需要独立的表现状态收尾。

## 实施及验证

- `presence.ts`增加本地waiting/empty处理：waiting或合成开始进入thinking，已有speaking保持；empty回idle。
- `useVoiceInput.ts`在文字朗读开始发waiting，在最终语音文本晚于合成开始/队列音频时补waiting；队列空且引擎发送结束后区分empty与真正playback_end。empty不触发“播完收气泡”。
- `avatar_tts_waiting_test.cjs`通过：生产presence和真实composable处理器的文字首段等待、最终文本乱序、空结果、取消、跨角色拒收。
- 播放回执、stream句序排期、AudioContext生命周期、Avatar基线专项通过；`pnpm --dir shell typecheck`及`pnpm --dir shell build`通过。
- 真实Electron/WebAudio两个角色fixture各覆盖有音频与空结果，四场景通过，见[事件记录](avatar-tts-waiting-browser-live.json)。有音频为thinking→speaking→idle；空结果thinking→idle且无playback_start/end；口型最终0、创建的AudioContext均closed。静音fixture并非真人语音或主模型整合演出。
- 首轮诊断以固定时间判断终态失败，未保存该轮完整参数，原因未定；后续记录末次尝试，改为有超时边界的事件等待后四场景通过。不将失败归为供应商问题，不当作稳定延迟分位数。
- 已确认主窗口加载`index-Cyk2OWl1.js`、Hotaru/idle/闭麦，见[最终状态](avatar-tts-waiting-final-state.json)。未启动额外桌宠实例或修改角色配置/捕获保护。Python诊断Ruff通过。

本轮无后端改动，没有重跑后端全量或新构建300秒待机；既有记录归属于各自候选。仍需真人Hiyori麦克风/打断、主观自然度及端到端语音指标，整体目标未完成。

后续已补[真实主窗口整合回放](2026-11-10-avatar-tts-waiting-integrated.md)：正式双向换角、六场景App/模型状态与口型props、旧会话音频/结束拒收通过；仍为本地模拟入站消息和静音WAV，不替代真实供应商/麦克风验收。
