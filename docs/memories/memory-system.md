# Yuiro 记忆系统设计与架构

> 本文件记录 Yuiro 桌宠记忆系统的完整设计思路、数据流、架构分层与关键实现。
> 核心代码：`engine/yuiro/memory/__init__.py`（`MemorySystem` 门面 + `Retriever` + `SQLiteVecStore` + `Embedder`）。

---

## 一、设计思路：检索式注入，而非强塞

**核心理念：持久化记忆不是"全部历史聊天记录塞进提示词"，而是"每次只检索 top_k 条最相关的记忆注入"。**

这样做的动机：

- **提示词长度可控**：无论积累了多久的对话，每次注入给 LLM 的记忆始终只有 `top_k`（默认 3）条，不随历史增长而膨胀。
- **相关性优先**：模型只看到与当前问题语义最相关的记忆，避免被无关历史干扰。
- **语义理解**：依赖 BGE-M3 嵌入 + 向量相似度，而非简单关键词拼接，能召回"意思相近但用词不同"的记忆。
- **成本可控**：LLM 输入 token 稳定，推理延迟与成本都可预期。

> ⚠️ 需区分的概念：
> - **持久化记忆**：跨会话、落库到 SQLite、每次检索 top_k 注入 —— 本文件主体。
> - **会话内 history**：当前 session 内多轮对话的上下文列表，随会话进行累积，不属于持久化记忆。

---

## 二、数据流总览

```
  用户输入 text
      │
      ▼
┌─────────────┐   retrieve(query=text, top_k=3)   ┌─────────────────────┐
│  AgentLoop  │ ──────────────────────────────────▶│  MemorySystem        │
└─────────────┘                                    │  (门面)              │
      ▲                                            └──────────┬──────────┘
      │  注入: "相关记忆:\n<m1>\n<m2>\n<m3>"                    │ top_k
      │  拼成一条 system 消息                                  ▼
      │                                            ┌─────────────────────┐
      │                                            │  Retriever           │
      │                                            │  (RRF 融合检索)      │
      │                                            └──────────┬──────────┘
      │                                                       │ 并行 4 信号
      │              ┌──────────────┬──────────────┬──────────┼─────────┐
      │              ▼              ▼              ▼          ▼         ▼
      │      vector_search      fts_search    recent_search  salient  (知识库/事实)
      │      (BGE-M3 向量)    (FTS5 trigram)  (时间新近)   (显著性)     │
      │              └──────────────┴──────────────┴──────────┴─────────┘
      │                                                       │ RRF 加权排序
      │                                                       ▼
      │                                        取 top_k 条 Memory 返回
      ▼
  LLM 生成回复 reply
      │
      ▼
┌─────────────────┐  remember(user_text, reply)   ┌────────────────────┐
│  AgentLoop      │ ─────────────────────────────▶│ MemorySystem.remember│
└─────────────────┘                               └─────────┬──────────┘
                                                            │
                                     ┌──────────────────────┼──────────────────┐
                                     ▼                      ▼                  ▼
                              retriever.add()         _extract_facts()   (L2 情景落库)
                              (L2 情景 + 向量)        (L3 用户事实)      (持久化 SQLite)
```

---

## 三、架构分层

### 1. `MemorySystem` —— 门面（`__init__.py`）

对外暴露的顶层接口，聚合检索器、事实库、知识库：

```python
async def remember(user_text, reply, session_id=None):  # 写：每轮对话落库
async def retrieve(query, top_k=None) -> list[Memory]:  # 读：检索 top_k 记忆
```

- `top_k` 默认来自配置 `cfg.memory.auto_inject_top_k`（默认 3）。
- `retrieve` 内部调用 `Retriever.retrieve`（L2 情景 top_k）+ 事实库 + 知识库，均按同一 `top_k` 限制条数。

### 2. `Retriever` —— RRF 融合检索（`__init__.py:406-439`）

核心检索逻辑，融合 4 个信号：

```python
async def retrieve(self, query, top_k=3):
    query_vec = await self.embedder.embed(query)            # BGE-M3 向量
    vector_hits, fts_hits, recent_hits, salient_hits = await asyncio.gather(
        asyncio.to_thread(self.store.vector_search, query_vec, VEC_K),  # 向量相似度
        asyncio.to_thread(self.store.fts_search, query, VEC_K),         # 全文
        asyncio.to_thread(self.store.recent_search, VEC_K),             # 新近度
        asyncio.to_thread(self.store.salient_search, VEC_K),            # 显著性
    )
    # RRF: score = Σ 1 / (rrf_k + rank)，rrf_k=60
    ranked = sorted(scores.items(), key=..., reverse=True)[:top_k]
```

- 每个信号各取 `VEC_K=32` 条候选。
- **RRF（Reciprocal Rank Fusion）**：对同一记忆在多个信号中出现的排名加权求和，鲁棒性优于单一信号。
- 最终**截断为 `[:top_k]`**。

| 信号 | 方法 | 说明 |
|---|---|---|
| 语义向量 | `vector_search` | BGE-M3 嵌入 + sqlite-vec cosine 距离 |
| 全文关键词 | `fts_search` | FTS5 trigram 匹配 |
| 时间新近 | `recent_search` | 越近的记忆权重越高 |
| 显著性 | `salient_search` | salience 字段高者优先 |

