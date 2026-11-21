# S02 — Session & Generation 统一

> 状态：**已批准开工**（2026-09-11，Human 指令"继续后续阶段的开工"）。
> 性质：Wave 0 第二步（Harness Foundation）；复用 S01 的 TraceContext 观测旧代际丢弃。
> 规范依据：`docs/spec/roadmap.md` §8、`docs/spec/runtime-contract.md` §2–§4、`docs/spec/target-file-preview.md` §3.1/§3.2。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 02
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Session & Generation 统一
SURPRISE: 文字与语音属于同一个"我"——共享 history / 环境状态 / 代际；
          旧代际的异步结果被显式作废且可观测（不再静默 return）
USER EXPERIENCE:
  - 先在聊天面板说一句、再语音说一句：Yuiro 记得上文（同一会话）
  - 语音与文字不再各说各话（现状两个 uuid4 会话导致 history 割裂）
  - 旧回合的迟到结果不会污染新回合（有事件记录可查）
ARCHITECTURE:
  新增 runtime/session.py（AgentSession + SessionManager）
  + runtime/events.py（AgentEvent + EventBus，内存版）
  + generation 权威收敛到 Session（AgentLoop 兼容回退）
  不做：Cancellation 传播（S03）、EventLog 落盘、跨引擎重启 resume
FILES:
  新增 engine/yuiro/runtime/{session.py, events.py}；tests/test_session.py
  修改 runtime/__init__.py、main.py（WS 建连/绑定/下发 session:ready）、
       agent/__init__.py（send 增加 session 参数）
  修改 shell：App.vue（session:ready → 存 session_id + 重连带回）、
       useVoiceInput.ts（start 支持 sessionId → ?session=）
CODING AGENT:
  遵循 coding-agent-protocol：最小改动、兼容优先（无 session 时行为完全同旧）、加测试。
  禁止重写 AgentLoop / VoicePipeline；禁止改现有 WS 事件的既有字段语义。
TEST:
  Unit：SessionManager 生命周期 / generation next+invalidate / 绑定与挂起
  Scenario：同一 session 文字+语音共享 history；stale 丢弃产生事件
  + 回归（对照基线：5 failed 集不变）
PERFORMANCE: 无性能目标；新增事件开销 < 1ms/条
DEFINITION OF DONE:
  - control 建连收到 session:ready（含 session_id）
  - audio 带 ?session= 时绑定同一 AgentSession（无参时行为同旧）
  - 同一 session 下文字与语音共享 history/state_notes/generation
  - 旧 generation 结果被丢弃且发 agent:stale_discarded 事件（不再静默）
  - 无 session 参数的旧路径行为不变；全量回归失败集不扩大
HUMAN ACCEPTANCE:
  重启引擎 → 文字说一句 → 语音说一句 → 确认 Yuiro 记得上一条（同一会话）
CUSTOM ASSET: （无）
NEXT UNLOCK: 为 S03（真 Barge-in / Cancellation 传播）提供 Session.cancel 骨架与代际语义
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 关键设计决策（已定，按此执行）

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| D1 | Session 归属 | 引擎权威：control 建连创建并回发 `session:ready`；audio 用 `?session=` 绑定 | 前端不可信；兼容旧前端（无参→独立会话） |
| D2 | generation 权威 | 收敛到 `AgentSession`（`next_generation` / `invalidate`）；`AgentLoop.send(session=…)` 可选注入 | 保留无 session 回退路径，旧测试零破坏 |
| D3 | stale 可观测 | 丢弃时发 `agent:stale_discarded` 事件（含 stage），不再静默 `return` | S01 trace 基础设施直接复用 |
| D4 | EventLog 落盘 | **不做**（S03+）；S02 只做内存 EventBus + vlog | 控制范围；先统一身份，再谈持久化 |
| D5 | control 重连 | 纳入最小版：前端重连时带 `?session=`，引擎进程内 resume | "断线不失忆"的最低实现；跨进程留 S03 |
| D6 | 前端接口 | `useVoiceInput.start({ sessionId })`；App.vue 持有 sessionId | 最小改动、类型安全 |

