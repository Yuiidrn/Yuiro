"""清理 L3 facts 的存量污染（S42 附带）。

**为什么要单独做**：S40 给 facts 写入加了四道闸门（值过滤 / LLM 触发门槛 / prompt
收紧 / 二次确认），但**闸门只管新增** —— 之前写进去的污染仍躺在库里，而且每一轮
都在参与注入。典型症状：

1. **死数据**：`facts` 的主键是 `(subject, key)`，检索按 `subject` 过滤，
   与 `[persona].memory_subject` 不一致的记录**永远查不到**（实测 `用户/名字=什么名字`）；
2. **无信息残留**：值是问句或元话语（"什么名字"），不是用户的属性；
3. **同义重复**：同一个意思占两个 key，注入时白占两份上下文预算；
4. **事件当画像**：把一次性事件（"《谁》Live版"）记成稳定偏好。

清理规则**全部显式列在下面**，不做任何启发式判断 —— 动用户的数据必须可解释、可复核。

用法：
    python scripts/clean_facts.py --dry-run   # 预览计划（默认，只读）
    python scripts/clean_facts.py --apply     # 执行（自动备份 db）
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import time

# ── 清理规则（改这里 = 改清理行为；每条都能一眼看懂为什么）────────────────

#: 没有信息量的值 → 删除（值是问句残留，不是用户属性）
JUNK: list[tuple[str, str]] = [
    ("名字", "什么名字"),
]

#: 键名太泛 → 重命名（保留值）。"喜欢"什么？值才是答案，键该是类别。
KEY_RENAMES: list[tuple[str, str]] = [
    ("喜欢", "饮食偏好"),
]

#: 同义重复 → 合并（左：删；右：留）。仅当两者语义确实一致时才这么写。
KEY_MERGES: list[tuple[str, str]] = [
    ("审美风格", "音乐偏好"),   # "老派浪漫" / "老派浪漫风格" 是同一件事
]

#: 事件被当成画像 → 删。值是具体作品名，属于"聊过一首歌"，不是稳定偏好。
EVENT_AS_PROFILE: list[tuple[str, str]] = [
    ("歌曲偏好", "《谁》Live版"),
]

#: subject 归一（信息保留，只修正归属）。None 表示用配置里的 memory_subject。
SUBJECT_FIX_FROM = "用户"


def _rows(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "select subject, key, value, confidence, decay, updated_at from facts"
    )]


def _plan(rows: list[dict], subject: str) -> list[tuple[str, dict, dict | None]]:
    """产出 ``(说明, 原记录, 新记录 | None(表示删除))``。

    三类规则按**互斥顺序**判定（一条记录只落一类，避免"归属修正先命中、
    导致键名规范化失效"这种顺序陷阱）：

    1. 纯删除（无信息残留 / 事件当画像）；
    2. 同义合并（删掉被并入的那个键）；
    3. 变换 —— 归属归一 + 键名规范化**可以同时发生**。
    """
    actions: list[tuple[str, dict, dict | None]] = []
    for r in rows:
        key, value = str(r["key"]), str(r["value"])

        if (key, value) in JUNK:
            actions.append((f"删除无信息残留：{key} = {value!r}", r, None))
            continue
        if (key, value) in EVENT_AS_PROFILE:
            actions.append((f"删除（事件被当画像）：{key} = {value!r}", r, None))
            continue

        merged = next((pair for pair in KEY_MERGES if pair[0] == key), None)
        if merged is not None:
            actions.append((f"同义合并：删除 {key}（并入 {merged[1]}）", r, None))
            continue

        new_subject = subject if r["subject"] != subject else str(r["subject"])
        new_key = next((nk for ok, nk in KEY_RENAMES if key == ok), key)
        if new_subject != r["subject"] or new_key != key:
            bits: list[str] = []
            if new_subject != r["subject"]:
                bits.append(f"归属 {r['subject']!r} → {new_subject!r}")
            if new_key != key:
                bits.append(f"键名 {key} → {new_key}")
            actions.append(("、".join(bits), r, dict(r, subject=new_subject, key=new_key)))
    return actions


def main() -> int:
    db = "data/yuiro_memory.db"
    for arg in sys.argv[1:]:
        if arg.startswith("--db="):
            db = arg.split("=", 1)[1]

    from yuiro.config import load_config

    cfg = load_config()
    subject = cfg.persona.memory_subject or cfg.memory.facts_subject
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = _rows(conn)

    print(f"库：{db}")
    print(f"检索用的 subject：{subject!r}")
    print(f"当前 facts 共 {len(rows)} 条\n")

    actions = _plan(rows, subject)
    if not actions:
        print("没有需要清理的记录 ✓")
        conn.close()
        return 0

    print(f"计划执行 {len(actions)} 项：")
    for desc, old, new in actions:
        tail = "" if new is None else f"  →  {new['subject']}/{new['key']} = {new['value']!r}"
        print(f"  · {desc}{tail}")

    if "--apply" not in sys.argv:
        print("\n（预览模式，未改动任何数据；确认后加 --apply）")
        conn.close()
        return 0

    backup = f"{db}.bak-facts-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(db, backup)
    print(f"\n已备份 → {backup}")

    applied = skipped = 0
    for _desc, old, new in actions:
        if new is None:
            conn.execute(
                "delete from facts where subject=? and key=?", (old["subject"], old["key"])
            )
            applied += 1
            continue
        # 主键是 (subject, key)：改任一个都要"插新的 + 删旧的"。
        # 目标键若已存在**不覆盖**（保留既有事实，人工复核更安全）。
        exists = conn.execute(
            "select 1 from facts where subject=? and key=?", (new["subject"], new["key"])
        ).fetchone()
        if exists:
            print(f"  ! 目标已存在，跳过：{new['subject']}/{new['key']}")
            skipped += 1
            continue
        conn.execute(
            "insert into facts(subject,key,value,confidence,decay,updated_at) "
            "values (?,?,?,?,?,?)",
            (new["subject"], new["key"], new["value"],
             old["confidence"], old["decay"], old["updated_at"]),
        )
        conn.execute(
            "delete from facts where subject=? and key=?", (old["subject"], old["key"])
        )
        applied += 1

    conn.commit()
    print(f"\n完成：执行 {applied} 项，跳过 {skipped} 项")
    print(f"剩余 facts：{conn.execute('select count(*) from facts').fetchone()[0]} 条")
    print("提示：facts 的注入走 subject 过滤，可用 scripts/inspect_memory.py 复核。")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