### 3. `SQLiteVecStore` —— 持久化存储（`__init__.py:313-324`）

- SQLite 文件（默认 `data/yuiro_memory.db`，WAL 模式）。
- 三张核心表：`messages`（原文）、`messages_vec`（向量）、`messages_fts`（全文索引）。
- `vector_search` 用 `MATCH ? AND k = ? ORDER BY distance` 做近似最近邻。

### 4. `Embedder` —— BGE-M3 嵌入（`__init__.py:166-179`）

- 异步 `embed()`，返回 1024 维向量。
- **子进程隔离**：`spawn` 加载 `FlagEmbedding.BGEM3FlagModel`，通过 `multiprocessing.Pipe` 通信，避免与主进程（ASR/TTS 的 CUDA/GIL）冲突。
- 只开 dense，关闭 sparse/colbert，归一化为单个向量。
- **降级回退**：子进程未就绪/通信异常时，回退到 md5 确定性向量，不阻断流程。

---

## 四、写入机制（每轮对话持久化）

`MemorySystem.remember`（`__init__.py:529-537`）：

```python
async def remember(self, user_text, reply, session_id=None):
    if not user_text.strip():
        return
    text = f"用户: {user_text}\n助手: {reply}"
    await self.retriever.add(text, salience=self._salience(user_text))   # L2 情景落库
    for key, value in self._extract_facts(user_text):
        await self._facts.upsert(self.facts_subject, key, value, confidence=0.9)  # L3 事实
```

- **L2 情景记忆**：`用户/助手` 完整对白写入，带 BGE-M3 向量，持久化。
- **L3 用户事实**：`_extract_facts` 用规则正则（`_FACT_PATTERNS`）抽取用户的名字/身份/喜欢/讨厌等，upsert 到 `facts` 表，confidence=0.9。
- **显著性 `_salience`**：命中偏好/事实模式 → 2.0；长文本 → 1.0；默认 0.8。

> ⚠️ **现状说明**：当前是**"一次写入即长期"**模式——`remember` 直接把对话写入 L2 长期情景表，跨会话可检索。
> **没有**显式 short-term → long-term 分层迁移（会话短期缓冲 + 定期落库的机制尚未实现）。
> `session_id` 参数被 `del` 掉，目前未做会话级隔离/过滤（预留）。

---

## 五、注入 Prompt 的方式

AgentLoop 调 LLM 前（`agent/__init__.py:183`）：

```python
mems = await self._memory.retrieve(text, top_k=3)
memory_lines = [m.text for m in mems if getattr(m, "text", "")]
messages.append({
    "role": "system",
    "content": "相关记忆：\n" + "\n".join(memory_lines),
})
```

即**拼成一条独立的 system 消息**，与 persona 系统提示词、会话内 history 并列传入 LLM。

---

## 六、配置项（`engine/config.toml` → `[memory]`）

| 配置 | 默认 | 作用 | 是否生效 |
|---|---|---|---|
| `auto_inject_top_k` | 3 | 每次检索注入的记忆条数 | ✅ 生效（作为 top_k） |
| `rrf_k` | 60 | RRF 融合的平滑参数 | ✅ 生效 |
| `auto_inject_threshold` | 0.6 | 按相似度阈值过滤记忆 | ⚠️ **预留，未实际消费** |

> ⚠️ **`auto_inject_threshold` 未实现**：`retrieve` 目前按条数截断，**没有**按分数 `> threshold` 过滤。即"只要 top3 就注入，不论与当前问题多相关"。若要"相似度过低就不注入"，需在 `retrieve` 返回前加阈值过滤逻辑。

---

## 七、设计取舍与后续方向

### 已实现
- BGE-M3 语义检索（向量）+ RRF 多信号融合
- SQLite 持久化，跨实例/跨会话检索（测试 `test_memory_persists_across_instances` 验证重启后仍命中）
- 子进程隔离嵌入，避免与主进程资源冲突
- L3 用户事实抽取（规则正则）

### 待优化 / 可能的方向
1. **实现 `auto_inject_threshold`**：检索结果按分数阈值过滤，避免注入无关记忆。
2. **会话级隔离**：`session_id` 已预留，可据此做短期缓冲与长期落库的分层迁移。
3. **嵌入降级策略**：当前 md5 回退向量只保证流程不中断，可加"子进程就绪后重试补嵌入"。
4. **记忆去重 / 压缩**：长期运行后相似记忆可能累积，可考虑摘要合并。
5. **可控性**：是否让用户能在调试台查看/编辑已存记忆。

---

## 八、与 AGENTS.md 的关联

- 记忆/嵌入与 TTS/ASR 的**资源隔离**是同一架构原则：嵌入跑子进程，TTS 跑独立进程，主进程（uvicorn）只做编排与 HTTP/WS。
- `vlog` 分阶段日志原则同样适用于记忆链路：`[memory]` 前缀用于标记检索/写入阶段，便于定位"卡在嵌入还是检索"。
