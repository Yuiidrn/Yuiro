# Yuiro Goal 入口

当前主线：**稳定、低延迟、贴合现有 Live2D 资产的自然演出**。

实施原则：**延续现有 Runtime、局部重构、分阶段迁移**。目标中的 Coordinator / Controller / Director / Scheduler 是既有模块的职责收敛，不是另起框架的指令。模块映射见统一 Goal §2.5，每阶段边界与回归门槛见 §7.1。

## 执行入口

从 [统一架构与分阶段 Engineering Goal（2026-10-23）](2026-10-23-unified-architecture-engineering-goal.md) 开始。它是本目录当前阶段目标、范围、依赖顺序与验收标准的唯一维护入口。先完成 G0，再按 G1 → G2 → G3 → G4 → G5 推进；不要同时启动整套重构。

该文档是目标与实施契约，**不是已完成功能清单**。此次仅更新文档，阶段均待实施/验收。

现行 [架构规范](../spec/README.md) 和 [Coding Agent 协议](../spec/coding-agent-protocol.md) 继续约束生命周期、取消、安全、配置与工程流程。执行本次用户指定的收敛路线时，先将对应阶段的最小规范增量同步到 `docs/spec/`，再实现代码；旧路线中的长期扩展不作为本阶段额外前置条件。具体冲突处理见统一 Goal §1。

## 参考材料

- [2026-10-22 调研与源码证据](2026-10-22-small-kernel-realtime-performance-goal.md)：保留 pi、AIRI、Project Waifu 的固定版本、代码证据和取舍分析；其中旧 G0–G5 已由统一 Goal 替代，不再独立执行。
- [Yuiro Architecture Evolution Goal](Yuiro%20Architecture%20Evolution%20Goal.md)、[Yuiro Evolution Roadmap](Yuiro%20Evolution%20Roadmap.md)、[Yuiro架构改进](Yuiro架构改进.md)、[市面Agent参考](市面Agent参考.md)：历史战略来源，保留原文，不把其中的历史现状描述或示例 Prompt 视作当前事实和新增实施要求。

每阶段完成证据记录到 `docs/plan/` 的独立报告，并在报告中标明统一 Goal 阶段与任务 ID。不要在调研原文中追加第二套路线。
