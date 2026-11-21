# 动作启动回调的请求归属

Goal：旧动作启动结果不再清理或通知新动作。Scenario：同一模型同一动作，第一次请求延迟失败，后一次已成功；或旧请求在表演取消后才完成。Architecture Increment：沿用现有modelRevision/motionRequestRevision，再给每次底层playMotion调用分配序号；不增加协议、不重写SDK。Tests：提取生产playMotion函数控制SDK Promise完成顺序，复现旧代码清空新动作；验证重复动作、取消、换模型、旧拒绝和当前失败。DoD：旧回调不能写状态/调用onStarted，当前回调保持原行为，类型/构建及相关Avatar回归通过。

源码发现：playMotion的settle只检查modelRevision，先清理同组同索引状态，再调用带上层request检查的onStarted。因此上层检查发生得太晚；相同资源不代表相同请求。

本轮为请求归属修复，不声称改善实际动作启动延迟或完成全部自然度验收。麦克风保持关闭。

## 验证结果

- `node scripts/diag/motion_start_ownership_test.cjs`通过：原始模型单检查复现旧失败清空新动作；新增生产函数验证全部场景通过。
- `node scripts/diag/avatar_expression_baseline_test.cjs`通过；`pnpm --dir shell typecheck`及`pnpm --dir shell build`通过。
- 构建工作台真实Hiyori Idle#7与Hotaru Motion#0，正常结束/显式取消共四场景回落通过，见[原始状态](avatar-motion-start-ownership-live.json)。该实机验证是SDK正常生命周期回归；延迟失败竞态由前述生产函数可控Promise专项验证。
- 主窗口已加载`index-BSDbt4w7.js`，恢复Hotaru/idle/闭麦，见[最终状态](avatar-motion-start-final-state.json)。没有启动新桌宠实例、调用云端、改角色配置或捕获保护。

最新构建仅完成本轮专项及短时实机，不挪用此前300秒记录。没有重跑后端全量；后端无改动。Hiyori真人麦克风/打断、自然度及端到端声学指标保持待验，整体目标继续。
