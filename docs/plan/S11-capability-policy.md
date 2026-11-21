# S11 — Capability 层（Policy / Permission 分级 / CapabilityView）

> 状态：**已批准开工**（2026-09-12，Human 指令"继续"）。
> 性质：spec 六实体的**最后一块**（Capability 此前完全缺失）+ Wave 6 Security Runtime 第一步。
> 规范依据：`docs/spec/architecture-goal.md` §3.7（PermissionProfile / Approval 分层 / Capability Scope）、
> `docs/spec/README.md` 约束 9（安全链）+ §3 六实体表。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 11
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Capability 层 —— 工具的权限分级与可见性
SURPRISE: "它做事我放心"：权限有档位、越界会被拦、危险工具默认看不到
USER EXPERIENCE:
  - 新增 `[capability].profile` 四档：read_only / privacy / normal（默认）/ trusted
  - read_only 档：写操作直接拒绝（不再"能写"），且该工具不会出现在 LLM 的工具表里
  - normal 档：与现状一致（低风险直通；中风险依审批模式；行为零变化）
  - trusted 档：中风险直通（写文件不再需要审批）
ARCHITECTURE:
  - 新增 capability/ 包：RiskLevel + Decision(ALLOW/ASK/DENY) + Profile + Policy + CapabilityView
  - AgentLoop 接入：执行前 Policy 判定（DENY → 不执行、不走审批，返回结构化 denied）
    + CapabilityView 过滤 tool_schemas（被拒工具不暴露给 LLM）
  - 分层原则：Policy 只做**工具级**决策；参数级边界（路径等）由执行后端承担（Sandbox 角色）
  不做：Capability Scope 域模型（filesystem/network/... 的细粒度声明）、Sandbox 真隔离、
        plan-level approval（LEVEL 4）、per-tool 覆盖配置（预留字段）
FILES:
  engine/yuiro/capability/{__init__.py, policy.py, view.py}（新增）
  engine/yuiro/agent/__init__.py（policy 注入 + 判定 + view 过滤）
  engine/yuiro/config.py（CapabilityConfig + FIELD_META）
  engine/config.toml + config.example.toml（[capability] 段）
  engine/yuiro/main.py + debug_api.py（装配透传）
  engine/tests/test_capability_policy.py（新增）
  docs/spec（六实体状态）+ ARCHITECTURE.md + docs/plan/README.md
CODING AGENT:
  遵循 coding-agent-protocol：**零行为变化优先**（默认档 normal + auto 审批模式 = 与 S10 前一致）；
  风险分级必须与既有 approval_required 语义协调（见下）；不改执行后端。
TEST:
  Unit：risk 分级表 / 四档决策矩阵（allow/ask/deny）/ 未知工具保守默认 /
        CapabilityView 过滤 / AgentLoop denied 不执行（fake registry 验证）/ 
        兼容（无 policy 时行为不变）/ 回归（S05–S10 护栏不破）
DEFINITION OF DONE:
  - Policy.decide 对 6+ 工具 × 4 档给出正确决策；DENY 的工具不被执行也不暴露
  - 默认配置（normal + auto）下行为与 S10 完全一致
  - read_only 档能真实拦截写操作（测试证明）；trusted 档能免审批写
  - 回归通过（159 passed 基线 + 新增）
HUMAN ACCEPTANCE:
  ① 把 `[capability].profile` 改成 `read_only` 重启 → 让 Yuiro 写文件应被拒绝并说明；
  ② 改回 `normal` → 行为与之前一致；③ 改 `trusted` + `[systemd].approval_mode = "manual"`
  → 写文件不再弹审批
NEXT UNLOCK: S12 Event Log（落盘 + Replay）+ Wave 6 的 Sandbox 真隔离
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 决策矩阵（风险 × 档位）

| 风险级 | 代表工具 | read_only | privacy | normal（默认） | trusted |
|---|---|---|---|---|---|
| LOW（只读/无副作用） | file_read / media_control / app_focus / task_* / artifact_read | allow | allow | allow | allow |
| MEDIUM（可逆写） | app_open / file_create / file_write / netease_play | **deny** | **deny** | ask | allow |
| HIGH（破坏性，预留） | process_kill / terminal_exec / *_inject | **deny** | **deny** | ask | ask |
| 未登记工具 | — | deny | deny | ask | ask |

