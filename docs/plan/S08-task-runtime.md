# S08 — TaskRuntime MVP（跨多轮目标）

> 状态：**已批准开工**（2026-09-12，Human 授权外出期间自主连续推进）。
> 性质：Wave 5（P1）第一步。Task 是 spec 六个一等实体之一。
> 规范依据：`docs/spec/architecture-goal.md` §3.5、`docs/spec/target-file-preview.md` §3.9。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 08
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    TaskRuntime —— Agent 管一步，TaskRuntime 管"为什么/到哪了/下一步"
SURPRISE: 说"帮我整理下载文件夹"，Yuiro 会立个目标、分步骤、逐轮推进并记得进度
USER EXPERIENCE:
  - 多步目标被登记为 Task（目标 + 步骤清单 + 进度）
  - 之后每轮对话自动注入【当前目标】（进度/已完成/进行中/待执行）
  - 中断（重启/离开）后任务仍在，可继续（Task Journal 落盘）
ARCHITECTURE:
  - 新增 task/ 包：TaskStatus 状态机 + TaskStep/Task（含 Journal）+ TaskRuntime
    （create/advance/complete/cancel/fail + 落盘 + 重启恢复 + 事件）
  - ContextEngine 新增 task 分段（P_TASK=80，仅次于人设）→ AgentLoop 注入
  - 4 个工具：task_create / task_advance / task_complete / task_list（免审批）
  不做：LLM 自动规划器（PLAN 模式）、plan 审批流、checkpoint/resume 断点续跑、
        工具调用与步骤的自动绑定、Task 与 Subagent 协作
FILES:
  engine/yuiro/task/{__init__.py, models.py, runtime.py}（新增）
  engine/yuiro/tools/task_tool.py（新增）
  engine/yuiro/context/engine.py（task 分段）
  engine/yuiro/agent/__init__.py（task_runtime 注入 + 工具注册 + build 透传）
  engine/yuiro/main.py（装配 TaskRuntime）
  engine/tests/test_task_runtime.py（新增）
CODING AGENT:
  遵循 coding-agent-protocol：最小改动；不动既有工具行为；Task 失败不得影响主链路。
  禁止把 Task 与 Session 混为一谈（Session 管一次会话，Task 管一个目标）。
TEST:
  Unit：状态机（create/advance/complete/cancel/fail + 终态保护）/
        落盘与重启恢复 / summary_for_context 文案 / ContextEngine task 分段 /
        4 个工具的 schema 与 run 返回 / 终态任务不再注入
  + 全量回归（对照基线：5 failed + 1 error 不变）
DEFINITION OF DONE:
  - Task 可创建/推进/完成/取消，状态与步骤正确流转，终态不可再推进
  - Journal 落盘；新实例读同一目录可恢复未完成任务
  - 活跃任务经 ContextEngine 注入【当前目标】分段
  - 4 个工具注册可用（免审批），返回结构化 JSON
  - 回归通过（S06/S07 护栏不破）
HUMAN ACCEPTANCE:
  对 Yuiro 说"帮我一步步整理下载文件夹"→ 观察日志/工具调用中出现 task_create，
  回复里体现步骤；再问"我们刚才的任务到哪了"→ 能答出进度
NEXT UNLOCK: Wave 5 完整形态（PLAN 模式 + 审批 + Checkpoint）与 Wave 6 权限/沙箱
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 现状基线（S08 前）

- 仅存在 **AgentLoop 单轮/单目标**：每轮对话独立，无跨轮目标实体；
- 工具调用靠 `_MAX_TOOL_ROUNDS=3` 轮内闭环，**跨轮的目标会丢**（"你先列清单，等我看完再说"）；
- 无 Task Journal，重启/长时间中断后无从恢复"我们进行到哪了"；
- ContextEngine（S06）已具备分段与预算能力，但**没有 task 来源**。

## 交付报告（2026-09-12 完成）

### Changed files

| 文件 | 改动 |
|---|---|
| `engine/yuiro/task/{__init__.py, models.py, runtime.py}` | **新增**：TaskStatus 状态机、TaskStep/Task（含 Journal 与 summary）、TaskRuntime（create/advance/complete/cancel/fail + 落盘 + 恢复 + 事件 + prune） |
| `engine/yuiro/tools/task_tool.py` | **新增**：task_create / task_advance / task_complete / task_list（免审批，未注入 runtime 时降级 pending） |
| `engine/yuiro/context/engine.py` | `P_TASK=80`；`_collect_task` 分段；`build(task_summary=...)` |
| `engine/yuiro/agent/__init__.py` | `task_runtime` 注入 + `task_summary` 传入 build + `build_agent_loop` 注册 TASK_TOOLS |
| `engine/yuiro/main.py` / `debug_api.py` | 装配 TaskRuntime（`app.state.tasks`，惰性创建）并透传 |
| `engine/tests/test_task_runtime.py` | **新增** 19 个用例 |

### 冒烟证据

```
CREATE: task_87123ac9 0/3 | 列清单
ADVANCE: 1/3 running | 按类型归档
ADVANCE: 2/3 running | 生成报告
SUMMARY: 目标：整理下载文件夹 / 进度：2/3 / [已完成] 列清单（清单列好了（42 个文件）） / …
RESTORED: 2/3 3 journal 条                          ← 重启后恢复
[context] [smoke-se] 组装 4 段 / 估算 170 tokens（预算 6000）
          ｜system:1 / persona:76 / task:90 / user:3 ← task 段注入成功
SEGMENTS: ['SYS', '【人设前置铁律】…', '【当前目标】你正在帮用户完成一件事…', '继续吧']
```

### 环境发现（记录备查）

`pytest` 的 `tmp_path` fixture 在本机**不可用**：`C:\Windows\Temp\pytest-of-张建宇` 拒绝访问
（WinError 5）。本 Sprint 测试改用 `tempfile.TemporaryDirectory`（与项目其余测试一致）；
这也解释了此前 `test_migrations_idempotent` 的 PermissionError —— **属既有环境问题**。

### Tests

- 新增 **19 个**全部通过；全量回归 **134 passed**（S07 基线 115 + 19），失败集与基线一致；
- `task/`、`tools/task_tool.py`、`context/`、测试文件 ruff 零告警。

### DoD 对照

- [x] Task 创建/推进/完成/取消/失败，终态不可再推进（`ValueError`）
- [x] 全部步骤完成 → 自动 COMPLETED；Journal 每步追加
- [x] Journal 落盘 + 新实例读取同目录恢复（含 progress 与事件）
- [x] 活跃任务经 ContextEngine 注入【当前目标】分段（P_TASK=80）
- [x] 4 个工具注册可用（免审批），返回结构化 JSON；无 runtime 时降级
- [x] 回归通过（S06 等价性 / S07 显式记忆护栏不破）

### Human Acceptance（待人工）

1. 对 Yuiro 说"**帮我一步步整理下载文件夹**" → 日志出现 `[任务创建]`，回复里体现步骤；
2. 中间隔几分钟再问"**我们刚才的任务到哪了**" → 应能答出进度（`task_list`）；
3. 重启引擎后再问同一句 → 任务仍在（`[任务恢复] 已载入 N 个任务`）。

### 风险 / 遗留

- 未做 LLM 自动规划（PLAN 模式）与 plan 审批流；
- 工具调用与步骤未自动绑定（由 LLM 显式调 `task_advance`）；
- 无 checkpoint/断点续跑与 Subagent 协作；
- Task 与 Session 的绑定目前是"会话 → 最近活跃任务"的弱绑定。
