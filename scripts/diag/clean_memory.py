"""清理记忆库中"打开网易云音乐/记事本"测试污染条目（三表同步删除，vec 表需加载扩展）。"""
import sqlite3

import sqlite_vec

conn = sqlite3.connect("data/yuiro_memory.db")
conn.enable_load_extension(True)
sqlite_vec.load(conn)
kw = ["%网易云%", "%记事本%", "%notepad%"]
rids = set()
for k in kw:
    for r in conn.execute("SELECT rowid FROM messages WHERE text LIKE ?", (k,)).fetchall():
        rids.add(r[0])
rids = sorted(rids)
print("待清理 rowid:", rids)
if rids:
    q = ",".join(str(r) for r in rids)
    for table in ("messages_vec", "messages_fts", "messages"):
        conn.execute(f"DELETE FROM {table} WHERE rowid IN ({q})")
    conn.commit()
print("清理后剩余:", conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], "条")
conn.close()
