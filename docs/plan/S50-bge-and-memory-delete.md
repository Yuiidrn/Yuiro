# S50 · BGE 嵌入真相 + 记忆删除落库排查

> 两个用户问题，两个决定性答案。方法：不猜，直接实测（权重文件、子进程握手、
> 生产 db 只读查询）。
>
> ## ★ 补充（第二轮实测反馈）：记忆其实有**三处存储**，全清必须全联动
>
> 用户清空全部记忆后，回复仍出现"认识六天、聊了一百三十九次"和"I_drcen/VIP 用户"。
> 排查结论：**记忆不止 SQLite 一处** ——
>
> | 存储 | 位置 | 全清此前是否覆盖 |
> |---|---|---|
> | L2 情景 + L3 事实 | `data/yuiro_memory.db`（SQLite） | ✅（本轮已修四表齐删） |
> | **关系记忆**（认识 X 天/聊 Y 次） | `data/relationship.json`（独立 JSON） | ❌ **此前清不到** |
> | **会话内存**（history / 状态摘要，含 NCM profile 工具结果） | AgentLoop 内存 dict | ❌ **此前清不到** |
>
> **修复**：`DELETE /memory` 现在四表 + `RelationshipMemory.reset()` +
> `AgentLoop.clear_session_memory()` **全联动**，响应逐项返回数量
> （`episodes` / `history_turns` / `relationship_reset`）。
>
> **身份冲突治理**："我是谁"→ `netease_library profile` 返回 NCM 昵称
> （I_drcen），模型把它当用户称呼，与人设（用户是 Yui）冲突且经 history
> 反复强化。已在 profile 返回中加 `note`：**NCM 昵称只是音乐服务身份，
> 用户称呼以人设与既有对话为准**。
>
> **判断规则**：任何"清空/删除 X"的操作，先枚举 X 的**全部存储位置**
> （持久层、独立文件、内存缓存），漏一处用户就会看到"删了还在"。

---

## 一、BGE 向量到底有没有载入成功？

**答案：生产引擎载入成功；测试环境失败 —— 两条路径用的是不同的模型来源。**

| 路径 | 来源 | 结果 |
|---|---|---|
| **生产**（config：`embedder = "models/bge-m3"`） | 本地目录 `engine/models/bge-m3`（文件齐全，`onnx/model.onnx_data` 2.27GB 完整） | ✅ **实测 19.2s 握手成功**，真 BGE 输出 1024 维，两句话余弦 0.59（真实语义） |
| **测试**（`MemorySystem` 默认 `DEFAULT_MODEL = "BAAI/bge-m3"`） | HF Hub 缓存 | ❌ **快照不完整**（缺 `onnx/model.onnx_data`）+ HF 不可达（`getaddrinfo failed`）→ 28.3s 后降级 md5 |

这正是 `test_agentloop_memory_roundtrip` 一直在失败集里的根因（测试里语义检索靠
HF 缓存路径，那份缓存永远加载不起来）。

### 附带发现（值得知道）

1. **启动后前 ~19s，embed 静默走 md5**：`embed()` 只做一次非阻塞握手探测，
   不等待 worker 加载完成。启动窗口期写入的记忆是 md5 向量 —— 与之后的
   BGE 向量**混在同一张向量表里**（同维不同分布，检索有噪声）。
   属已知取舍（embed 不能无限等），但要知道它的存在。
2. **降级曾经完全静默**：worker 握手返回失败时无任何日志 —— "感觉记忆不太准"
   是唯一信号（实测拖了数周）。已修：降级时打一次性 `warning`。
3. HF 缓存里那份不完整快照建议清理（`models--BAAI--bge-m3`），避免以后
   误用 DEFAULT_MODEL 时再踩。

---

## 二、"记忆删除没落库"？

**答案：删除其实已经落库了 —— 但有一个真 bug 让它看起来没删干净。**

### db 实测证据

```
messages=7（rowid 已到 311，原 300+ 条确实删了）
facts=0
messages_vec=159，其中孤儿向量=152   ← 真 bug
```

### 真 bug：向量表 / FTS 表从不跟随删除

- `DELETE /memory`（全清）只删 messages / messages_fts / facts，**漏了 messages_vec**；
- `DELETE /memory/episodes/{rowid}`（单条）**只删主表**，FTS 与向量全留孤儿。

**后果**（不止"看起来没删干净"）：

1. 直接看库/看检索计数 → 误以为删除没生效（用户的观察）；
2. **全清后新记忆 rowid 从头编号，会与旧向量错位关联** —— 新文本拿到旧语义，
   向量检索从此悄悄失真（比残留更危险）；
3. "没反应"的删除体验：响应只有 `{"ok": true}`，无数量反馈。

### 修复

| 项 | 内容 |
|---|---|
| `DELETE /memory` | **四表齐删** + 返回 `deleted.episodes` 数量 |
| `DELETE /memory/episodes/{rowid}` | **主表 + FTS + 向量三表齐删** + 返回 `deleted`（rowcount） |
| 数据修复 | 生产库 152 条孤儿已清理（159 → 7，与主表一致） |
| 护栏测试 | `test_delete_episode_removes_message_fts_and_vector` / `test_clear_memory_wipes_all_tables_and_reports_count` 把契约钉死 |
| Embedder | 降级时打一次性 `warning`（不再静默） |

### "删除后记忆又出现"的另一半解释

删除后继续对话，记忆系统**持续工作**会写入新条目（rowid 307-311 的播放记录
就是删除后产生的）—— 这是预期行为，不是删除失败。

---

## 验证

- 新增 2 个删除契约测试，`test_debug_api_panels.py` 12 passed
- 全量 601 passed / 5 failed（失败集不变，均为环境相关）
- ruff 无新增问题
