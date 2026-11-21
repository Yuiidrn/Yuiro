# S22 — Presence 深化（voice 通道 / 系统事件 / Intervention quality）

> 状态：**进行中**（2026-09-13）。
> 来源：S20 的三项遗留（见 `S20-presence.md` 风险/遗留）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 22
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Presence 深化 —— 会出声、能接外部事件、可量"有用率"
SURPRISE: 编译成功它出声说一句（而不只是气泡）
ARCHITECTURE:
  1. VoicePipeline.speak_text()（公开主动说话入口；忙时自行跳过，不打断对话）
  2. PresenceRuntime: voice_speaker 注入 → Channel.VOICE 真正出声
     （失败/未注入 → 退化为气泡，内容永不丢失）
  3. system.* 事件通用入口（EventBus + POST /debug/presence/system-event）
  4. Intervention quality：主动表达后用户是否在窗口内回应 → useful_rate
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 设计要点

| 项 | 决策 |
|---|---|
| 主动说话 | **复用对话 TTS 编排**（分段流式 + 口型 + 可中断），但**该会话正在说话时直接跳过**——主动表达永不抢占用户正在听的对话 |
| 失败降级 | voice 失败 → 内容仍经 `proactive:intent` 气泡可见（与 S20 的"降级而非丢弃"一脉相承） |
| 系统事件 | 事件只需带 `hint`（要说什么）；**是否真说出口仍由 AttentionPolicy 决定**（保持"想说 ≠ 说出口"的单一裁决点） |
| 有用率 | 近似指标：表达后 `respond_window_s`（默认 120s）内用户发言 → 记为有响应 |

## 交付报告（2026-09-13 完成）

### Changed files

| 文件 | 改动 |
|---|---|
| `engine/yuiro/audio/__init__.py` | 新增 `VoicePipeline.speak_text()`（公开主动说话入口；**忙时直接跳过**，不抢占对话）；补 `__all__`（明确导出，修 S16b 遗留的 re-export F401） |
| `engine/yuiro/presence/runtime.py` | `voice_speaker` 注入 + `Channel.VOICE` 真正出声（失败退化气泡）；`system.*` 事件通用入口（`hint`/`urgency`/`channel` 可从 payload 透传）；Intervention quality（`_pending_response` + `responded` + `state()["intervention_quality"]`） |
| `engine/yuiro/main.py` | `_presence_speak()`（复用 VoicePipeline）+ 注入 `voice_speaker` |
| `engine/yuiro/debug_api.py` | `POST /presence/system-event?text=&kind=&urgency=`（外部集成入口） |
| `engine/tests/test_presence_voice.py` | 新增 11 个用例 |

### 冒烟证据

```
SYSTEM EVENT: 欸，刚刚编译成功了。| channel: voice
SPOKEN: ('sess-1', '欸，刚刚编译成功了。')        ← 真正出声
LOW URGENCY CHANNEL: bubble | spoken count: 1     ← 低 urgency 只气泡，不出声
QUALITY (responded):   {'delivered': 2, 'responded': 1, 'useful_rate': 0.5}
QUALITY (late reply):  {'delivered': 3, 'responded': 1, 'useful_rate': 0.33}  ← 超窗口不计数
VOICE FAILED → bubble ok: True                     ← 出声失败退化为气泡
```

### Tests

- 新增 **11 个**全部通过；全量回归 **275 passed / 5 failed / 1 error**（失败集与基线一致）；
- `presence/`、`test_presence_voice.py` ruff 零告警；`audio/__init__.py` 本次引入的告警已修（余 4 个为既有）。

### DoD 对照

- [x] `Channel.VOICE` 真正出声（复用对话 TTS 编排；忙时跳过）
- [x] 出声失败/未注入 → 退化为气泡（内容永不丢失）
- [x] `system.*` 事件通用入口（EventBus + HTTP API），spec 的「Build completed」用例有接入点
- [x] Intervention quality 可观测（`useful_rate` 近似指标）
- [x] 回归通过（S20 的 21 个用例仍全绿）

### Human Acceptance（待人工）

1. `POST /debug/presence/system-event?text=欸，刚刚编译成功了。&urgency=high` → 应**听到**它说这句话；
2. 同上一句但 `urgency=low` → **只看到气泡**、不出声；
3. 主动表达后你立刻回一句话 → `GET /debug/presence/state` 的 `useful_rate` 上升。

### 风险 / 遗留

- 主动说话**不打断**正在进行的对话（有意）；若用户此时在说话，会静默跳过（记为"跳过"而非失败）；
- `useful_rate` 是**近似指标**（用户发言 ≠ 因它而起）；严谨归因需要 LLM 判定，属后续；
- 系统事件源仍需外部集成方（终端/IDE/脚本）主动调用（引擎不猜测系统状态）。
