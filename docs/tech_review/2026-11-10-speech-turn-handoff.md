# 语音作用域之外的文本入口也要交接输出

VoicePipeline内部取消epoch与前端旧状态护栏不能代替入口编排。普通文本worker以前只cancel旧文字朗读，旧语音合成和主动发言仍可能继续占用服务；统一_cancel_turn传播到VoicePipeline时，又遗漏独立登记的_reply_speak_tasks。

本次复用既有interrupt和RuntimeRegistry补接线：文本回合只交接语音输出，快照并取消/join自己的旧producer，等停止通知后才进入Agent；统一取消同时取消文本朗读，但先派发语音停止再join HTTP清理。这样保留低延迟打断，也避免新回合提前启动后被迟到停止通知误伤。没有为普通文本取消用户的持久Task/Plan，也没有引入第二套Session generation。

interrupt原本fire-and-forget，现在额外返回已派发通知的Task：无需等待的既有调用不变，需保证交接顺序的入口显式等待。producer按会话快照，其他会话不受影响，父取消仍传播；return_exceptions仅收集已被我们取消的子任务结果，不吞父任务CancelledError。

验证直接执行工作树生产函数和实际嵌套chat_worker，使用真实VoicePipeline与可控合成/通知门闩，证明旧资源释放和Agent启动顺序。RuntimeRegistry真实适配器路径与fallback均覆盖；Electron/WebAudio四隔离夹具复验。具体证据和剩余边界见[计划](../plan/2026-11-10-speech-turn-handoff.md)。

尚未凭这些测试断言所有媒体/日记入口均已统一交接，也未证明真人双角色重叠听感。provider若违反取消契约可能阻塞交接，应作为后续接入验收问题暴露，不能偷偷让新输出越过未释放的旧任务。

## 当前候选真实链路复验

后续经正式角色选择入口实测Hiyori→Hotaru，用不含工具名的自然招呼话术触发真实Agent。两角色均出现source=agent/greet、匹配started回执、正确模型路径、speaking与非零口型prop、最后idle/零口型；配置前后相同。Hiyori实际Idle#6、Hotaru Motion#4，接上了本地动态资源抽查的具体动作。它证明当前配套候选的普通文本进入、演出和真实TTS能够一起运行；仍不是语音/文本交叠抢占、麦克风或声学听感的额外证明。

该轮用CDP元数据与实际组件采样，未保存正文/音频/鉴权URL。观察首帧时间包含全部上游环节且有观测偏差，不作为TTS独立性能或P95。详见[完整原始证据及范围](../plan/2026-11-10-avatar-dual-natural-current.md)；人工自然度未收到反馈时仍保持待验。
