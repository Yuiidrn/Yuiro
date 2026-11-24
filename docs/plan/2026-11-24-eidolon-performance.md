# 参考 eidolon 的表演管线增量

Goal：让角色对用户说话有自然、可靠的回应。Scenario：真实语音从聆听进入识别时，在角色具备合适资源的条件下轻点头；用户再次开口、角色开口或功能关闭后结束该反应。Architecture Increment：沿用 Presence、语义槽位、IntentLease 和 Live2DCanvas，不增加 Runtime，不更换口型或播放器。Tests：状态转移、冷却、动作占用及鼠标注视门控；类型检查、构建；真实角色动作和人工自然度待验收。DoD：不打断高优先表演、不强行使用缺失资源，不将合成完成误当实际播放。

## 参考对照与实施取舍

用户提供的 `D:/Project/Yuii/eidolon-sc-架构解析.md` 和 `D:/Project/Yuii/表演与语音管线-实现参考.md` 为参考材料。其 eidolon-sc 目标是 Spine 和 Pipecat；Yuiro 是 Live2D、现有 Session/Generation 与 WebAudio。借鉴语义意图、实际播放锚点、低优先级回应和丢弃迟到事件，不复制 Spine 内部技巧，也不直接采用参考中对 TTS、采样率、VAD、框架的假设。eidolon-sc 标注 AGPL-3.0，本次没有复制其实现代码。

现状已有 `presenceAfter`、模型清单与 `resolveMotion`、`IntentLease`、基于音频实际播放时钟的口型和 speaking 状态；不重复建设。新增聆听结束微反应：仅 `listening → thinking`，使用当前角色 nod 语义槽位，受现有短动作时长上限、冷却、表演占用、鼠标注视与角色配置限制；无槽位或动作过长时静默跳过。回应离开 thinking 即停止；说话微动作仅按明确 source 标识，避免把其他 priority=2 的表演误认为说话动作。

## 后续分阶段

1. 盘点两个模型 nod 资源及自然度，真实语音与连续说话、打断、单击优先级和换角验收；缺少合适资源时在角色映射中人工挑选，不自动随机替代。
2. 核对完整 reply / segment 身份是否贯穿生成、合成和播放；基于实际 WebAudio 排期设计段开始事件，优先复用现有流与取消协议，再考虑按段驱动表情。Fish WS 一轮多个句子共享 stream_id，不能将 stream_id 直接当句号。
3. 在真实段身份存在后实现情绪早到缓存、当前段更新、过期结果丢弃，保持无判定时当前表情；禁止预测音频开始或丢弃回合后触发表演。
4. 使用双角色素材对动作强度、持续时间和节奏做受控试演；必要时扩展角色独立槽位。性能和自然度以实际播放与人工观察验证，文档中的延迟目标不是本机实测。

## 本轮验证与限制

`node scripts/diag/avatar_listening_reaction_test.cjs` 与 `gaze-handoff-test.cjs` 通过；`pnpm typecheck`、`pnpm build` 通过。未进行真实麦克风或双角色动作自然度验收。

现有 `avatar_expression_baseline_test.cjs` 停在旧眼球幅度断言（预期0.2，当前0.4）；`avatar_tts_waiting_test.cjs` 的测试桩缺少近期 PlaybackAdmission 实现，无法启动。两项作为回归缺口保留，不能视为通过。
