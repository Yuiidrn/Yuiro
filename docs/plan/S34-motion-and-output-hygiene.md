# S34 — 动作映射 + 输出净化（含 5 项问题诊断）

> 状态：**部分完成**（2026-09-14）。
> 触发：用户实测反馈 5 个问题（动作/表情不稳定、日志暴露的空壳、调试日志泄漏、
> 任务循环不足、ncm-cli/mpv 需加强）。
> 本文档 = 已修 2 项 + 诊断 3 项（各自给出根因与修复方案）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 34
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    动作可复现 + 回复干净
SURPRISE: 同一个表演每次都是同一个动作；它嘴里不会再念出"左括号本轮操作"
ARCHITECTURE:
  A. 动作语义**自动推断**（扫描 motion 曲线 + cdi3 中文参数名），索引写死不再随机
  B. 表演时长**跟随动作真实时长**（避免动作播一半表情就回落）
  C. 输出净化双层：源头（history 不拼调试注记）+ 出口（剥离兜底）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 1. 问题①：动作描述 —— 自动推断（已解）

### 1.1 结论先说：**asset 里确实没有语义描述**

| 文件 | 内容 | 有语义吗 |
|---|---|---|
| `feiniu.model3.json` | `Motions.TapBody` 只列 `File` 名（`Hiyori_m01~m10` / `micon` / `micoff` / `singing`） | ❌ 只有文件名 |
| `*.motion3.json` | 纯曲线数据（`Curves[].Id` + `Segments`） | ❌ 无描述字段 |
| `feiniu.cdi3.json` | **参数的中文名**（"角度 Y"、"眼珠 X"、"左臂 A"…） | ✅ 可用于推断 |

所以"逐个预览分辨"确实是原始条件下唯一办法 —— 但**曲线本身就是可读证据**：
`ParamAngleY` 大幅变化 = 点头，`ParamHandRB` 变化 = 手部动作，时长 = 动作体量。

### 1.2 做法：`engine/scripts/motion_scan.py` 扫描曲线特征

> 保留为**正式工具**（非一次性脚本）：换模型或想复核时 `python scripts/motion_scan.py` 即可重跑。

扫描 13 个动作的「影响参数 × 幅度 × 时长」，配合 cdi3 的中文名得出：

| # | 文件 | 时长 | 主导参数（幅度） | 推断语义 |
|---|---|---|---|---|
| 0 | Hiyori_m01 | 4.70s | AngleY 46 / AngleZ 29 | 点头类 |
| 1 | Hiyori_m02 | 5.93s | **AngleZ 60**（最大歪头） | 大幅歪头 |
| 2 | Hiyori_m03 | 4.20s | AngleZ 39 / AngleY 31 | 温和歪头 |
| 3 | Hiyori_m04 | 4.43s | 三轴均衡（X 29.9/Y 28.3/Z 32） | 环顾 |
| 4 | Hiyori_m05 | **8.57s** | AngleZ 55 / AngleY 40 / BodyAngleX 20 | 全身大动作 |
| 5 | Hiyori_m06 | 5.37s | **HandRB 18.5 / HandLB 15.8** | **手部动作** |
| 6 | Hiyori_m07 | 1.90s | Ahoge 19.9 / BodyAngleY 16 | 轻快点动 |
| 7 | Hiyori_m08 | 2.10s | **ArmLB 14.8 / HandLB·RB 14.6** | **手部动作** |
| 8 | Hiyori_m09 | 1.60s | AngleY 23（最短） | 低头 |
| 9 | Hiyori_m10 | 4.17s | AngleY 34 / BodyAngleX 16 | 抬头 |
| 10 | micoff | 1.10s | AngleY 28（极短） | 微动 |
| 11 | micon | 1.10s | **与 #10 数值完全相同** | ⚠️ 同一动作的副本 |
| 12 | singing | 4.70s | **与 #0 数值完全相同** | ⚠️ 同一动作的副本 |

> **13 个"动作"实际只有 11 个唯一动作**：`singing` 是 `m01` 的副本、`micon` 是 `micoff` 的副本。
> 这也解释了为什么原始描述里"micon/micoff 文件大小完全一致（8358 字节）"。

### 1.3 问题①的另一半：**"不稳定"= 随机索引**

根因（代码级）：

```python
# performance.py（修复前）
"celebrate": ("excited", "TapBody", None, ...)   # ← index=None
# runtime.py → AvatarIntent(motion_index=None)
# Live2DCanvas.vue
if (index === undefined) { mm.startRandomMotion?.(group) }   # ← 随机播任意一个
```

`TapBody` 里**既有 8.6s 的全身大动作，也有 1.1s 几乎不动的 micoff** ——
随机播就是"有时很活、有时像没动"。**这才是"调用不稳定"的真正原因**（不是通道坏了）。

修复：

1. **索引写死在表演包里**（依据上表特征）：
   `celebrate → #5`（手部动作）、`greet → #7`（手部动作）、`surprise → #9`、`comfort → #2`；
   **情绪类表演（happy/sad/angry…）不配动作** —— 说话时一直大幅挥手很吵，只演表情更自然；
