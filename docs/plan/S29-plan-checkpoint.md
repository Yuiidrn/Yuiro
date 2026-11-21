# S29 — Plan 审批 + Checkpoint + 失败恢复（Era 4 Act 深化）

> 状态：**进行中**（2026-09-13）。
> 来源：`docs/spec/roadmap.md` Wave 5 留白（`TaskPlan / Checkpoint`）+
> `architecture-goal.md` §3.7 的审批分层 LEVEL 4（"批量整理用户文件 → plan approval"）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 29
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Plan 审批 + 失败恢复 —— "它能帮我做完一件事"的最后一环
SURPRISE: 大动作之前它会先给你看计划；做砸了它会换方法再试，试不动就如实说
ARCHITECTURE:
  A. Plan 审批：TaskStatus.PENDING_APPROVAL
       plan() → 待批准（不可推进）→ approve(steps=可改写) / reject
       LLM 侧：task_plan 工具（语义判断"该先问一声"）
  B. 失败恢复：TaskStep.attempts / last_error
       retry() → attempts+1（换思路）→ 达 max_attempts 判定 FAILED
       LLM 侧：task_retry 工具
  C. Checkpoint（轻量）：summary() 携带恢复线索
       "计划待确认" / "当前步骤已尝试 N 次（上次失败：…），请换思路"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 设计取舍

| 决策 | 理由 |
|---|---|
| **新增 `task_plan`，而非改造 `task_create`** | 默认行为零变化（回归安全）；由 LLM **语义判断**"这件事要不要先问一声"，而非硬开关 |
| 批准时**可改写 steps** | 用户"改一下再执行"是真实需求（spec 的 plan approval 本来就含修改） |
| `advance` / `retry` 在待批准时**直接报错** | 审批是硬边界——批准前动手就失去了审批的意义 |
| Checkpoint 走**摘要**而非二进制快照 | 执行主体是 LLM：它需要的不是内存快照，而是"卡在哪、试过几次、为什么失败" |

## 交付报告（2026-09-13 完成）

### Changed files

**新增**：`engine/tests/test_task_plan.py`（17 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/task/models.py` | `TaskStatus.PENDING_APPROVAL` + `awaiting_approval`；`TaskStep.attempts/last_error`；`summary()` 携带恢复线索（"等待用户确认" / "已尝试 N 次（上次失败：…），请换思路"） |
| `engine/yuiro/task/runtime.py` | `_create_task`（create/plan 共用落盘）；`plan()`；`approve(approved=/steps=/note=)`；`retry()`（attempts+1 → 超限 `fail`）；`advance/retry` 的审批保护；`list_all()`；`max_attempts` 参数；`task.planned` 事件带 steps |
| `engine/yuiro/tools/task_tool.py` | **新增** `task_plan`（提交计划待确认）与 `task_retry`（换思路重试）工具；`TASK_TOOLS` 6 项 |
| `engine/yuiro/main.py` | 订阅 `task.planned` → 推壳层 `task:planned`（人工确认环节） |
| `engine/yuiro/debug_api.py` | `GET /task/list`（含待批准）+ `POST /task/{id}/approve`（`steps` 用 `\|` 分隔可改写）+ `/reject` + `/retry` |
| `shell/.../App.vue` | **计划审批卡片**（goal + 步骤清单 + "按这个来 / 先别做"） |

### 冒烟证据（4 个场景）

```
PLANNED: pending_approval | steps: ['列清单', '按类型归档', '生成报告']
BLOCKED: 计划尚未获用户批准，不能推进（先等用户确认）
SUMMARY(planned): 状态：计划已提交，**等待用户确认后才可执行**（不要提前动手）
APPROVED: running | steps: 4                  ← 批准时改写步骤生效（3 → 4）
RETRY 1/2: running | attempts 1/2             ← 换思路重试
RETRY 3: failed | attempts: 3                 ← 超限判失败（不再无限重试）
SUMMARY(failed): 注意：当前步骤已尝试 3 次（上次失败：第 3 次：文件被占用），请换思路…
EVENTS: ['task.created', 'task.failed', 'task.planned', 'task.retrying']
RESTART: running 0/4                          ← 重启后仍是待执行（可继续）
```

### 三个设计取舍

1. **新增 `task_plan` 而非改造 `task_create`**：默认行为零变化（回归安全）；
   由 LLM **语义判断**"这件事要不要先问一声"（工具 description 明确引导：
   影响大量文件/难以回退 → 先提交计划），而不是硬开关。
2. **批准时可改写 steps**：用户"改一下再执行"是真实需求。
3. **Checkpoint 走摘要而非二进制快照**：执行主体是 LLM，它需要的不是内存快照，
   而是"**卡在哪、试过几次、为什么失败**"。
4. 补齐了**人工确认链路**（否则功能断链）：引擎 `task.planned` → 壳层卡片 → 点击 → `approve`。

### Tests

- 新增 **17 个**全部通过（含"批准前不可推进"、"改写步骤"、"超限判失败"、
  "换思路后 attempts 归零"、"重启后仍待批准"）；
- 全量回归 **331 passed / 5 failed / 1 error**（失败集与基线一致）；
- `task/`、`tools/task_tool.py`、测试文件 ruff 零告警；前端 `pnpm typecheck` 通过。

### DoD 对照

- [x] Plan 审批：`plan()` → `PENDING_APPROVAL` → 批准前 `advance/retry` 硬拒绝
- [x] 批准可改写步骤；拒绝转 `cancelled`；`task.planned` / `task.rejected` 事件
- [x] 失败恢复：`attempts` / `last_error` → 超 `max_attempts` 自动 `FAILED`
- [x] Checkpoint：摘要携带恢复线索（重启/换会话后可接着做）
- [x] LLM 侧工具体系（`task_plan` / `task_retry`）+ 人工确认 UI（壳层卡片）
- [x] 回归通过（S08 的 19 个任务用例全绿）

### Human Acceptance（待人工）

1. 对 Yuiro 说「**帮我整理整个下载文件夹**」→ 预期它先给出计划卡片（而不是直接动手）；
2. 点「**按这个来**」→ 它开始执行（日志 `[计划批准]`）；点「**先别做**」→ 任务取消；
3. 说「**按你列的做，但最后加一步清理空目录**」→ 它应改写计划（approve with steps）；
4. 故意让它做一件会失败的事 → 观察 `[任务重试]` 与摘要里的"请换思路"提示；
5. `GET /debug/task/list` 查看全部任务（含待批准）。

### 风险 / 遗留

- **无 plan 编辑 UI**：目前只有"批准 / 拒绝"两个按钮，改写步骤需通过 API
  （`steps` 用 `|` 分隔）或让 LLM 重新提交；
- 审批**无超时**：计划会一直等待（重启后仍待批准 —— 这是有意的，不算 bug）；
- `plan` 的触发依赖 LLM 判断（工具 description 引导），没有硬规则强制"多步必审批"；
  若需要强约束，可加配置开关（`[task].require_plan_approval`）；
- Checkpoint 是**摘要级**：不含外部资源的快照（如"已移动了哪些文件"）——
  真正的文件级回滚属 spec 的 `transaction.cpp`（Wave 5 另一条线，未做）。
