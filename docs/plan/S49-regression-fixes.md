# S49 · 回归修复记录与防再犯护栏

> 本轮修复了三处用户实测反馈的 bug + 一次测试套件压缩。本文的**重点不是"修了什么"，
> 而是"怎么防止以后再犯"** —— 每个 bug 都配了护栏测试与一条可复用的判断规则。

---

## 一、Bug 1：TTS 无声音（日志 `0B`）—— S47 流式 TTS 引入的竞态

### 根因

`_speak_impl` 的 `_feed` 里 `create_task(mgr.enqueue(...))` 是 **fire-and-forget**，
紧接着 `finally: await mgr.finish()` 把 `_done` 置 True。而真实 TTS 合成要几百 ms ——
`wait_next()` 看到 `_done=True` 且 buffer 还空着，**直接返回 None → 主循环 break →
所有段被丢弃（0B）**。

### 修复

`_feed` 改为 **gather 所有 enqueue 任务完成后再 finish**。

### ★ 防再犯护栏

- 测试 `test_speak_plays_all_segments_with_slow_synthesis` / `test_speak_stream_plays_with_slow_synthesis`
  用**带延迟的 fake TTS**（`_SlowTTS`）。**瞬间完成的 fake 会掩盖这类竞态** ——
  这是本次最痛的教训：测试过了，真机却 0B。
- **判断规则**：`create_task(...)` 之后若有依赖"任务全部完成"的收尾逻辑，
  **必须 gather**，不能只 fire-and-forget。

---

## 二、Bug 2：语音回复不显示气泡

### 根因

语音链路的 `llm:text` 事件在前端**只打日志**，从不触发 `showSpeech`（说话云框）。

### 修复

`App.vue`：`llm:text` → `clearActivity() + showSpeech()`。

### ★ 防再犯护栏

- **判断规则**：语音与文字是**两条链路**，但它们应该共享"回复呈现"这一件事。
  凡新增一条链路，先问一句：**它的回复有没有和另一条走同一个 UI 出口？**

---

## 三、Bug 3：媒体失效 + 收尾撒谎"已经放起来了"

### 根因链（日志完整暴露）

1. `netease_play` 搜不到歌时返回 `status: "ok", played: false` —— **语义错误**（"没找到"不是"成功"）；
2. TurnPolicy 把这个 `ok` 登记为**成功去重**；
3. 模型重复调用 → 被挡回 `done`（"该操作已完成"）；
4. 收尾总结看到 `done` → 误判"已成功" → 撒谎。

### 修复两处

1. `netease_play` 所有 `played: false` 的 `status: "ok"` → **`pending`**（与正常路径 `"ok" if played else "pending"` 对齐）；
2. `turn_policy.py` 的 `done`/`asked` 占位 note 改为**"回看真实结果、不要臆造成功"**。

### ★ 防再犯护栏

- **判断规则 ①**：返回里 `status` 与 `played/success` 等**结果字段必须语义一致**。
  结果字段为假时，`status` 绝不能是 `ok`/`success`。
- **判断规则 ②**：**去重/占位返回绝不能宣称"完成/成功"** —— 它只会被下游
  （收尾总结、兜底语）误解。占位 note 必须指向"第一次的真实结果"。
- 测试 `test_skip_result_payloads` 已钉住 note 文案含"不要臆造成功"。

---

## 四、附带修复：测试套件 172s → 22s（7.8 倍）

### 根因：`Embedder` 把字符串 `"md5"` 当成模型名

`config.toml` 与大量测试写 `embedder_model="md5"`（配置层对"降级向量"的显式写法），
但 `Embedder` 只认 `None`（`None` 才不 spawn）。于是 `"md5"` 被当成模型名去 spawn
worker、尝试加载失败后才降级 —— **每次白白耗 3s**，20 个测试因此慢成整齐的 3.1s。

### 修复

`Embedder.__init__` 归一：`if model_name == "md5": model_name = None`。
另补齐 6 处测试里**漏传** `embedder_model`（用了默认 BGE-M3）。

### ★ 防再犯护栏

- **判断规则**：**配置层的"哨兵值"（如 "md5"）必须在最下游消费点归一**，
  不能指望每个调用方都自己转换。`main.py` 转了、测试没转 —— 这种不一致就是隐患。
- 附带修复 `SQLiteVecStore.close()` 加 `wal_checkpoint(TRUNCATE)`（Windows 文件锁防御）。

---

## 五、仍为环境相关的既有失败（本轮未解决，已定位）

| 失败 | 根因 | 性质 |
|---|---|---|
| `test_audio.py` 4 个 | VAD/音频模型环境相关 | 既有，与本次无关 |
| `test_agentloop_memory_roundtrip` | 语义检索依赖 BGE-M3，测试环境权重不可用 → 降级 md5 | 既有，环境相关 |

`test_agentloop_memory_roundtrip` 已在清理阶段加 `ignore_cleanup_errors`
（Windows 文件锁导致 tempfile 清理失败，非断言失败）。**BGE-M3 可用时它能通过**。
