# S06 — ContextEngine（Context 是独立基础设施）

> 状态：**已批准开工**（2026-09-12，Human 指令"继续"＝按推荐做 ContextEngine）。
> 性质：Wave 3（P1）第一步。W3 验收标准：`context/` 包存在；`_build_messages` 改为
> `ContextEngine.build`；存在 ContextItem 元数据与预算裁剪。
> 规范依据：`docs/spec/architecture-goal.md` §3.3、`docs/spec/target-file-preview.md` §3.8。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 06
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    ContextEngine —— Context 从"手工拼接"升级为"受预算管理的组装"
SURPRISE: 长对话/大工具结果不再挤爆上下文；每次注入都可解释（哪段、多贵、丢没丢）
USER EXPERIENCE:
  - 行为无感（文案与注入顺序零改动，等价性测试护栏）
  - 日志可读出：本次组装 N 段 / 估算 M tokens（预算 X）/ 裁剪 K 段
  - 工具返回超长结果时不再整段回灌（截断 + 标注）
ARCHITECTURE:
  - 新增 context/ 包：ContextItem（source/scope/priority/token_cost/mandatory）
    + ContextBudget + ContextEngine（收集 → 排序 → 预算裁剪 → messages）
  - AgentLoop 接入：传 context_engine 时走 build；缺省回退旧 _build_messages（兼容）
  - 工具结果 Context-aware：超长截断（只影响喂给 LLM 的副本，前端 chunk 保留完整）
  - [context] 配置段：budget_tokens / tool_result_max_chars（数字不硬编码）
  不做：Cold/Warm/Hot 三层完整落地、compaction/摘要压缩、Artifact Store、插件式 source 体系
FILES:
  engine/yuiro/context/{__init__.py, item.py, engine.py}（新增）
  engine/yuiro/config.py（ContextConfig）
  engine/config.toml + config.example.toml（[context] 段）
  engine/yuiro/agent/__init__.py（AgentLoop 接入 + 工具结果截断 + build_agent_loop 透传）
  engine/yuiro/main.py + debug_api.py（装配透传 context_config）
  engine/tests/test_context_engine.py（新增）
CODING AGENT:
  遵循 coding-agent-protocol：**文案逐字照搬**（现有 _build_messages 含大量实测调优，
  一字不改）；等价性测试（新旧输出逐字节相同）是硬护栏；最小改动。
  禁止重写 AgentLoop；禁止改注入顺序。
TEST:
  Unit：等价性（新旧 messages 完全相同）/ 预算裁剪（低优先级先丢、mandatory 保留）/
        排序与输出顺序 / token 估算 / 工具结果截断
  + 回归（对照基线：5 failed 集不变）
DEFINITION OF DONE:
  - context/ 包就位；ContextEngine.build 输出与旧 _build_messages 逐字节等价
  - 预算裁剪生效且可观测（vlog：组装段数/估算 tokens/裁剪明细）
  - 工具结果超长截断（LLM 副本截断；前端 chunk 完整）
  - [context] 配置可调；回归通过
HUMAN ACCEPTANCE:
  连续对话 10+ 轮 + 触发一次长结果工具（如 file_read 大文件），确认回答质量无退化，
  日志中出现 context 组装/裁剪记录
NEXT UNLOCK: Wave 4 Memory Lifecycle（记忆候选 → ContextEngine 预算）与 Wave 5 Task
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 现状基线（S06 前）

- `AgentLoop._build_messages`（agent/__init__.py L404-479）：手工拼 6 段（system → persona →
  facts → knowledge → episodes → state → history → user），**无元数据、无预算、无裁剪**；
- 记忆检索（`retrieve(top_k=3)`）在 `send()` 内（L496-505），注入策略与拼接耦合；
- 工具结果直接 append 进 messages（L737-741），**大结果整段回灌**；
- 现文案含大量实测结论（PERSONA 稀释工具识别 → 铁律前置；system vs user suffix 6/8 vs 4/8；
  L2 白熊效应等）——**必须零改动保留**。

## 交付报告（2026-09-12 完成）

### Changed files

**新增**：`engine/yuiro/context/{__init__.py, item.py, engine.py}`、`engine/tests/test_context_engine.py`（10 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/agent/__init__.py` | `AgentLoop` 注入 `context_engine`；`send()` 优先走 `ContextEngine.build`（缺省回退旧 `_build_messages`）；工具结果 Context-aware 截断（仅 LLM 副本，前端 chunk 完整）；`build_agent_loop` 装配并透传 |
| `engine/yuiro/config.py` | 新增 `ContextConfig`（budget_tokens / tool_result_max_chars）+ AppConfig 字段 + load_config + TOML_SECTIONS + FIELD_META（调试台可调） |
| `engine/config.toml` + `config.example.toml` | 新增 `[context]` 段 |
| `engine/yuiro/main.py` + `debug_api.py` | 装配透传 `context_config=cfg.context`（含热重载路径） |

### 冒烟证据

```
CONFIG budget: 6000 tool_max: 2000
LOOP: True CTX: True
[context] [smoke] 组装 6 段 / 估算 1533 tokens（预算 6000）
          ｜system:994 / persona:386 / facts:50 / episodes:85 / state:15 / user:3
MSGS: 6 ['system', 'system', 'system', 'system', 'system', 'user']
[context] 工具结果截断: file_read 3000 → 2000 字符
```

### 关键护栏：等价性测试

`_build_messages` 含大量实测调优结论（人设前置铁律、白熊效应、system vs user suffix 6/8 vs 4/8 等），
S06 全部**逐字照搬**；3 个等价性测试断言 `ContextEngine.build` 输出与旧路径**逐字节相同**
（全量 fixture / 最小 fixture / episodic 过滤场景）。

### Tests

- 新增 **10 个**全部通过（含 3 个等价性护栏）；全量回归 **107 passed**（失败集与基线一致）；
- `context/` 与测试文件 ruff 零告警；
- 既有告警说明：`agent/__init__.py`、`config.py` 存在历史 ruff 告警（位置均不在本次改动处，未扩大范围修复）。

### DoD 对照

- [x] `context/` 包就位；`ContextEngine.build` 与旧 `_build_messages` 逐字节等价
- [x] 预算裁剪生效且可观测（vlog：段数 / 估算 tokens / 分段明细 / 裁剪列表）
- [x] 工具结果超长截断（LLM 副本截断 + 标注；前端 chunk 完整）
- [x] `[context]` 配置可调（config.toml / 调试台表单）；回归通过
- [x] mandatory（system/persona/本轮用户输入）永不裁剪；kept 保持注入顺序

### Human Acceptance（待人工）

1. 连续对话 10+ 轮 → 确认回答质量无退化（注入顺序/文案与 S06 前完全一致）；
2. 让 Yuiro 读一个大文件（如 `file_read` 长文本）→ 日志出现 `工具结果截断`；
3. 观察日志 `[context] 组装 N 段 / 估算 M tokens（预算 6000）` 是否随记忆/状态变化。

### 风险 / 遗留

- 截断的完整结果当前**未落盘**（spec 的 Artifact Store 是后续 Wave；截断即丢弃，前端 chunk 仍可见完整内容）；
- Cold/Warm/Hot 三层与 compaction（摘要压缩）未落地；插件式 source 体系未做（内部分段 collector 形式）；
- 预算为**估算 token**（非真实 tokenizer），用于相对比较与裁剪排序。