> `ask` 的最终效果取决于既有 `[systemd].approval_mode`：`auto`（用户当前）→ 直接放行；
> `manual` → 弹审批窗。**DENY 则无论什么模式都拒绝**（硬边界，S11 新增能力）。
> 这保证"默认配置零行为变化"（normal + auto = 与 S10 前逐字节一致）。

## 交付报告（2026-09-12 完成）

### Changed files

| 文件 | 改动 |
|---|---|
| `engine/yuiro/capability/{__init__.py, policy.py, view.py}` | **新增**：`RiskLevel`（工具风险表）+ `Decision(allow/ask/deny)` + `Profile` × 4 档 + `Policy` + `CapabilityView` |
| `engine/yuiro/agent/__init__.py` | `policy=` 注入；`send()` 用 `CapabilityView` 过滤工具表；`_run_one` 执行前判定（DENY → 不执行、不走审批、返回结构化结果；ask → 传 approval_callback） |
| `engine/yuiro/config.py` | `CapabilityConfig(profile)` + AppConfig + load_config + TOML_SECTIONS + FIELD_META |
| `engine/config.toml` + `config.example.toml` | `[capability] profile = "normal"` |
| `engine/yuiro/main.py` + `debug_api.py` | 装配透传 `capability_config=cfg.capability` |
| `engine/tests/test_capability_policy.py` | **新增** 14 个用例 |
| `docs/spec/README.md`（六实体表）+ `ARCHITECTURE.md`（CAPABILITY 层图） | 状态同步 |

### 冒烟证据（真实装配）

```
CONFIG profile: normal
PROFILE read_only: {'file_read': 'allow', 'app_open': 'deny', 'file_write': 'deny', 'terminal_exec': 'deny'}
PROFILE normal:    {'file_read': 'allow', 'app_open': 'ask',  'file_write': 'ask',  'terminal_exec': 'ask'}
PROFILE trusted:   {'file_read': 'allow', 'app_open': 'allow','file_write': 'allow','terminal_exec': 'ask'}
LOOP policy: normal
TOOLS total: 14 | visible: 14 | hidden: []                                   ← normal 档零行为变化
READ_ONLY hidden: ['app_open','file_create','file_write','netease_login','netease_play']  ← 只读档真实隐藏写工具
```

### Tests

- 新增 **14 个**全部通过（决策矩阵 4 档 × 风险级 / 可见性 / AgentLoop 拦截集成 / 装配）；
- 全量回归 **173 passed**（S10 基线 159 + 14），失败集与基线一致；
- `capability/` 与测试文件 ruff 零告警。

### DoD 对照

- [x] `Policy.decide` 对工具 × 4 档给出正确决策（矩阵逐项断言）
- [x] DENY 的工具**不执行**（集成测试：registry 未收到调用）且**不暴露**给 LLM（工具表过滤）
- [x] 默认配置（normal + auto）行为与 S10 完全一致（"ask 在无审批门下照常执行"用例）
- [x] read_only 档真实拦截写操作；trusted 档中风险免审批
- [x] 回归通过（S05–S10 护栏不破）

### Human Acceptance（待人工）

1. `[capability].profile = "read_only"` 重启 → 让 Yuiro 写文件 → 应被拒绝并说明原因（日志 `拒绝 file_write：超出当前权限档位 read_only`）；
2. 改回 `normal` → 行为与之前完全一致；
3. 改 `trusted` + `[systemd].approval_mode = "manual"` → 写文件不再弹审批。

### 风险 / 遗留

- 未做 Capability Scope 域模型（filesystem/network/process 细粒度声明）与 plan-level approval（LEVEL 4）；
- 未做 per-tool 覆盖配置（如"单独放行 netease_play"）；
- `privacy` 档目前等同只读（预留：网络外发类工具另加拦截）；
- Sandbox 真隔离仍由执行后端承担（`file_roots`）；更强隔离待后续 Wave。
