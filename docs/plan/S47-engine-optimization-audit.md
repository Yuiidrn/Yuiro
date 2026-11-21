# S47 · 引擎端全方位优化审视（延迟 / 架构 / 交互体验）

**方法**：先用代码取证，再对照 2026 前沿实践；每条发现都附**代码位置或日志证据**，
推断性的收益明确标注为推断（不做无根据的量化）。

> ## ✅ 实施状态
>
> **P0 两项已落地（观测 + 排序），并有测试钉住**：
>
> | 项 | 内容 |
> |---|---|
> | **观测** | `usage` 打通 provider → `LLMChunk` → `TraceContext`；trace 日志新增 `cache_hit=N（P%）`。**字段跨 provider 归一**（DeepSeek `prompt_cache_hit_tokens` / OpenAI `prompt_tokens_details.cached_tokens` / Anthropic `cache_read_input_tokens`）；端点不支持上报时**安静降级**（绝不拖垮对话） |
> | **排序** | `ContextEngine.build` 重排为**稳定前缀 + 变化后缀**；情绪提示从 persona 段**移出**（独立段、置末尾）；`tool_results` / `nudges` **收进 ContextEngine** |
> | **★ 顺带修掉一个真 bug** | 工具轮的重建走的是旧 `_build_messages` —— **从第 2 轮起就绕过 ContextEngine**（无预算裁剪、无组装日志）。已收敛为唯一入口 `_context_messages` |
> | **可缓存前缀** | 从"时常退回到 system 一段（≈30%）"→ **system+persona+relationship+用户画像（≈56%）**，由 `test_cache_prefix_is_byte_stable_across_turns` **逐字节**钉住 |
> | **回归** | 539 passed / 5 failed（失败集自 S01 未变）；ruff 全绿 |
>
> **如何确认缓存真的生效**：启动引擎随便说一句，看日志里 trace 那一行末尾的
> `cache_hit=N（P%）`。**改前对比即可** —— 这正是先做观测的意义：不靠"感觉快了"。
>
> ### ★ 实证：当前 provider **支持**前缀缓存（2026-09-17 实测）
>
> `scripts/cache_probe.py` 用**逐字节相同**的消息连发两次：
>
> | | prompt_tokens | cached_tokens |
> |---|---|---|
> | 第 1 次（建立缓存） | 2310 | **0** |
> | 第 2 次（预期命中） | 2310 | **2304（99%）** |
>
> **三条结论**（实测，非推测）：
> 1. 阿里云百炼 `qwen3.7-max` **支持自动（隐式）前缀缓存**，命中率 99% ——
>    即 **S47 的「稳定前缀 + 变化后缀」排序会直接转化为延迟下降**，**不必换 provider**；
> 2. `stream_options: {include_usage: true}` **被该端点接受**（拿到了完整 usage、
>    未触发降级）—— P0-1 的观测能力在这个端点上**有效**；
> 3. 命中字段是 `prompt_tokens_details.cached_tokens`，**已在 `cache_line()` 的归一逻辑内**；
>    `cache_write_tokens: None` 说明是**隐式缓存**，无需额外声明。
>
> 复现：`cd engine && python scripts/cache_probe.py`（仅两次极短请求）。
>
> **⚠ provider 差异（务必知道）**：当前用的是**阿里云百炼兼容端点**（`qwen3.7-max`）。
> 按其官方文档，`stream_options.include_usage=true` 是标准做法（usage 在最后一个
> **无 choices** 的 chunk 上返回），缓存命中字段为 `prompt_tokens_details.cached_tokens`
> —— 两者都已被代码覆盖（并在 `tests/test_llm_usage.py` 里钉住）。
> 但"上下文缓存"是**部分模型**支持，且分隐式/显式两类。**因此**：
> 若日志里 `cache_hit` 长期为 0，说明**该模型不吃"前缀稳定"这套**，
> 而不是排序没生效（排序已由测试逐字节保证）。**换到 DeepSeek / OpenAI 这类
> 自动前缀缓存的端点会立刻看到差别。** 这正是先接观测的价值：不用猜，看一眼就知道
> 该不该换 provider —— 而不是先花一周"优化"一个根本不存在的缓存。
>
> **P1 已完成（A1 流式 TTS）**：
> - `TTSTaskManager.finish()` —— 流式路径句子数未知，缺这个结束信号 `wait_next` 会**永久挂住**；
> - `_speak_impl`（统一实现）+ `_speak_stream`（流式入口）：两条路径**只在"句子从哪来"上不同**，
>   刻意不再写两份（本会话已多次踩"两条路径各自漂移"：提示词三份、上下文注入两条、工具轮绕预算）；
> - `_agent_reply(on_sentence=...)`：每凑出一个完整句子就立刻交出去（首句阈值 6 字更早出声、后续 12 字免碎句）；
> - 开关 `[tts].stream_llm`（默认开，可一键回退整段路径）。
> - **护栏**：`test_first_sentence_plays_before_stream_ends` 断言**第一句在句子流尚未结束时就已播出**
>   —— 这就是 A1 的全部意义，若它不成立，收益为零。
> - ⚠ **已知限制**：`reset`（幻觉纠错）时**已交付给 TTS 的句子收不回来**。reset 是罕见路径，
>   且此时多半只说出了"我这就帮你…"这类无害内容；真流式必然有这个代价，这里选择接受。
>
> **B3（turn 级预算）已完成**：
> - `TurnBudget`（时间 / token / 轮数）—— 三个维度独立，对应三种不同的坏体验（体感 / 成本 / 绕圈）；
> - `send()` 循环改为**预算驱动**：耗尽就不再开新一轮工具，而是让模型用文字收尾；
> - **渐进收尾**：接近上限先注入"收尾提醒"（`budget.warning()`），
>   而不是到点掐断给用户半截回复 —— 这正是前沿 "budgeted loop" 与"超时抛异常"的区别；
> - `exhausted()` 返回**原因字符串**（不是 bool）：停下必须能如实告知；
> - 一份 usage 两处用：`trace`（观测缓存命中）+ `budget`（token 维度的刹车）。
>
> **B4（turn 级 checkpoint）已完成「记录 + 可查询」**：
> - `TurnJournal` 建立在本已完备的 `EventLog` 之上，**刻意是薄层** —— 不再造第二套存储
>   （多一套真相源就会漂移，本项目已吃过三次亏）；
> - 事件三类：`turn.started` / `turn.step`（**只记已完成的步骤** —— 它才代表已发生的副作用）/
>   `turn.completed`；
> - `replay_unfinished()` 是**纯函数**，即 durable execution 的 **replay boundary**
>   （"可以安全重放的起点"），因此可被穷举单测；
> - ⚠ **未做**：真正的"自动续跑" —— 它需要处理幂等副作用（哪些步骤可重放、哪些必须跳过），
>   属于后续工作。但没有记录就无从谈起；而且现在至少能看到"上次做到哪了"，
>   而不是一片空白。
>
> **S48（方案 D：崩溃恢复的副作用分级）已完成「标记 + 建议 + 可查」**：
>
> - **工具自描述副作用**：`BaseTool.effect`（`read` / `local` / `external`）；未声明时
>   按名字**保守推断**（`infer_effect`）—— **认不出来一律当 external**：
>   宁可多问一句，也不要静默重复放歌或重复发消息；
> - **★ 线索顺序即优先级**：危险线索优先于只读线索。否则 `netease_play_state`
>   这类名字会被 "state" 带成只读，恢复时静默重放 —— 正是要防的事故；
> - **`ResumePlan`**：按步骤副作用分两堆 —— `read`/`local` **可安全重放**，
>   `external` **必须问用户**。三个"一律"都被否掉：一律重放（会重复）、
>   一律跳过（读文件也白做）、一律问（**唠叨到没人看 = 没有防护**）；
> - **`/api/turns`**：回合级视图；未完成的回合附 `resume_plan`
>   （含 `auto_safe` / `question`），调试面板可直接展示；
> - **旧事件兼容**：S48 之前的事件没有 `effect` 字段 → 按工具名重新推断
>   （既不一律当危险吓人，也不一律当安全漏防护）。
>
> **后续待做**：
> - **真正的"自动执行续跑"** —— 现在给的是**分级建议 + 询问文案**，由上层
>   （LLM / UI）决定是否执行。这属于**有意为之**：恢复涉及副作用，
>   先让人确认比自动重放更稳。
> - 给具体工具补**显式 `effect` 声明**（现在主要靠名字推断，够用但不精确）。

