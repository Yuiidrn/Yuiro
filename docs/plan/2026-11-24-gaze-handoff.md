# 单击动作与鼠标注视交接

Goal / Scenario：动作结束时，脸部从动作姿态自然过渡到鼠标或待机姿态，减轻相反方向拉扯；Hiyori 与 Hotaru 保持各自注视设置。Architecture Increment：复用现有参数更新和动作调度，不新增 Runtime。Tests / DoD：交接参数速度受限、目标反向可收敛，构建通过；真实双角色视觉自然度仍需验收。

此前固定700ms混合在目标不断变化时仍强制结束；待机动作启动也会提前清除过渡。现在逐帧从上一帧呈现的参数追随实时目标，分别限制头部与眼球速度，待机接管保留过渡，新的高优先动作仍可接管；鼠标注视不再把头部 Z 轴拉直。眼球相对头部的目标响应提高一倍并限制最大值，沿用原角色幅度设置。

参考 [AIRI motion manager](https://github.com/moeru-ai/airi/blob/main/packages/stage-ui-live2d/src/composables/live2d/motion-manager.ts) 在参数更新阶段结合注视偏置和平滑控制的思路，未引入其驱动。`node scripts/diag/gaze-handoff-test.cjs` 覆盖同向、反向、中途目标改变、速度限制及收敛；pnpm typecheck/build通过。数值模拟并非真实 Live2D 或用户观感验收；尚未重启桌宠、尚未核对双角色实际动作末帧与鼠标交错。后续需在真实模型和不同光标位置观察，按反馈调整幅度和速度。

## 后续修正：单一注视写入

检查本机 pixi-live2d-display 的 Cubism4 更新顺序发现，SDK `updateFocus()` 已向头、眼、身体叠加 focus，本项目随后又在 beforeModelUpdate 写入注视。当前对模型实例关闭 SDK 的这一自动叠加，仍保留其 focusController 平滑，统一由项目更新注视；上下映射灵敏度提高。SDK 在渲染后会 loadParameters，故动作末帧不应在完成回调里直接读取 core 当前值；现保存 beforeModelUpdate 的实际渲染姿态，在注视接管、释放和动作结束时从该姿态过渡。

真实开发窗口移动鼠标有限检查：Hiyori 注视接管、静止后释放并恢复 Idle#0 通过；Hotaru 注视接管和释放通过，但原脚本要求 0.7 秒内必须进入 Motion#19，观察到动作为空，故整体断言失败，不能称 Hotaru 待机恢复通过。脚本恢复鼠标及原角色。模拟测试新增上下方向断言，typecheck/build通过；未完成真实动作结束与相反鼠标方向的参数/视觉采样，用户体感仍需确认。
