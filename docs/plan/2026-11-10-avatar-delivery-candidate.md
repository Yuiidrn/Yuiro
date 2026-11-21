# Live2D自然交互：候选收敛与剩余验收

Goal：按原六阶段范围审计当前候选，不用旧样本或局部fixture替代整体完成。Scenario：两角色正式换角、当前构建持续待机；与已完成的状态联动、仲裁、取消、资源和真实语音证据逐项对齐。Architecture Increment：本轮不改生产代码，冻结候选并核对交付。Tests：相关生产专项、当前构建双角色各300秒可见待机、源码/产物哈希复核。DoD：有完整候选指纹和有界结果；人工/声学/语义缺口保留，不宣称整体完成。

## 候选证据

[指纹](avatar-delivery-candidate-manifest.json)覆盖545个生产Python、TS/Vue/CSS、构建文件及Live2D JSON资源，不含凭证/配置/运行数据/纹理。[专项汇总](avatar-delivery-candidate-regression.json)记录本轮九个相关生产函数/composable专项的命令、退出码和原始输出，均通过。此范围不等于全仓库lint或后端全量。

双角色各300秒当前待机采样已通过，545个所列文件前后哈希完全一致。采样期间没有重建/重载或修改生产文件；rAF间隔不等于GPU耗时或语音延迟。

## 原六阶段逐项审计

| 阶段 | 当前证据 | 未证明/待完成 |
| --- | --- | --- |
| 1.资源与基线 | 两套真实清单、80张缩略图；六段真实动态抽查；实际眼睛/口型参数验证；安抚默认悲伤动作误推断已撤销 | 全部80个动作的动态语义未逐个审定，comfort默认sad表情的场景适配仍待确认；真实事件→画面/供应商端到端指标缺少完整前后分位数 |
| 2.衔接与生命周期 | 持续/临时表情恢复、SDK finish与循环兜底、动作/表情加载迟到回调失效；真实单击和重叠意图回放，Hiyori固定Idle#0 | 全套资源/长期多种混合交互不能由少数动作回放外推；当前候选持续观察本轮补证 |
| 3.状态感知微反应 | 四态由本地播放事实驱动；首段等待/空结果已补；真实App入站fixture双向换角六场景；Hotaru真人语音与打断历史已通过 | Hiyori真人麦克风、打断仍待；供应商欠载后持续语音的听感和真实首句分位数未完成 |
| 4.分层仲裁与同步 | 真实眼睛/眨眼顺序、动作+合成口型参数；注视接管/归还；重叠优先级与旧计时器隔离；身份/epoch/请求与回执边界专项 | Hotaru注视已有用户通过，Hiyori固定待机后的主观衔接尚未确认；声学口型和物理停声指标不能由props或WebAudio时钟替代 |
| 5.角色风格与调试 | 按角色模型存储参数、单击池、预览/分类/缩略图；正式两向换角、语音设置同步与draft保护；各意图选中资源/状态可观测 | 未审定语义保持待验，不能恢复将哭泣文件名等同安抚；需要后续用户自然度反馈决定定稿风格 |
| 6.真实演出验收 | 原生鼠标点击/注视、真实Agent/TTS招呼、说话中换角、Hotaru真人打断已有各自证据；本轮当前候选持续观察 | Hiyori真人录音/打断与自然度、完整端到端P50/P95、混合语音压力/多小时稳定性未证明；不以300秒待机代替 |

原始六阶段见[live2d-expression-evolution.md](live2d-expression-evolution.md)，逐项证据索引见[live2d-acceptance-audit.md](live2d-acceptance-audit.md)。本表不撤销原范围、不添加新的Runtime架构任务。

## 后续验收边界

用户明确暂不方便人工参与，保持闭麦，不自动请求重复准备确认。下一轮人工参与时才做Hiyori实际讲话→回复→说“停一下”、固定待机/注视衔接反馈；完成后仍需真实供应商首句/物理停声多次测量与资源语义定稿。这里列的是尚未完成的要求，不能被自动fixture改名为已完成。

本轮冻结不代表以后不能修缺陷；若新证据要求改动，记录新候选及相称验证，不借用此指纹或旧构建结果。

## 当前候选持续运行结果

[原始记录](avatar-delivery-candidate-idle-soak.json)、[断言汇总](avatar-delivery-candidate-idle-summary.json)、[结束状态](avatar-delivery-candidate-final-state.json)。当前主窗口资源为`index-DqEO7Ugf.js`。

| 角色 | 时长/状态采样 | 画布最小非空像素/不同alpha哈希 | 绘制边界眼睛范围 | rAF间隔P95/最大 | 动作 |
| --- | --- | --- | --- | --- | --- |
| Hotaru | 300.15秒/300次，全部可见且idle | 312/299 | 0–1 | 6.2/24.3ms | Motion#19 |
| Hiyori | 300.09秒/300次，全部可见且idle | 269/300 | 0–1 | 6.2/7.4ms | 仅Idle#0，允许间歇无动作 |

画布按80×100采样；alpha变化只支持持续视觉更新，不支持自然度结论。眼睛阈值闭合转换包含动作控制，不作为SDK精确眨眼次数。最终Hotaru/idle/闭麦，帧与原生眼睛采样器均清理。

可复跑断言：`.env-local/engine-venv2/Scripts/python.exe scripts/diag/avatar_candidate_idle_report.py --soak docs/plan/avatar-delivery-candidate-idle-soak.json --manifest docs/plan/avatar-delivery-candidate-manifest.json --output docs/plan/avatar-delivery-candidate-idle-summary.json`。该诊断Ruff通过，仅验证候选与有界待机，不能把原目标整体标为完成。

本轮没有生产修改，相关类型/构建沿用该候选上一轮通过记录，后端全量沿用1000项通过记录且不声称本轮重跑。当前候选的自动交付证据已集中；下一步仍以表中未完成项为准，不靠反复新增小专项代替人工/真实端到端验收。

[冻结候选后的Fish供给采样](2026-11-10-fish-current-candidate-sampling.md)：三次真实首块1.72–3.32秒且存在整句接收13.75秒慢样本，生产545指纹未变。补强“供应商/端到端稳定性仍待验”的证据，不能以自动播放器回放替代。
