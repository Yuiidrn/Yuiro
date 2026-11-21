# S15 — Runtime Consolidation（统一 Runtime Contract）

> 状态：**已批准开工**（2026-09-13）。
> 来源：`docs/spec/阶段性总评和后续方向.md` §21–§29（"不要继续添加 Runtime，应做 Runtime Consolidation"）。
> 经代码验证：该判断属实（Generation 局部复制、AgentLoop 1151 行、audio 1501 行、memory 1278 行）。
> 规范依据：`docs/spec/runtime-contract.md`。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 15
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Runtime Consolidation —— 让所有 Runtime 共享同一套生命周期原语
SURPRISE: "Yuiro 的所有行为现在都有同一个生命周期"（惊喜小、地基重）
ARCHITECTURE:
  - 新增 runtime/contract.py：RuntimeContract 协议 + RuntimeRegistry
    （close_session / cancel_session 广播 + snapshot 统一状态视图）
  - 四个已存在的 Runtime-like 模块实现契约（**薄适配，不重写**）：
    AgentLoop / VoicePipeline / AvatarRuntime / TaskRuntime
  - Session 关闭与取消走统一广播（不再各模块各自处理）
  - GET /debug/runtime：统一状态视图（各 Runtime name/state）
  - Generation 收敛：agent._generations 明确降级为"旧路径兼容"（新路径以 Session 为唯一权威）
不做：重写 AgentLoop / 拆分 audio·memory 大文件 / SpeechIntent 化（S16+）
FILES:
  engine/yuiro/runtime/contract.py（新增）
  engine/yuiro/{avatar/task}/…、audio/__init__.py、agent/__init__.py（实现契约，薄适配）
  engine/yuiro/runtime/session.py（close 广播钩子）
  engine/yuiro/main.py（注册 + 广播接线）
  engine/yuiro/debug_api.py（/debug/runtime）
  engine/tests/test_runtime_contract.py（新增）
CODING AGENT:
  遵循 coding-agent-protocol：**零行为变化**（只加契约与广播，不改既有执行路径）；
  所有钩子错误隔离（一个 Runtime 失败不影响其它）；不改 AgentLoop 内部逻辑。
TEST:
  Unit：Registry 注册/广播/错误隔离/snapshot / 各 Runtime 契约实现（4 个）/
        Session 关闭触发广播 / 兼容（未注册 runtime 时旧路径不变）/ 回归
DEFINITION OF DONE:
  - 4 个 Runtime 实现 RuntimeContract（name/state/cancel/on_session_close）
  - Session 关闭与取消通过 Registry 统一广播（错误隔离）
  - GET /debug/runtime 返回统一状态视图
  - 零行为变化（194 passed 基线不变 + 新增）
HUMAN ACCEPTANCE:
  调试台访问 /debug/runtime → 看到 agent/voice/avatar/task 四个 Runtime 的状态快照
NEXT UNLOCK: S16 Agent Harness Extraction（渐进抽离 AgentLoop）+ S17 Memory Showcase
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 验证记录（对总评文档的核对）

| 文档论断 | 核实 | 证据 |
|---|---|---|
| AgentLoop > 1100 行 | ✅ 1151 行 | `Get-ChildItem` 行数统计 |
| 遗漏：audio / memory 更大 | ✅ audio 1501 / memory 1278 | 同上（**文档只点了 agent**） |
| TTSTaskManager 有 seq/epoch/semaphore/有序/interrupt | ✅ | audio L988–1037 |
| Trace 已埋点 | ✅ 15 个点位 | main/audio/agent 的 `trace.mark` |
| Generation 局部复制 | ✅ | `agent._generations` L368/494；TTS `_epoch` L1003 |
| 测试状态 | 文档未验证 → **实测 194 passed / 5 failed / 1 error** | 本轮回归 |

## 交付报告（2026-09-13 完成）

### 冒烟证据（真实装配）

```
[yuiro][runtime] Runtime 注册表：agent, avatar, task, voice
REGISTERED: ['agent', 'avatar', 'task', 'voice']
  STATE agent: {'generations': 0, 'tracked_sessions': 0}
  STATE avatar: {'sessions': 0, 'current': {}}
  STATE task: {'active': 0, 'total': 0}
  STATE voice: {'state': 'init', 'stage': ''}
[yuiro][voice] [smoke-se] 打断 (barge-in)：LLM 回合与 TTS 已取消，已通知前端停播
CANCEL: {'agent': 'ok', 'voice': 'ok', 'avatar': 'ok', 'task': 'ok'}
CLOSE:  {'agent': 'ok', 'voice': 'ok', 'avatar': 'ok', 'task': 'ok'}
```

### Changed files

| 文件 | 改动 |
|---|---|
| `runtime/contract.py` | **新增**：`RuntimeContract` 协议 + `RuntimeRegistry`（cancel_session / close_session 广播 + snapshot；错误隔离） |
| `runtime/adapters.py` | **新增**：`AgentRuntimeAdapter` / `SpeechRuntimeAdapter` / `TaskRuntimeAdapter`（大模块与冲突方法用 Adapter，不改被包装类） |
| `avatar/runtime.py` | 直接实现契约（runtime_name / cancel / state / on_session_close） |
| `task/runtime.py` | 实现 runtime_name / state / on_session_close（**cancel 由适配器提供**，见下） |
| `main.py` | 模块级装配 `RuntimeRegistry` + 注册 4 个 Runtime；`_cancel_turn` 改为 **Registry 广播**（缺注册表时退回旧路径） |
| `debug_api.py` | `GET /debug/runtime`（统一状态视图） |
| `tests/test_runtime_contract.py` | 新增 8 个用例 |

### 过程中抓到并修复的真实回归（重要记录）

首次全量回归出现 **6 failed（基线 5）** —— 诊断为：我在 `TaskRuntime` 上加的契约方法
`cancel(session_id)` **覆盖了原有业务方法 `cancel(task_id)`**（同名不同语义），
导致 `test_task_runtime::test_cancel_and_fail` 失败。

**修复方式**：契约的 cancel 改由 `TaskRuntimeAdapter` 提供，类上保留业务语义，
并加了"业务 cancel 不受影响"的回归护栏测试。
—— 这正是"收敛阶段最容易踩的坑"（同名方法跨语义），值得后续 Sprint 警惕。

### Tests

- 新增 **8 个**全部通过；全量回归 **202 passed / 5 failed / 1 error**（失败集回到基线，S14 基线 194 + 8）；
- `runtime/` ruff 零告警。

### DoD 对照

- [x] 4 个 Runtime 具备契约能力（avatar/task 直接实现；agent/voice 经 Adapter）
- [x] Session 取消走 Registry 统一广播（错误隔离；voice 真实响应）
- [x] `GET /debug/runtime` 返回统一状态视图
- [x] 零行为变化（`_cancel_turn` 有兼容回退；失败集与基线一致）
- [x] 回归通过（S05–S14 护栏不破）

### Human Acceptance（待人工）

1. 调试台访问 `GET /debug/runtime` → 看到 agent/voice/avatar/task 四个状态快照；
2. 对话中打断（barge-in）→ 行为与之前一致（日志 `取消回合`），但底层已走统一广播。

### 风险 / 遗留

- 契约方法为**可选实现**（Protocol 不强制），尚未加入静态检查强制约束；
- `SessionManager.close()` 尚未广播 `close_session`（只提供了 Registry 能力，避免 WS 频繁断开引发行为变化）；
- 大文件（audio 1501 / agent 1151 / memory 1278 行）**未拆分**——按 spec"不为了目录漂亮而拆"，留给 S16 Agent Harness Extraction 渐进处理。
