# S13 — Memory Lifecycle 收尾（衰减 + 遗忘 + 显式记忆管理）

> 状态：**已完成**（2026-09-12，Human 指令"全部进行"）。
> 性质：Wave 4 收尾——记忆从"只写不忘"升级为"有生命周期"。
> 规范依据：`docs/spec/roadmap.md` Wave 4、`docs/spec/README.md` §3（Relationship Memory 配套区分）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 13
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Memory Lifecycle —— 会遗忘的记忆才可信
SURPRISE: Yuiro 会"淡忘"过时的小事，但你明确让它记住的事永远不忘
ARCHITECTURE:
  - 事实衰减真正生效：upsert_fact 支持 decay；写入按来源定衰减率
    （rule/llm 缓慢衰减 ≈ 每天 2%；explicit 永不衰减）
  - MemorySystem.forget()：删除长期未更新且衰减到低置信度的事实（>90 天且 <0.15）
    + 删除过老的低显著性情景（>60 天且 salience<2.0），**显式记忆永不删除**
  - 维护循环：启动后每 6 小时自动遗忘一次（失败静默）
  - 记忆管理 API：GET/DELETE /memory/explicit + POST /memory/forget
不做：关系记忆（Relationship）、记忆聚类/合并（Consolidation）、前端记忆管理 UI 改版
FILES:
  engine/yuiro/memory/__init__.py（upsert decay / _decay_for / forget / list_explicit / delete_explicit）
  engine/yuiro/main.py（维护循环）
  engine/yuiro/debug_api.py（3 个端点）
  engine/tests/test_memory_lifecycle.py（新增）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 现状基线（S13 前）

| 环节 | 现状 | 缺口 |
|---|---|---|
| facts.decay 字段 | 表里有 `decay` 列，`query_facts` 也算 `effective_confidence` | **`upsert_fact` 写死 decay=0.0 → 永不衰减（机制形同虚设）** |
| 遗忘 | 无 | 只增不减；低价值情景/过时事实永久占用检索 |
| 显式记忆（S07） | 常驻注入 | **不可管理**（用户无法查看/删除"记住的事"） |
| 维护 | 无 | 无任何自动清理 |

## 交付报告（2026-09-13 完成）

### 冒烟证据

```
FACT decay: 2.31e-07 | effective: 0.9          ← 衰减真正生效（S13 前写死 0）
EXPLICIT: [(1, '[用户要求记住] 我下周要参加算法竞赛（用户原话…）')]
FORGET: {'facts_removed': 0, 'episodes_removed': 0}   ← 新数据不删（正确）
AFTER DELETE: []                                  ← 显式记忆可删除
```

### Changed files

| 文件 | 改动 |
|---|---|
| `memory/__init__.py` | `upsert_fact(decay=…)` + `FactsStore.upsert(decay=…)`；`_FACT_DECAY_PER_DAY`/`_decay_for`；`_apply_facts` 按来源注入衰减；`forget()`/`_forget_sync`（事实衰减清理 + 过老低显著性情景清理，**显式记忆永不删除**）；`list_explicit`/`delete_explicit` |
| `main.py` | `_memory_maintenance_loop`（每 6h 遗忘一次）+ lifespan 启动 |
| `debug_api.py` | `GET /memory/explicit`、`DELETE /memory/explicit/{rowid}`、`POST /memory/forget` |
| `tests/test_memory_lifecycle.py` | 新增 8 个用例 |

### Tests

- 新增 **8 个**全部通过；全量回归 **191 passed**（S12 基线 183 + 8），失败集与基线一致；
- 新增代码零 lint 告警（`memory/__init__.py` 的其余告警为历史遗留，非本次引入）。

### DoD 对照

- [x] 事实衰减真正生效（decay 写入非 0；explicit 永不衰减）
- [x] `forget()` 清理"陈旧 + 低有效置信度"事实与"过老 + 低显著性"情景
- [x] 显式记忆永不删除，且可查看/删除（管理 API）
- [x] 维护循环每 6h 自动遗忘（失败静默）
- [x] 回归通过

### Human Acceptance（待人工）

1. 说"记住：我下周要参加算法竞赛" → `GET /debug/memory/explicit` 应列出；
2. `POST /debug/memory/forget` → 返回 `removed` 计数（新记忆应不删）；
3. 反悔时 `DELETE /debug/memory/explicit/{rowid}` → 该条消失。

### 风险 / 遗留

- 衰减是"排序降权 + 超阈值删除"，不做记忆聚类/合并（Consolidation）；
- 未做 Relationship Memory（Era 3）；前端记忆管理 UI 未改版（后端 API 就绪）。
