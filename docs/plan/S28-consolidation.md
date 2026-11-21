# S28 — Memory Consolidation（Era 2→3 的桥）

> 状态：**进行中**（2026-09-13）。
> 来源：`docs/spec/architecture-goal.md` §3.10 +
> `target-file-preview.md`（`memory/consolidation.py` ★ Wave 4）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 28
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Consolidation —— 从"它记得"到"它了解我"
SURPRISE: 你反复提过的事，它自己归纳成对你的认识（而不是只记住原话）
ARCHITECTURE:
  Episodes（L2） ──异步归纳──▶ 候选事实 ──安全阀──▶ L3 Facts
                    │
                    ├─ 支持度：同一 (key, value) 需在 ≥N 条不同 episode 出现
                    ├─ 时效：consolidation 来源的衰减比 explicit 快（推断可被淘汰）
                    └─ 不阻塞：只在维护循环/手动触发时运行
  规范红线（architecture-goal.md §3.10）：
   - "Consolidation 异步进行，不得阻塞用户正常聊天"；
   - "Memory Write Safety：旧 generation 的结果不得进入当前 Memory"；
   - runtime-contract 竞态清单："Memory consolidation finishes after session reset → NOT corrupt current state"。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 关键设计：**支持度**而非"一次推断"

最危险的做法是"每条 episode 都让 LLM 归纳一遍"——必然产生大量幻觉事实。
本 Sprint 的做法：

1. **复用既有规则抽取**（`_extract_facts`，精确、无幻觉）在每条 episode 上跑；
2. **统计支持度**：同一 `(key, value)` 在 **≥N 条不同 episode** 出现 → 才升级为 L3 事实；
3. **LLM 可选**（`fact_llm` 存在时）用于补充规则抓不到的隐含画像，但同样要经安全阀；
4. 归纳来源的事实用**更快的衰减**（推断 ≠ 用户亲口说的），错的会自然淡出。

## 交付报告（2026-09-13 完成）

### Changed files

**新增**：`engine/yuiro/memory/consolidation.py`、`engine/tests/test_consolidation.py`（16 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/memory/__init__.py` | `MemorySystem.consolidate()`（IO 编排：取快照 → 规则/LLM 候选 → 安全阀 → 写 L3）；`_decay_for` 新增 `consolidation` 分支（每天 5%，比普通事实更快） |
| `engine/yuiro/main.py` | 维护循环（每 6h）在 `forget()` 之后追加 `consolidate()`（失败静默） |
| `engine/yuiro/debug_api.py` | `POST /memory/consolidate?min_support=&use_llm=`（手动触发，返回完整结果） |

### 冒烟证据（4 个场景）

```
RESULT: {scanned: 4, candidates: 2, accepted: 1, written: 1,
         skipped_low_support: 1, skipped_existing: 0, llm_used: False}
DETAILS: [{'key': '宠物', 'value': '猫', 'support': 3}]     ← 支持度 3 才升级
FACTS:   [('宠物', '猫', 0.7)]                              ← 推断置信度上限 0.7
IDEMPOTENT written: 0 | skipped_existing: 1                 ← 幂等
AFTER HIGH-CONF: [('宠物', '狗')] | skipped_existing: 1      ← 0.95 的旧事实未被覆盖
EPISODES UNTOUCHED: 4                                       ← L2 完全没动（规范红线）
```

### 三个设计决策

1. **支持度而非"一次推断"**：复用既有规则抽取器（精确、无幻觉）统计跨 episode 的
   `(key, value)` 出现次数，≥ `min_support` 才升级。LLM 只作可选补充通道。
   —— 若每条 episode 都让 LLM 归纳，必然产生大量幻觉事实。
2. **推断衰减更快**（每天 5% vs 普通 2%）：推断 ≠ 用户亲口说的，错的应更快淡出。
   与 S13 的衰减/遗忘机制形成闭环（consolidation 写入 → 衰减 → 若长期无新证据被清除）。
3. **不降级已有**：同 key 已存在且有效置信度 ≥ 0.7 时跳过（保护用户亲口说的），
   同值直接跳过（省 IO）。

### 规范红线对照（architecture-goal.md §3.10）

- [x] **异步、不阻塞聊天**：只在维护循环 / 手动 API 运行，绝不进入 `send()` 主链路；
- [x] **不污染当前状态**：只写 L3 facts；输入是 L2 **快照**；测试断言 L2 行数不变
      （对应 runtime-contract 的竞态清单 "consolidation finishes after session reset → NOT corrupt"）；
- [x] **显式记忆不参与归纳**（用户的直接意图不该被推断改写）。

### Tests

- 新增 **16 个**全部通过；全量回归 **314 passed / 5 failed / 1 error**（失败集与基线一致）；
- `memory/consolidation.py` 与测试文件 ruff 零告警。

### Human Acceptance（待人工）

1. 连续几天反复聊到同一件事（如"我在用 Python 写脚本"多次）→
   之后 `GET /debug/memory/showcase` 的 facts 里应出现归纳出的画像（日志 `[归纳] …`）；
2. `POST /debug/memory/consolidate` → 返回 `{scanned, candidates, written, skipped_*}`；
3. 确认它**没有**把"记住 X"这类显式记忆改掉（显式记忆只在 explicit 通道）；
4. 观察引擎启动日志：每 6h 的维护会依次打 `[遗忘]` 与 `[归纳]`。

### 风险 / 遗留

- **规则抽取器的覆盖率决定归纳上限**：`_extract_facts` 抓不到的画像（如隐含偏好）
  只能靠 LLM 路径；LLM 路径需要 `fact_llm` 已注入（当前由配置决定）；
- 归纳**无去重合并**（同一语义的不同 key 会各自成条，如"技术栈"与"技能"）；
- 未做 Semantic Memory（自由文本级长期知识）—— 当前只落地到 Fact（结构化）；
- 触发频率固定 6h，未做"新 episode 达 N 条才触发"的增量策略（重复归纳靠幂等兜底）。
