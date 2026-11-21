# 音频下发与实际播放占用分离

## 问题与实现边界

真人反馈“说停后旧声音仍拖延”之后，审计发现VoicePipeline在TTS下发结束后清除`_speaking`，但renderer队列尚可继续播放；VAD自动取消只看`_speaking`，因而漏掉这段播放窗口。之前`audio:playback_started`只写Trace，不维护实际占用。

本次延续VoicePipeline、原有串行WebAudio播放器和统一取消入口，新增`audio/playback.py::PlaybackLeases`，没有建立替代Runtime。每段下发前登记唯一`playback_id`，绑定权威角色、会话、generation；VAD判定使用“生成中或仍有待播片段”。TTS下发完成仍按原语义发`tts:end`，不会代替播放完成。

`main._play_audio`从WAV读取真实时长作为占用期限预算；前端在实际source开始时回执started，在自然结束、解码失败、当前段/排队段取消时回执finished。回执仅包含type和四个身份字段，不回传WAV/volume。自然结束重复回执幂等无效；旧片段回执只能释放同一个ID，不能清掉后继片段。

WS入口验证当前会话代际和角色，再核对完整片段身份。取消立即清当前session的占用；音频连接关闭只由仍拥有注册连接的socket清理，避免旧连接关闭影响后继。没有回执时按已下发音频总时长加10秒容差惰性过期，不设永久busy锁。该容差不是用户停声目标，也不是任意设备停滞下仍可无限保持的承诺。

前端的语音音频帧校验会话、角色和不低于已接收音频generation；解码前后的playbackEpoch守卫继续防止取消中的异步结果重新开始播放。本增量没有把ws/audio全部状态事件迁移为强类型，也没有证明所有晚到无身份状态帧均被拒绝；相关缺口继续保留在交付审计。

## 验证

- `engine/tests/test_playback_ownership.py`六项：下发结束仍占用时开关两种VAD行为、后继/跨角色/跨会话/重复回执、丢回执期限、生产下发函数成功与发送失败。
- `scripts/diag/voice_playback_receipts_test.cjs`执行生产composable（仅测试注入私有socket）：队列未空时tts:end不释放，逐段完成与取消、身份拒绝、坏WAV释放，回执最小字段。
- `voice_input_lifecycle_test.cjs`、`avatar_expression_baseline_test.cjs`继续通过。
- 真实Electron内WebAudio+localhost WS场景见`docs/plan/avatar-playback-ownership-browser-live.json`：Hiyori/Hotaru隔离测试配置各自然结束、下发完后VAD打断，共四场通过。调用生产下发函数、VoicePipeline和临时转译生产composable，使用静音WAV与明确的合成非零口型包络；没有采麦、调用云端或切换正式角色模型。VAD触发到结束回执21.19/14.73ms是本地fixture链路，不是用户开口到物理停声。
- 在engine工作目录执行完整pytest：969 passed，96.99秒。前端typecheck/build通过；新增Python文件Ruff通过。根目录先前一次全量为966 passed/1 skipped，不混用作正式工作目录基线。

## 实机与后续限制

已重启引擎并刷新原有renderer，未新建桌宠实例；Hotaru真人复验已反馈“打断效果已经很不错了”，修复后原始记录为`docs/plan/avatar-barge-in-user-after-playback-fix.json`，不覆盖旧失败。结束读回原barge_in=false、麦克风关闭。用户最新问题转向首句TTS返回不稳定，仍需独立排查，不能由打断听感外推完成。

当前仍需分别观察VAD确认耗时、播放期能量门槛/自听，以及设备缓冲。没有用户开口起点与声学停声采集，不给出全链路停声P95；不通过单纯降低阈值规避占用状态问题。固定待机、单击池、两角色音色和注视优先级本次未改。
