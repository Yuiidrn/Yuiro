# S01 — Voice Latency Observatory

> 状态：**已批准执行**（2026-09-11）。
> 性质：只观测、不改行为。为 S02（Session/Generation）与 S03（Barge-in）提供度量与 trace 基建。
> 规范依据：`docs/spec/roadmap.md` §8、`docs/spec/coding-agent-protocol.md`、`docs/spec/target-file-preview.md` §3.3。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 01
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Voice Latency Observatory（语音链路可观测性基线）
SURPRISE: 每次回应的耗时都能被完整解释，不再靠猜
USER EXPERIENCE:
  完成一次交互后，日志/调试面读出完整阶段序列与耗时：
  chat  ：turn_start → llm_first_token → agent_end → reply_sent
  voice ：speech_start → speech_end → asr_final → llm_start → llm_first_token
          → llm_final → tts_first_audio → playback_started(前端回执) → tts_end
ARCHITECTURE:
  Trace 基线（只观测不改行为）：TraceContext + 阶段打点 + 交互级汇总行。
  不新增：Session 实体、Cancellation 传播、TTSTaskManager 接线（留给 S02/S03）。
FILES:
  新增 engine/yuiro/runtime/{__init__.py, trace.py}
  修改 engine/yuiro/main.py（chat_worker / _agent_reply / audio_channel）
  修改 engine/yuiro/audio/__init__.py（_process_audio_chunk / on_speech_end / _speak / interrupt）
  修改 engine/yuiro/agent/__init__.py（AgentLoop.send 加可选 trace：memory_retrieve 打点）
  修改 shell/src/renderer/src/composables/useVoiceInput.ts（playback_started 回执）
  新增 engine/tests/test_trace.py + engine/tests/test_voice_trace.py
CODING AGENT:
  遵循 coding-agent-protocol：Inspect first、最小改动、不改行为、加测试、报告基线。
  禁止重写 VoicePipeline / AgentLoop；禁止改动事件既有语义（仅可选新增字段）。
TEST:
  Unit（TraceContext 行为）+ Scenario（chat 链路一次问答产出完整 trace）
  + 人工验收（真实语音一次，日志含完整 trace 行）
PERFORMANCE:
  产出基线数字：TTFA / TTFT / ASR / TTS / E2E（引擎侧；TTFA 含前端播放回执）
DEFINITION OF DONE:
  - 所有阶段共享同一 trace_id 且有时间戳
  - 日志/调试面可读出一行完整汇总
  - 现有行为不变（回归测试通过 + 人工确认）
  - 基线指标记录在交付报告
HUMAN ACCEPTANCE: 真实说一次话，确认能解释每一秒花在哪
CUSTOM ASSET: （无）
NEXT UNLOCK: 为 S02（Session/Generation）与 S03（Barge-in）提供度量与 trace 基建
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 确认结论（Human 决策）

1. 阶段粒度：采纳本表，`vad_confirmed` 延后；
2. 端到端 TTFA：**需要**前端 `audio:playback_started` 回执（shell 小改）；
3. 执行：已批准。

## 实现要点（执行记录）

- `TraceContext`：`trace_id`(8hex) + `session_id` + `mode` + `mark(stage)`（相对 t0 毫秒；重复 mark 保首个；异常静默）+ `summary()` + `emit()`（vlog + log_ring）。
- voice trace 生命周期：VAD SpeechStart 创建 → 各阶段 mark → `tts_end` 后延迟 2s finalize（容纳前端 `playback_started` 回执）；interrupt 丢弃；重新 SpeechStart 时兜底输出上一条。
- chat trace：`chat:user` 创建 → `reply_sent` 后 emit（finally 保证异常也输出）。
- 前端回执：`useVoiceInput` 在真正开始播放时向 audio WS 发 `{"type":"audio:playback_started"}`（无参数，引擎按 session 关联）。

## 交付报告（2026-09-11 完成）

### Changed files

**新增**：

