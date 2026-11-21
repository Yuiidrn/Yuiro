"""检视记忆库实况（诊断工具）。

回答"记忆是不是记了不该记的"这类问题：**直接看库，不靠猜**。

输出：
- 各表行数与结构；
- L3 事实（用户画像）最近 N 条 —— 重点看有没有把"临时感受/测试性发言"记成画像；
- L2 情景记忆最近 N 条；
- 显式记忆（"记住 X"）最近 N 条。

用法：python scripts/inspect_memory.py [--db data/yuiro_memory.db] [--limit 20]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

_DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "yuiro_memory.db"
)


def _dump(conn: sqlite3.Connection, table: str, limit: int, cols: str = "*") -> None:
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.Error as exc:
        print(f"  （跳过 {table}：{exc}）")
        return
    print(f"\n=== {table}（共 {total} 行，显示最近 {limit}） ===")
    try:
        rows = conn.execute(
            f"SELECT {cols} FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,)
        ).fetchall()
    except sqlite3.Error as exc:
        print(f"  （查询失败：{exc}）")
        return
    if not rows:
        print("  （空）")
    for row in rows:
        print("  ", dict(row))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=_DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    db = os.path.abspath(args.db)
    if not os.path.exists(db):
        print(f"记忆库不存在：{db}")
        return 1
    print(f"记忆库：{db}（{os.path.getsize(db) / 1024:.0f} KB）")

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    tables = [
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    ]
    print("表：", tables)

    # L3 事实（用户画像）—— 最需要审视的一张表
    for name in tables:
        low = name.lower()
        if "fact" in low:
            _dump(conn, name, args.limit)
    # L2 情景 + 显式记忆
    for name in tables:
        low = name.lower()
        if "episode" in low or "memory" in low or "explicit" in low:
            _dump(conn, name, min(10, args.limit))

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
