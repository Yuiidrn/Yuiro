# S35 + S36 + S37 — 任务续跑 / 媒体信息 / 延迟（一次性实现）

> 状态：**完成**（2026-09-14）。
> 触发：用户对 S34 诊断清单（`S34-motion-and-output-hygiene.md` §3）的逐条修复要求：
> "一次性全部实现" —— 即 S35（任务续跑 + 结果可见性）、S36（音乐媒体）、S37（延迟）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
S35  任务续跑 —— "说一句就把多步任务跑起来"
S36  媒体信息 —— "它知道自己（和你）在放什么歌"
S37  延迟    —— "trace 不再串线，首段更快出声"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## S35 — 任务续跑 + 结果可见性

### 1.1 问题

实测（日志）：`task_plan → task_create → "计划确认，任务已创建，现在开始第一步扫描文件"`
**之后没有任何工具调用** —— 用户看到的就是"空壳"。

**根因不是功能没写**，而是**没有驱动**：

```
task_plan → PENDING_APPROVAL → approve → RUNNING ──┐
                                                    │ 谁推进？
task_advance(step, status) ←── 只有 LLM 主动调用 ───┘
```

`TaskRuntime` 的状态机 / Journal / 重启恢复 / 失败重试 / 审批都齐了，缺的是"执行第 1 步 →
检查 → 第 2 步"的循环。LLM 一轮产出文本后循环即终止。

### 1.2 修法：注入「任务续跑」提示（不代执行）

引擎不替 LLM 干活（只有 LLM 看得懂步骤语义），只负责"别说完就停"：

- 检测本轮调用了 `task_create` / `task_advance` / `task_retry` → 置标志；
- 下一轮 LLM 调用前注入 system 提示：**"立刻动手执行当前步骤…不要只描述计划"**；
- 上限 **2 次**（避免与"无进展早停"相互抵消、也避免烧 token）。

### 1.3 踩坑记录（值得记住的架构事实）

**初版失败**：直接在循环末尾 `messages.append(提示)` —— 日志显示提示已注入，**模型却看不到**。

原因：**每轮 LLM 调用都会 `_build_messages()` 重建 messages**（`agent/__init__.py` 内注释：
"每轮重建消息：让状态摘要/最新 history 反映上一轮工具执行后的状态"）。
工具结果靠 `_update_state` → StateNotes 跨轮传递，**不是**靠 messages 累积。

修正：**只置标志，由循环开头在重建之后注入**。这一点已写进代码注释，避免后人再踩。

### 1.4 结果可见性（artifact 幻觉与反复重拉）

| 现象 | 根因 | 修复 |
|---|---|---|
| LLM 编造 `art_9f8e7d6c5b4a3210` | artifact id 只存在于**当轮** tool 消息里，跨轮即失 | `artifact_read` 报错文案改为**明确引导**："id 不跨轮记忆，不要凭印象编造；如需最新内容请重新调用原工具" |
| `netease_recommend` 连调 3 次、端到端 **18 秒** | 歌单结果超 2000 字符被截成**半截 JSON** → LLM 解析不了 → 以为失败 → 重拉 | ① `tool_result_max_chars` 2000 → **3500**（默认值 + `config.toml`）；② `_brief_song` 去掉模型用不上的 `vip` 字段；③ `clip_tool_result` 提示语明确"本轮内可读、跨轮请重新调工具" |

---

## S36 — 音乐媒体

| # | 问题 | 证据 | 修复 |
|---|---|---|---|
| P0 | `media-title` 是哈希文件名 → **用户和 LLM 都不知道在放什么** | `"title": "3ac3424e4c7fd1948e8bb2a01025cb12.mp3"` | `play_urls(urls, titles)` 把歌名作为 **`force-media-title`** 传给 `loadfile`（第 4 个 per-file options 参数）；老版本 mpv 拒绝时**自动降级**重发（至少保证能播） |
| P0 | 刚切歌时 `duration: 0.0`，易被当成"0 秒的歌" | 同上日志 | `get_state()` 新增 **`ready`** 字段（title 有且 duration > 0）；`control("state")` 单独补查 `volume` |
| P1 | 歌单结果超长 → 反复重拉 | 见 S35 §1.4 | 截断阈值 2000 → 3500；`_brief_song` 精简 |
| P1 | `queueLength: 0` 与实际 5 首不符 | 切歌瞬间查询过早 | 保持读真实值（`playlist-count/-pos`）；`ready` 字段已能表达"未就绪" |

---

## S37 — 延迟

### 3.1 trace 串线（真 bug，已修）

**现象**：