2. **`motion_map` 支持 `"组名#索引"`**（如 `greet = "TapBody#7"`），你可以在桌宠里 Alt+M 看编号后精调；
3. **表演时长跟随动作真实时长**（`TAPBODY_DURATIONS_MS`）：
   `duration = max(2600, 动作时长 + 300)` —— 否则动作还在播、表情已被情绪回落（"动作闪一下就没"）。

---

## 2. 问题③：调试日志泄漏到回复（已修）

### 2.1 现象与根因

日志实证（**被 TTS 念出来**）：

```
TTS 合成: '……反正我也不嫌麻烦。（本轮操作：无工具调用'（分 3 段，首段先播）
```

根因不在 TTS，而在 **history 的写法**：

```python
# agent/__init__.py（修复前）
content = f"{content}（本轮操作：{note}）"      # ← 拼进 assistant 消息
```

模型看到 history 里"自己说过的话"带这个后缀 → **模仿该格式**，并在回复里自行生成
（甚至**凭空编造**"（本轮操作：无工具调用）"—— 日志 L60/L92 都是这种）。

### 2.2 修复（两层，互为保险）

| 层 | 改动 |
|---|---|
| **源头** | assistant 内容保持干净；工具痕迹改挂 **`system` 角色**（附"不要模仿此格式"提示）—— 模型仍知道上轮做了什么，但不会当成"我该说的格式" |
| **出口** | 新增 `yuiro/text_hygiene.py`：在 `_agent_reply` 返回前剥离 `（本轮操作：…）`（chat 与 voice 共用此出口，TTS 不会再念到） |

出口净化用**括号配对扫描**而非简单正则 —— 注记内部常嵌套括号
（`（本轮操作：我调用了 X（action=next），已完成）`），正则会在第一个 `）` 处截断。
只从高度特征化的「（本轮操作：」起算，**不误伤用户正常括号内容**（有测试固化）。

---

## 3. 问题②：日志暴露的"空壳"清单（诊断）

证据来自 `.env-local/engine_start.out.log`（543 行真实会话）。

| # | 现象 | 证据 | 根因 | 修复方向 |
|---|---|---|---|---|
| **A** | 调试注记被念出来 | `TTS 合成: '…（本轮操作：无工具调用'` | ✅ 见 §2 | **已修** |
| **B** | LLM 编造 artifact id | 工具结果 `{"status":"error","note":"artifact 不存在或已清理: art_9f8e7d6c5b4a3210"}` | 工具结果（含真实 `art_xxx`）只在**当轮** messages 里，**跨轮丢失**；LLM 想"再读一次"时只能编 | ① artifact_read 报错文案引导"重新调用原工具"；② 把最近 artifact id 放进 history 的 system 备注（同 S34 工具痕迹的做法） |
| **C** | 同一工具反复调用 → 18 秒 | `netease_recommend` 连调 3 次（第 3 次才被去重挡住），`llm_first_token=17005ms` | 工具结果超长被 clip（只留前 2000 字符 + artifact 指引），LLM 看不到完整列表 → 以为失败 → 重试 | 同 B（让 LLM 知道"结果已拿到"）；或对"已完成的操作"返回可读摘要 |
| **D** | 播放状态只有哈希文件名 | `"state": {"title": "3ac3424e4c7fd1948e8bb2a01025cb12.mp3", "duration": 0.0}` | `player.py` 用**直链**播放，mpv 的 `media-title` = URL basename；`play_urls(titles=…)` 收了歌名却**没传给 mpv** | `loadfile` 第三参数加 `{"force-media-title": "歌名 - 歌手"}`（mpv 原生支持） |
| **E** | 任务建完就停 | `task_plan → task_create → "现在开始第一步扫描文件"` **之后没有任何工具调用** | TaskRuntime 只是**状态机 + Journal**，`advance()` 靠 LLM 主动调；一轮结束无驱动续跑 | 见 §4 |
| **F** | voice 端到端 10s | `e2e=10010ms`：`tts_first_audio=8476`（TTS 首段 3.9s）、`speech_end=2876`（VAD 尾静音） | SiliconFlow 云端 TTS 首段延迟 + VAD 尾静音 800ms | ① TTS 首段并行化（分句已做，首句可再短）；② VAD 尾静音按场景调小；③ 本地 TTS 做兜底 |
| **G** | trace 打点串线 | `trace=c90738bb … tts_start=75 tts_first_audio=7875`（tts_start 早于 speech_start） | 同一 session 连续语音时，新 trace 覆盖后旧 TTS 仍往新对象打点 | trace 打点带 generation/轮次校验 |
| **H** | FunASR 噪音 | `Loading remote code failed: model, No module named 'model'` | 模型加载路径告警 | 低优先（不影响识别） |

> **共同模式**：C/D/E 都是"**有返回但信息不足**"—— 调用方（LLM 或前端）拿不到能行动的信息，
> 于是重试、或退化成看不到。这与"空壳"的直觉一致，但**不是没实现，而是链路信息断了**。

---

## 4. 问题④：任务循环与回调机制（诊断）

**你的判断是对的**：不是"功能没写"，而是**缺少驱动**。

现状（S08 + S29）：

