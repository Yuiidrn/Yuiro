# 表情加载预约的取消与回落

Goal：表演结束回默认、切回当前表情或卸载模型后，不被旧异步加载重新覆盖。Scenario：慢加载表情A期间重置/选择当前B；旧A完成后仍保持最新指令。Architecture Increment：模型实例级SDK适配，仅撤销旧reserveExpressionIndex；沿用现有AvatarRuntime与表情加载，不增加事件、服务或资源。Tests：本机SDK原始ExpressionManager的确定性延迟加载、生产适配回归、类型/构建及真实双角色表情/回落。DoD：复现旧故障并验证reset/current/newer/dispose，实际模型回落证据与测试边界明确。

## 源码证据与修复

本机`pixi-live2d-display/dist/cubism4.es.js`中，`ExpressionManager.setExpression`在加载前写预约，加载后只比较预约索引；`resetExpression`未清预约。选择已是currentExpression的表情也会在更新预约前早退。因而旧请求可以在默认回落后重新应用。

新增`expressionRequests.ts`，在set/reset之前使旧预约失效，随后保留SDK原有加载及同索引优化。Live2DCanvas模型初始化时安装、unloadModel时撤销预约并恢复原方法。无需修改SDK包或模型资源；表情缓存照常保留。相同目标的并发请求仍可共享资源，本修复保证最新目标语义，不声称取消底层网络传输。

`scripts/diag/expression_requests_test.cjs`直接提取本机SDK类，注入可控制完成顺序的loadExpression。原始类复现reset后旧表情重新应用；适配后的reset、切回当前、更新为另一表情、dispose四类均拒绝旧加载。测试不复制setExpression控制逻辑。

## 验证

生产预约专项、眨眼顺序专项、Avatar基线专项及`pnpm --dir shell typecheck`、`pnpm --dir shell build`通过。真实双模型中性→表情→重置六阶段已通过，原始参数和截图见[实机结果](avatar-expression-request-reset-live/result.json)：Hiyori happy眼睛稳定0.55，Hotaru exp_bsmile01稳定0；两个角色重置后8.2秒采样均覆盖0–1且口型为0。主窗口已加载index-BNQm6MSm.js，Hotaru/idle/闭麦、采样器已清理，见[最终状态](avatar-expression-request-reset-live/final-state.json)。不把确定性SDK类测试称作真实网络慢加载测试。

本修复产生新构建。上一轮双角色各300秒证据保留为上一构建的有界稳定性记录，不自动外推到新构建。真人Hiyori麦克风/打断与自然度仍待用户方便，麦克风保持关闭。
