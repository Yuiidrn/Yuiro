# 当前候选双角色自然语言联动实测

Goal：用真实Agent→Avatar→TTS链路复验此前局部修复能够一起运行。Scenario：正式切换Hiyori→Hotaru，各发送“请向我打个招呼，配合一个合适的小动作，只回复一句话。”，不在话术中指定工具名；不采麦，最终恢复Hotaru。

Architecture Increment：本轮没有生产架构改动，只新增可复用的有界实机诊断与证据。Tests：Agent意图及对应started回执、实际模型路径、说话状态/口型prop、语音帧session/generation、正常收尾与配置一致性。DoD：原始观测落盘，结论限制到此次文本链路，不替代真人麦克风、听感或全套动作语义审定。

原始证据：[avatar-dual-natural-current-live.json](avatar-dual-natural-current-live.json)。脚本`scripts/diag/avatar_dual_natural_acceptance_live.py`使用调试台正式角色选择入口，刷新后监听真实控制WS元数据并采样实际桌宠组件。只记录回复字数、身份、回执与状态，不保存正文、音频、密钥或WS鉴权URL。两次请求经过正常会话流程，未绕开Agent/记忆；可能产生通常的互动记忆。

| 检查 | Hiyori | Hotaru |
| --- | --- | --- |
| 实际模型 | hiyori/Hiyori.model3.json | Hotaru Shiomi/016_casual_spring_01 |
| Agent演出 | source=agent、performance=greet | source=agent、performance=greet |
| 实际动作采样 | Idle#6 | Motion#4 |
| 对应意图started回执 | 有 | 有 |
| 真实语音帧 | 1块，非HTTP分块 | 12块，HTTP分块 |
| session/generation匹配 | 全部匹配 | 全部匹配 |
| speaking与非零mouth prop | 有 | 有 |
| 最后idle、mouth=0、until=0 | 通过 | 通过 |
| 配置前后一致 | 完整配置JSON在内存比较相同 | 完整配置JSON在内存比较相同 |
| 可见状态采样 | 46个，均visible | 44个，均visible |

这一轮把此前独立的资源抽查与Agent调用接起来：Hiyori的greet确实落到刚抽查的Idle#6，Hotaru落到Motion#4。不能据此声称所有表演映射均已正确。Hiyori固定待机偏好未改，预览/招呼没有重新启用随机Idle。

调试器观察到Agent招呼意图约4227.0/1596.1ms，首音频帧约13529.3/5819.9ms（Hiyori/Hotaru）。这些是包含LLM、工具轮、出口翻译、供应商及观测延迟的单次文本请求时间，不能作为物理首音、TTS独立耗时、P50/P95或角色间性能结论。mouth prop变化只补齐当前候选的绑定链路，不取代此前core参数验证或声学同步测量。

原运行检查已覆盖意图、回执、身份、说话、回落和配置；随后从原始samples补核对finalMouthZero、modelMatchesRole、visibleSamples，记在postRunRawChecks，不伪称额外供应商重测。诊断源码也补入前两项供未来复跑。结束恢复Hotaru并刷新，真人自然度反馈尚未收到，不能标为已通过；Hiyori真实麦克风/打断仍待验。

新增诊断Ruff通过；本轮未修改生产代码，前端沿用上一轮已通过的构建，后端沿用1000项回归基线，没有为新增诊断无故重跑全部测试。未改捕获保护、背景、角色配置或开麦状态。
