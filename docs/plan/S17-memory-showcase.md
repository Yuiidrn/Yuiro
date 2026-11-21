# S17 — Memory Showcase（"它真的记得"端到端验收）

> 状态：**已完成**（2026-09-13）。
> 来源：`docs/spec/阶段性总评和后续方向.md` §31（"现在已非常接近『三天后真的记得我说过的话』，
> 应把 Memory Lifecycle + Context + Scenario + Replay + UI 串起来，这是很强的正反馈节点"）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 17
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Memory Showcase —— 把"记得"变成可验证、可观察的事实
SURPRISE: 200 天后它仍记得你让它记住的事；而随口一说的琐事已被淡忘
ARCHITECTURE:
  - Scenario 测试（5 个端到端场景）：三天后仍记得 / 琐事淡忘但显式保留 /
    重启仍在 / 记忆→Context 注入链 / EventLog 完整回放
  - GET /debug/memory/showcase：三通道快照（explicit / facts / episodes + 计数）
  不做：前端 Showcase UI（后端 API 就绪）；记忆聚类/合并（Consolidation）
FILES:
  engine/tests/test_memory_showcase.py（新增 5 场景）
  engine/yuiro/debug_api.py（GET /memory/showcase）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 交付报告（2026-09-13 完成）

### 冒烟证据（真实 MemorySystem + 时间推进 200 天）

```
AFTER 200D HITS: [('explicit', '[用户要求记住] 我下周要参加算法竞赛（用户原话：…')]
EXPLICIT:  [(1, '[用户要求记住] 我下周要参加算法竞赛（用户原话：记住：我…')]
FORGET:    {'facts_removed': 0, 'episodes_removed': 2}      ← 琐事被淡忘
LEFT:      ['[用户要求记住] 我下周要参加算法竞赛（用户…']      ← 只剩显式记忆
RESTART EXPLICIT COUNT: 1                                    ← 重启后仍在
```

### 五个场景（测试固化）

| 场景 | 断言 |
|---|---|
| A 三天后仍记得 | `retrieve("我下周要做什么？")` 命中，且 `meta.kind == "explicit"` |
| B 琐事淡忘 / 显式保留 | 200 天后 `forget()` 删除琐事情景，显式记忆仍在 |
| C 重启仍在 | 新实例同 db → 仍可检索 + `list_explicit()` 非空 |
| D 注入链 | 显式记忆经 `ContextEngine` → 组装出【你答应用户记住的事】分段 |
| E Replay | EventLog 完整回放事件序列（可观测底座） |

### Tests

- 新增 **5 个**全部通过；全量回归 **217 passed / 5 failed / 1 error**（失败集与基线一致，S16b 基线 212 + 5）；
- 测试与 `debug_api.py` ruff 零告警。

### Human Acceptance（待人工）

1. 说「**记住：我下周要参加算法竞赛**」→ 日志 `[显式记忆] 已记住：…`；
2. 隔几天（或重启后）问「**我下周要做什么**」→ 应能答出；
3. 访问 `GET /debug/memory/showcase` → 看到三通道快照（explicit 里有那条）；
4. 反悔时 `DELETE /debug/memory/explicit/{rowid}` → 该条消失。

### 风险 / 遗留

- 无前端 Showcase UI（后端 API 就绪，可直接 curl / 调试台）；
- 未做记忆 Consolidation（情景 → 语义合并）与 Relationship Memory；
- "三天后"是用时间戳推进模拟的，真实跨天行为需人工按第 2 步验证。