```
task_plan → PENDING_APPROVAL → approve → RUNNING ──┐
                                                    │  谁推进？
task_advance(step, status) ←── 只有 LLM 主动调用 ───┘
```

- `TaskRuntime` 有：状态机、Journal 落盘、重启恢复、失败重试、审批 —— **契约齐全**；
- **缺的是"执行循环"**：任务创建后没有东西推动"执行第 1 步 → 检查 → 第 2 步"。
  LLM 一轮回复结束，循环就终止了（因为它已经产出文本）。

spec 里对应的形态是 Task Runtime 的 **step driver**。最小可行方案：

| 方案 | 内容 | 代价 |
|---|---|---|
| **① 续跑提示**（推荐先做） | `task_create` 成功后，引擎在下一次 LLM 调用前注入 system 提示："任务 X 当前进行中，请立刻执行第 1 步（必要时调用工具），完成后用 task_advance 标记" | 小；复用现有 AgentLoop |
| ② 任务回合（Task Mode） | AgentLoop 增加"任务模式"：任务 RUNNING 且未完成时自动续跑（最大轮次 + 可中断 + 每步事件） | 中；需处理与 barge-in/取消的交互 |
| ③ 后台任务 | TaskRuntime 自己驱动（不占用对话轮次），完成时事件通知 | 大；属 Wave 7 Background |

**建议**：先做 ①（一天内可验证），确认"说一句话就能把多步任务跑起来"再评估 ②。

---

## 5. 问题⑤：ncm-cli / mpv 加强（计划）

从日志与代码定位的**具体缺口**（按优先级）：

| 优先级 | 问题 | 修复 |
|---|---|---|
| **P0** | `media-title` 是哈希文件名 → 用户与 LLM 都不知道在放什么 | `loadfile` 传 `force-media-title`（歌名 - 歌手） |
| **P0** | `duration: 0.0` / `volume: null` 恒为默认 | 补齐 `get_property duration/volume`；未就绪时标注 `loading` 而非 0 |
| **P1** | 歌单类工具结果超长被 clip，LLM 看不到 → 反复重拉 | 返回**精简可读列表**（前 N 首：歌名-歌手-时长），完整内容才进 artifact |
| **P1** | 播放队列与"当前播放第几首"对不上（`queueLength: 0`） | 用 `playlist-count/-pos` 如实回传；`play_urls(titles=…)` 把歌名带进 mpv 播放列表 |
| **P2** | 网易云登录/扫码等交互流程跨轮断片 | 依赖 §4 的续跑机制 + history system 备注 |

---

## 6. 交付报告（本轮已做部分）

### Changed files

**新增**：`engine/yuiro/text_hygiene.py`、`engine/tests/test_output_hygiene.py`（7 用例）、
`engine/tests/test_motion_mapping.py`（9 用例）、`engine/_motion_scan.py`（扫描器，一次性工具）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/avatar/performance.py` | `TAPBODY_DURATIONS_MS`（13 个动作真实时长）；`parse_motion_spec()`（`"TapBody#7"`）；`motion_duration_ms()`；内置表演包**索引明确化**；`_duration_for()` 让时长跟随动作 |
| `engine/yuiro/avatar/runtime.py` | `[表演]` 日志带上索引（`动作 TapBody#5`） |
| `engine/yuiro/avatar/__init__.py` | 导出新 API |
| `engine/yuiro/agent/__init__.py` | 工具痕迹改挂 `system` 角色（不再污染 assistant 内容） |
| `engine/yuiro/main.py` | `_agent_reply` 出口净化（`strip_debug_notes`）+ 命中时告警日志 |
| `engine/yuiro/config.py` / `config.toml` / `config.example.toml` | `motion_map` 文档化新格式与随机风险 |
| `engine/tests/test_agent_chat_reply.py` | 历史形态断言更新（system 备注 + assistant 干净） |

### 验证

- 新增 **16 个**测试全过；全量回归 **418 passed / 5 failed**（失败集与基线一致）；
- `text_hygiene.py` / `avatar/` / 新测试文件 ruff 全绿。

### 修复前后的行为差异（对照日志）

| 场景 | 之前 | 现在 |
|---|---|---|
| greet 表演 | 随机播 13 个动作之一（可能是 1.1s 的 micoff） | 固定 `TapBody#7`（手部招手动作） |
| celebrate 表演 | 2600ms 后表情回落（动作还在播） | 时长 5670ms（跟随 `#5` 真实 5370ms） |
| 回复文本 | `……（本轮操作：无工具调用）` 被 TTS 念出 | assistant 内容干净 + 出口兜底剥离 |

---

## 7. 遗留（下一 Sprint 候选）

| 候选 | 内容 | 依据 |
|---|---|---|
| **S35（推荐）** | 任务续跑（§4 方案①）+ artifact/工具结果可见性（§3 B/C） | 直接决定"多步任务能不能跑完" |
| S36 | 音乐媒体加强（§5 的 P0/P1 四项） | 用户明确要求；且属高频交互 |
| S37 | 延迟专项（§3 F/G）：TTS 首段、VAD 尾静音、trace 串线 | 用户实测 10s 端到端 |
