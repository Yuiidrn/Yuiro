# G0 原始证据索引

对应 `../G0-realtime-baseline.md`，2026-10-23，HEAD `e2af077b03f204a4394b9eaedc530f4d337c4c9e`。

- `environment.json`、`package-versions.json`：环境、白名单 TOML 与包版本，无凭证；不代表活跃服务状态。
- `source-hashes.json`、`source-integrity.json`：236 个既有源文件的扫描和采样前后完整性。
- `source-landmarks.json`：9 个关键 Python 模块的 AST 符号及行号。
- `pytest.xml`、`regression-summary.json`：本轮 772 项回归原始结果及分文件汇总。
- `synthetic-latency.json`：30 次 fake 依赖下的真实编排管线回调采样；真实热启动样本为 0。含旧 Agent adapter 引用行为诊断。
- `frontend-race.json`：抽取真实 playOne/stopPlayback 函数，受控 decode 迟到导致 lateStarts=1；不是完整浏览器测试。
- `shutdown-characterization.json`、`main-f821.json`：真实 teardown AST 的隔离异常和限定范围的静态诊断。
- `live2d-inventory.json`：8 份 model3 的实际引用、时长、循环、参数和 JSON 哈希；不是模型二进制完整认证。
- `live2d-slot-candidates.json`：实际 TS 候选推断，不包含人工审定，也不替代 profile。
- `effective-avatar-profile.json`：当前生效 profile 配置快照；不代表视觉效果通过。

前端 typecheck/build 的本轮退出状态与输出摘要记录在主报告；未保存完整构建控制台日志，不伪装为此目录中的自动验收文件。复跑会覆写文件，应先归档；诊断成功运行与被诊断功能安全通过必须分开看。
