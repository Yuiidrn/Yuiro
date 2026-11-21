"""Yuiro engine — memory package (three-layer + sqlite-vec + RRF).

- L1: short-term current conversation buffer (sqlite WAL)
- L2: episodic cross-session recall (messages_vec vec0 + FTS5 + recency)
- L3: entity facts (subject/key/value/confidence/decay)
Embedding: BGE-M3 in subprocess isolation (avoids CUDA conflicts), md5-mock fallback.
Retrieval: RRF fuses vector / FTS5 / recency / salience at k=60.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import multiprocessing as mp
import os
import re
import struct
import sys
import time
from typing import ClassVar

logger = logging.getLogger(__name__)

from yuiro.memory.constants import (
    DEFAULT_MODEL,
    DIM,
    EXPLICIT_PREFIX,
    VEC_K,
)


class Memory:
    """A single retrievable memory record."""

    def __init__(self, *, text: str, score: float = 0.0, meta: dict | None = None):
        self.text = text
        self.score = score
        self.meta = meta or {}


def _fallback_vector(text: str, dim: int = DIM) -> list[float]:
    """md5 确定性降级向量：与 BGE-M3 同维，用于子进程不可用时的兜底。

    使用 splitmix64 从 md5 摘要派生 1024 维，再 L2 归一化，保证同文同向量、
    近似保留余弦相似度语义。
    """
    seed = int.from_bytes(hashlib.md5(text.encode("utf-8")).digest(), "big")
    state = seed
    out: list[float] = []
    for _ in range(dim):
        state = (state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        z = z ^ (z >> 31)
        out.append((z / 0xFFFFFFFFFFFFFFFF) * 2.0 - 1.0)
    norm = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / norm for v in out]


def _embed_worker(model_name: str, device: str | None, conn: mp.connection.Connection) -> None:
    """子进程 worker：加载 BGE-M3 并响应嵌入请求，隔离 CUDA 冲突。

    握手协议：先发 ("ready", bool, str)，随后对每条 ("embed", text) 返回向量。
    """
    def _safe_send(*args) -> bool:
        """发送握手消息；管道已关（父进程退出/GC）时静默返回 False，不抛 BrokenPipe。"""
        try:
            conn.send(args)
            return True
        except (EOFError, BrokenPipeError, OSError):
            return False

    try:
        from FlagEmbedding import BGEM3FlagModel  # 延迟导入，避免主进程引入重型依赖

        model = BGEM3FlagModel(
            model_name,
            devices=[device] if device else None,
            use_fp16=False,
        )
        if not _safe_send("ready", True, model_name):
            conn.close()
            return
    except Exception as exc:  # noqa: BLE001 - 子进程需捕获一切加载错误
        _safe_send("ready", False, str(exc))
        conn.close()
        return

    try:
        while True:
            kind, payload = conn.recv()
            if kind == "stop":
                break
            if kind == "embed":
                encoded = model.encode(
                    payload,
                    return_dense=True,
                    return_sparse=False,
                    return_colbert_vecs=False,
                )
                dense = encoded["dense_vecs"]
                # BGE-M3 对单条字符串返回一维向量 (dim,)，对列表返回二维 (batch, dim)。
                # 统一归一为单个一维向量，避免 [0] 取到 float 标量报 TypeError。
                if dense.ndim == 2:
                    dense = dense[0]
                vec = [float(x) for x in dense]
                conn.send(("vec", vec))
            elif kind == "embed_many":
                # S41：一次 IPC 算**一批**。逐条 embed 在"歌单名匹配"这类场景
                #（几十条名字）会产生几十次进程往返，实测慢到语义匹配形同虚设。
                encoded = model.encode(
                    list(payload),
                    return_dense=True,
                    return_sparse=False,
                    return_colbert_vecs=False,
                )
                dense = encoded["dense_vecs"]
                if dense.ndim == 1:  # 单条也走批量入口时，补成 (1, dim)
                    dense = dense.reshape(1, -1)
                conn.send(("vecs", [[float(x) for x in row] for row in dense]))
    except (EOFError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        conn.close()


class Embedder:
    """BGE-M3 (1024-dim)。子进程隔离嵌入，FlagEmbedding 不可用时 md5 兜底。"""

    def __init__(self, model_name: str | None = DEFAULT_MODEL, device: str | None = None) -> None:
        # "md5" 是配置层对「降级确定性向量」的显式写法（config.toml 与大量测试都这么
        # 写），但本类只认 None（None 才不 spawn 子进程）。若不归一，"md5" 会被当成
        # 模型名去 spawn worker、尝试加载失败后才降级 —— **每次白白耗 3s**（实测
        # 20 个测试用例因此慢成整齐的 3.1s 一片）。归一后行为完全一致（都是 md5
        # 向量），只是省掉那次注定失败的 spawn。见 S49。
        if model_name == "md5":
            model_name = None
        self.model_name = model_name
        self.device = device
        self._ready: bool | None = None
        self._proc: mp.Process | None = None
        self._conn: mp.connection.Connection | None = None
        self._ready_reason = "未启动"
        # model_name 为空表示显式要求降级（便于测试与轻量场景）
        if model_name:
            # 净化 sys.path：移除指向其他 Python 安装（含 "ComfyUI"）的外部路径，
            # 否则 spawn 将污染后的 sys.path 传给子进程，使其 import 到错误的
            # multiprocessing 而 BrokenPipe。spawn 子进程继承当前 sys.path，故必须在
            # Process.start() 之前清理父进程。仅按路径特征移除，保留本 venv / 项目路径。
            sys.path = [p for p in sys.path if not p or "ComfyUI" not in p]
            ctx = mp.get_context("spawn")
            parent_conn, child_conn = ctx.Pipe(duplex=True)
            self._conn = parent_conn
            self._proc = ctx.Process(
                target=_embed_worker, args=(model_name, device, child_conn), daemon=True
            )
            self._proc.start()

    def is_ready(self) -> bool:
        """真实 BGE-M3 子进程是否完成加载并可用；降级模式恒为 False。"""
        self._drain_ready()
        return self._ready is True

    def _drain_ready(self) -> None:
        """非阻塞轮询子进程握手消息，确认加载状态。"""
        if self._ready is not None or self._conn is None:
            return
        if self._conn.poll(0):
            try:
                kind, ok, detail = self._conn.recv()
            except (EOFError, BrokenPipeError, OSError):
                self._ready = False
                self._ready_reason = "子进程意外退出"
                self._log_degraded(self._ready_reason)
                return
            if kind == "ready":
                self._ready = bool(ok)
                self._ready_reason = str(detail)
                # ★ 降级必须出声（S50）：此前加载失败被静默吞掉，唯一的信号是
                # "感觉记忆不太准" —— 实测 BGE 权重缺失拖了数周没人发现。
                # _ready 已被置值，本分支天然只打一次。
                if not ok:
                    self._log_degraded(f"BGE-M3 加载失败：{detail}")
        elif self._proc is not None and not self._proc.is_alive():
            self._ready = False
            self._ready_reason = "子进程加载失败并退出"
            self._log_degraded(self._ready_reason)

    def _log_degraded(self, why: str) -> None:
        """降级一次性告警（观测失败不阻断主流程）。"""
        try:
            logger.warning("⚠ 嵌入模型已降级为 md5 向量（无语义）：%s", why)
        except Exception:  # noqa: BLE001
            pass

    async def wait_ready(self, timeout_s: float = 8.0) -> bool:
        """等子进程就绪（BGE-M3 加载要几秒），返回是否可用。

        **为什么必须有它**：``embed()`` 在子进程还没 ready 时会**静默降级成 md5 向量**
        —— 那种向量没有语义，余弦相似度等于随机。调用方（如歌单名匹配）若直接开算，
        会得到一个"看起来跑过了、结果全错"的匹配（实测：说"学习"匹配不到"自习室"，
        因为当时拿的是 md5 向量）。
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.1, timeout_s)
        while loop.time() < deadline:
            self._drain_ready()
            if self._ready is not None:
                return bool(self._ready)
            await asyncio.sleep(0.2)
        return False

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入（S41）：**一次 IPC 算一批**。

        为什么必须有这个入口：歌单名匹配要对几十个候选名算相似度，
        逐条 ``embed`` = 几十次子进程往返（每次几十 ms），实测慢到"语义匹配"
        实际上从不生效（用户说"学习"，53 个歌单里愣是没匹配到"自习室"那个）。
        批量后一次往返解决，语义这条路才真正可用。

        失败时逐条退化为 ``embed``（其内部含 md5 兜底），保证不阻断调用方。
        """
        items = [str(t or "") for t in texts]
        if not items:
            return []
        # **必须分批**：单次 IPC 传太多会让 Pipe 消息过大，子进程连接直接断言失败
        # （实测 129 条 × 1024 维时 `AssertionError: rbytes == left`；
        #  53 条时侥幸能过 —— 上限卡在中间，所以按 16 条一批留足余量）。
        batch = 16
        out: list[list[float]] = []
        for i in range(0, len(items), batch):
            out.extend(await self._embed_one_batch(items[i:i + batch]))
        return out

    async def _embed_one_batch(self, items: list[str]) -> list[list[float]]:
        """单批嵌入（失败则逐条退化为 embed，其内含 md5 兜底）。"""
        self._drain_ready()
        if self._ready is True and self._conn is not None:
            try:
                self._conn.send(("embed_many", items))
                kind, payload = await asyncio.wait_for(
                    asyncio.to_thread(self._conn.recv), timeout=60.0
                )
                if kind == "vecs":
                    return [list(v) for v in payload]
            except Exception:  # noqa: BLE001 — 批量失败则逐条降级
                pass
        return [await self.embed(t) for t in items]

    async def embed(self, text: str) -> list[float]:
        """返回 1024 维向量；子进程未就绪/超时/通信失败时回退到 md5 确定性向量。

        必须给 Pipe 阻塞读加超时：BGE-M3 子进程可能因 GPU 忙/模型加载卡住，
        若无超时，`await embed()` 会无限挂起，连带卡死 AgentLoop 的整条聊天链路。
        """
        self._drain_ready()
        if self._ready is True and self._conn is not None:
            try:
                self._conn.send(("embed", text))
                kind, payload = await asyncio.wait_for(
                    asyncio.to_thread(self._conn.recv), timeout=10.0
                )
                if kind == "vec":
                    return payload
            except TimeoutError:
                logger.warning("BGE-M3 子进程响应超时（>10s），回退 md5")
                self._ready = False
                self._ready_reason = "recv timeout"
            except (EOFError, BrokenPipeError, OSError) as exc:
                logger.warning("BGE-M3 子进程通信失败，回退 md5：%s", exc)
                self._ready = False
                self._ready_reason = str(exc)
        return _fallback_vector(text)

    def close(self) -> None:
        """结束子进程并释放资源。"""
        if self._proc is not None and self._proc.is_alive():
            try:
                if self._conn is not None:
                    self._conn.send(("stop", None))
                self._proc.join(timeout=3)
            except (EOFError, BrokenPipeError, OSError):
                pass
        if self._proc is not None:
            if self._proc.is_alive():
                self._proc.terminate()
            self._proc = None
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# S23：存储层已抽离到 memory/store.py（逐字搬运；此处 re-export 保持兼容）
from yuiro.memory.store import SQLiteVecStore


class Retriever:
    """RRF 融合 vector / FTS5 / recency / salience 四信号。"""

    def __init__(self, embedder: Embedder, rrf_k: int = 60, *, owns_embedder: bool = True) -> None:
        self.embedder = embedder
        self._owns_embedder = owns_embedder
        self.rrf_k = rrf_k
        # 默认内存库；外部可替换为持久化 SQLiteVecStore 以跨会话复用
        self.store = SQLiteVecStore(":memory:")

    async def add(self, text: str, *, ts: float | None = None, salience: float = 1.0) -> int:
        """写入记忆（计算向量后落库），供检索使用。"""
        vector = await self.embedder.embed(text)
        return self.store.add_message(text, vector, ts=ts, salience=salience)

    async def retrieve(self, query: str, top_k: int = 3) -> list[Memory]:
        """返回 RRF 融合后的 top-k 记忆，score 为融合分。"""
        query_vec = await self.embedder.embed(query)
        try:
            vector_hits, fts_hits, recent_hits, salient_hits = await asyncio.wait_for(
                asyncio.gather(
                    asyncio.to_thread(self.store.vector_search, query_vec, VEC_K),
                    asyncio.to_thread(self.store.fts_search, query, VEC_K),
                    asyncio.to_thread(self.store.recent_search, VEC_K),
                    asyncio.to_thread(self.store.salient_search, VEC_K),
                ),
                timeout=5.0,
            )
        except TimeoutError:
            # 检索超时不阻断对话：返回空记忆，AgentLoop 继续走 LLM
            logger.warning("记忆检索超时（>5s），本次跳过记忆注入")
            return []
        scores: dict[int, float] = {}
        meta_by_id: dict[int, dict] = {}
        for hits in (vector_hits, fts_hits, recent_hits, salient_hits):
            for rank, hit in enumerate(hits, start=1):
                rid = int(hit["rowid"])
                scores[rid] = scores.get(rid, 0.0) + 1.0 / (self.rrf_k + rank)
                meta_by_id.setdefault(rid, hit)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        memories: list[Memory] = []
        for rid, score in ranked:
            meta = meta_by_id[rid]
            memories.append(
                Memory(
                    text=meta["text"],
                    score=score,
                    meta={
                        "rowid": rid,
                        "ts": meta["ts"],
                        "salience": meta["salience"],
                        "distance": meta.get("distance"),
                        "fts_rank": meta.get("rank"),
                    },
                )
            )
        # S51：记下"这几条被用到了" —— 空闲期整理靠它区分"常被想起"与"长期没人回顾"。
        # ★ 这一步**必须存在**：不记的话 access_count 恒为 0，冷门压缩会把**所有**旧记忆
        # 都判成"无人回顾"（危险）；而且计数失败绝不能影响本次检索结果。
        if memories:
            try:
                await asyncio.to_thread(
                    self.store.mark_accessed,
                    [int(m.meta.get("rowid", 0)) for m in memories],
                )
            except Exception:  # noqa: BLE001, S110 — 计数失败不影响检索
                pass
        return memories

    def close(self) -> None:
        """释放底层存储与嵌入器。"""
        self.store.close()
        if self._owns_embedder:
            self.embedder.close()


# 历史 facts subject：早期版本把用户画像存在 subject="用户" 下。现在默认改为
# 真实人名（如 "Yui"）以保证人称一致，查询时需回退读取旧 subject 下的历史画像。
_LEGACY_FACTS_SUBJECT = "用户"


class FactsStore:
    """L3 结构化实体存储（subject/key/value/confidence/decay）。"""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.store = SQLiteVecStore(db_path)

    async def upsert(self, subject: str, key: str, value: str, confidence: float = 1.0,
                     decay: float = 0.0) -> None:
        """写入或覆盖一条事实（decay：每秒衰减率，0 = 永不衰减）。"""
        await asyncio.to_thread(self.store.upsert_fact, subject, key, value, confidence, decay)

    async def query(self, subject: str) -> list[dict]:
        """返回 subject 下全部事实（含有效置信度）。"""
        return await asyncio.to_thread(self.store.query_facts, subject)

    def close(self) -> None:
        """释放底层存储。"""
        self.store.close()


class MemorySystem:
    """三层记忆门面（框架版）：L2 情景检索 + L3 用户事实，统一写入/注入。

    灵感来源（docs/debug-log.md §RAG 调研）：
    - 架构（SQLite + FTS5 + vector + RRF）与 eidetic-memory/memento/HoardCore 共识一致
    - 记忆分类（EPISODE vs 用户事实/偏好）借鉴 agentic-memory 的类型化记忆
    - 写入策略（salience 加权 + 偏好模式高显著性）借鉴 memory-hygiene 实践

    框架版：嵌入用 md5 确定性降级向量（不下载 BGE-M3）；事实抽取用
    规则启发式（偏好模式正则）；调优阶段可换 LLM 抽取 + 真嵌入。
    """

    # 用户偏好/事实模式：命中即高 salience，并抽取进 L3 facts。
    _FACT_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"我叫\s*([^\s，。,.!?！？]{1,12})"), "名字"),
        (re.compile(r"我的名字(?:是|叫)\s*([^\s，。,.!?！？]{1,12})"), "名字"),
        (re.compile(r"我是\s*([^\s，。,.!?！？]{1,16})"), "身份"),
        (re.compile(r"我喜欢\s*(.+?)[。.!?！？]?$"), "喜欢"),
        (re.compile(r"我爱(?:吃|喝|玩)?\s*(.+?)[。.!?！？]?$"), "喜欢"),
        (re.compile(r"我讨厌\s*(.+?)[。.!?！？]?$"), "讨厌"),
        (re.compile(r"我不喜欢\s*(.+?)[。.!?！？]?$"), "讨厌"),
        (re.compile(r"我(?:住|家)在\s*(.+?)[。.!?！？]?$"), "住址"),
        (re.compile(r"我的工作(?:是)\s*(.+?)[。.!?！？]?$"), "工作"),
        (re.compile(r"我养了(?:一只|一个)?\s*(.+?)[。.!?！？]?$"), "宠物"),
    ]

    # 明显不是用户画像的"事实值"（S40）。起因是**实测记忆库**里躺着
    # ``名字: 什么名字`` —— 用户反问"我的名字是什么名字？"被当成事实写进了画像，
    # 还进了「自我认知」常驻注入（人设被噪声带偏）。
    _NOT_A_FACT: ClassVar[re.Pattern] = re.compile(
        r"什么|啥|哪个|哪儿|哪里|谁|多少|怎么|为什么|不知道|忘了|记不得|测试|试试|随便"
    )
    #: 声明式事实（首次出现即入库：这些几乎不可能是临时感受）
    _STRONG_FACT_KEYS: ClassVar[frozenset[str]] = frozenset(
        {"名字", "住址", "工作", "宠物", "籍贯"}
    )
    #: 弱信号事实需出现几次才入库（S40：防"一次提及即成画像"）
    _CONFIRM_THRESHOLD: ClassVar[int] = 2

    # 显式记忆指令（S07）：用户明确要求"记住某事"。
    # 命中即走同步写入 + 独立注入通道，不依赖规则/LLM 抽取——后者会主动忽略
    # "一次性事件"，而用户主动要求记住的往往正是这类未来安排（"下周要参加算法竞赛"）。
    _EXPLICIT_PATTERNS: ClassVar[list[re.Pattern]] = [
        re.compile(r"(?:请|帮我|你要|你得|给我)?记住[：:，,、\s]*(?P<content>.+)"),
        re.compile(r"(?:请|帮我)?记一下[：:，,、\s]*(?P<content>.+)"),
        re.compile(r"别忘了[：:，,、\s]*(?P<content>.+)"),
        re.compile(r"记牢[：:，,、\s]*(?P<content>.+)"),
    ]
    # 无实际内容的显式指令（"你记住了吗""记住啦"等）：不算"要记住的事"。
    _EXPLICIT_INVALID: ClassVar[re.Pattern] = re.compile(
        r"^[了吗呢嘛吧啊哦噢嗯好行可以晓得的\s]+$"
    )
    # 显式记忆注入条数上限：用户明确要求记住的事应"总是"能被提起（数量天然很少）。
    _EXPLICIT_INJECT_LIMIT: int = 5
    # 显式记忆写入显著性：高于事实模式（2.0），保证在 RRF/显著性通道中优先。
    _EXPLICIT_SALIENCE: float = 3.0

    def __init__(self, db_path: str, rrf_k: int = 60, top_k: int = 3,
                 facts_subject: str = "Yui", knowledge: KnowledgeStore | None = None,
                 embedder_model: str | None = DEFAULT_MODEL,
                 fact_llm: object | None = None, embedder: Embedder | None = None) -> None:
        # fact_llm：可选的 LLM 提供者（需实现 stream_text），用于增强 L3 事实抽取，
        # 捕获规则正则抓不到的隐含画像（如"广东人→不吃辣"）。为 None 时仅用规则。
        self._fact_llm = fact_llm
        # 后台异步抽取任务的强引用集合。
        # ★ 关键：asyncio.create_task 返回的任务若不被强引用，可能在完成前被 GC 回收，
        # 导致事实抽取"静默丢失"（现象：用户说了画像信息，L3 却查不到）。
        # 这里保存引用并在任务结束时自动移除，既防 GC 又不会无限增长。
        self._pending_tasks: set = set()
        self.store = SQLiteVecStore(db_path)  # 持久化（WAL；sqlite-vec 可用则含向量）
        # 默认 BGE-M3（子进程隔离）；None = md5 降级；模型不可用自动回退 md5。
        self.embedder = embedder if embedder is not None else Embedder(embedder_model)
        self.retriever = Retriever(self.embedder, rrf_k=rrf_k, owns_embedder=embedder is None)
        self.retriever.store = self.store  # 共享持久化存储
        self._facts = FactsStore(db_path)
        # S40：弱信号事实的"出现次数"计数（内存态，重启即清）——
        # 见 _needs_confirmation：同一个事实说两次，才算稳定画像。
        self._confirm_counts: dict[tuple[str, str], int] = {}
        self._knowledge = knowledge  # 可选：知识库 RAG（文档检索）
        self.top_k = top_k
        self.facts_subject = facts_subject
        # 语义检索标志：True 时向量有真实语义（BGE-M3 等），可信任 RRF 融合，
        # 不再做字面 LIKE 兜底过滤；False（md5 降级）时向量无语义，保留 LIKE
        # 过滤避免无关记忆注入。这层开关是"高召回"与"降级保护"的取舍。
        self._semantic = embedder_model is not None and embedder_model != "md5"

    def _extract_facts(self, text: str) -> list[tuple[str, str]]:
        """规则启发式抽取用户事实（快路径；LLM 抽取失败时降级用）。

        早期版本对所有疑问句一律 return []，导致"我可是土生的广东人，我怎么会
        点辣锅呢"这类**以反问语气陈述事实**的句子被整体丢弃（画像全丢）。
        现改为只排除「真·提问」（问号结尾且含疑问代词、或纯疑问句式），
        保留反问/感叹中的事实陈述。
        """
        # 仅排除"真提问"：以问号结尾且含疑问代词，或整句是询问自身信息。
        # 反问句（"我怎么可能点辣锅呢"）不含索取信息的意图，应保留事实。
        is_question = text.rstrip().endswith(("？", "?")) and any(
            w in text for w in ("什么", "啥", "哪个", "多少", "几", "谁")
        )
        if is_question:
            return []
        facts: list[tuple[str, str]] = []
        for pattern, key in self._FACT_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            value = m.group(1).strip()[:60]
            if self._is_plausible_fact_value(value):
                facts.append((key, value))
        return facts

    @classmethod
    def _is_plausible_fact_value(cls, value: str) -> bool:
        """值是否像"稳定的用户画像"（而非提问 / 临时感受 / 测试性发言）。

        S40 加的闸门，对应的实测污染：

        - ``名字: 什么名字`` —— 疑问词（被用户反问带出来）；
        - ``我喜欢这首歌`` —— **指示代词开头**，是当下感受而非稳定偏好；
        - ``我喜欢试试看`` —— 测试性发言。
        """
        v = (value or "").strip()
        # 只拦空值 —— 单字完全可能是合法画像（"猫""辣"），
        # 第一版用 `len < 2` 直接打挂了 consolidation 的"我养了一只猫"。
        if not v:
            return False
        if cls._NOT_A_FACT.search(v):
            return False
        # 指示代词开头 = 指向"当下这个东西"，不是稳定偏好
        return not v.startswith(("这", "那", "刚才", "现在"))

    # 触发 LLM 抽取的信号词：命中任一即认为文本可能含用户事实。
    # 用于成本控制——避免每轮闲聊都额外调一次 LLM。
    _FACT_SIGNALS = (
        "我叫", "我的名字", "我是", "我喜欢", "我爱", "我讨厌", "我不喜欢",
        "我住在", "我家在", "我的工作", "我养了", "我在", "我不吃", "不吃",
        "不喝", "不吃辣", "我是广东", "广东人", "南方", "北方", "本地",
        "习惯", "平时", "一般", "总是", "从来", "过敏", "戒了", "不用",
    )

    @staticmethod
    def _has_fact_signal(text: str) -> bool:
        """文本是否含可能的事实信号（用于决定是否触发 LLM 抽取）。

        S40：**去掉"长度 ≥ 12 就触发"的兜底** —— 那等于"几乎所有长句都调一次 LLM 抽取"，
        既费成本、又容易把闲聊/测试性发言记成画像（实测污染：``名字: 什么名字``）。
        现在只在高信号词命中时才触发：漏抽的概率，换来的是画像的干净。
        """
        return any(s in text for s in MemorySystem._FACT_SIGNALS)

    def _salience(self, user_text: str) -> float:
        """写入显著性：偏好/事实模式 2.0；较长文本 1.0；默认 0.8。"""
        if any(p.search(user_text) for p, _ in self._FACT_PATTERNS):
            return 2.0
        return 1.0 if len(user_text) >= 10 else 0.8

    @classmethod
    def _extract_explicit(cls, text: str) -> str | None:
        """提取用户显式要求记住的内容（无则 None）。

        例：「记住我下周要参加算法竞赛」→「我下周要参加算法竞赛」。
        纯指令词（"记住"/"你记住了吗"）或过短内容视为无内容。
        """
        t = (text or "").strip()
        for p in cls._EXPLICIT_PATTERNS:
            m = p.search(t)
            if not m:
                continue
            content = m.group("content").strip(" 。.，,、!！?？~～")
            if len(content) >= 2 and not cls._EXPLICIT_INVALID.match(content):
                return content[:120]
        return None

    async def _remember_explicit(self, content: str, user_text: str) -> None:
        """显式记忆：立即写入 L2（不等后台抽取），高显著性 + 专用前缀。"""
        try:
            await self.retriever.add(
                f"{EXPLICIT_PREFIX}{content}（用户原话：{user_text}）",
                salience=self._EXPLICIT_SALIENCE,
            )
            from yuiro.logger import vlog

            vlog("memory", f"[显式记忆] 已记住：{content}")
        except Exception:  # noqa: BLE001 — 记忆写入失败不影响对话
            pass

    async def remember(self, user_text: str, reply: str, session_id: str | None = None,
                       tool_trace: str = "") -> None:
        """写入一条情景记忆（L2）+ 抽取用户事实（L3），供跨会话检索。

        ``tool_trace`` 非空（本轮确实执行了工具）时，写入"命令 → 动作"的片段化形式
        （不含傲娇人设口吻），语义更精准且是可安全注入的好范例；为空（纯文字闲聊）时
        保持"用户/助手"转述形式——这类默认不注入上下文（由 episodic_inject 控制），
        避免"光说不做"范例经检索注入后自我强化退化。
        """
        del session_id  # 预留：未来可按会话隔离/过滤
        if not user_text.strip():
            return
        # S07：显式记忆（"记住 X"）→ 立即同步写入，保证用户下一句追问就能检索到。
        # 不依赖规则/LLM 抽取：LLM 抽取 prompt 明确忽略"一次性事件"，
        # 而用户主动要求记住的往往正是这类未来安排（"下周要参加算法竞赛"）。
        explicit = self._extract_explicit(user_text)
        if explicit is not None:
            await self._remember_explicit(explicit, user_text)
        # 无 fact_llm：同步走模板（零延迟路径），保证任何情况下记忆都会落库。
        if self._fact_llm is None:
            await self._write_episode(user_text, reply, tool_trace, summary=None)
            rule_facts = self._gate_facts(self._extract_facts(user_text), "rule")
            if rule_facts:
                await self._apply_facts(rule_facts, source="rule")
            return
        # 有 fact_llm：交给后台任务，一次 LLM 调用同时产出「事件摘要 + 事实」，
        # 再写入 L2/L3。摘要生成失败时自动降级为模板，记忆绝不丢失。
        # ★ 必须用 _spawn 保存任务强引用，否则任务可能被 GC 导致写入静默丢失。
        self._spawn(self._remember_async(user_text, reply, tool_trace))

    def _compose_episode(self, user_text: str, reply: str, tool_trace: str,
                         summary: str | None) -> str:
        """合成一句自然语言的情景记忆（L2 存档文本）。

        优先用 LLM 摘要；否则按「是否含工具事件」拼自然语言模板。
        注意：tool_trace 传入的已是自然语言事件（见 AgentLoop._describe_tool_event），
        不再是 "app_open(name=X)->done" 这类机器日志。
        """
        if summary:
            return summary.strip()
        if tool_trace:
            # 工具轮：事件 + 用户当时的原话，便于按命令检索命中
            return f"{tool_trace}（当时用户说：{user_text}）"
        # 闲聊轮：口语化转述，避免 "用户: xxx\n助手: yyy" 的生硬日志体
        return f"用户说：{user_text}；我回复：{reply}"

    async def _write_episode(self, user_text: str, reply: str, tool_trace: str,
                             summary: str | None) -> None:
        """写入一条 L2 情景记忆（失败静默，不阻断对话）。"""
        try:
            text = self._compose_episode(user_text, reply, tool_trace, summary)
            await self.retriever.add(text, salience=self._salience(user_text))
        except Exception:  # noqa: BLE001 — 记忆写入失败不影响对话
            pass

    async def _remember_async(self, user_text: str, reply: str, tool_trace: str) -> None:
        """后台任务：一次 LLM 调用同时拿到事件摘要与事实，写入 L2/L3。

        两部分都做了降级：LLM 失败/超时/返回空 → 事件回退模板、事实回退正则，
        因此开启 LLM 增强不会让记忆变得"更脆弱"。
        """
        summary: str | None = None
        facts: list[tuple[str, str]] = []
        try:
            summary, facts = await self._extract_episode_and_facts(
                user_text, reply, tool_trace
            )
        except Exception:  # noqa: BLE001
            pass
        await self._write_episode(user_text, reply, tool_trace, summary)
        if not facts:
            facts = self._extract_facts(user_text)
            await self._apply_facts(self._gate_facts(facts, "rule"), source="rule")
        else:
            await self._apply_facts(
                self._gate_facts(facts, "llm"), source="llm", confidence=0.85
            )

    async def _extract_episode_and_facts(
        self, user_text: str, reply: str, tool_trace: str
    ) -> tuple[str | None, list[tuple[str, str]]]:
        """一次 LLM 调用同时产出：情景事件摘要 + 用户事实。

        合并为单次调用是为了不增加额外往返（事实抽取原本就要调一次），
        从而在不牺牲延迟的前提下让 L2 记忆也变成自然语句。
        """
        if self._fact_llm is None:
            return None, []
        event_hint = f"本轮我执行过的操作：{tool_trace}\n" if tool_trace else ""
        prompt = (
            "下面是刚刚发生的一段对话，请完成两件事：\n"
            "1) 用一句自然的中文概括「刚才发生了什么」，作为记忆存档。"
            "要求：以「我」为主语叙述自己的行为，20-40 字，"
            "不要出现工具名、参数、状态码等技术术语。\n"
            "2) 从中抽取**关于用户的稳定事实**（身份/籍贯/口味/习惯/长期偏好等）。"
            "**严格排除**以下情况，宁可写「无」也不要猜：\n"
            "   - 用户的**提问或反问**（例：「我的名字是什么名字？」→ 无）；\n"
            "   - **临时感受 / 当下指代**（例：「我喜欢这首歌」→ 无，因为「这首」不是长期偏好）；\n"
            "   - **测试性或试探性发言**（例：「我喜欢试试看」「随便说说」→ 无）；\n"
            "   - 一次性动作、事件、请求（例：「帮我放首歌」→ 无）。\n"
            "   只有明确表达**长期属性**时才抽取（例：「我是广东人」「我不吃辣」「我养了一只猫」）。\n\n"
            f"{event_hint}"
            f"用户说：{user_text}\n"
            f"我回复：{reply}\n\n"
            "严格按以下格式输出，不要任何多余文字：\n"
            "摘要：<一句话概括>\n"
            "事实：<键>: <值>\n"
            "事实：<键>: <值>\n"
            "（没有可抽取的事实时，写一行：事实：无）"
        )
        raw = ""
        try:
            async for chunk in self._fact_llm.stream_text(
                [{"role": "user", "content": prompt}], tools=None
            ):
                if chunk.kind == "token":
                    raw += chunk.content
        except Exception:  # noqa: BLE001
            return None, []
        summary: str | None = None
        facts: list[tuple[str, str]] = []
        for line in raw.splitlines():
            line = line.strip().lstrip("-•*0123456789.、) ")
            if not line:
                continue
            if line.startswith("摘要") and ("：" in line or ":" in line):
                sep = "：" if "：" in line else ":"
                value = line.split(sep, 1)[1].strip()
                if value and value != "无":
                    summary = value[:120]
            elif line.startswith("事实") and ("：" in line or ":" in line):
                sep = "：" if "：" in line else ":"
                body = line.split(sep, 1)[1].strip()
                if not body or body == "无":
                    continue
                if ":" in body:
                    key, value = body.split(":", 1)
                elif "：" in body:
                    key, value = body.split("：", 1)
                else:
                    continue
                key, value = key.strip()[:20], value.strip()[:60]
                if key and value:
                    facts.append((key, value))
        return summary, facts

    def _spawn(self, coro) -> None:
        """启动后台任务并持有强引用（防 GC），完成后自动从集合移除。"""
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:  # 无运行中事件循环（如同步上下文调用）
            try:
                coro.close()  # 避免 "coroutine was never awaited" 警告
            except Exception:  # noqa: BLE001
                pass
            return
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    # 事实衰减率（S13）：每秒衰减 ≈ 每天 2%（一个月后有效置信度约 55%）
    # —— 陈旧事实在注入排序中自然靠后，但不会消失；explicit 来源永不衰减。
    _FACT_DECAY_PER_DAY: ClassVar[float] = 0.02
    # S28：归纳（推断）事实衰减更快（每天 5%）——推断可能错，应比用户亲口说的更快淡出。
    _CONSOLIDATION_DECAY_PER_DAY: ClassVar[float] = 0.05

    @classmethod
    def _decay_for(cls, source: str) -> float:
        """按来源决定衰减率（explicit = 永不衰减；consolidation = 更快）。"""
        if source == "explicit":
            return 0.0
        if source == "consolidation":
            return cls._CONSOLIDATION_DECAY_PER_DAY / 86400.0
        return cls._FACT_DECAY_PER_DAY / 86400.0

    def _needs_confirmation(self, key: str, value: str) -> bool:
        """弱信号事实是否"还没到入库门槛"（首次 True / 第二次 False）。

        **S40 的动机来自实测记忆库的污染**：

        - ``名字: 什么名字`` —— 用户反问"我的名字是什么名字？"；
        - ``歌曲偏好: 《谁》Live版`` —— 单首歌被当成稳定画像。

        它们一旦入库就进入「自我认知」常驻注入，人设会被噪声带偏。

        判定：**声明式**事实（名字/住址/工作/宠物）首次即入库；
        **弱信号**（我是 / 我喜欢 / 我讨厌 …）需同一 key+value 出现 ``_CONFIRM_THRESHOLD`` 次。
        计数只在内存 —— 代价是"重启后要再说一次"，换来的是画像不求全但求准。
        """
        if key in self._STRONG_FACT_KEYS:
            return False
        k = (key, str(value).strip())
        count = self._confirm_counts.get(k, 0) + 1
        self._confirm_counts[k] = count
        return count < self._CONFIRM_THRESHOLD

    def _gate_facts(self, facts: list[tuple[str, str]], source: str) -> list[tuple[str, str]]:
        """确认门（S40）：**只作用于粗规则抽取**，弱信号事实首次只计数、不入库。

        为什么只卡 ``rule``：

        - **规则**（正则）粗 —— "我喜欢这首歌"、"我是来测试的"都能命中，需要"再说一次"兜底；
        - **LLM 抽取**已有两重闸门（prompt 明确排除提问/临时感受 + 值过滤），
          再叠加确认会让合理画像（"我是广东人→籍贯"）被无谓延迟；
        - ``consolidation`` 本身就有支持度门槛；``explicit`` 是用户明确要求 —— 一次即当。

        **刻意放在调用点而不是 `_apply_facts` 内**：后者是"写入原语"，契约是
        "调用即写入"，遗忘/衰减/归纳链路都依赖它。第一版把门塞进原语，
        直接打挂 6 个既有记忆测试 —— 策略归策略，原语归原语。
        """
        if source != "rule" or not facts:
            return facts
        kept = [f for f in facts if not self._needs_confirmation(f[0], f[1])]
        if not kept:
            from yuiro.logger import vlog

            vlog("memory", f"[事实] {len(facts)} 条规则抽取首次出现，暂不入库（待确认）")
        return kept

    async def _apply_facts(self, facts: list[tuple[str, str]], source: str,
                           confidence: float = 0.9) -> None:
        """把抽取到的事实写入 L3，并做冲突消解（Mem0/SOTA 做法）。

        借鉴 Mem0 的 ADD/UPDATE/NOOP 判定：
        - 同 key 且同 value        → NOOP（跳过，避免无谓写入）
        - 同 key 但 value 变化    → UPDATE（覆盖旧值，如"喜欢辣"→"不吃辣"）
        - 新 key                   → ADD
        每次写入都有 vlog，便于观测"记忆有没有真的存进去"。
        """
        if not facts:
            return
        try:
            existing = await self._facts.query(self.facts_subject)
        except Exception:  # noqa: BLE001
            existing = []
        old_map = {f.get("key", ""): f.get("value", "") for f in existing}
        for key, value in facts:
            key = self._normalize_key(key)
            if not key or not value:
                continue
            old_value = old_map.get(key)
            if old_value == value:
                continue  # NOOP
            try:
                await self._facts.upsert(
                    self.facts_subject, key, value, confidence,
                    decay=self._decay_for(source),
                )
            except Exception:  # noqa: BLE001 — 写入失败不阻断
                continue
            action = "UPDATE" if old_value is not None else "ADD"
            try:
                from yuiro.logger import vlog
                if action == "UPDATE":
                    vlog("memory", f"[事实{action}·{source}] {key}: {old_value!r} → {value!r}")
                else:
                    vlog("memory", f"[事实{action}·{source}] {key}: {value!r}")
            except Exception:  # noqa: BLE001
                pass

    # 事实注入上下文的条数上限（独立于 top_k）。
    # top_k 服务于「情景片段检索」，默认仅 3 条；用户画像若被同样截断，
    # 会导致多数事实永远注入不进提示词（表现为"记不住用户"）。
    # 画像条目少且短，这里放宽到 8 条，几乎等同全量注入。
    _FACT_INJECT_LIMIT: int = 8

    # 同义 key 归并表：LLM 抽取的 key 常常五花八门（籍贯/家乡/来自/老家），
    # 若直接入库会导致 key 爆炸、同一画像散落多处，检索时命中不全。
    _KEY_ALIASES: dict[str, str] = {
        "家乡": "籍贯", "老家": "籍贯", "来自": "籍贯", "出生地": "籍贯", "哪里人": "籍贯",
        "姓名": "名字", "称呼": "名字", "叫什么": "名字",
        "职业": "工作", "职位": "工作", "干什么": "工作", "上班": "工作",
        "爱好": "喜欢", "兴趣": "喜欢", "喜好": "喜欢", "爱": "喜欢",
        "反感": "讨厌", "不喜欢": "讨厌", "厌恶": "讨厌", "忌口": "讨厌",
        "口味": "饮食偏好", "饮食": "饮食偏好", "吃的": "饮食偏好", "忌食": "饮食偏好",
        "岁数": "年龄", "年纪": "年龄", "多大": "年龄",
        "住处": "住址", "所在地": "住址", "城市": "住址",
    }

    @classmethod
    def _normalize_key(cls, key: str) -> str:
        """把同义 key 归并到统一主 key，避免 key 爆炸。"""
        key = (key or "").strip()
        return cls._KEY_ALIASES.get(key, key)

    # ---- 生命周期（S13）------------------------------------------------------
    def list_explicit(self, limit: int = 20) -> list[dict]:
        """列出显式记忆（用户要求记住的事；供管理 API）。"""
        try:
            return self.store.explicit_search(k=limit)
        except Exception:  # noqa: BLE001 — 读取失败返回空
            return []

    def delete_explicit(self, rowid: int) -> bool:
        """删除一条显式记忆（"忘掉这个"）。"""
        try:
            conn = self.store.conn
            conn.execute("DELETE FROM messages WHERE rowid = ?", (rowid,))
            conn.execute("DELETE FROM messages_fts WHERE rowid = ?", (rowid,))
            try:
                conn.execute("DELETE FROM messages_vec WHERE rowid = ?", (rowid,))
            except Exception:  # noqa: BLE001, S110 — vec 表可能不可用
                pass
            conn.commit()
            return True
        except Exception:  # noqa: BLE001 — 删除失败视为未发生
            return False

    async def forget(self, *, fact_keep_days: float = 90.0, min_confidence: float = 0.15,
                     episode_keep_days: float = 60.0) -> dict:
        """记忆遗忘（S13）：清理"陈旧且已衰减"的事实与过老的低显著性情景。

        铁律：**显式记忆永不删除**（用户明确要求记住的事）。
        """
        result = await asyncio.to_thread(
            self._forget_sync, fact_keep_days, min_confidence, episode_keep_days
        )
        if result.get("facts_removed") or result.get("episodes_removed"):
            try:
                from yuiro.logger import vlog

                vlog(
                    "memory",
                    f"[遗忘] 事实 -{result['facts_removed']} / 情景 -{result['episodes_removed']}",
                )
            except Exception:  # noqa: BLE001
                pass
        return result

    async def consolidate(self, *, min_support: int = 3, max_episodes: int = 200,
                          use_llm: bool = True) -> dict:
        """S28：把**反复出现**的画像信息归纳为稳定事实（异步；不阻塞、不降级已有）。

        规范红线（``architecture-goal.md`` §3.10）：

        - **不阻塞**：只在维护循环 / 手动触发时运行，绝不进入聊天主链路；
        - **不污染当前状态**：只写 L3 facts（不改会话与近期记忆），输入是**快照**；
        - **推断 ≠ 事实**：来源为 ``consolidation``（衰减更快、置信度上限 0.7），
          错误归纳会自然淡出；已有更可信的事实时**不覆盖**。

        返回结果 dict（可观测：扫描/候选/采纳/跳过原因）。
        """
        from yuiro.logger import vlog
        from yuiro.memory.consolidation import Consolidator

        cons = Consolidator(min_support=min_support)
        try:
            rows = self.store.recent_search(k=max_episodes)
        except Exception:  # noqa: BLE001 — 读取失败不阻断
            rows = []
        episodes: list[str] = []
        for r in rows:
            text = str(r.get("text", ""))
            # 显式记忆是用户的直接意图，不该被"推断"改写
            if not text.strip() or text.startswith(EXPLICIT_PREFIX):
                continue
            episodes.append(text)

        counter = cons.collect_candidates(episodes, self._extract_facts)
        llm_facts: list[tuple[str, str]] = []
        if use_llm and self._fact_llm is not None and episodes:
            llm_facts = await cons.llm_candidates(self._fact_llm, episodes)

        try:
            existing = await self._facts.query(self.facts_subject)
        except Exception:  # noqa: BLE001 — 查询失败按"无已有"处理
            existing = []

        accepted, skipped_existing, skipped_low = cons.apply_safety(
            counter, existing, llm_facts=llm_facts
        )
        written = 0
        if accepted:
            await self._apply_facts(
                [(k, v) for k, v, _ in accepted],
                source="consolidation",
                confidence=cons.confidence_cap,
            )
            written = len(accepted)

        result = {
            "scanned": len(episodes),
            "candidates": len(counter) + len(llm_facts),
            "accepted": len(accepted),
            "written": written,
            "skipped_low_support": skipped_low,
            "skipped_existing": skipped_existing,
            "llm_used": bool(llm_facts),
            "details": [
                {"key": k, "value": v, "support": counter.get((k, v), 0)}
                for k, v, _ in accepted
            ],
        }
        if written:
            vlog(
                "memory",
                f"[归纳] 扫描 {len(episodes)} 条情景 → 写入 {written} 条稳定画像",
            )
        else:
            vlog(
                "memory",
                f"[归纳] 扫描 {len(episodes)} 条情景 → 无新画像"
                f"（低支持 {skipped_low} / 已有 {skipped_existing}）",
            )
        return result

    # ---- 空闲期整理（S51）--------------------------------------------------
    #: 语义重复判定：向量**距离**上限（越小越像；0.06 ≈ 余弦相似度 0.94）。
    #: 刻意偏紧：宁可少合，不可把"两件不同的事"合成一条。
    _TIDY_MERGE_DISTANCE: ClassVar[float] = 0.06
    #: "长期无人回顾"的年龄下限（天）
    _TIDY_STALE_DAYS: ClassVar[float] = 45.0
    #: 视为"无人回顾"的最大访问次数（0 = 从没被检索命中过）
    _TIDY_STALE_MAX_ACCESS: ClassVar[int] = 0
    #: 至少这么多条冷门记忆才值得压缩（太少不如留着）
    _TIDY_COMPRESS_MIN: ClassVar[int] = 3

    async def tidy(self, *, max_merge: int = 20, max_compress: int = 30,
                   use_llm: bool = True) -> dict:
        """空闲期整理：**语义重复归一 + 冷门记忆压缩**（异步、保守、可观测）。

        与既有三条链路的分工（别混在一起）：

        - ``forget``      ：按**时间**过期就删；
        - ``consolidate`` ：L2 → L3，反复出现的升级为**稳定画像**；
        - ``tidy``（本方法）：**在 L2 内部做减法** —— 重复归一、冷门压缩。

        ★ 三条红线（与 consolidation 同源）：

        1. **不阻塞**：只在空闲/会话结束时跑，绝不进聊天主链路；
        2. **不误伤**：只动"语义几乎相同"与"长期无人回顾"的；归一时**保留信息更全的
           原文**（不改写、不做摘要 → 零幻觉）；冷门判定要求"够老 **且** 从没被检索命中"；
        3. **可观测**：返回每一项到底做了什么（合了/压了哪些 rowid），并写 vlog。
        """
        from yuiro.logger import vlog

        result: dict = {
            "merged": 0,
            "merge_removed": [],
            "compressed": 0,
            "compressed_from": [],
            "scanned": 0,
            "skipped": 0,
        }

        # ── ① 语义重复 → 归一 ────────────────────────────────────────────────
        if self.store.vec_available:
            try:
                rows = await asyncio.to_thread(self.store.recent_search, 200)
            except Exception:  # noqa: BLE001
                rows = []
            result["scanned"] = len(rows)
            seen: set[int] = set()
            for r in rows:
                if result["merged"] >= max_merge:
                    break
                rid = int(r["rowid"])
                if rid in seen:
                    continue
                try:
                    nb = await asyncio.to_thread(self.store.nearest_other, rid)
                except Exception:  # noqa: BLE001
                    nb = None
                if nb is None or float(nb["distance"]) > self._TIDY_MERGE_DISTANCE:
                    continue
                other = int(nb["rowid"])
                if other in seen:
                    continue
                try:
                    pair = await asyncio.to_thread(self.store.message_rows, [rid, other])
                except Exception:  # noqa: BLE001
                    continue
                if len(pair) < 2:
                    continue
                keep, drop = self._pick_merge_pair(pair[0], pair[1])
                try:
                    await asyncio.to_thread(
                        self.store.delete_messages, [int(drop["rowid"])]
                    )
                except Exception:  # noqa: BLE001
                    result["skipped"] += 1
                    continue
                seen.update({rid, other})
                result["merged"] += 1
                result["merge_removed"].append(int(drop["rowid"]))
            if result["merged"]:
                vlog(
                    "memory",
                    f"[整理] 语义重复归一 {result['merged']} 条"
                    f"（保留信息更全的原文，删 {result['merge_removed'][:8]}…）",
                )

        # ── ② 长期无人回顾 → 压缩成简短摘要 ──────────────────────────────────
        cutoff = time.time() - self._TIDY_STALE_DAYS * 86400
        try:
            stale = await asyncio.to_thread(
                self.store.stale_messages,
                older_than_ts=cutoff,
                max_access=self._TIDY_STALE_MAX_ACCESS,
                limit=max_compress,
            )
        except Exception:  # noqa: BLE001
            stale = []
        if len(stale) >= self._TIDY_COMPRESS_MIN and self._fact_llm is not None and use_llm:
            summary = await self._summarize_stale(stale)
            if summary:
                earliest = min(float(s["ts"]) for s in stale)
                vec = None
                try:
                    vec = await self.embedder.embed(summary)
                except Exception:  # noqa: BLE001 — 无向量则退化为仅 FTS/recency
                    vec = None
                try:
                    new_id = await asyncio.to_thread(
                        self.store.add_message, summary, vec, earliest, 0.6
                    )
                    removed = await asyncio.to_thread(
                        self.store.delete_messages, [int(s["rowid"]) for s in stale]
                    )
                    result["compressed"] = removed
                    result["compressed_from"] = [int(s["rowid"]) for s in stale]
                    result["summary_rowid"] = int(new_id)
                    vlog(
                        "memory",
                        f"[整理] 冷门压缩 {len(stale)} 条 → 1 条摘要"
                        f"（均已 {self._TIDY_STALE_DAYS:.0f} 天以上没被想起）",
                    )
                except Exception as exc:  # noqa: BLE001
                    result["skipped"] += 1
                    vlog("memory", f"[整理] 压缩写入失败（跳过）：{type(exc).__name__}: {exc}")
        return result

    @staticmethod
    def _pick_merge_pair(a: dict, b: dict) -> tuple[dict, dict]:
        """语义重复的两条里留哪条：**留信息更多的**（文本更长）；
        等长则留**更早**的那条（保持它在时间线上的位置）。

        刻意不做任何改写 —— 归一只是"去重"，不产生新文本，因此零幻觉风险。
        """
        ta, tb = str(a.get("text") or ""), str(b.get("text") or "")
        if len(ta) != len(tb):
            return (a, b) if len(ta) > len(tb) else (b, a)
        return (a, b) if float(a.get("ts") or 0) <= float(b.get("ts") or 0) else (b, a)

    async def _summarize_stale(self, rows: list[dict]) -> str:
        """把若干条冷门旧记忆压成一两句（**只压缩、不添加**）。失败返回空串。"""
        lines = "\n".join(f"- {str(r.get('text') or '')[:120]}" for r in rows)
        prompt = (
            "下面是我过去陆续留下的几条零散记忆（按时间先后）。\n"
            "请把它们压缩成**一到两句**中文，只保留共同的主题与关键事实。\n"
            "要求：不添加原文没有的任何信息；不做评价、不猜测、不补全；"
            "只输出压缩后的句子本身。\n\n" + lines
        )
        parts: list[str] = []
        try:
            async for chunk in self._fact_llm.stream_text(
                [{"role": "user", "content": prompt}], tools=None
            ):
                if getattr(chunk, "kind", "") == "token":
                    parts.append(str(getattr(chunk, "content", "")))
        except Exception as exc:  # noqa: BLE001 — 压缩失败就本轮不做，绝不半途改数据
            from yuiro.logger import vlog

            vlog("memory", f"[整理] 冷门压缩生成失败（本轮跳过）：{type(exc).__name__}: {exc}")
            return ""
        return "".join(parts).strip()[:200]

    def _forget_sync(self, fact_keep_days: float, min_confidence: float,
                     episode_keep_days: float) -> dict:
        now = time.time()
        conn = self.store.conn
        facts_removed = 0
        episodes_removed = 0
        try:
            rows = conn.execute(
                "SELECT key, confidence, decay, updated_at FROM facts WHERE subject = ?",
                (self.facts_subject,),
            ).fetchall()
            for r in rows:
                age = max(0.0, now - float(r["updated_at"]))
                effective = float(r["confidence"]) * math.exp(-float(r["decay"]) * age)
                if age >= fact_keep_days * 86400 and effective < min_confidence:
                    conn.execute(
                        "DELETE FROM facts WHERE subject = ? AND key = ?",
                        (self.facts_subject, r["key"]),
                    )
                    facts_removed += 1
        except Exception:  # noqa: BLE001, S110 — 遗忘失败不影响主链路
            pass
        try:
            cutoff = now - episode_keep_days * 86400
            olds = conn.execute(
                "SELECT rowid FROM messages WHERE ts < ? AND salience < 2.0 "
                "AND text NOT LIKE ?",
                (cutoff, EXPLICIT_PREFIX + "%"),
            ).fetchall()
            for r in olds:
                rid = r["rowid"]
                conn.execute("DELETE FROM messages WHERE rowid = ?", (rid,))
                conn.execute("DELETE FROM messages_fts WHERE rowid = ?", (rid,))
                try:
                    conn.execute("DELETE FROM messages_vec WHERE rowid = ?", (rid,))
                except Exception:  # noqa: BLE001, S110 — vec 表可能不可用
                    pass
                episodes_removed += 1
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            conn.commit()
        except Exception:  # noqa: BLE001, S110
            pass
        return {"facts_removed": facts_removed, "episodes_removed": episodes_removed}

    async def retrieve(self, query: str, top_k: int | None = None) -> list[Memory]:
        """检索注入上下文：L2 情景（RRF）+ L3 用户事实 + 知识库（可选）。

        三类结果统一为 Memory 列表；知识库结果以 "（知识库）" 前缀标注。
        """
        k = top_k or self.top_k
        memories = await self.retriever.retrieve(query, top_k=k)
        # [召回修复] 旧逻辑在 retriever 已返回 top-k 之后，又用「查询核心词必须字面
        # 出现在记忆文本」做硬性 LIKE 过滤，会砍掉语义相关但字面不重叠的记忆
        # （如「我想听歌」匹配不到「打开了网易云音乐」），严重损害召回率。
        # 仅在非语义嵌入（md5 降级，向量无语义）时保留该字面过滤作为退化保护；
        # 语义嵌入（BGE-M3 等）时信任 RRF 融合，不做字面裁剪，恢复语义召回。
        if not self._semantic:
            try:
                core = "".join(ch for ch in query if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
                if core:
                    memories = [
                        m for m in memories
                        if core in "".join(ch for ch in m.text if ch.isalnum()
                                           or "\u4e00" <= ch <= "\u9fff")
                    ]
            except Exception:  # noqa: BLE001 — 门槛过滤失败回退为不过滤（不阻断对话）
                pass
        if self._knowledge is not None:
            try:
                for doc in await self._knowledge.retrieve(query, top_k=k):
                    # 引用溯源：带来源标注（有 source 时附在尾部）
                    source = doc.get("source", "")
                    text = f"（知识库）{doc['text'][:200]}"
                    if source:
                        text += f"\n（来源: {source}）"
                    memories.append(
                        Memory(
                            text=text,
                            score=doc.get("score", 0.0),
                            meta={"kind": "knowledge", "source": source},
                        )
                    )
            except Exception:  # noqa: BLE001 — 知识库检索失败不阻断
                pass
        try:
            facts = await self._facts.query(self.facts_subject)
            # 兼容回退：facts subject 改名后（如 "用户" → "Yui"），历史事实仍应可见，
            # 否则此前积累的用户画像会突然"失忆"。新 subject 查不到时回退读旧 subject。
            if not facts and self.facts_subject != _LEGACY_FACTS_SUBJECT:
                facts = await self._facts.query(_LEGACY_FACTS_SUBJECT)
        except Exception:  # noqa: BLE001 — facts 读取失败不阻断
            facts = []
        # 事实注入上限独立于 top_k：top_k(默认3) 是为「情景片段检索」设计的，
        # 用它截断用户画像会让多数事实永远注入不进来（现象：记忆"没呼出"）。
        # 用户画像条目本身很少且短，这里按有效置信度排序后取前 _FACT_INJECT_LIMIT 条。
        try:
            facts.sort(key=lambda f: float(f.get("effective_confidence", 1.0)), reverse=True)
        except Exception:  # noqa: BLE001
            pass
        injected = facts[:self._FACT_INJECT_LIMIT]
        if injected:
            try:
                from yuiro.logger import vlog
                # vlog("memory",
                #      f"[事实注入] 共 {len(facts)} 条，注入 {len(injected)} 条："
                #      + "; ".join(f"{f.get('key','')}={f.get('value','')}" for f in injected))
            except Exception:  # noqa: BLE001
                pass
        for f in injected:
            value = f.get("value", "")
            memories.append(
                Memory(
                    # 用 subject 动态标注事实归属（默认 "Yui"），而非笼统的"已知事实"。
                    # 这让 LLM 明确这些画像属于正在对话的 Yui 本人，避免把事实当成
                    # 某个第三方的信息（人称一致性）。
                    text=f"（{self.facts_subject}的事实）{f.get('key', '')}: {value}",
                    score=f.get("effective_confidence", 1.0),
                    meta={"kind": "fact"},
                )
            )
        # 显式记忆通道（S07）：用户明确要求记住的事"总是"注入（不受 top_k / 相关性限制），
        # 否则会被情景检索挤掉——这正是"说了却没记住"的信任缺口来源。
        try:
            for row in self.store.explicit_search(k=self._EXPLICIT_INJECT_LIMIT):
                text = str(row.get("text", ""))
                content = (
                    text.removeprefix(EXPLICIT_PREFIX)
                )
                memories.append(
                    Memory(
                        text=f"（用户要求记住）{content}",
                        score=float(row.get("salience", self._EXPLICIT_SALIENCE)),
                        meta={"kind": "explicit"},
                    )
                )
        except Exception:  # noqa: BLE001 — 显式记忆读取失败不阻断
            pass
        return memories

    async def forget_text(self, text: str) -> int:
        """按**文本精确匹配**删除 L2 情景条目；返回删除条数（S51）。

        为什么需要它：日记从"共享"改为"仅保存"（或删除）时，必须把**已写入的
        记忆条目**一并清掉 —— 否则用户以为"改成私密就安全了"，记忆里却还留着
        （谎报隐私，与 S50 的"删了还在"同类）。

        ★ **三表齐删**（S50 教训）：``messages`` / ``messages_fts`` / ``messages_vec``
        都要清，否则向量与 FTS 索引留下孤儿行 —— 既造成"删了还在"的错觉，
        又让孤儿占着 rowid 污染语义检索。
        """
        target = (text or "").strip()
        if not target:
            return 0

        def _do() -> int:
            rows = self.store.conn.execute(
                "SELECT rowid FROM messages WHERE text = ?", (target,)
            ).fetchall()
            for r in rows:
                rid = int(r["rowid"])
                self.store.conn.execute("DELETE FROM messages WHERE rowid = ?", (rid,))
                self.store.conn.execute("DELETE FROM messages_fts WHERE rowid = ?", (rid,))
                self.store.conn.execute("DELETE FROM messages_vec WHERE rowid = ?", (rid,))
            self.store.conn.commit()
            return len(rows)

        return await asyncio.to_thread(_do)

    def close(self) -> None:
        self.retriever.close()
        self._facts.close()
        if self._knowledge is not None:
            self._knowledge.close()


class KnowledgeStore:
    """知识库 RAG：文档切块 → 向量 + FTS5 入库 → RRF 混合检索。

    与情景记忆共用同一个 SQLite 文件但独立表（knowledge_chunks /
    knowledge_vec / knowledge_fts），语义不混。嵌入默认 BGE-M3（子进程
    隔离），模型不可用时自动降级 md5 确定性向量。
    """

    CHUNK_SIZE = 500  # 字符
    CHUNK_OVERLAP = 50

    def __init__(self, db_path: str, rrf_k: int = 60,
                 embedder_model: str | None = DEFAULT_MODEL, embedder: Embedder | None = None) -> None:
        self.store = SQLiteVecStore(db_path)
        self._owns_embedder = embedder is None
        self.embedder = embedder if embedder is not None else Embedder(embedder_model)
        self.rrf_k = rrf_k
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = self.store.conn
        conn.execute(
            "CREATE TABLE IF NOT EXISTS knowledge_chunks ("
            "rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
            "text TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', ts FLOAT NOT NULL)"
        )
        if self.store.vec_available:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_vec USING vec0("
                "embedding float[1024], chunk_size=256)"
            )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
            "text, source, tokenize='trigram')"
        )
        conn.commit()

    def _chunk_text(self, text: str) -> list[str]:
        """按标题切块（Markdown）：``#/##/###`` 标题为界，标题路径作前缀。

        每段保留其所属标题链（如 "M4 AI 动手 > 验收"），提升检索时的
        上下文完整性；无标题的纯文本回退固定长度滑窗。
        """
        import re as _re

        # 提取标题行（# 级数 + 标题文本）
        heading_re = _re.compile(r"^(#{1,6})\s+(.+)$", _re.MULTILINE)
        headings = list(heading_re.finditer(text))
        if not headings:
            # 纯文本：固定长度滑窗（带重叠）
            step = self.CHUNK_SIZE - self.CHUNK_OVERLAP
            n = len(text)
            if n <= self.CHUNK_SIZE:
                return [text]
            return [text[i : i + self.CHUNK_SIZE] for i in range(0, n, step)]

        chunks: list[str] = []
        # 标题链栈：[级数, 文本]
        stack: list[tuple[int, str]] = []
        for idx, m in enumerate(headings):
            level = len(m.group(1))
            title = m.group(2).strip()
            # 维护标题链：弹出不小于当前级数的标题
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            # 本段内容：当前标题到下一个标题之间
            start = m.end()
            end = headings[idx + 1].start() if idx + 1 < len(headings) else len(text)
            body = text[start:end].strip()
            if not body:
                continue
            prefix = " > ".join(t for _, t in stack)
            full = f"[{prefix}]\n{body}"
            # 段超长再按固定长度切（保留前缀）
            if len(full) <= self.CHUNK_SIZE:
                chunks.append(full)
            else:
                step = self.CHUNK_SIZE - self.CHUNK_OVERLAP
                for i in range(0, len(body), step):
                    part = body[i : i + self.CHUNK_SIZE]
                    if part.strip():
                        chunks.append(f"[{prefix}]\n{part}")
        # 首个标题之前的内容（文档头部）
        if headings and headings[0].start() > 0:
            head = text[: headings[0].start()].strip()
            if head:
                chunks.append(head[: self.CHUNK_SIZE])
        return chunks

    async def ingest(self, text: str, source: str = "") -> int:
        """切块并入库（向量 + FTS）；返回写入块数。"""
        chunks = [c.strip() for c in self._chunk_text(text) if c.strip()]
        count = 0
        for chunk in chunks:
            vec = await self.embedder.embed(chunk)
            await asyncio.to_thread(
                self._insert_chunk, chunk, source, vec
            )
            count += 1
        return count

    def _insert_chunk(self, text: str, source: str, vec: list[float]) -> None:
        conn = self.store.conn
        ts = time.time()
        cur = conn.execute(
            "INSERT INTO knowledge_chunks (text, source, ts) VALUES (?, ?, ?)",
            (text, source, ts),
        )
        rowid = cur.lastrowid
        if self.store.vec_available and vec:
            blob = struct.pack(f"{DIM}f", *vec)
            conn.execute(
                "INSERT INTO knowledge_vec (rowid, embedding) VALUES (?, ?)",
                (rowid, blob),
            )
        conn.execute(
            "INSERT INTO knowledge_fts (rowid, text, source) VALUES (?, ?, ?)",
            (rowid, text, source),
        )
        conn.commit()

    async def ingest_file(self, path: str) -> int:
        """导入单个文本文件（.md/.txt/.toml/.py 等可读文本）。"""
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        return await self.ingest(text, source=path)

    async def ingest_dir(self, directory: str, suffixs: tuple = (".md", ".txt")) -> int:
        """递归导入目录下指定后缀的文本文件。"""
        total = 0
        for root, _dirs, files in os.walk(directory):
            for name in files:
                if not name.endswith(suffixs):
                    continue
                path = os.path.join(root, name)
                try:
                    total += await self.ingest_file(path)
                except Exception as exc:  # noqa: BLE001 — 单文件失败不阻断
                    logger.warning("知识库导入失败 %s: %s", path, exc)
        return total

    def _vector_search(self, vec: list[float], k: int = 8) -> list[dict]:
        if not self.store.vec_available or not vec:
            return []
        blob = struct.pack(f"{DIM}f", *vec)
        rows = self.store.conn.execute(
            "SELECT v.rowid, v.distance, c.text, c.source "
            "FROM knowledge_vec v JOIN knowledge_chunks c ON c.rowid = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (blob, k),
        ).fetchall()
        return [dict(r) for r in rows]

    def _fts_search(self, query: str, k: int = 8) -> list[dict]:
        q = query.strip()
        if not q:
            return []
        escaped = '"' + q.replace('"', '""') + '"'
        rows = self.store.conn.execute(
            "SELECT c.rowid, c.text, c.source, bm25(knowledge_fts) AS rank "
            "FROM knowledge_fts JOIN knowledge_chunks c ON c.rowid = knowledge_fts.rowid "
            "WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?",
            (escaped, k),
        ).fetchall()
        return [dict(r) for r in rows]

    async def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        """RRF 融合向量 + FTS 检索，返回 {text, source, score} 列表。"""
        # 空知识库无可召回内容，不为每轮对话支付一次BGE查询编码。
        # 每次读真实表而不缓存空状态，后续导入立即生效。
        if self.store.conn.execute("SELECT 1 FROM knowledge_chunks LIMIT 1").fetchone() is None:
            return []
        query_vec = await self.embedder.embed(query)
        vector_hits, fts_hits = await asyncio.gather(
            asyncio.to_thread(self._vector_search, query_vec, 8),
            asyncio.to_thread(self._fts_search, query, 8),
        )
        scores: dict[int, float] = {}
        meta_by_id: dict[int, dict] = {}
        for hits in (vector_hits, fts_hits):
            for rank, hit in enumerate(hits, start=1):
                rid = int(hit["rowid"])
                scores[rid] = scores.get(rid, 0.0) + 1.0 / (self.rrf_k + rank)
                meta_by_id.setdefault(rid, hit)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [
            {
                "text": meta_by_id[rid]["text"],
                "source": meta_by_id[rid].get("source", ""),
                "score": score,
            }
            for rid, score in ranked
        ]

    def stats(self) -> dict:
        row = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks"
        ).fetchone()
        return {"chunks": int(row[0] if row else 0)}

    def sources(self, limit: int = 50) -> list[dict]:
        """按来源汇总（块数 + 一条样本）。

        为什么需要它：知识库此前**只有"块数"一个数字**，没有界面也没有来源清单 ——
        于是"里面到底装了什么"用户完全看不见（实测后果：`docs/init/milestones.md`
        在里面躺了很久、每轮对话注入 286 tokens，直到有人发现她在聊里程碑才发现）。
        """
        rows = self.store.conn.execute(
            "SELECT source, COUNT(*) AS n, MIN(substr(text, 1, 80)) AS sample "
            "FROM knowledge_chunks GROUP BY source ORDER BY n DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [
            {"source": str(r["source"]), "chunks": int(r["n"]), "sample": str(r["sample"] or "")}
            for r in rows
        ]

    def clear(self) -> None:
        """清空知识库：**三张表一起删**（chunks / fts / vec）。

        ⚠ 此前漏了 ``knowledge_vec`` —— 与 S50 在情景记忆上踩过的坑**完全同款**：
        向量残留成孤儿，语义检索仍可能命中它们；更隐蔽的是清空后新导入的 chunk
        rowid 从头编号，会与旧向量**错位关联**（新文本拿到旧语义），检索从此悄悄失真。
        """
        conn = self.store.conn
        conn.execute("DELETE FROM knowledge_chunks")
        conn.execute("DELETE FROM knowledge_fts")
        if self.store.vec_available:
            conn.execute("DELETE FROM knowledge_vec")
        conn.commit()

    def close(self) -> None:
        self.store.close()
        if self._owns_embedder:
            self.embedder.close()