- `engine/yuiro/runtime/__init__.py`、`engine/yuiro/runtime/trace.py`（TraceContext：mark / get / elapsed_ms / summary / emit）
- `engine/tests/test_trace.py`（Unit）、`engine/tests/test_voice_trace.py`（Scenario，Fake 组件）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/main.py` | `_agent_reply` 增加可选 `trace` 参数与打点（agent_start / llm_first_token / agent_end）；`_llm_reply` 从 VoicePipeline 只读获取 trace（**不改 llm_callback 签名**）；`chat_worker` 创建并输出 chat trace；`audio_channel` 处理 `audio:playback_started` 回执 |
| `engine/yuiro/audio/__init__.py` | VoicePipeline 新增 `_traces` + 4 方法（`_start_trace` / `get_trace` / `mark_playback_started` / `_finalize_trace`）；SpeechStart / SpeechEnd / asr_final / llm_start / llm_final / tts_start / tts_first_audio / tts_end 打点；`interrupt` 丢弃 trace；`tts_end` 后延迟 2s 汇总（容纳前端回执） |
| `engine/yuiro/agent/__init__.py` | `AgentLoop.send` 增加可选 `trace` 参数 + `memory_retrieve` 打点（缺省 None 时零行为变化） |
| `shell/src/renderer/src/composables/useVoiceInput.ts` | 真正开始出声时经 audio WS 回执 `{"type":"audio:playback_started"}` |

### Tests

- 新增 **11 个**（5 Unit + 6 Scenario），全部通过；
- 全量回归：**67 passed**（含本 Sprint 新增 11 个）；失败集与改动前基线**完全一致**（4 个 `test_audio` mock 用例因冷启动门控未同步 + 2 个 Windows Temp 权限问题；已用 `git stash` 对照实验证实均非本 Sprint 引入）；
- ruff：新增文件与新增代码区间全部干净（既有代码的历史告警未扩大）。

### 基线指标（真实链路实测）

**chat 链路（`TestClient` 冒烟，真实 LLM）**：

```
[yuiro][trace] trace=b71104ab session=4b5606b6 mode=chat e2e=3339ms |
turn_start=0 agent_start=0 memory_retrieve=46 llm_first_token=2664 agent_end=3337 reply_sent=3339
```

- 记忆检索 **46ms**；LLM 首 token **2664ms**；收尾 **2ms**；E2E **3339ms**。

**voice 链路（2026-09-11 真实语音验收）**：

```
[yuiro][trace] trace=c36f355a session=c0e0e856 mode=voice e2e=9848ms |
speech_start=0 speech_end=2232 agent_start=2986 memory_retrieve=2996 asr_final=2985
llm_start=2986 llm_first_token=5483 llm_final=6003 tts_start=6081 tts_first_audio=9755
playback_started=9848 tts_end=9755 agent_end=6003
```

| 阶段 | 耗时 | 占"说完→出声" |
|---|---|---|
| 说话时长（不计延迟） | 2232ms | — |
| VAD 判定 → ASR 完成 | **753ms** | 10% |
| LLM 首 token（TTFT） | **2497ms** | 33% |
| LLM 生成余量 | 520ms | 7% |
| TTS 合成 + 回传（整段 822KB） | **3674ms** | **48%（最大瓶颈）** |
| 前端解码 → 真正出声 | 93ms | 1% |
| **说完 → 出声（真实延迟）** | **7616ms** | 100% |

**瓶颈结论（供 Wave 1 决策）**：

1. TTS 整段合成是最大瓶颈（≥48%）→ Wave 1 的"分段流式 + TTSTaskManager 有序播放"应优先让**首句先合成先播**；
2. LLM TTFT 33% 属外部 API 延迟，可通过更快模型/Provider 缓解（属配置与 Provider 层）；
3. ASR 753ms 与前端解码 93ms 均正常，无需优化。
4. `tts_first_audio` 与 `tts_end` 目前同刻（整段合成），Wave 1 分段后二者将分离，可分别度量"首段音频"与"全部音频"。

### 架构影响

- 新增 `runtime/` 包（Wave 0 的第一个落点），`TraceContext` 即 S02 Session/Generation 的观测基座；
- 所有打点为旁路，不改控制流、不改事件载荷；`llm_callback` / `play_callback` 签名保持不变（零兼容风险）。

### 风险 / 遗留

- 语音 trace 汇总有 **2s 延迟**（等待前端 `playback_started` 回执），日志时间晚于交互结束——预期行为；
- 既有 `test_audio` 4 个失败与 Temp 权限问题建议单独排期修复（非 S01 范围）；
- `NEXT UNLOCK`：S02（Session & Generation 统一）可直接复用 `TraceContext` 与 `trace_id`。

### Human Acceptance（2026-09-11 已通过 ✓）

真实语音一次，`engine_start.out.log` 出现完整语音 trace 行（含 `playback_started` 回执阶段）；
阶段序列正确、E2E 可解释；语音基线已记录（见上表）。
