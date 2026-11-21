# S31 — 管理 UI（调试台：记忆洞察 / 任务 / 人格基线）

> 状态：**已完成**（2026-09-13）。
> 来源：S17/S26/S28/S29/S30 的后端能力已齐，缺的是**看得见的界面**。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 31
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    管理 UI —— 把"它记得什么 / 在做什么 / 人格几分"搬到界面上
SURPRISE: 调试台里一眼看到它在替你做什么（含待你点头的计划）
ARCHITECTURE（纯前端接线，零引擎逻辑改动）:
  调试台 DevApp 新增两个 tab：
    · 运行状况 › 人格基线（BaselinePanel.vue）
    · 调教   › 任务（TaskPanel.vue）
    · 记忆页追加 记忆洞察（MemoryInsights.vue）
  api.ts 补齐 11 个接口 + 类型；所有请求走 /api 前缀（debug router）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 顺带修掉的两个真 bug（本次才暴露）

1. **桌宠窗口的 API 前缀写错**：debug router 的前缀是 `/api`，而 S23/S29 在
   `App.vue` 里写成了 `/debug/...` → **表演库（Alt+G）与计划审批卡片的网络调用全部 404**。
   这两个功能"看起来实现了"，实际点下去是静默失败。
2. **任务视图字段覆盖**：`{"status": "ok", **_task_view(task)}` 中 `_task_view` 的 `status`
   会覆盖外层的 `"ok"` → 改用 `task_status`（前端类型同步）。

> 两条都属于"不接 UI 就发现不了"的类别 —— 后端测试全绿、前端 typecheck 全绿，
> 但真正点一下才知道不通。这正是 S31 的价值。

## 交付报告（2026-09-13 完成）

### Changed files

**新增**（前端）：
- `shell/.../dev/components/TaskPanel.vue`（任务列表 + 待批准计划的批准/拒绝/重试）
- `shell/.../dev/components/BaselinePanel.vue`（场景集 + 跑基线 + 报告 + 失败明细）
- `shell/.../dev/components/MemoryInsights.vue`（三通道计数 / 关系记忆 / 显式记忆管理 / 归纳）

**修改**：
| 文件 | 改动 |
|---|---|
| `shell/.../dev/DevApp.vue` | 新增 `baseline` / `task` 两个 tab（导航 + 描述 + 页面挂载）；记忆页追加 `MemoryInsights` |
| `shell/.../dev/api.ts` | 11 个接口（showcase / relationship / consolidate / explicit 列表与删除 / task list+approve+reject+retry / eval scenarios+run）+ 相关类型 |
| `shell/.../App.vue` | **修 bug 1**：`ENGINE_HTTP + /debug/...` → `ENGINE_API + /api/...`（3 处） |
| `engine/yuiro/debug_api.py` | **修 bug 2**：`_task_view` 的 `status` → `task_status` |
| `engine/tests/test_debug_api_panels.py` | **新增** 10 个契约测试 |

### 冒烟证据

```
$ pytest tests/test_debug_api_panels.py -q
..........                                                     [10 passed]

$ pnpm typecheck
（无输出 = 通过）

全量回归：358 passed / 5 failed / 1 error（失败集与基线一致）
```

### 契约测试覆盖（前端依赖的接口）

- `GET /api/task/list` → 外层 `status == "ok"`、条目用 `task_status`、`steps` 为字符串数组；
- `POST /api/task/{id}/approve?steps=A|B|C` → 改写步骤生效；重复批准返回 `error`；
- `/reject` → `cancelled`；`/retry` → `attempts` 递增；
- `GET /api/eval/personality/scenarios` → ≥20 条且含分类统计；
- `POST /api/eval/personality?live=false&limit=3` → 报告含 `prompt_hash` / `by_category`；
- `GET /api/memory/relationship` → `days_known` / `summary`；
- **未装配时的 warn 路径**（前端据此显示提示而不是崩）。

### DoD 对照

- [x] 调试台可见"它在做什么"（含待批准计划，可批准/拒绝/重试）
- [x] 调试台可见"它记得什么"（三通道计数 + 关系记忆 + 显式记忆可删 + 归纳按钮）
- [x] 调试台可跑人格基线（离线自检 / 真跑 + 分类通过率 + 失败明细）
- [x] 修复两个真 bug（API 前缀 / 字段覆盖）并有契约测试护栏
- [x] 前端 typecheck 通过；全量回归失败集未变

### Human Acceptance（待人工）

1. 打开调试台 → 左侧「运行状况 › 人格基线」→ 点「开始跑」（先不勾"真跑"）→ 应看到通过率与分类条；
2. 左侧「调教 › 任务」→ 让桌宠提交一个计划（"帮我整理整个下载文件夹"）→ 回到这里应看到**待批准**卡片，点「按这个来」；
3. 左侧「调教 › 记忆」→ 页面下半应出现「记忆洞察」：三通道计数、你们的认识天数、你要求它记住的事（可「忘掉」）；
4. 桌宠窗口按 **Alt+G** → 表演库应真的列出来（这是 bug 1 的验收点）；
5. 桌宠窗口做一次计划确认 → 点「按这个来」应成功（不再是静默失败）。

### 风险 / 遗留

- **未做视觉回归**（无截图基线）：布局改动只能靠肉眼；
- **计划编辑 UI 未做**：改写步骤目前只能通过 API（`steps` 用 `|` 分隔）或让 LLM 重提；
- **基线报告未落盘**：每次跑完只显示当前结果，没有"历史上多次基线的趋势图"；
- 记忆洞察与既有 `MemoryManager` 有轻微功能重叠（前者偏"洞察"，后者偏"编辑"），
  暂不合并（合并需要重构既有组件，收益不抵风险）。
