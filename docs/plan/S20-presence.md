# S20 — Presence（Wave 7：它真的住在桌面上）

> 状态：**进行中**（2026-09-13）。
> 来源：`docs/spec/roadmap.md` Wave 7 +
> `docs/spec/阶段性总评和后续方向.md`（Presence 成熟度 15%，是目前最低的一块）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 20
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Presence —— 从"定时轮询打招呼"到"事件驱动 + 注意力策略"
SURPRISE: 你离开一会儿回来，它说"回来啦"；事情办成了，它主动告诉你
ARCHITECTURE:
  Event ──▶ PresenceRuntime ──▶ ProactiveIntent ──▶ AttentionPolicy ──▶ 交付
                                                    ├─ proactive:intent（气泡）
                                                    └─ avatar.perform（表演）
  约束（spec 原文）：
   1. "必须 event-driven + policy-driven，不是 LLM 每秒问一次我要不要说话"；
   2. "必须克制：Attention Policy + Cooldown + User Preference
      + Context Awareness + Quiet Hours + Confidence"；
   3. "低 urgency 只抬头/气泡，高 urgency 才 TTS"。
  迁移策略：`proactive/` 保留不动（旧配置与代码零破坏），presence 默认接管调度。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 设计

| 层 | 职责 | 文件 |
|---|---|---|
| Intent | `ProactiveIntent{urgency, channel, performance, confidence}` + `Urgency`/`Channel` | `presence/intent.py` |
| Policy | 裁决"该不该打扰"（Quiet Hours → Cooldown → Confidence → 上下文降级 → 偏好降级） | `presence/attention.py` |
| Runtime | 事件驱动（task.completed/failed、session.*）+ 空闲 tick + 交付 | `presence/runtime.py` |
| 配置 | `[presence]`（cooldown / quiet_hours / max_urgency / idle_trigger / tick） | `config.py` + toml |
| 前端 | `proactive:intent` → 说话云框（保留 `proactive:greet` 兼容） | `App.vue` |

**核心取舍：降级而非丢弃** —— 用户活跃时把"出声/表演"降为"气泡"，
内容仍然可见（避免"想说却憋住"的另一种体验缺陷）。

## 交付报告（2026-09-13 完成）

### Changed files

**新增**：`engine/yuiro/presence/{__init__.py, intent.py, attention.py, runtime.py}`、
`engine/tests/test_presence.py`（21 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/config.py` | 新增 `PresenceConfig`（enabled / cooldown_s / quiet_hours / max_urgency / idle_trigger_s / tick_s）+ AppConfig 字段 + load_config + TOML_SECTIONS + FIELD_META（调试台可调） |
| `engine/config.toml` + `config.example.toml` | 新增 `[presence]` 段 |
| `engine/yuiro/main.py` | 装配 `PresenceRuntime`（AttentionPolicy + broadcast + avatar_getter）；`subscribe_all(on_event)`；lifespan 启停（**presence 优先，未启用时回退 M5 proactive**）；`_agent_reply` 记录用户在场信号 |
| `engine/yuiro/debug_api.py` | `GET /presence/state`（空闲/冷却/静默/裁决计数）+ `POST /presence/nudge`（手动提交，同样经策略裁决） |
| `shell/.../App.vue` | `proactive:intent` → 说话云框 + 日志（保留 `proactive:greet` 兼容） |

### 冒烟证据（5 个场景）

```
TASK DONE: 整理下载文件夹 办好了。        | normal / bubble     ← 事件驱动
COOLDOWN:  False | 冷却中（还需 899s）                          ← 克制
IDLE GREET: 回来啦。 | performance: greet                       ← 空闲触发 + 表演
ACTIVE DOWNGRADE: True | 用户活跃中 → 降级为气泡 | channel: bubble  ← 降级不丢弃
QUIET: False | 静默时段（quiet hours）| quiet_now: True          ← 静默时段
STATE: {candidates: 4, delivered: 3, suppressed: 1, downgraded: 1}
```

### 一个设计瑕疵（测试逼出）

初版在**降级时覆盖了 intent.reason**（`task_done` → `user-active`），触发原因在观测中丢失；
且对"本来就是气泡"的 intent 也标记降级（降级了个寂寞）。修正为：

- `reason` **始终保留触发原因**（`task_done` / `idle_return` / `task_failed`）；
- 仅当 `channel != BUBBLE` 时才真正降级（已是最低打扰通道则直接放行）。

### Tests

- 新增 **21 个**全部通过；全量回归 **264 passed / 5 failed / 1 error**（失败集与基线一致）；
- `presence/` 与测试文件 ruff 零告警；前端 `pnpm typecheck` 通过。

### DoD 对照

- [x] **事件驱动**：`task.completed` / `task.failed` / `session.*` → 候选 Intent（非轮询 LLM）
- [x] **Attention Policy 六要素**：Quiet Hours（跨午夜）/ Cooldown / Confidence / Context Awareness / User Preference / 降级
- [x] `ProactiveIntent{urgency, interruptibility, channel, performance, confidence}`
- [x] **降级而非丢弃**（用户活跃时降为气泡，内容仍可见）
- [x] 交付：`proactive:intent` 气泡 + `avatar.perform` 表演（S18 表演库复用）
- [x] 配置可调（含调试台表单）；`proactive/` 旧路径零破坏（兼容回退）
- [x] 可观测：`GET /presence/state` + `POST /presence/nudge`；回归通过

### Human Acceptance（待人工）

1. 对 Yuiro 说完一件事后**静置 30 分钟**（或把 `idle_trigger_s` 临时改小）→ 预期它说"回来啦"；
2. 让它跑一个多步任务（`task_create` → 逐步 `task_advance`）→ 任务完成时**主动告知**（气泡）；
3. 把 `quiet_hours` 设为当前时段（如 `"00:00-23:59"`）→ 确认它**什么都不说**（日志 `[主动克制] 静默时段`）；
4. `GET /debug/presence/state` 观察 `idle_s` / `cooldown_left_s` / `counters`。

### 风险 / 遗留

- **`voice` 通道 v1 未落地**：`Channel.VOICE` 已建模并被策略正确降级，但交付层仍走气泡
  （主动出声需要"为主动表达创建/复用会话 + TTS 编排"，属后续）；
- **系统事件未接入**：spec 举例的「Build completed → 欸，刚刚编译成功了」需要终端/IDE 事件源，
  当前消费的是 Task 事件与时间（Task 覆盖了"它替我做完一件事"的主场景）；
- `AttentionObserver`（截图观察）未接进 PresenceRuntime（M5 的视觉观察路径保留在 `proactive/`）；
- 打扰率/有用率指标未做埋点（spec 的 Intervention quality 需要长期数据）；
