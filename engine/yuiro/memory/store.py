"""L2/L3 存储层（S23：从 memory/__init__.py 逐字抽离）。

职责边界：**只做数据访问**（SQL + 行 → dict），不含业务策略
（去重 / 显著性 / 衰减 / 抽取等留在 ``MemorySystem``）。

- ``messages``：L2 情景记忆（+ ``messages_vec`` 向量 / ``messages_fts`` 全文）；
- ``facts``：L3 事实（subject/key/value/confidence/decay）。
"""
from __future__ import annotations

import logging
import math
import sqlite3
import struct
import time
from typing import ClassVar

from yuiro.memory.constants import DIM, EXPLICIT_PREFIX, VEC_K

logger = logging.getLogger(__name__)


class SQLiteVecStore:
    """管理 sqlite + sqlite-vec 建表；采用 additive 运行时迁移，不 PRAGMA 升级。"""

    _migrations: ClassVar[list[tuple[str, str, bool]]] = [
        # (迁移 id, 建表 SQL, 是否需要 sqlite-vec)
        (
            "001_messages",
            (
                "CREATE TABLE IF NOT EXISTS messages ("
                "rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
                "text TEXT NOT NULL, ts FLOAT NOT NULL, salience FLOAT NOT NULL DEFAULT 1.0)"
            ),
            False,
        ),
        (
            "002_vec",
            (
                "CREATE VIRTUAL TABLE messages_vec USING vec0("
                "embedding float[1024], chunk_size=256)"
            ),
            True,
        ),
        (
            "003_fts",
            (
                "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
                "text, tokenize='trigram')"
            ),
            False,
        ),
        (
            "004_facts",
            (
                "CREATE TABLE IF NOT EXISTS facts ("
                "subject TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
                "confidence FLOAT NOT NULL DEFAULT 1.0, decay FLOAT NOT NULL DEFAULT 0.0, "
                "updated_at FLOAT NOT NULL, PRIMARY KEY (subject, key))"
            ),
            False,
        ),
        # S51：空闲期整理需要"这条记忆被用过几次" —— 没有访问计数就无法判断
        # "长期无人回顾"（此前这张表根本没有这列，"压缩无人回顾的记忆"也就无从谈起）。
        (
            "005_message_access_count",
            "ALTER TABLE messages ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0",
            False,
        ),
        (
            "006_message_last_access",
            "ALTER TABLE messages ADD COLUMN last_access_at FLOAT",
            False,
        ),
    ]

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # 文件库开启 WAL 提升并发；内存库忽略该 PRAGMA
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        # 锁等待上限：多进程共享同一 db（如双引擎）时避免无限等待/挂起
        try:
            self.conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.Error:
            pass
        self._load_vec()
        self._migrate()

    def _load_vec(self) -> None:
        """探测并加载 sqlite-vec 扩展，记录可用性。"""
        self.vec_available = False
        try:
            self.conn.enable_load_extension(True)
            import sqlite_vec

            sqlite_vec.load(self.conn)
            self.vec_available = True
        except Exception as exc:  # noqa: BLE001 - 扩展缺失时降级为纯 FTS/recency
            logger.warning("sqlite-vec 不可用，向量信号降级：%s", exc)

    def _migrate(self) -> None:
        """按迁移表逐条幂等建表；不修改 user_version。"""
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS _migrations (id TEXT PRIMARY KEY, applied_at FLOAT)"
        )
        applied = {
            row["id"] for row in self.conn.execute("SELECT id FROM _migrations").fetchall()
        }
        now = time.time()
        for mig_id, sql, needs_vec in self._migrations:
            if mig_id in applied:
                continue
            if needs_vec and not self.vec_available:
                continue  # 向量表留待后续运行时探测到扩展后补齐
            self.conn.execute(sql)
            self.conn.execute(
                "INSERT OR REPLACE INTO _migrations (id, applied_at) VALUES (?, ?)",
                (mig_id, now),
            )
        self.conn.commit()

    def add_message(self, text: str, vector: list[float] | None, ts: float | None = None,
                    salience: float = 1.0) -> int:
        """写入一条 episodic 记忆，返回 rowid。向量为空时仅写 FTS/recency。"""
        ts = time.time() if ts is None else ts
        cur = self.conn.execute(
            "INSERT INTO messages (text, ts, salience) VALUES (?, ?, ?)", (text, ts, salience)
        )
        rowid = cur.lastrowid
        if self.vec_available and vector is not None:
            blob = struct.pack(f"{DIM}f", *vector)
            self.conn.execute(
                "INSERT INTO messages_vec (rowid, embedding) VALUES (?, ?)", (rowid, blob)
            )
        self.conn.execute("INSERT INTO messages_fts (rowid, text) VALUES (?, ?)", (rowid, text))
        self.conn.commit()
        return rowid

    @staticmethod
    def _fts_query(text: str) -> str:
        """trigram 短语查询，双引号包裹并转义内部引号。"""
        return '"' + text.replace('"', '""') + '"'

    def vector_search(self, vector: list[float], k: int = VEC_K) -> list[dict]:
        """按余弦距离检索，距离越小越相似。"""
        if not self.vec_available or not vector:
            return []
        blob = struct.pack(f"{DIM}f", *vector)
        rows = self.conn.execute(
            "SELECT v.rowid, v.distance, m.text, m.ts, m.salience "
            "FROM messages_vec v JOIN messages m ON m.rowid = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (blob, k),
        ).fetchall()
        return [dict(r) for r in rows]

    def fts_search(self, query: str, k: int = VEC_K) -> list[dict]:
        """trigram FTS 全文检索，bm25 排序（越小越好）。"""
        q = query.strip()
        if not q:
            return []
        rows = self.conn.execute(
            "SELECT m.rowid, m.text, m.ts, m.salience, bm25(messages_fts) AS rank "
            "FROM messages_fts JOIN messages m ON m.rowid = messages_fts.rowid "
            "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?",
            (self._fts_query(q), k),
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_search(self, k: int = VEC_K) -> list[dict]:
        """按时间新近度排序。"""
        rows = self.conn.execute(
            "SELECT rowid, text, ts, salience FROM messages ORDER BY ts DESC LIMIT ?", (k,)
        ).fetchall()
        return [dict(r) for r in rows]

    def salient_search(self, k: int = VEC_K) -> list[dict]:
        """按显著性排序。"""
        rows = self.conn.execute(
            "SELECT rowid, text, ts, salience FROM messages ORDER BY salience DESC, ts DESC LIMIT ?",
            (k,),
        ).fetchall()
        return [dict(r) for r in rows]

    def explicit_search(self, k: int = VEC_K) -> list[dict]:
        """显式记忆通道（S07）：按前缀取「用户要求记住」的记忆，新近优先。"""
        rows = self.conn.execute(
            "SELECT rowid, text, ts, salience FROM messages "
            "WHERE text LIKE ? ORDER BY ts DESC LIMIT ?",
            (EXPLICIT_PREFIX + "%", k),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # S51：空闲期记忆整理所需的原语（访问计数 / 语义归并 / 四表齐删）
    # ------------------------------------------------------------------
    def mark_accessed(self, rowids: list[int]) -> None:
        """记录"这些记忆被用到了"（检索命中时调用）。

        为什么必须记：**"压缩长期无人回顾的记忆"完全依赖它** —— 没有访问计数，
        就只剩"年龄"这一个维度，那样会压掉"很久以前但常被想起"的事（恰恰最该留着）。
        """
        ids = [int(r) for r in rowids if r]
        if not ids:
            return
        now = time.time()
        q = ",".join("?" for _ in ids)
        self.conn.execute(
            f"UPDATE messages SET access_count = access_count + 1, last_access_at = ? "
            f"WHERE rowid IN ({q})",
            (now, *ids),
        )
        self.conn.commit()

    def message_rows(self, rowids: list[int]) -> list[dict]:
        """按 rowid 取回情景记忆（整理时读原文用）。"""
        ids = [int(r) for r in rowids]
        if not ids:
            return []
        q = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT rowid, text, ts, salience, COALESCE(access_count, 0) AS access_count "
            f"FROM messages WHERE rowid IN ({q})",
            ids,
        ).fetchall()
        return [dict(r) for r in rows]

    def stale_messages(self, *, older_than_ts: float, max_access: int,
                       limit: int = 50) -> list[dict]:
        """取"长期无人回顾"的情景记忆：**够老 且 几乎没被检索命中过**。

        两个条件缺一不可 ——
        - 只看年龄：会压掉"很久以前但常被想起"的事（最该留着的）；
        - 只看访问次数：会压掉刚写下、还没机会被检索到的新记忆。
        """
        rows = self.conn.execute(
            "SELECT rowid, text, ts, salience, access_count FROM messages "
            "WHERE ts < ? AND COALESCE(access_count, 0) <= ? "
            "ORDER BY ts ASC LIMIT ?",
            (older_than_ts, max_access, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_messages(self, rowids: list[int]) -> int:
        """删除情景记忆：**主表 + FTS + 向量三张一起删**。

        ⚠ 必须齐删（S50 的教训）：只删主表会留下 FTS 与**孤儿向量** ——
        直接查库看起来"删了还在"，孤儿向量还占着 rowid 污染语义检索。
        把它放在 store 层而不是各处手写 SQL：手写的那个调用点一定会漏。
        """
        ids = [int(r) for r in rowids]
        if not ids:
            return 0
        q = ",".join("?" for _ in ids)
        cur = self.conn.execute(f"DELETE FROM messages WHERE rowid IN ({q})", ids)
        self.conn.execute(f"DELETE FROM messages_fts WHERE rowid IN ({q})", ids)
        if self.vec_available:
            self.conn.execute(f"DELETE FROM messages_vec WHERE rowid IN ({q})", ids)
        self.conn.commit()
        return int(cur.rowcount or 0)

    def merge_messages(self, keep_rowid: int, drop_rowids: list[int], text: str,
                       vector: list[float] | None) -> dict:
        """把若干条情景记忆**归并**进 ``keep_rowid``（改写文本 + 删掉其余）。

        向量与 FTS 必须**同步替换**，否则会出现"文本是新的、语义检索命中的还是旧的"
        —— 那比不整理更糟：检索命中的内容与用户看到的文本对不上。

        ``ts`` 刻意**保持不变**：合并后的条目代表的是那段历史，把时间改成"现在"
        会让它凭空跳到时间线最前面。
        """
        keep = int(keep_rowid)
        drops = [int(r) for r in drop_rowids if int(r) != keep]
        old = self.conn.execute(
            "SELECT text FROM messages WHERE rowid = ?", (keep,)
        ).fetchone()
        changed = old is None or str(old["text"]) != text
        self.conn.execute("UPDATE messages SET text = ? WHERE rowid = ?", (text, keep))
        # 文本没变（如"保留信息更全的那条"式归并）就**别动 fts/vec** ——
        # 无谓的删+插不仅白费，还可能在并发读时出现"文本在、向量短暂缺失"的窗口。
        if changed:
            self.conn.execute("DELETE FROM messages_fts WHERE rowid = ?", (keep,))
            self.conn.execute(
                "INSERT INTO messages_fts (rowid, text) VALUES (?, ?)", (keep, text)
            )
            if self.vec_available:
                self.conn.execute("DELETE FROM messages_vec WHERE rowid = ?", (keep,))
                if vector is not None:
                    blob = struct.pack(f"{DIM}f", *vector)
                    self.conn.execute(
                        "INSERT INTO messages_vec (rowid, embedding) VALUES (?, ?)", (keep, blob)
                    )
        self.conn.commit()
        return {"kept": keep, "removed": self.delete_messages(drops)}

    def message_vector(self, rowid: int) -> list[float] | None:
        """取某条情景记忆的向量（无向量表 / 无向量时返回 None）。"""
        if not self.vec_available:
            return None
        row = self.conn.execute(
            "SELECT embedding FROM messages_vec WHERE rowid = ?", (int(rowid),)
        ).fetchone()
        if row is None:
            return None
        return list(struct.unpack(f"{DIM}f", row["embedding"]))

    def nearest_other(self, rowid: int) -> dict | None:
        """找与某条**最相似的其它条目**（语义重复检测用）；无则 None。"""
        vec = self.message_vector(rowid)
        if vec is None:
            return None
        blob = struct.pack(f"{DIM}f", *vec)
        # k=2：最近的两条必然是"自己 + 最像的另一个"
        rows = self.conn.execute(
            "SELECT rowid, distance FROM messages_vec WHERE embedding MATCH ? AND k = 2",
            (blob,),
        ).fetchall()
        for r in rows:
            if int(r["rowid"]) != int(rowid):
                return {"rowid": int(r["rowid"]), "distance": float(r["distance"])}
        return None

    def upsert_fact(self, subject: str, key: str, value: str, confidence: float = 1.0,
                    decay: float = 0.0) -> None:
        """L3 事实 upsert（subject/key 主键冲突时覆盖）。

        ``decay``：每秒衰减率（0 = 永不衰减）；有效置信度 = confidence × exp(-decay × 年龄秒)。
        S13 起由 MemorySystem 按来源注入（explicit 永不衰减，其余缓慢衰减）。
        """
        now = time.time()
        self.conn.execute(
            "INSERT INTO facts (subject, key, value, confidence, decay, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (subject, key) DO UPDATE SET "
            "value = excluded.value, confidence = excluded.confidence, "
            "decay = excluded.decay, "
            "updated_at = excluded.updated_at",
            (subject, key, value, confidence, decay, now),
        )
        self.conn.commit()

    def query_facts(self, subject: str) -> list[dict]:
        """按 subject 查询事实，含置信度衰减后的有效置信度。"""
        now = time.time()
        rows = self.conn.execute(
            "SELECT subject, key, value, confidence, decay, updated_at "
            "FROM facts WHERE subject = ? ORDER BY key",
            (subject,),
        ).fetchall()
        result: list[dict] = []
        for r in rows:
            age = max(0.0, now - r["updated_at"])
            effective = r["confidence"] * math.exp(-r["decay"] * age)
            item = dict(r)
            item["effective_confidence"] = effective
            result.append(item)
        return result

    def close(self) -> None:
        """关闭连接（先 checkpoint WAL，确保 Windows 上文件锁能释放）。

        ⚠ WAL 模式下，最后一个连接关闭时 SQLite 会自行 checkpoint 并删除
        ``-wal`` 文件，但 Windows 上若 WAL 未合并干净，**主 db 文件仍会被锁**，
        表现为临时目录清理失败（``PermissionError [WinError 32]``，实测于
        ``test_agentloop_memory_roundtrip``）。显式 ``TRUNCATE`` checkpoint 把
        WAL 合并回主文件，能可靠释放文件锁。见 S49。
        """
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