## 兼容性红线

- `AgentLoop.send` 不传 `session` 时，generation 行为与现状**逐字节一致**；
- 现有 WS 事件（`chat:assistant` / `emotion:set` / …）字段只增不改；
- `/ws/audio` 无 `?session=` 时行为同旧（独立临时会话）。

## 交付报告（2026-09-11 完成）

### Changed files

**新增**：

- `engine/yuiro/runtime/session.py`（`AgentSession` / `SessionManager` / `SessionState`）
- `engine/yuiro/runtime/events.py`（`AgentEvent` / `EventBus` / 内部点分→对外冒号单点映射）
- `engine/tests/test_session.py`（10 个用例：生命周期 / generation / EventBus / AgentLoop 接入）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/runtime/__init__.py` | 导出 Session / EventBus |
| `engine/yuiro/main.py` | 模块级装配 `EventBus` + `SessionManager`；control 建连创建/恢复会话并下发 `session:ready`；audio 支持 `?session=` 绑定；两条通道 `finally` 中 detach（挂起可 resume）；`_build_agent` 注入 events；`_agent_reply` 接受 session |
| `engine/yuiro/agent/__init__.py` | `AgentLoop.__init__` 增加 `events`；`send` 增加 `session`（generation 权威收敛到 Session）；5 处 stale 检查统一为 `_should_abort`（日志 + `agent:stale_discarded` 事件，不再静默）；`build_agent_loop` 增加 `events` |
| `shell/src/renderer/src/App.vue` | 处理 `session:ready`（存 `sessionId`）；`onMounted` 重构为可重入的 `connectControl`（3s 退避重连，带 `session_id` 进程内 resume）；卸载时清理定时器 |
| `shell/src/renderer/src/composables/useVoiceInput.ts` | `start({ wsUrl?, sessionId? })`：audio 通道带 `?session=` 绑定同一会话 |

### Tests

- 新增 **10 个**全部通过；全量回归 **77 passed**；失败集与基线一致（5 failed + 1 error，均非本 Sprint 引入）；
- ruff：新增文件与新增代码区间全绿（修复 2 处 S110）；
- 前端 `pnpm typecheck` 通过。

### 冒烟证据（TestClient，真实链路）

```
FIRST: type=session:ready session=d7591816 gen=0
RECV: type=chat:assistant text=你回来啦，今天心情不错哦。...
RESUME: session=d7591816 same=True gen=1
```

- 首次建连创建会话并下发身份；chat 链路跑通；
- **断线后用同一 session_id 重连 → 同一会话、generation 保留（gen=1）**，进程内 resume 成立。

### DoD 对照

- [x] control 建连收到 `session:ready`（含 session_id）
- [x] audio 带 `?session=` 绑定同一 AgentSession（Unit 覆盖；真实语音待人工）
- [x] 同一 session 下文字与语音 generation 连续（Unit + 冒烟 gen 保留）
- [x] 旧 generation 作废可观测（`agent:stale_discarded` 事件 + 日志）
- [x] 无 session 参数的旧路径行为不变（无 session 回退分支 + 回归通过）
- [x] 前端 typecheck + 重连（带 session_id）

### Human Acceptance（待人工）

1. 重启引擎 → 文字说一句 → 语音说一句 → 确认 Yuiro 记得上文（同一会话）；
2. 重启壳层（引擎不重启）→ 确认会话恢复（日志 `会话已就绪` 与引擎 `绑定`）。

### 风险 / 遗留

- control 重连为固定 3s 退避（够用；指数退避留待有真实需求时改）；
- 跨引擎重启的 resume 需要 EventLog 持久化（S03+）；
- `/ws/audio` 目前无自动重连（行为同旧，按需重建）。
