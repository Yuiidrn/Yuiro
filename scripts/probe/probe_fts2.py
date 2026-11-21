import sqlite3
import sqlite_vec

conn = sqlite3.connect("data/yuiro_memory.db")
conn.enable_load_extension(True)
sqlite_vec.load(conn)

# 看 rowid=144 完整文本
r = conn.execute("SELECT rowid, text FROM messages WHERE rowid=144").fetchone()
print(f"rowid=144 完整文本:\n{r[1]!r}\n")

# 看 messages_fts 的 schema
schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='messages_fts'").fetchone()
print(f"messages_fts schema: {schema[0]}\n")

# 直接用 highlight 或检查匹配
rows = conn.execute(
    "SELECT m.rowid, m.text FROM messages_fts JOIN messages m ON m.rowid=messages_fts.rowid "
    "WHERE messages_fts MATCH '网易云音乐'"
).fetchall()
print(f"MATCH '网易云音乐' 命中 {len(rows)} 条:")
for row in rows:
    print(f"  rowid={row[0]}: {row[1][:80]!r}")
conn.close()