```
trace=c90738bb ... speech_start=0 speech_end=1098 tts_start=75 tts_first_audio=7875
                                  ↑ tts_start=75ms 早于 speech_start —— 时序矛盾
```

**根因**：`_speak()` 内部 `self.get_trace(session_id)` 取 trace，但用户连续说话时
`_start_trace()` 已把该 session 的 trace 换成**新一轮**的对象 —— 上一轮的 TTS 打点落在新对象上。

**修复**：`_speak(session_id, reply, trace=None)` —— **由调用方传本轮 trace**
（`on_speech_end` 传自己的；`speak_text` 主动说话不传，天然不打点）。

### 3.2 首段收紧（TTFA 优化）

端到端首音频 ≈ **第一段的合成耗时** + 网络往返（实测 `tts_start=5882 → tts_first_audio=8476`，
首段 2.6 秒）。后续段本来就并行合成，**只有首段影响 TTFA**。

修复：首段超过 `_FIRST_SEG_MAX = 28` 字时**再切一刀**（整体 `max_len` 不变，
避免把语流切得太碎）。只在首段偏长时生效，影响面最小。

### 3.3 VAD 尾静音（给出建议，未改默认）

`max_end_silence_time`（默认 800ms）**已配置化**（`[hard_of_hearing]`，见 `config.example.toml`）。
实测 `speech_end=2876ms` 包含尾静音等待。

**不改默认值的理由**：调小（300–500ms）省 300–500ms，但风险是"说话中途停顿被过早截断"——
这是体验权衡，应由你在 `config.toml` 里按习惯定。建议先试 `500`。

### 3.4 未做（明确遗留）

**LLM 流式 → TTS 流水线**：当前是"LLM 完整回复 → 分句 → 并行合成"。理想形态是
LLM 吐出第一句就立刻开始合成，可再省 1–2 秒。但这要改动 S04 的 TTSTaskManager 与
S03 的取消语义（流式期间的 barge-in），**属架构级改动，单独 Sprint 更安全**。

---

## 4. 交付报告

### Changed files

**新增**：`engine/tests/test_s35_s36_s37.py`（7 用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/agent/__init__.py` | S35 任务续跑（标志 + 重建后注入，上限 2 次） |
| `engine/yuiro/tools/artifact_tool.py` | artifact 失效文案引导"重新调原工具、不要编 id" |
| `engine/yuiro/context/engine.py` | clip 提示语明确"本轮内有效 / 跨轮请重调工具" |
| `engine/yuiro/config.py` + `config.toml` | `tool_result_max_chars` 2000 → 3500 |
| `engine/yuiro/netease/player.py` | `force-media-title`（含降级）；`get_state` 加 `ready`；`state` 补 `volume` |
| `engine/yuiro/tools/netease_tool.py` | `_brief_song` 去掉 `vip` |
| `engine/yuiro/audio/__init__.py` | `_speak(trace=…)` 修复打点串线；首段 `_FIRST_SEG_MAX` 收紧 |

### Tests

- 新增 **7 个**全过：任务工具触发续跑 / 普通工具不触发 / 歌名传入 mpv / `ready` 字段 /
  首段可收紧 / `_speak` 接受调用方 trace / 三链路可导入；
- 全量回归 **425 passed / 5 failed**（失败集自 S01 从未变化）；
- 改动的文件 ruff 零告警（`netease_tool.py` / `player.py` 的报错均为**既有**问题，未新增）。

### Human Acceptance（待人工）

1. **任务续跑**：说「**帮我一步步整理下载文件夹**」→ 批准 → **观察它是否真的开始扫描/移动**
   （而不是只回一句"现在开始第一步"）；日志应出现 `任务续跑 #1（下一轮推动执行当前步骤）`；
2. **媒体信息**：放一首歌 → 问「**现在放的什么**」→ 应答出**歌名与歌手**（而不是 `.mp3` 哈希文件名）；
   调 `/api/netease/probe` 或看日志里 `state.title`；
3. **trace 不再串线**：连续说两句话 → 日志里每条 trace 的 `tts_start` 应 ≥ `speech_end`；
4. **首段更快**：长回复时首个字出声应更早（首段被切短）。

---

## 5. 遗留

| 项 | 说明 | 建议 |
|---|---|---|
| LLM 流式 → TTS 流水线 | 可再省 1–2 秒首音频延迟 | 单独 Sprint（涉取消语义，风险中） |
| VAD 尾静音默认值 | 800ms，建议试 500ms | 你在 `config.toml` 调（权衡由你定） |
| netease 交互流程跨轮 | 登录/扫码断片应随 S35 缓解，需实测 | 观察 |
| `netease_tool.py` 既有 lint | I001/FURB167/S110 等 | 技术债，可顺手清理 |