**总体判断**：**我们不缺"大东西"，缺的是三个"收口"** ——

| 收口 | 一句话 | 类型 |
|---|---|---|
| **流式收口** | LLM 的 token 流没有真正流到 TTS | 把已有的接起来 |
| **缓存收口** | 上下文排序让稳定段无法成为缓存前缀 | 把已有的排好 |
| **路径收口** | 注入有两条路径，预算只管其中一条 | 把重复的删掉 |

> 三条都**不是新建能力**，而是"把已经具备的东西接起来/排好/去重"——
> 这正是"泛化优于打补丁"的具体形态：**能力都在，只是没连上。**

---

## 一、延迟：7 个发现

### A1 ★★★ 语音链路等 LLM **全量回复**才开始 TTS

`audio/__init__.py` L1037-1064：

```python
turn = asyncio.create_task(self._llm(text, session_id))
reply = await turn                      # ← 等**完整**回复
...
trace.mark("llm_final")
task = asyncio.create_task(self._speak(session_id, reply, trace))   # ← 才开始 TTS
```

**而 S04 的"分句流式"只是 TTS _内部_ 把整段文本切句并行合成**，输入仍是完整 `reply`。

**后果**：首句出声时间 = `LLM 全量耗时 + TTS 首段耗时`。
若 LLM 出 120 字要 3 秒，用户要等 3 秒多才听到第一个字 —— **TTFT 的优势被完全浪费**。

