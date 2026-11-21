"""记忆向量的诊断与重建。

**什么情况下需要它**：嵌入模型换过之后（例如从 md5 降级切回 BGE-M3），
库里旧向量是用**旧模型**算的，与新查询的向量**不在同一个空间** ——
向量召回对旧数据完全失效。

症状很有辨识度：**新记忆搜得到，老记忆"怎么问都想不起来"**；
但如果关键词恰好对上，又能命中（因为 FTS 全文检索那一路不依赖向量）。

用法：
    python scripts/rebuild_vectors.py --inspect   # 只看现状（默认，只读）
    python scripts/rebuild_vectors.py --rebuild   # 用当前模型重算全部向量
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
import sys

#: (源表, 文本列的候选名, 向量表)。列名自动探测，兼容表结构演进。
SOURCES: list[tuple[str, tuple[str, ...], str]] = [
    ("messages", ("text", "content", "message", "body"), "messages_vec"),
    ("knowledge_chunks", ("text", "content", "chunk"), "knowledge_vec"),
]


def _connect(db: str) -> sqlite3.Connection:
    import sqlite_vec

    conn = sqlite3.connect(db)
    # Python 3.11+ 要求显式允许加载扩展，否则 sqlite_vec.load 报 "not authorized"
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")]
    except sqlite3.Error:
        return []


def _pick_column(conn: sqlite3.Connection, table: str,
                 candidates: tuple[str, ...]) -> str:
    cols = _columns(conn, table)
    for name in candidates:
        if name in cols:
            return name
    return ""


def _vec_dim(conn: sqlite3.Connection, vec_table: str) -> int:
    """从建表语句里读出向量维度（vec0(embedding float[N])）。"""
    row = conn.execute(
        "select sql from sqlite_master where name = ?", (vec_table,)
    ).fetchone()
    if not row or not row[0]:
        return 0
    m = re.search(r"float\[(\d+)\]", str(row[0]))
    return int(m.group(1)) if m else 0


def inspect(db: str) -> int:
    conn = _connect(db)
    from yuiro.config import load_config

    model = load_config().memory.embedder
    print(f"记忆库：{db}")
    print(f"当前嵌入模型：[memory].embedder = {model!r}\n")

    print(f"{'源表':<20}{'条数':>6}{'文本列':>12}{'向量表':>18}{'条数':>6}{'维度':>7}")
    total_src = total_vec = 0
    for src, cands, vec in SOURCES:
        col = _pick_column(conn, src, cands)
        n_src = conn.execute(f"select count(*) from {src}").fetchone()[0] if col else 0
        try:
            n_vec = conn.execute(f"select count(*) from {vec}").fetchone()[0]
        except sqlite3.Error:
            n_vec = 0
        total_src += n_src
        total_vec += n_vec
        print(f"{src:<20}{n_src:>6}{col or '(未找到)':>12}{vec:>18}{n_vec:>6}"
              f"{_vec_dim(conn, vec):>7}")

    print(f"\n合计：源 {total_src} 条，向量 {total_vec} 条")
    if model == "md5":
        print("提示：当前配置就是 md5（无语义），重建没有意义 —— 先换回真模型。")
    elif total_src and total_vec == 0:
        print("⚠ 没有任何向量 —— 此前多半一直在降级，建议执行 --rebuild。")
    elif total_src != total_vec:
        print(f"⚠ 源与向量数量不一致（{total_src} vs {total_vec}）—— 建议执行 --rebuild。")
    else:
        print("数量一致。**但数量一致不代表向量同源**："
              "若期间更换过嵌入模型，仍需 --rebuild 才能在语义上兼容。")
    conn.close()
    return 0


async def rebuild(db: str) -> int:
    conn = _connect(db)
    from yuiro.config import load_config
    from yuiro.memory import Embedder

    model = load_config().memory.embedder
    if model == "md5":
        print("当前模型是 md5 —— 重建出来的向量没有语义，已中止。")
        return 1

    emb = Embedder(model)
    if not await emb.wait_ready(120.0):
        print(f"嵌入器未就绪（{getattr(emb, '_ready_reason', '')}），已中止。")
        return 1

    total = 0
    for src, cands, vec in SOURCES:
        col = _pick_column(conn, src, cands)
        if not col:
            print(f"跳过 {src}：找不到文本列（候选 {cands}）")
            continue
        rows = conn.execute(f"select rowid, {col} from {src}").fetchall()
        texts = [str(r[1] or "") for r in rows]
        if not texts:
            print(f"{src}：无数据，跳过")
            continue

        print(f"{src}：重算 {len(texts)} 条 …")
        vecs = await emb.embed_many(texts)
        if len(vecs) != len(texts):
            print(f"⚠ 向量数不匹配（{len(vecs)} vs {len(texts)}），跳过 {src}")
            continue

        conn.execute(f"delete from {vec}")
        # sqlite-vec 不接受 Python list，必须用官方的 float32 二进制序列化
        from sqlite_vec import serialize_float32

        conn.executemany(
            f"insert into {vec}(rowid, embedding) values (?, ?)",
            [(int(r[0]), serialize_float32(v)) for r, v in zip(rows, vecs)],
        )
        conn.commit()
        total += len(vecs)
        print(f"  ✓ 已写入 {len(vecs)} 条")

    conn.close()
    print(f"\n完成：共重建 {total} 条向量。")
    print("提示：换个说法问一条老记忆，确认语义召回恢复（关键词命中不算——FTS 本来就有效）。")
    return 0


def main() -> int:
    db = "data/yuiro_memory.db"
    for arg in sys.argv[1:]:
        if arg.startswith("--db="):
            db = arg.split("=", 1)[1]
    if "--rebuild" in sys.argv:
        return asyncio.run(rebuild(db))
    return inspect(db)


if __name__ == "__main__":
    raise SystemExit(main())
