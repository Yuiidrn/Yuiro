# S48 · 崩溃恢复的副作用分级（方案 D）

> 关联：[S47](S47-engine-optimization-audit.md)（B4 turn 级 checkpoint 的续作）、
> `docs/spec/architecture-goal.md`（Capability / Policy）
> 前置：S47 的 `TurnJournal`。
> **本 Sprint 只做"记录 + 建议"，明确不做自动执行**（见 §4）。

---

## 1. 为什么做

S47 的 B4 让"这一轮做到哪"第一次落盘（`turn.started` / `turn.step` /
`turn.completed`），并给出了 **replay boundary**。但它**没回答一个关键问题**：

> 崩溃恢复时，那些**已经执行过的工具步骤**该怎么办？

三个"一律"都不成立：

| 做法 | 问题 |
|---|---|
| 一律重放 | **放歌 / 发消息会重复**（外部副作用不幂等） |
| 一律跳过 | 读文件这类安全步骤也白丢了，用户还得从头说一遍 |
| 一律问用户 | **唠叨到没人看 = 没有防护** |

→ 必须**按步骤的副作用等级分级**。而这要求工具**自描述自己的副作用** ——
这本来就该有，属于"能力自描述规约"的一部分（同 S41 的 `options`、G7 的结果卡）：
**新增工具时顺手就得想清楚自己的副作用语义，而不是让恢复逻辑去猜。**

---

## 2. 交付物

| 文件 | 改动 |
|---|---|
| `tools/__init__.py` | `BaseTool.effect`（`""` = 未声明）+ `infer_effect()` + `resolve_effect()` + `ToolRegistry.get()/effect_of()` |
| `agent/turn_journal.py` | `step(effect=…)` 记录副作用；`ResumePlan` + `resume_plan()` + `_step_effect()` |
| `agent/__init__.py` | 记录 step 时写入 `effect=self._tools.effect_of(...)` |
| `debug_api.py` | `GET /api/turns`：回合级视图 + 未完成回合的 `resume_plan` |
| `tests/test_tool_effect.py` | 新建（9 条） |
| `tests/test_turn_journal.py` | +4 条（ResumePlan） |

---

## 3. 关键设计

### 3.1 三级副作用 + **保守推断**

```
read      只读（file_read / netease_search / …）      → 总是可重放
local     本地写（file_write / task_ / memory_ …）    → 重复通常收敛（覆盖写），可重放
external  对外影响（netease_play / app_open / …）     → **不可重放**
```

**认不出来一律当 `external`** —— 宁可多问一句，也不要静默重复放歌。

### 3.2 ★ 线索顺序即优先级

```
_EXTERNAL_HINTS → _LOCAL_HINTS → _READ_HINTS
```

**危险的先判**。否则 `netease_play_state` 这类名字会被 "state" 线索带成只读，
恢复时**静默重放** —— 正是要防的事故。（已有测试 `test_external_hint_wins_over_read_hint` 钉住。）

### 3.3 ★ 判太严和判太松是**同等严重**的 bug

**实测踩到**：初版 `effect_of()` 对**未注册**的工具直接返回 `external`
→ 于是"读个文件"也会被当成危险操作去问用户。
**这会让防护退化成噪音，最终被彻底无视。**

修法：未注册时**按名字保守推断**，而不是直接判危险。

> 这个 bug 是**双向测试**抓到的：只测"危险的工具能被认出"会漏掉它。
> 教训写在测试文件头部：**判断类功能必须两侧都测** ——
> 判太松是事故，判太严是噪音，而**噪音会让防护失效**。

### 3.4 旧事件兼容

S48 之前的事件没有 `effect` 字段 → `_step_effect()` **按工具名重新推断**。
既不能一律当危险（把老记录全吓一遍），也不能一律当安全（漏防护）。

---

## 4. 明确不做：自动执行续跑

现在只给**分级建议 + 询问文案**（`ResumePlan.question()`），
由上层（LLM / UI）决定是否执行。

**理由**：恢复涉及副作用，**先让人确认比自动重放更稳**。
而"要不要确认"现在有了依据（`ResumePlan.auto_safe`），不再是拍脑袋 ——
**这一步把一个哲学问题（能不能自动续）变成了数据问题（这步有没有外部副作用）。**

---

## 5. 验证

- 全量 **581 passed / 5 failed**（失败集自 S01 未变）
- 新增 **13** 个测试（工具副作用 9 + ResumePlan 4）
- `ruff` 对新改文件全绿
- `GET /api/turns` 可返回 `auto_safe` / `question` / `risky_steps` / `replayable_steps`

---

## 6. 遗留

- 给具体工具补**显式 `effect` 声明**（现在主要靠名字推断：够用，但不精确）；
- 前端展示 `ResumePlan`（接口已就绪，未接线）；
- 真正的自动续跑（见 §4）。
