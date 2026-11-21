# G0：测试分层与阶段效果（2026-10-23）

本文件解释统一 Goal 的体验收益，并登记测试精简实验。实施仍停留在 G0。

## 测试精简：精简日常运行成本，保留契约覆盖

第一轮完整回归：772 passed，87.53s；`test_agent_memory.py` 两项累计约 56.99s。当前重新执行排除 `test_agentloop_memory_roundtrip` 的候选快测：**771 passed，1 deselected，27.63s**，见 `G0-live-artifacts/pytest-fast-candidate.xml`。相对前轮全量耗时减少约 68%，两次执行环境不同且本轮 Engine 同时运行，不能把差值全部当作该单项用例的精确耗时。

这项真实 BGE-M3 用例覆盖“闲聊不写情景记忆、真实语义召回、事实抽取”，并非可随手删除的重复测试。另一项 md5 用例验证重启持久化，保留在快测中；md5 不能代替真实语义检索。

建议按用途分层：

| 层 | 运行时机 | 内容 | 门禁 |
|---|---|---|---|
| 当前切片快测 | 每次局部迭代 | 修改模块及关联取消/权限/输出回归 | 不可跳过相关安全与时序护栏 |
| 常规全局快测 | 每阶段切片结束 | 771 项候选集 + shell typecheck/build（触及 TS 时） | 明示 1 项被排除，不宣称完整 772 |
| 真实模型集成 | Memory/embedding/依赖/检索改动，阶段交付与发布前 | 单独运行真实 BGE-M3 roundtrip | 模型不可用/skip 不算真实语义验收通过 |
| 实机体验 | 语音/模型/调度改动及发布前 | 真实 provider、设备、取消、两模型演出 | pytest 全绿不能替代 |

复现候选快测（engine 目录，先加载 `..\config\env.ps1`）：

```powershell
& ..\.env-local\engine-venv2\Scripts\python.exe -m pytest tests/ -q -k 'not test_agentloop_memory_roundtrip' --disable-warnings -p no:cacheprovider --durations=8 --junitxml=../docs/plan/G0-live-artifacts/pytest-fast-candidate.xml
```

单独真实语义用例：

```powershell
& ..\.env-local\engine-venv2\Scripts\python.exe -m pytest tests/test_agent_memory.py::test_agentloop_memory_roundtrip -q
```

本轮没有删除/合并测试，也没有修改默认 pytest 收集规则。后续可以加明确 marker 和快捷入口；先确定依赖覆盖关系，不能以“数量多”作为删测试理由。进一步耗时线索：快测中歌单合并 5.20s、首次 VAD 单测 4.06s、artifact 工厂 2.39s。前两项应先区分外部边界未隔离与首次导入成本；不要直接压低断言或把真实睡眠改成随机短 sleep。G0 不顺手重写这些测试。

## 每阶段能明显感受到什么

| 阶段 | 架构增量落点 | 对用户的显著改善 | 如何知道做到了 |
|---|---|---|---|
| G0 基线 | 原有入口旁路观测、固定资源与场景 | 卡顿能定位到识别、模型、合成或播放；知道哪些动作真的能用 | 有真实样本、失败证据和两模型检查记录；本阶段本身不承诺加速 |
| G1 归属与取消 | 现有 Session/Adapter/Agent 工厂与播放器 epoch | 说“停”或改口后，不会突然冒出上一句、旧动作或旧审批；设置更新作用于正在服务的对象 | 各异步阶段取消后旧结果不能恢复，实际本地停播有测量 |
| G2 输出调度 | 原有 VoicePipeline/TTS manager 上收敛文字、语音、Presence | 第一小句先说；长回复保序，主动搭话不抢声音，长时间等待不越攒越多 | 真实首音频对比、队列预算、播放回执；改善幅度由 provider 实测决定 |
| G3 模型档案与裁决 | 现有 manifest/profile/Avatar 与 SDK 播放边界 | 换 Hiyori/Hotaru 后用对动作；循环能退出，嘴型不被待机动作争抢，失败不会假装演完 | 两套资源有审定记录；Promise/结束/切换/嘴眼冲突回归通过 |
| G4 自然演出 | 同一演出管理器增加节奏、微动与冷却 | 思考时有细微回应，安慰不变成哭闹，成功反馈克制，重复对话有自然变化 | 六场景评分、正反例和 fallback；慢语音下动作不抢跑或补演 |
| G5 稳定发布 | 现有观测/回归上固定跨端验收 | 连续聊、切模型、断线重连后仍稳定，出现问题能复现并有序退出 | 每支持配置正式样本、冷启动与 60 分钟交互记录，无阻断缺陷 |

这些是分阶段验收的预期收益，不是当前已经实现的性能承诺。每阶段沿用现有 Runtime，按一个入口/一个场景迁移，避免一口气重写造成已用功能回退。
