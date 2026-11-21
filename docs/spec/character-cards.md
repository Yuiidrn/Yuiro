# C0：双角色隔离与切换契约

用户优先项（2026-10-23）：先完成 Hiyori / Hotaru Shiomi，再继续 G1–G5。沿用单活跃角色的现有 Runtime，不启动两套引擎，不增加角色商店/创建器。

角色卡位于 engine/characters/<id>.toml；独立保存 llm、tts、persona（含表现映射）、language、agent、context、memory。server、设备/VAD/ASR、安全权限、系统工具、用户日记及通用开关共用。凭证保持现有 keychain，不复制进角色卡；两角色可共用服务凭证，模型/端点配置独立。

首次初始化保留当前角色所有设置及旧数据库，不覆盖用户文件；另一个角色只生成可编辑初值，不冒充审定人设/音色。角色 memory/relationship/task/eventlog 独立；用户日记仍共享，切换时刷新其 LLM/memory 绑定。历史数据不自动复制给另一个角色。

切换必须串行：验证并准备目标 → 旧角色停播/取消/等待在途工作 → 应用统一 factory/Registry/输出与 Avatar 配置 → 提交 active 指针 → 通知 renderer。失败不提交 active，恢复原配置与引用；无法安全收敛则拒绝切换。角色切换不宣称撤销已发生的外部副作用。

调试台头部始终显示当前角色，所有角色页在切换后重新挂载，不携带旧草稿；保存请求携带 character_id，旧窗口/迟到保存返回 409。表演候选按当前 model3 加载，异步结果必须受 revision 约束；Agent 的语义表演不直接依赖具体 Live2D 索引。未知资源不继承 Hiyori 的表情名。

角色切换事件包括 id/revision/model_path；renderer 立即停旧声音、清旧会话及表现，再加载当前模型。模型首次加载和远端首次合成可能冷启动，不能承诺零延迟。DIY 只预留 store/list/resolve 接口，无任意文件路径导入或脚本执行能力。

验收：A→B→A 独立持久化；启动恢复 active；角色/共享设置边界；非法 id 与旧保存拒绝；准备/提交失败回退；旧输出不复活；两个角色表演选项不串；真实模型视觉与切换速度另做实机验收。
