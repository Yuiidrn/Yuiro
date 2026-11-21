# S26 — Relationship Memory（Era 3 Relate）

> 状态：**已完成**（2026-09-13）。
> 来源：`docs/spec/README.md` 的配套区分（不得混用）：
> `Conversation Memory = 用户和我聊了什么` / **`Relationship Memory = 我们之间发生过什么`**。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 26
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Relationship Memory —— "我们之间"
SURPRISE: 它会记得你们认识多久、一起做成过什么（而不只是"记得你说过的话"）
ARCHITECTURE:
  RelationshipMemory（JSON；无 sqlite / 无 embedding）
        │  note_interaction / note_task_completed / note_explicit_memory
        ▼
  summary() ──▶ ContextEngine【我们的关系】(P_RELATION=72；always-on，不检索)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 关键设计：为什么它**不该**进检索层

| | Conversation Memory | Relationship Memory |
|---|---|---|
| 内容 | 对话与事实 | 关系事实（认识多久 / 聊过多少次 / 一起做成过什么） |
| 规模 | 大且持续增长 | 极小（几十字节，稳定） |
| 取用 | 语义检索（RRF 命中片段） | **always-on**（每次都在，不检索） |
| 存储 | sqlite + 向量 + FTS | **一份 JSON**（不写 sqlite、不做 embedding） |

把关系事实塞进向量库会稀释检索、且**必然时有时无**——而"我们认识多久"这种背景
本就该每次都在。优先级定为 `P_RELATION=72`：高于普通事实（它更稳定、更像"自我认知"），
低于当前目标与用户明确要求。

## 交付报告（2026-09-13 完成）

### Changed files

**新增**：`engine/yuiro/memory/relationship.py`、`engine/tests/test_relationship.py`（12 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/context/engine.py` | `P_RELATION=72`；`_collect_relationship()`；`build(relationship_summary=...)` |
| `engine/yuiro/agent/__init__.py` | `relationship` 注入 + `relationship_summary` 传入 build（同 task_summary 模式） |
| `engine/yuiro/main.py` | 装配 `RelationshipMemory`（`data/relationship.json`）；三处写入钩子：用户发言（互动 + 天数里程碑）、`task.completed`（一起完成一件事）、启动日志 |
| `engine/yuiro/debug_api.py` | `GET /memory/relationship`（视图） |

### 冒烟证据

```
EMPTY SUMMARY: ''                                        ← 从没聊过 → 不注入
MILESTONES day1: []
SUMMARY: 你和用户已经认识 1 天，聊过 1 次，一起完成过 1 件事，用户让你记住 1 件事。
         值得记住的时刻：第一次一起完成一件事（整理下载文件夹）。
MILESTONES day8: ['认识第 3 天', '认识第 7 天']           ← 时间推进 → 里程碑
INJECTED: 【我们的关系】以下是你们之间的相处背景… | 你和用户已经认识 8 天…
RESTART: 2 次互动 / 1 件事                                ← 重启持久化
TO_DICT days: 8
```

### Tests

- 新增 **12 个**全部通过；全量回归 **298 passed / 5 failed / 1 error**（失败集与基线一致）；
- `memory/relationship.py` 与测试文件 ruff 零告警。

### DoD 对照

- [x] 关系事实独立存储（JSON；与 Conversation Memory 物理隔离）
- [x] `summary()` 产出自然语言（不是 JSON），无记录时返回空串**不注入**
- [x] 天数里程碑（3/7/30/100/365）跨重启不重复记
- [x] 首次一起完成任务 → 里程碑（带目标名）
- [x] ContextEngine 独立分段【我们的关系】（always-on；P_RELATION 处于 task/explicit 与 fact 之间）
- [x] 损坏文件容错（按全新关系处理，不抛错）；回归通过

### Human Acceptance（待人工）

1. 聊几句后 `GET /debug/presence/state` 不显示关系；改看 `GET /debug/memory/relationship` → 有 `interactions`/`days_known`；
2. 让它完成一个多步任务 → `tasks_completed` +1，且里程碑出现"第一次一起完成一件事（…）"；
3. 重启引擎 → 计数不丢；过几天再看 → 出现"认识第 3 天/第 7 天"；
4. 对话中它应**自然**带入关系（不要生硬报数字——注入文案已明确要求）。

### 风险 / 遗留

- 里程碑目前只有"天数"与"第一次完成任务"两类（可扩展：第一次叫名字 / 第一次被夸 / 第一次吵架后和好）；
- 未做 Relationship Memory 的**衰减或修正**（如"我们已经很久没聊了"这类状态，需要 last_seen 语义）；
- 互动计数按"用户发言次数"计，不含 Yuiro 主动发起的互动（主动表达场景下计数偏低）。