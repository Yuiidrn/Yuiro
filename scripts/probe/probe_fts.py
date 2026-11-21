import sqlite3
import sqlite_vec

conn = sqlite3.connect("data/yuiro_memory.db")
conn.enable_load_extension(True)
sqlite_vec.load(conn)

for q in ["网易云音乐", "下一首", "记事本"]:
    print(f"\nFTS 查询: {q!r}")
    rows = conn.execute(
        "SELECT m.rowid, m.text, bm25(messages_fts) AS rank "
        "FROM messages_fts JOIN messages m ON m.rowid = messages_fts.rowid "
        "WHERE messages_fts MATCH ? ORDER BY rank LIMIT 5",
        (q,),
    ).fetchall()
    for r in rows:
        print(f"  rowid={r[0]} rank={r[2]} text={r[1][:60]!r}")
conn.close()