**而我们其实已经能观测到首 token**（`main.py` L311 `trace.mark("llm_first_token")`）——
**有能力观测，却没用来提前出声。**

**修法**：`AgentLoop.send` 本身就是 async generator（逐 token yield），
按**句子边界**把首句送给 TTS 即可。**预估收益：首句提前 1-3 秒**（推断，取决于回复长度）。

⚠️ 两个必须处理的点：
1. **工具轮的 token 不该 TTS**（如"正在准备播放…"这类中间文本）；
2. `_inspect_after`（对越权/拒答的后置检查）目前作用于**完整 reply**，
   流式下要改成**增量检查**。

---

### A2 ★★★ 上下文排序把**稳定段夹在变化段之后**

`context/engine.py` L93-101（组装顺序 = 注入顺序）：

```python
items += self._collect_persona(style_hint)     # 稳定（除非 style_hint 变，见 A3）
items += self._collect_task(task_summary)      # ← 变（长任务时每轮不同）
items += self._collect_pending(pending_note)   # ← 变
items += self._collect_relationship(...)       # ★ 稳定，却被排在两个变化段之后
items += self._collect_memory(memory_items)    # ← 每轮检索结果不同
items += self._collect_state(state_notes)      # ← 变
items += self._collect_history(history)        # ← 变
items += self._collect_user(user_text)         # ← 变
```

**为什么这是延迟问题**：我们用的是 OpenAI 兼容端点（qwen/deepseek），
**前缀缓存是自动的**（不像 Anthropic 要显式 `cache_control`）——
**命中前提是前缀逐字节稳定**。而这里：

