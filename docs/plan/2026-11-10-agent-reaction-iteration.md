# Agent工具互动反馈迭代

Goal：Agent执行工具时有与真实状态对应的短反应，结果可辨且不串角色。Scenario：搜歌/检索/读文件开始关注，明确成功后轻快回应；待选择与失败保持克制；重复事件和密集工具不反复起舞，用户点击/显式表演优先。Architecture Increment：延续agent.activity与Live2DCanvas，补结果阶段/身份和本地反应规划；不改Agent决策循环/工具权限，不增加LLM或TTS请求。Tests：真实AgentLoop假工具场景、转发身份边界、前端决策与优先级、类型/构建、双角色本地整合。DoD：明确成功才正向反馈，缺资源安全回退，角色/会话/generation/取消隔离，调试台按角色启停/冷却/时长热更新。

TTS问题单独保留：真实Fish首段仍波动，本轮不以动画遮掩供应商延迟，也不宣称TTS已稳定。

## 已落地行为

- 真实工具批次开始与结果各发一次关联activity事件。明确成功才开心/短招呼，失败回中性、待选择保持思考；未知结果不触发成功反馈。
- 新增搜歌、推荐、检索、日记回顾、规划的thinking槽位建议。动作资源缺失或超过角色时长上限时仅表情。
- 消息携带session/generation/角色/revision并校验；换角/新回合重置本地反应记录。去重按批次/阶段，开始与结果分别冷却，避免同一工具重试反复起舞。
- 自动priority=2，不覆盖单击4或显式Agent表演3；排除avatar_perform的二次自动反应。
- 调试台「外观→互动节奏」新增独立开关、冷却和动作时长上限；Hiyori默认10秒、Hotaru14秒冷却，动作上限4秒。总交互状态反应关闭时同样不触发Agent微反应。

## 验证与当前状态

后端全量`pytest tests/ -q`：1011 passed，106.53秒；新增+相关专项18 passed。前端Agent反应planner、实际偏好composable角色隔离及Avatar基线专项通过；typecheck/build通过。新活动模块/新增测试/诊断Ruff通过。

[双角色实际主窗口回放](agent-reactions-live.json)：Hiyori关注→happy+Idle#6，Hotaru关注→happy+Motion#4；重复成功不重启、其他角色消息拒收、自动反应不覆盖高优先级用户表演，均通过。事件为本地fixture，后端真实结果处理由真实AgentLoop+假工具测试验证，未冒充真实工具/LLM服务全链。

[实际调试台控件](agent-reactions-controls-live.json)确认三个控件已加载。测试未改角色配置，未采麦或请求TTS/LLM，最后恢复Hotaru并移除全部回放钩子。新引擎已重启、新壳构建已加载。此轮新候选不沿用此前545文件指纹或300秒待机通过声明；未新做多小时压力或真人自然度验收。

TTS仍未彻底解决：本次未改供应商接入，继续保留[真实Fish采样](2026-11-10-fish-current-candidate-sampling.md)的1.72–3.32秒首块和13.75秒慢样本。此次改善Agent动画反馈，不等于供应商提速。

后续应继续审定更多资源的语义与组合，按用户自然度反馈调整节奏；避免仅增加随机动作。表演库原始元数据不能直接当作wire意图：Runtime会把有槽位时的空expression转为None，诊断/预览需要保留这一差别。
