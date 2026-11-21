# S03 — 真 Barge-in（取消传播链）

> 状态：**已批准开工**（2026-09-11，Human 指令"按照建议继续"）。
> 性质：Wave 1 核心（SpeechRuntime 接入的第一步）；建立 `Session.cancel` 统一入口。
> 规范依据：`docs/spec/runtime-contract.md` §4（Cancellation Protocol）、`docs/spec/roadmap.md` §8。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 03
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    真 Barge-in —— 取消传播链
SURPRISE: 用户说"等等！"，Yuiro 立刻闭嘴，且后台不再偷偷继续生成
USER EXPERIENCE:
  - 语音打断：Yuiro 说话中，用户开口 → 立即停声 + 前端立即停播（本地操作，不等引擎往返）
  - 不再出现"TTS 停了但 LLM 还在后台跑完"的隐形消耗
  - 日志可查打断原因与停止结果
ARCHITECTURE:
  - SessionManager.cancel() —— 统一取消入口（代际作废 + 编排）
  - VoicePipeline：LLM 回合可取消（_turn_tasks）+ interrupt() 增强 + `tts:interrupted` 事件
  - main：_cancel_turn 编排（sessions.cancel + pipeline.interrupt + session.cancelled 事件）；
    VAD barge-in 与前端 interrupt 共用同一条路径
  不做：TTSTaskManager 接线（与分段流式在 S04 合并——epoch 取消只有配合分句才有真实收益）；
        文字链路强取消（chat 队列保持串行，属既有行为）
FILES:
  engine/yuiro/runtime/session.py（cancel 入口）
  engine/yuiro/audio/__init__.py（turn task / interrupt / barge_in_callback）
  engine/yuiro/main.py（_cancel_turn / audio 通道 / pipeline 注入）
  shell/src/renderer/src/composables/useVoiceInput.ts（tts:interrupted → 立即停播）
  engine/tests/test_barge_in.py（新增）
CODING AGENT:
  遵循 coding-agent-protocol：最小改动、兼容优先（未注入回调时回退旧行为）、加测试。
  禁止重写 VoicePipeline；禁止改变现有事件的既有字段语义。
TEST:
  Unit：SessionManager.cancel（代际自增）；interrupt 取消 LLM 回合；tts:interrupted 发出
  + 回归（对照基线：5 failed 集不变）
PERFORMANCE:
  Interrupt → 前端停播 < 100ms（前端本地清队列 + 停口型，不等引擎）
DEFINITION OF DONE:
  - 语音打断走统一入口 _cancel_turn（VAD 与前端 interrupt 同一路径）
  - LLM 回合在打断后立即结束（不再后台跑完），且不进入 TTS
  - 前端收到 tts:interrupted 立即清播放队列 + 停口型
  - 打断后会话可用（下一轮正常工作）；旧代际结果不污染（复用 S02 语义）
  - 回归通过；无 session/无回调的旧路径行为不变
HUMAN ACCEPTANCE:
  Yuiro 说话中开口打断 → 立即静音且不再出声；连续打断 3 次仍正常
CUSTOM ASSET: （无）
NEXT UNLOCK: 为 S04（TTSTaskManager + 分段流式）提供 epoch/取消语义与前端停播能力
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 取消传播链（本 Sprint 实现）

```
用户开口（VAD SpeechStart） / 前端 interrupt
        │
        ▼
_cancel_turn(session_id, reason)            ← main 编排（统一入口）
        ├── sessions.cancel()               ← 代际作废（旧结果沿 S02 路径丢弃）
        ├── voice_pipeline.interrupt()      ← 取消 LLM 回合 task + TTS 播放 task
        │        └── emit "tts:interrupted" ← 前端立即清队列 + 停口型
        └── events.publish("session.cancelled")
```

## 兼容性红线

- 未注入 `barge_in_callback` 时，VoicePipeline 回退到本地 `interrupt()`（行为同旧）；
- `interrupt()` 对外仍是同步方法（不改变调用方）；
- `tts:interrupted` 为**新增**事件（前端不处理时静默忽略，无副作用）。

## 交付报告（2026-09-11 完成）

### Changed files

**新增**：`engine/tests/test_barge_in.py`（4 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/runtime/session.py` | `SessionManager.cancel()` 统一入口（代际作废；保持同步不阻塞，编排由 main 负责） |
| `engine/yuiro/audio/__init__.py` | `barge_in_callback` 注入点（未注入时回退本地 interrupt）；`_turn_tasks`（LLM 回合 task）；`on_speech_end` 把 LLM 调用包成可取消 task（取消后立即结束、不进入 TTS）；`interrupt()` 增强（取消回合 + 发 `tts:interrupted`）；VAD SpeechStart 走统一回调 |
| `engine/yuiro/main.py` | `_cancel_turn()` 编排（代际 + 停语音 + `session.cancelled` 事件）+ `_schedule_cancel()` 同步包装；`/ws/audio` interrupt 走统一入口；VoicePipeline 注入 `barge_in_callback` |
| `shell/.../useVoiceInput.ts` | `stopPlayback()`（清播放队列 + 停当前段 + 停口型）；处理 `tts:interrupted` |

### 取消传播链（已实现）

```
用户开口（VAD SpeechStart） / 前端 interrupt
        ▼
_cancel_turn(session_id, reason)              ← 统一入口（main 编排）
        ├── sessions.cancel()                 ← 代际++（旧结果沿 S02 语义丢弃）
        ├── voice_pipeline.interrupt()        ← 取消 LLM 回合 + TTS 播放
        │        └── emit "tts:interrupted"   ← 前端立即停播（本地操作）
        └── events.publish("session.cancelled")
```

### Tests

- 新增 **4 个**全部通过；S01–S03 合计 **25 个**新测试全过；
- 全量回归 **81 passed**；失败集与基线一致（5 failed + 1 error，均非本 Sprint 引入）；
- ruff 全绿；前端 `pnpm typecheck` 通过；
- 修复 1 个 `RuntimeWarning`（同步调用场景 coroutine 未 await → 改为"检查 loop 再建 task"）。

### 冒烟证据

```
BEFORE: session=3799ddf2 gen=0
[yuiro][voice] [3799ddf2] 打断 (barge-in)：LLM 回合与 TTS 已取消，已通知前端停播
[yuiro][event] [3799ddf2] session.cancelled (gen=1, src=SessionManager) {'reason': 'smoke-test'}
[yuiro][cancel] [3799ddf2] 取消回合（reason=smoke-test, gen=1）
AFTER: gen=1
```

### DoD 对照

- [x] 语音打断走统一入口 `_cancel_turn`（VAD 与前端 interrupt 同一路径，Unit 覆盖回调优先级）
- [x] LLM 回合在打断后立即结束（`turn.cancel()`，测试验证"LLM 未跑完且未进入 TTS"）
- [x] 前端收到 `tts:interrupted` 立即清队列 + 停当前段 + 停口型
- [x] 打断后会话可用（`test_pipeline_usable_after_interrupt`）
- [x] 无回调的旧路径行为不变（回退分支）；回归通过

### Human Acceptance（待人工）

1. Yuiro 说话中开口打断 → **立即静音**且后台不再继续生成；
2. 连续打断 3 次仍正常；
3. 打断后继续说下一句，链路正常。

### 风险 / 遗留

- 文字链路强取消未做（chat 队列保持串行，属既有行为；如需"发新消息即打断旧回合"列入后续 Sprint）；
- `TTSTaskManager` 接线 + 分段流式 = **S04**（epoch 取消与分句一起做才有收益，已在 Plan 顶部说明）。
