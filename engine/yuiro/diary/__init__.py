"""日记存储（S51）：独立库 ``yuiro_diary.db``。

设计：`docs/features/diary-feature-design.md`（§3 数据模型 / §9 结构化与回顾）。
这里只记**实现级**的关键判断：

1. **独立库**：日记库 ≠ 记忆库 —— 前者服务"用户回顾"，后者服务"她记得"。
   "仅保存不进记忆"的日记**必须仍能被用户回顾**，所以回顾不能依赖记忆库（§9.0）。
2. **结构化，而非只存 JSON**：``mood_tags/topics/entities`` 的 JSON 列**保留**作原始
   产物，另有 ``diary_tags`` 表作**可索引投影** —— 按情绪/主题筛选、出趋势，
   JSON 列做不到（§9.1.1）。
3. **FTS 用触发器同步**（而不是在代码里手动 INSERT/DELETE）：一致性由数据库保证，
   任何写入路径都不会漏（"多路径必然不同步"的教训，S47/S50）。
4. **删除必须连带附属表**（S50 教训）：``diary_tags`` 靠外键 CASCADE（注意
   ``PRAGMA foreign_keys=ON`` 是它生效的前提），FTS 靠触发器。
5. **隐私档位是数据的一部分**：三档决定是否写入记忆；改档位时的**联动**
   （删/补记忆）由上层负责（§9.1.4），本层只如实记录状态。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

# ---- 隐私三档（§1.1）-------------------------------------------------------
PRIVACY_DISCARD = "discard"        # 阅后即焚：不落库
PRIVACY_LOCAL_ONLY = "local_only"  # 仅保存：她检索不到，但用户可回顾
PRIVACY_SHARED = "shared"          # 保存 + 进记忆：她可以自然提起
PRIVACY_ALL = (PRIVACY_DISCARD, PRIVACY_LOCAL_ONLY, PRIVACY_SHARED)

_SCHEMA = [
    # 主表（§3.1 + §8.3/§9.1 的增量列）
    """
    CREATE TABLE IF NOT EXISTS diaries (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      raw_text TEXT NOT NULL,
      polished_text TEXT,
      summary TEXT,
      mood_tags TEXT,
      topics TEXT,
      entities TEXT,
      followup_question TEXT,
      narrative_type TEXT,
      privacy TEXT NOT NULL,
      memory_written INTEGER NOT NULL DEFAULT 0,
      closing_review TEXT,
      quip_mode INTEGER NOT NULL DEFAULT 0,
      source_meta TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_diaries_created ON diaries(created_at DESC)",
    # 标签投影（可索引；JSON 列仍是原始产物）
    """
    CREATE TABLE IF NOT EXISTS diary_tags (
      diary_id INTEGER NOT NULL REFERENCES diaries(id) ON DELETE CASCADE,
      tag_type TEXT NOT NULL,
      tag_value TEXT NOT NULL,
      PRIMARY KEY (diary_id, tag_type, tag_value)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_diary_tags_lookup ON diary_tags(tag_type, tag_value)",
    # 全文检索（trigram，与记忆库同一方案；外部内容表 + 触发器同步）
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS diary_fts USING fts5(
      raw_text, polished_text, summary, closing_review,
      content='diaries', content_rowid='id', tokenize='trigram'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS diaries_ai AFTER INSERT ON diaries BEGIN
      INSERT INTO diary_fts(rowid, raw_text, polished_text, summary, closing_review)
      VALUES (new.id, new.raw_text, new.polished_text, new.summary, new.closing_review);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS diaries_ad AFTER DELETE ON diaries BEGIN
      INSERT INTO diary_fts(diary_fts, rowid, raw_text, polished_text, summary, closing_review)
      VALUES ('delete', old.id, old.raw_text, old.polished_text, old.summary, old.closing_review);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS diaries_au AFTER UPDATE ON diaries BEGIN
      INSERT INTO diary_fts(diary_fts, rowid, raw_text, polished_text, summary, closing_review)
      VALUES ('delete', old.id, old.raw_text, old.polished_text, old.summary, old.closing_review);
      INSERT INTO diary_fts(rowid, raw_text, polished_text, summary, closing_review)
      VALUES (new.id, new.raw_text, new.polished_text, new.summary, new.closing_review);
    END
    """,
]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class DiaryStore:
    """日记库（同步 SQLite；调用方按需 ``asyncio.to_thread``）。"""

    def __init__(self, db_path: str | Path = "data/yuiro_diary.db") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # WAL 提升并发；busy_timeout 避免多进程（双引擎）无限等待；
        # ★ foreign_keys=ON 是 diary_tags 的 CASCADE 生效前提（默认是关的！）
        for pragma in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA busy_timeout=5000",
            "PRAGMA foreign_keys=ON",
        ):
            try:
                self.conn.execute(pragma)
            except sqlite3.Error:
                pass
        self._migrate()

    def _migrate(self) -> None:
        for sql in _SCHEMA:
            self.conn.execute(sql)
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(diaries)")}
        for name, definition in (("title", "TEXT NOT NULL DEFAULT ''"), ("revision", "INTEGER NOT NULL DEFAULT 1")):
            if name not in columns:
                self.conn.execute(f"ALTER TABLE diaries ADD COLUMN {name} {definition}")
        self.conn.execute("CREATE TABLE IF NOT EXISTS diary_revisions (diary_id INTEGER REFERENCES diaries(id) ON DELETE CASCADE, revision INTEGER, snapshot TEXT NOT NULL, PRIMARY KEY(diary_id,revision))")
        self.conn.execute("CREATE TABLE IF NOT EXISTS diary_assets (id TEXT PRIMARY KEY, name TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL, created_at REAL NOT NULL, diary_id INTEGER REFERENCES diaries(id) ON DELETE CASCADE)")
        self.conn.commit()

    # ---- 写入 ---------------------------------------------------------------
    def save(
        self,
        *,
        raw_text: str,
        polished_text: str = "",
        summary: str = "",
        mood_tags: list[str] | None = None,
        topics: list[str] | None = None,
        entities: list[dict] | None = None,
        followup_question: str = "",
        narrative_type: str = "short",
        privacy: str = PRIVACY_LOCAL_ONLY,
        quip_mode: bool = False,
        source_meta: dict | None = None,
        title: str = "",
        attachment_ids: list[str] | None = None,
    ) -> int:
        """落一篇日记，返回 ``diary_id``；``privacy=discard`` 时**返回 0 且不写入**。

        ``privacy`` 只接受三档之一（**写非法的档位不是"宽松处理"，而是制造
        一个语义不明的数据**）→ 非法值直接抛错，由调用方修正。
        """
        if privacy not in PRIVACY_ALL:
            raise ValueError(f"未知隐私档位：{privacy!r}（应为 {PRIVACY_ALL}）")
        if privacy == PRIVACY_DISCARD:
            # 阅后即焚 = **不落库**（§3.2），不是"落库后标记 discard"。
            # 在这里强制保证语义，而不是指望每个调用方自己记得别写。
            return 0
        from yuiro.diary.media import validate_assets
        validate_assets(self, attachment_ids or [])
        now = _now_iso()
        cur = self.conn.execute(
            "INSERT INTO diaries (created_at, updated_at, raw_text, polished_text, summary,"
            " mood_tags, topics, entities, followup_question, narrative_type, privacy,"
            " quip_mode, source_meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                now, now, raw_text, polished_text, summary,
                json.dumps(mood_tags or [], ensure_ascii=False),
                json.dumps(topics or [], ensure_ascii=False),
                json.dumps(entities or [], ensure_ascii=False),
                followup_question, narrative_type, privacy,
                1 if quip_mode else 0,
                json.dumps(source_meta or {}, ensure_ascii=False),
            ),
        )
        diary_id = int(cur.lastrowid)
        meta = dict(source_meta or {})
        meta["attachment_ids"] = attachment_ids or []
        self.conn.execute("UPDATE diaries SET title=?,source_meta=? WHERE id=?", (title[:160],json.dumps(meta,ensure_ascii=False),diary_id))
        for asset_id in attachment_ids or []:
            self.conn.execute("UPDATE diary_assets SET diary_id=? WHERE id=?",(diary_id,asset_id))
        self._project_tags(diary_id, mood_tags or [], topics or [], entities or [])
        self.conn.commit()
        return diary_id

    def _project_tags(
        self, diary_id: int, moods: list[str], topics: list[str], entities: list[dict]
    ) -> None:
        """把标签投影进 ``diary_tags``（可索引）。

        与 JSON 列**同事务双写**：JSON 是原始产物（可回放），tags 是查询用的投影。
        """
        rows: list[tuple[int, str, str]] = []
        rows += [(diary_id, "mood", str(m).strip()) for m in moods if str(m).strip()]
        rows += [(diary_id, "topic", str(t).strip()) for t in topics if str(t).strip()]
        for ent in entities:
            if isinstance(ent, dict):
                name = str(ent.get("name") or "").strip()
                if name:
                    rows.append((diary_id, "entity", name))
        if rows:
            self.conn.executemany(
                "INSERT OR IGNORE INTO diary_tags (diary_id, tag_type, tag_value)"
                " VALUES (?,?,?)",
                rows,
            )

    def update(
        self,
        diary_id: int,
        *,
        raw_text: str | None = None,
        polished_text: str | None = None,
        summary: str | None = None,
    ) -> bool:
        """编辑内容（审阅态可改写；FTS 由触发器自动同步）。"""
        sets: list[str] = []
        args: list[Any] = []
        for col, val in (
            ("raw_text", raw_text),
            ("polished_text", polished_text),
            ("summary", summary),
        ):
            if val is not None:
                sets.append(f"{col} = ?")
                args.append(val)
        if not sets:
            return False
        sets.append("updated_at = ?")
        args.extend([_now_iso(), diary_id])
        cur = self.conn.execute(f"UPDATE diaries SET {', '.join(sets)} WHERE id = ?", args)
        self.conn.commit()
        return cur.rowcount > 0

    def set_privacy(self, diary_id: int, privacy: str) -> tuple[bool, str]:
        """改隐私档位，返回 ``(是否改到, 旧档位)``。

        **旧档位必须返回**：上层据此判断"要不要补写/删除记忆条目"——
        改档位却不同步记忆，就是**谎报隐私**（§9.1.4，S50 同胞问题）。
        """
        if privacy not in PRIVACY_ALL:
            raise ValueError(f"未知隐私档位：{privacy!r}")
        row = self.conn.execute(
            "SELECT privacy FROM diaries WHERE id = ?", (diary_id,)
        ).fetchone()
        if row is None:
            return False, ""
        old = str(row["privacy"])
        self.conn.execute(
            "UPDATE diaries SET privacy = ?, updated_at = ? WHERE id = ?",
            (privacy, _now_iso(), diary_id),
        )
        self.conn.commit()
        return True, old

    def set_closing_review(self, diary_id: int, text: str) -> bool:
        """记录总评（§8.2）。总评是**她的话**，不进记忆。"""
        cur = self.conn.execute(
            "UPDATE diaries SET closing_review = ?, updated_at = ? WHERE id = ?",
            (text, _now_iso(), diary_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_memory_written(self, diary_id: int, written: bool = True) -> None:
        self.conn.execute(
            "UPDATE diaries SET memory_written = ? WHERE id = ?",
            (1 if written else 0, diary_id),
        )
        self.conn.commit()

    # ---- 读取 ---------------------------------------------------------------
    def get(self, diary_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM diaries WHERE id = ?", (diary_id,)).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def list_recent(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        mood: str = "",
        topic: str = "",
        privacy: str = "",
    ) -> list[dict]:
        """时间线（倒序）+ 可选筛选（情绪/主题/隐私档）。

        无需过滤 discard：它在 ``save`` 阶段就没落库（阅后即焚的定义）。
        """
        where: list[str] = []
        args: list[Any] = []
        if privacy:
            where.append("d.privacy = ?")
            args.append(privacy)
        if mood:
            where.append(
                "EXISTS (SELECT 1 FROM diary_tags t WHERE t.diary_id = d.id"
                " AND t.tag_type = 'mood' AND t.tag_value = ?)"
            )
            args.append(mood)
        if topic:
            where.append(
                "EXISTS (SELECT 1 FROM diary_tags t WHERE t.diary_id = d.id"
                " AND t.tag_type = 'topic' AND t.tag_value = ?)"
            )
            args.append(topic)
        sql = "SELECT d.* FROM diaries d"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY d.created_at DESC, d.id DESC LIMIT ? OFFSET ?"
        args.extend([max(1, int(limit)), max(0, int(offset))])
        rows = self.conn.execute(sql, args).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search(self, keyword: str, *, limit: int = 20) -> list[dict]:
        """全文检索：FTS5 trigram 优先，**短词/无命中时回退 LIKE 子串**。

        为什么必须有回退（实测）：FTS5 的 trigram 分词器**对 <3 字符的查询返回空**，
        而中文里 2 字词极其常见（"跑步/工作/火锅/天气"）—— 只靠 FTS 会让用户
        觉得"搜索坏了"。故短查询直接走 LIKE；长查询若 FTS 无命中，也回退一次
        （宁可慢一点，也不要"明明有却搜不到"）。
        """
        q = (keyword or "").strip()
        if not q:
            return []
        cap = max(1, int(limit))
        rows: list[sqlite3.Row] = []
        if len(q) >= 3:
            try:
                rows = self.conn.execute(
                    "SELECT d.* FROM diary_fts f JOIN diaries d ON d.id = f.rowid"
                    " WHERE diary_fts MATCH ? ORDER BY rank LIMIT ?",
                    ('"' + q.replace('"', '""') + '"', cap),
                ).fetchall()
            except sqlite3.Error:
                rows = []
        if not rows:
            like = f"%{q}%"
            rows = self.conn.execute(
                "SELECT * FROM diaries WHERE raw_text LIKE ? OR polished_text LIKE ?"
                " OR summary LIKE ? OR closing_review LIKE ?"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (like, like, like, like, cap),
            ).fetchall()
        title_rows = self.conn.execute("SELECT * FROM diaries WHERE title LIKE ? ORDER BY created_at DESC LIMIT ?", (f"%{q}%",cap)).fetchall()
        merged = {r["id"]:r for r in [*title_rows,*rows]}
        return [self._row_to_dict(r) for r in list(merged.values())[:cap]]

    def tags_of(self, diary_id: int) -> dict[str, list[str]]:
        rows = self.conn.execute(
            "SELECT tag_type, tag_value FROM diary_tags WHERE diary_id = ? ORDER BY tag_value",
            (diary_id,),
        ).fetchall()
        out: dict[str, list[str]] = {"mood": [], "topic": [], "entity": []}
        for r in rows:
            out.setdefault(str(r["tag_type"]), []).append(str(r["tag_value"]))
        return out

    def stats(self) -> dict:
        """只呈现事实，不做评价（§9.2.2）。"""
        total = int(self.conn.execute("SELECT COUNT(*) FROM diaries").fetchone()[0])
        by_privacy = {
            str(r["privacy"]): int(r["c"])
            for r in self.conn.execute(
                "SELECT privacy, COUNT(*) AS c FROM diaries GROUP BY privacy"
            ).fetchall()
        }
        moods = [
            {"mood": str(r["tag_value"]), "count": int(r["c"])}
            for r in self.conn.execute(
                "SELECT tag_value, COUNT(*) AS c FROM diary_tags WHERE tag_type = 'mood'"
                " GROUP BY tag_value ORDER BY c DESC LIMIT 10"
            ).fetchall()
        ]
        return {"total": total, "by_privacy": by_privacy, "top_moods": moods}

    # ---- 删除 ---------------------------------------------------------------
    def delete(self, diary_id: int) -> bool:
        """删一篇。

        附属表（``diary_tags`` / FTS）由外键 CASCADE 与触发器一并清理 ——
        这正是 S50 的教训：只删主表会留下"删了还在"的错觉。
        """
        cur = self.conn.execute("DELETE FROM diaries WHERE id = ?", (diary_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def clear_all(self) -> int:
        """清空全部日记（用户销毁自己的记录）。返回删除数。"""
        n = int(self.conn.execute("SELECT COUNT(*) FROM diaries").fetchone()[0])
        self.conn.execute("DELETE FROM diaries")
        self.conn.execute("DELETE FROM diary_tags")
        self.conn.commit()
        return n

    # ---- 工具 ---------------------------------------------------------------
    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        out = dict(row)
        for col, default in (
            ("mood_tags", []),
            ("topics", []),
            ("entities", []),
            ("source_meta", {}),
        ):
            raw = out.get(col)
            try:
                out[col] = json.loads(raw) if raw else default
            except (json.JSONDecodeError, TypeError):
                out[col] = default
        out["memory_written"] = bool(out.get("memory_written"))
        out["quip_mode"] = bool(out.get("quip_mode"))
        return out

    def close(self) -> None:
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