- 一旦有 task 或 pending（长任务、点歌确认），**relationship 及其后全部无法命中**；
- `memory_items` 每轮都不同，**它之后的所有段（state/history/user）也全部失效**。

**用真实日志估算**（`system:578 / persona:270 / relationship:77 / facts:134 / knowledge:355 / episodes:144 / history:×9 / user:3`，合计 1896）：

| 场景 | 可缓存前缀 | 占比 |
|---|---|---|
| 无 task / pending、情绪不变 | system+persona+relationship+facts ≈ **1059** | **56%** |
| **有 task 或 pending** | 只剩 system ≈ **578** | **30%** |
| **情绪变化时**（A3） | 同样退到 **578** | **30%** |

**修法**：**稳定前缀 + 变化后缀**，把 `task`/`pending` 挪到 memory 之后：

```
[system][persona][relationship][facts]      ← 稳定前缀（可缓存）
[knowledge][task][pending][state][history][user]   ← 变化部分
```

**这不是"再优化一点"，而是让缓存真正生效** —— 差别是"每轮重新 prefill 1300 tokens"
还是"只 prefill 变化的几百 tokens"。

**★ 可验证**：DeepSeek/OpenAI 的响应 `usage` 里有 `prompt_cache_hit_tokens` 之类的字段，
**接上它就能从日志看到命中率**（见 §四 验证）。

---

### A3 ★★ `style_hint`（情绪提示）拼进了 persona 段

`context/engine.py` L176-177 / `agent/__init__.py` L552-553：

```python
if style_hint.strip():
    persona_content = f"{persona_content}\n（当前情绪提示：{style_hint}）"
```

`style_hint` 来自 `emotion_engine.style_hint()`（`main.py` L296-297），**情绪每轮都可能变**
（互动加成 + 指数衰减）。

**后果**：**persona 段每轮都可能是新内容** → 它后面的 relationship/facts 也无法成为前缀 →
**缓存从第 2 段就断**。

**修法**：把情绪提示挪到**末尾独立小段**（或紧贴 user 之前）。persona 段即可完全稳定。

---

### A4 ★★ nudge 追加在 **user 消息之后**

`agent/__init__.py` L793-800：

```python
messages = self._build_messages(...)            # 末尾是 {"role": "user", ...}
for _nudge_text in st.injections():
    messages.append({"role": "system", "content": _nudge_text})   # ← system 在 user 之后
```

**两个问题**：
1. **顺序违反 chat 模板惯例**（system 应在 user 之前），部分服务端/模型对此处理不佳；
2. **每次注入内容不同** → 破坏缓存尾部。

**修法**：插到最后一条 user **之前**（这需要 `_build_messages` 支持"预留位"，
或直接在 build 时把 nudge 作为参数传入，见 B2）。

---

### A5 ★ `memory.retrieve()` 串行阻塞在 LLM 之前

`agent/__init__.py` L654-659：

```python
memory_mems = await self._memory.retrieve(text, top_k=3)   # ← 串行等待
```

这条链上是：**嵌入器子进程 IPC（算 query 向量）→ sqlite 向量检索 + FTS + RRF**。
嵌入器是**子进程**（BGE-M3），单次 IPC 往返 + 推理估算 **50-300ms**（推断）。

**修法（按性价比）**：
1. 给它加 **超时保护**（现在没有 —— 嵌入器卡住会拖整个回合）；
2. 与"工具表构建 / 交互形态分类"等**并行**（省的不多，但顺手）；
3. **更根本**：**query 向量可以预热**（用户开始说话/打字时先算，而非等到 send）。

---

### A6 ★ 每轮**重建** messages，且"本轮工具结果"段内容每轮变

`agent/__init__.py` L789-795（每轮 `_build_messages`）+ L622-630（工具结果段）。

重建本身是**有意为之**（让状态/history 反映最新）✓，但把**内容多变**的段放在中部，
就是 A2 的同类问题。工具结果段应**整体挪到末尾区**。

