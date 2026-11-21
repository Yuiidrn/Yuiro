# S07 — Explicit Memory（"说了就要记住"）+ Memory 接入 ContextEngine

> 状态：**已批准开工**（2026-09-12，Human 授权外出期间自主连续推进）。
> 性质：Wave 4（Memory Lifecycle）第一步 + Era 2 产品线（Personal Brain）首个可见惊喜。
> 规范依据：`docs/spec/architecture-goal.md` §3.3/§3.4、`docs/spec/roadmap.md` Wave 4 / PB Track。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 07
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Explicit Memory —— 用户说"记住"，就真的记住
SURPRISE: 对 Yuiro 说"记住我下周要参加算法竞赛"，几天后它仍会主动提起
USER EXPERIENCE:
  - "记住 X" / "帮我记一下 X" / "别忘了 X" → 立即写入（不等后台异步）
  - 之后无需提醒，相关时会主动提起（注入【你答应用户记住的事】独立通道）
  - 显式记忆总是被注入（不受 top_k 限制），且优先级高于普通事实
ARCHITECTURE:
  - 新增显式记忆通道：EXPLICIT_PREFIX 标记 + explicit_search（零表结构改动）
  - retrieve() 附加 explicit 记忆（独立通道，类似 facts 的常驻注入）
  - ContextEngine 新增 explicit 分段（P_EXPLICIT=75 > facts=70）+ Memory.relevance 接入 ContextItem
  不做：记忆衰减/遗忘曲线、记忆去重聚类、用户可查的记忆管理 UI（后续 Wave）
FILES:
  engine/yuiro/memory/__init__.py（显式识别 + 写入 + 检索通道）
  engine/yuiro/context/engine.py（explicit 分段 + relevance）
  engine/tests/test_explicit_memory.py（新增）
CODING AGENT:
  遵循 coding-agent-protocol：最小改动、不破坏既有抽取路径（规则/LLM 双通道保持）、加测试。
  禁止改动 L2/L3 既有语义；禁止引入表结构迁移（用前缀标记实现通道）。
TEST:
  Unit：显式句式识别（含否定/边界）/ 写入与检索命中 / retrieve 常驻注入 /
        ContextEngine explicit 分段与优先级 / 等价性回归（S06 护栏不破）
  + 全量回归（对照基线：5 failed 集不变）
DEFINITION OF DONE:
  - "记住 X" → 立即落库（同一回合之后即可检索到）
  - retrieve 总是返回 explicit 记忆（meta.kind="explicit"）
  - ContextEngine 输出含【你答应用户记住的事】独立分段
  - 既有事实抽取（规则 + LLM）行为不变；回归通过
HUMAN ACCEPTANCE:
  对 Yuiro 说"记住：我下周要参加算法竞赛" → 隔几分钟问"我下周要干什么"，
  它应能答出（且日志有 [显式记忆] 写入记录）
NEXT UNLOCK: Wave 4 完整生命周期（衰减/遗忘）与 Wave 5 Task（跨多轮目标）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 现状基线（S07 前）

| 环节 | 现状 | 缺口 |
|---|---|---|
| 规则抽取 | `_FACT_PATTERNS`（我叫/我喜欢/我讨厌…） | **"记住 X" 不匹配任何模式** |
| LLM 抽取 | prompt 明确要求"忽略临时情绪与**一次性事件**" | **"下周参加算法竞赛"被主动丢弃** |
| 写入时机 | `remember()` 走 `_spawn` 后台异步 | 用户立刻追问时可能还查不到 |
| 检索注入 | L2 受 top_k 截断（默认 3） | 显式记忆可能被挤掉 |
| Context 分段 | facts / knowledge / episodes | 无「用户要求记住的事」通道 |

**结论**：用户明确说"记住"的内容当前**必然丢失** —— 这是 Era 2 最直观的信任缺口。

## 交付报告（2026-09-12 完成）

### Changed files

| 文件 | 改动 |
|---|---|
| `engine/yuiro/memory/__init__.py` | 模块常量 `EXPLICIT_PREFIX`；`SQLiteVecStore.explicit_search`；`_EXPLICIT_PATTERNS` + `_EXPLICIT_INVALID` + `_extract_explicit` + `_remember_explicit`；`remember()` 同步优先写入；`retrieve()` 常驻 explicit 通道 |
| `engine/yuiro/context/item.py` | 补 `freshness` / `relevance` 字段（S06 遗漏，spec §3.3 要求） |
| `engine/yuiro/context/engine.py` | `P_EXPLICIT=75`；`_collect_memory` 新增 explicit 分段 + 各分段填 `relevance`（取该段检索最高分） |
| `engine/tests/test_explicit_memory.py` | 新增 8 个用例 |

### 冒烟证据

```
HITS: [('explicit', '（用户要求记住）我下周要参加算法竞赛（用户原话：记住我下周要参加算法竞赛）')]
[context] [smoke] 组装 4 段 / 估算 162 tokens（预算 6000）｜system:1 / persona:76 / explicit:83 / user:2
CTX: 【你答应用户记住的事】以下是用户明确要求你记住的内容，请在相关时主动提起（不要等用户提醒）…
```

### 修复的两个真问题（测试暴露）

1. `ContextItem` 缺 `freshness/relevance` 字段 → 补上（S06 spec 要求的元数据）；
2. `_extract_explicit("你记住了吗？")` 误判为内容"了吗" → 加 `_EXPLICIT_INVALID` 过滤纯语气词。

### Tests

- 新增 **8 个**全部通过；全量回归 **115 passed**（S06 基线 107 + 8），失败集与基线完全一致
  （5 failed + 1 error；其中 `test_migrations_idempotent` 的 PermissionError 经单独运行确认为**既有环境问题**，
  不在本次改动路径上）；
- `context/`、测试文件 ruff 零告警。

### DoD 对照

- [x] "记住 X" → 立即落库（同步 `await`，同一回合之后即可检索）
- [x] `retrieve` 总是返回 explicit 记忆（`meta.kind="explicit"`，不受 top_k / 相关性限制）
- [x] ContextEngine 输出含【你答应用户记住的事】独立分段，排在事实段之前
- [x] 既有事实抽取（规则 + LLM）行为不变；等价性护栏（S06）仍全绿
- [x] 跨实例（模拟重启）仍可常驻注入

### Human Acceptance（待人工）

1. 对 Yuiro 说"**记住：我下周要参加算法竞赛**" → 日志应出现 `[显式记忆] 已记住：…`；
2. 隔一段时间问"我下周要干什么" → 它应能答出（或主动提起）；
3. 说"你记住了吗"（无内容）→ 不应误存任何东西。

### 风险 / 遗留

- 无遗忘/衰减机制（显式记忆永久常驻；数量上限 5 条注入，超出按新近度取）；
- 未做记忆管理 UI（用户无法查看/删除已记住的事）——属后续 Wave；
- 显式记忆与 L3 事实相互独立（不写 facts 表，避免 key 冲突）。
