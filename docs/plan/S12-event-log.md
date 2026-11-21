# S12 — Event Log（落盘 + Replay）

> 状态：**已完成**（2026-09-12，Human 指令"全部进行"）。
> 性质：补 spec 六实体最后缺口——Event 从"内存总线"升级为"可持久化、可回放"。
> 规范依据：`docs/spec/README.md` §3（Event = 已经发生了什么，可持久化、可回放）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 12
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Event Log —— 事件落盘与回放
SURPRISE: 一次交互的全过程可回查（"刚才到底发生了什么"不再靠日志翻找）
ARCHITECTURE:
  - 新增 runtime/event_log.py：EventLog（JSONL 追加落盘 + load/replay + 轮转 + 统计）
  - EventBus 新增 subscribe_all（全局订阅；EventLog 作为横切订阅者）
  - debug_api 新增 GET /debug/events（回放某会话事件 + 会话列表/统计）
不做：完整 Replay 引擎（重放驱动状态）、前端事件浏览器 UI、冷热分层存储
FILES:
  engine/yuiro/runtime/event_log.py（新增）
  engine/yuiro/runtime/events.py（subscribe_all）
  engine/yuiro/main.py（装配 EventLog 为全局订阅者）
  engine/yuiro/debug_api.py（GET /debug/events）
  engine/tests/test_event_log.py（新增 10 用例）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 交付报告（2026-09-12 完成）

### 冒烟证据

```
[yuiro][event] [smoke1] agent.stale_discarded (gen=0, src=smoke) {'i': 0}
...（6 条事件）...
STATS: {'dir': '...\\events', 'sessions': 1, 'lines': 6}
REPLAY: 6 ['agent.stale_discarded', 'agent.stale_discarded', 'agent.stale_discarded']
```

### 过程中修复的真问题

事件轮转的触发频率写成了 `n % max_lines == 0`——恰好整百条时文件只有 100 行（未超限不轮转），
之后永远触发不到 → 改为每 `max_lines/2` 条检查一次（测试 `test_trim_on_max_lines` 抓出）。

### Tests

- 新增 **10 个**全部通过（落盘/回放/过滤/损坏行容忍/轮转/统计/落盘失败静默/全局订阅）；
- 全量回归 **183 passed**（S11 基线 173 + 10），失败集与基线一致；
- `runtime/` ruff 零告警。

### DoD 对照

- [x] 所有 AgentEvent 经 EventBus 自动落盘（JSONL，按会话分文件）
- [x] `load` / `replay` 可按会话回放（时间升序、type 过滤、limit）；
- [x] 损坏行/落盘失败均不影响主链路（静默）
- [x] 单文件超限自动轮转（保留最近一半）
- [x] 调试 API `GET /debug/events` 可浏览会话列表与事件流
- [x] 回归通过

### Human Acceptance（待人工）

1. 跑几次对话后访问 `http://127.0.0.1:8200/debug/events`（带鉴权头）→ 应看到会话列表与统计；
2. `GET /debug/events?session_id=<id>` → 能看到该会话的完整事件序列（session.started / agent.stale_discarded / …）。

### 风险 / 遗留

- 无完整 Replay 引擎（不能"重放驱动状态"）；无前端事件浏览器 UI；
- 单文件轮转是行级近似（非按时间窗口）；事件量大时建议后续做冷热分层。