---

### A7 ★ 超时与预算：硬编码且分散

| 位置 | 值 | 问题 |
|---|---|---|
| `OpenAIProvider` | `connect=10 / read=30 / write=30` | 硬编码 |
| 建流 | `wait_for(..., timeout=20.0)` | 硬编码 |
| 每轮 LLM | `deadline = loop.time() + 30.0` | 硬编码 |
| 工具轮数 | `_MAX_TOOL_ROUNDS = 3` | 硬编码 |
| 上下文 | `ContextBudget(total=6000)` | 可配 ✓ |

**最坏路径**：3 轮 × 30s = **90 秒**无响应（虽然逐 chunk 有 deadline 保护 ✓）。
**且没有 token / 成本预算**（前沿做法是 budgeted loop，见 §三）。

---

## 二、架构：5 个发现

### B1 ★★★ **两条注入路径并存** → 文案必然双份

`agent/__init__.py` L670-691：

```python
if self._context is not None:
    messages = await self._context.build(...)    # 新路径：ContextEngine（带预算）
else:
    messages = self._build_messages(...)         # 旧路径：内联（无预算）
```

而 `_build_messages`（L535-637）里**同样有一份** `state_notes` / `pending_note` /
`tool_results` / memory 分层的文案 —— **与 `ContextEngine._collect_*` 是两份**。

**这与"S42 发现的三份提示词"是同一类问题**：多路径并存 → 必然不同步。
**而这次更隐蔽**：不是"哪份生效"的问题，是**两份都要维护**。

**修法**：删掉旧路径（`_context` 现在总是注入 ✓），让 `_build_messages` 退化为薄封装或移除。

---

### B2 ★★ nudge 绕过了 ContextEngine 的预算管理

`st.injections()` 的文本是 **AgentLoop 侧直接 `append`** 的（A4），
**不经过 `ContextEngine`** → **不受 6000 token 预算约束**，也不会出现在组装日志里
（日志只统计 ContextEngine 的段）。

**后果**：nudge 可能把上下文挤超预算，而**观测上看不到**。

**修法**：把 nudge 作为 `build()` 的参数（如 `nudges: list[str]`），
由 ContextEngine 统一放入**末尾变化区**并计入预算。

---

### B3 ★★ 没有 turn 级预算（token / 时间 / 工具调用数）

现状只有：`_MAX_TOOL_ROUNDS=3`（轮数）+ `ContextBudget=6000`（单次上下文）。

**缺**：整轮（含多轮工具）的**总 token 上限 / 总时长上限**。
长任务或模型绕圈时，唯一刹车是"轮数"，而单轮可能很贵。

前沿做法（§三）：**budgeted loop** —— 预算是一等公民，耗尽则优雅收尾并如实告知。

---

### B4 ★ 没有 turn 级 checkpoint（durable execution）

我们有：`TaskRuntime` + **Task Journal**（任务级 ✓）、`EventLog`（落盘 ✓）、
`SessionManager.revive`（会话级 ✓ S43）。

**缺**：**"这一轮做到哪"** —— 已调用过哪些工具、各自结果是什么。
引擎崩溃/重启后，**进行中的 turn 全部丢失**，只能重来（而工具可能有副作用，
重来会**重复执行**）。

前沿共识：*"durable execution 在声明成功前持久化每一步，并按确定性的方式重放"*；
关键概念是 **replay boundary** 与**幂等副作用**。

**我们的有利条件**：`EventLog` 已经是**追加式事件流** ✓
→ 若把"工具调用与结果"写成事件，**turn 级恢复几乎是现成的**（事件溯源）。

**修法**：turn 内的关键步骤（tool.requested / tool.completed + 结果摘要）进 EventLog，
复活会话时可选择"重放已完成步骤"。

---

### B5 ★ 配置项硬编码（见 A7 表）

---

## 三、对照前沿（2026）

检索到的高共识项与我们现状：

| 前沿实践 | 我们 | 判定 |
|---|---|---|
| **Prompt caching**（被称为"最高杠杆优化"） | 有上下文分层 ✓ 但**排序让缓存失效** | ❌ **A2/A3/A4 就是在补这条** |
| **Parallel tool calling** | ✅ `ToolDispatcher` 并发执行 | ✅ 已有 |
| **Streaming / TTFT 优化** | 🟡 有逐 token 流 + 埋点，**但没流到 TTS** | ❌ **A1** |
| **Budgeted loop** | 🟡 只有轮数上限 | 🟡 **B3** |
| **Durable execution / checkpoint** | 🟡 任务级 ✓，turn 级 ✗ | 🟡 **B4** |
| **Human-in-the-loop / interrupt** | ✅ `approval_gate` + 计划审批 + barge-in | ✅ 领先 |
| **可观测（trace / event log）** | ✅ Trace 阶段丰富（含 `llm_first_token`） | ✅ 领先 |
| **反循环护栏** | ✅ `TurnPolicy`（去重/限流/早停） | ✅ 已有 |

**结论**：**我们领先的是"工程化"，落后的是"数据流与排序"** ——
前者靠投入，后者靠**设计眼光**（把稳定与变化分开、把流接上）。

---

## 四、按 ROI 排序的行动清单

| 优先 | 项 | 收益 | 成本 | 风险 |
|---|---|---|---|---|
| **P0** | **A2 + A3 + A4 上下文排序**（稳定前缀 + 变化后缀；情绪提示挪末尾；nudge 挪 user 前） | 缓存命中率 30% → 55%+；**每轮省数百 token prefill** | 低（纯排序） | 低（有等价性测试） |
| **P0** | **观测先行**：把 `usage` 的 **cache hit** 字段接进 trace | 让上面这条**可验证**，否则是盲改 | 极低 | 极低 |
| **P1** | **A1 流式 TTS**（LLM token → 句子边界 → 立即合成） | **首句提前 1-3 秒**（用户感知最强） | 中（要处理工具轮与增量检查） | 中 |
| **P1** | **B2 nudge 纳入 ContextEngine** | 预算真正闭环 + 组装日志完整 | 低 | 低 |
| **P2** | **B1 删掉旧注入路径** | 消除双份文案的腐化源头 | 低 | 低（先确认无调用方） |
| **P2** | **B3 turn 级预算** | 长任务有上限保护 | 中 | 低 |
| **P3** | **B4 turn 级 checkpoint**（事件溯源） | 崩溃后能续跑而非重来 | 高 | 中 |
| **P3** | **A7 超时/轮数配置化** | 可调优 | 低 | 低 |

---

## 五、验证方法（避免"改了但不知道有没有用"）

1. **缓存命中最直接**：把 LLM 响应 `usage` 里的 `prompt_cache_hit_tokens`（DeepSeek）
   或 `prompt_tokens_details.cached_tokens`（OpenAI）接进 `TraceContext`，
   日志里就能看到**每轮的命中率**。改 A2 前后对比即可判断。
2. **TTFT**：`trace` 已有 `llm_first_token` ✓；补一个 `tts_first_audio`（已有 ✓）
   → **`tts_first_audio - llm_first_token`** 就是 A1 的收益指标。
3. **上下文稳定性**：可加一个"前缀指纹"（对稳定段的 hash）打点，
   若它每轮变化就说明又被污染了。

---

## 六、一句话总结

> 蓝图里的**大件都到位了**（六项 ownership、InteractionMode、durable 的任务/会话/事件）。
> 现在最影响体验的不是"缺什么能力"，而是**三条没接上的线**：
> **token 流没流到 TTS**、**稳定段没排在前面**、**注入走了两条路**。
> 这三条都属于"排列与连接"，改动小、风险低、**用户能立刻感觉到**。
