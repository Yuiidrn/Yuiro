"""S51 日记存储测试：结构化 / 隐私三档 / 删除连带 / 检索。

每条都对应设计文档里的一个硬判断（不是"顺手测一下"）：

- **discard 不落库**：阅后即焚的定义是"不存在"，不是"落库后标记 discard"；
- **delete 必须连带附属表**：S50 的教训 —— 只删主表会留下"删了还在"的错觉，
  并让孤儿标签/索引污染后续检索；
- **set_privacy 必须返回旧档位**：上层据此联动记忆（改档位却不同步 = 谎报隐私）；
- **FTS 中文子串可检索**：回顾的"搜索"必须真的好用（trigram 方案）。
"""
from __future__ import annotations

import pytest

from yuiro.diary import (
    PRIVACY_DISCARD,
    PRIVACY_LOCAL_ONLY,
    PRIVACY_SHARED,
    DiaryStore,
)


@pytest.fixture()
def store(tmp_path):
    s = DiaryStore(tmp_path / "diary.db")
    yield s
    s.close()


def _save(store: DiaryStore, text: str = "今天写代码到很晚，吃了火锅。", **kw) -> int:
    base = {
        "raw_text": text,
        "polished_text": text,
        "summary": "写代码 + 火锅",
        "mood_tags": ["疲惫"],
        "topics": ["工作"],
        "entities": [{"type": "food", "name": "火锅"}],
        "privacy": PRIVACY_LOCAL_ONLY,
    }
    base.update(kw)
    return store.save(**base)


# ── 基本往返与结构化 ─────────────────────────────────────────────────────────
def test_save_and_get_roundtrip(store: DiaryStore) -> None:
    did = _save(store)
    assert did > 0
    row = store.get(did)
    assert row is not None
    assert row["raw_text"].startswith("今天写代码")
    assert row["mood_tags"] == ["疲惫"]
    assert row["topics"] == ["工作"]
    assert row["entities"][0]["name"] == "火锅"
    assert row["privacy"] == PRIVACY_LOCAL_ONLY
    assert row["memory_written"] is False


def test_tags_projected_for_indexing(store: DiaryStore) -> None:
    """★ JSON 列是原始产物，``diary_tags`` 是**可索引投影**（回顾筛选靠它）。"""
    did = _save(store)
    tags = store.tags_of(did)
    assert tags["mood"] == ["疲惫"]
    assert tags["topic"] == ["工作"]
    assert tags["entity"] == ["火锅"]


def test_unknown_privacy_raises(store: DiaryStore) -> None:
    """非法档位**抛错**：写进去就是一条语义不明的数据。"""
    with pytest.raises(ValueError):
        _save(store, privacy="whatever")


# ── ★ discard：不落库 ────────────────────────────────────────────────────────
def test_discard_is_not_persisted(store: DiaryStore) -> None:
    """阅后即焚 = 不存在（返回 0 且任何表都没有它）。"""
    did = _save(store, privacy=PRIVACY_DISCARD)
    assert did == 0
    assert store.list_recent() == []
    assert store.stats()["total"] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM diary_tags").fetchone()[0] == 0


# ── ★ 删除连带（S50 教训）────────────────────────────────────────────────────
def test_delete_removes_tags_and_fts(store: DiaryStore) -> None:
    """★ 删主表必须连带 tags 与 FTS —— 否则"删了还在"（S50 实测过）。"""
    did = _save(store, raw_text="今天研究了检索增强生成")
    assert store.search("检索增强") , "删除前应能搜到"

    assert store.delete(did) is True
    assert store.get(did) is None
    assert store.tags_of(did) == {"mood": [], "topic": [], "entity": []}
    assert store.conn.execute("SELECT COUNT(*) FROM diary_tags").fetchone()[0] == 0
    assert store.search("检索增强") == [], "删除后 FTS 不得残留"


def test_delete_missing_returns_false(store: DiaryStore) -> None:
    assert store.delete(9999) is False


def test_clear_all(store: DiaryStore) -> None:
    _save(store)
    _save(store, raw_text="第二篇")
    assert store.clear_all() == 2
    assert store.stats()["total"] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM diary_tags").fetchone()[0] == 0


# ── 检索与筛选 ───────────────────────────────────────────────────────────────
def test_search_finds_chinese_substring(store: DiaryStore) -> None:
    """★ 2 字中文词也必须搜得到（FTS trigram 对 <3 字符返回空 → 回退 LIKE）。

    "跑步/工作/火锅"这类 2 字词在中文里极常见；只靠 FTS 会让用户觉得
    "搜索坏了" —— 这是实测发现的真问题，不是理论风险。
    """
    _save(store, raw_text="今天去公园跑步，很轻松")
    _save(store, raw_text="加班到很晚，只吃了泡面")
    short_hits = store.search("跑步")
    assert len(short_hits) == 1
    assert "公园" in short_hits[0]["raw_text"]
    # 长词走 FTS 路径，同样要准
    long_hits = store.search("加班到很晚")
    assert len(long_hits) == 1
    assert "泡面" in long_hits[0]["raw_text"]


def test_update_syncs_fts_via_trigger(store: DiaryStore) -> None:
    """FTS 由触发器同步 —— 改内容后旧词查不到、新词查得到。"""
    did = _save(store, raw_text="今天在研究向量数据库")
    assert store.update(did, raw_text="今天在研究提示词工程") is True
    assert store.search("向量数据库") == []
    assert store.search("提示词工程")


def test_list_recent_filters(store: DiaryStore) -> None:
    _save(store, raw_text="A", mood_tags=["开心"], privacy=PRIVACY_SHARED)
    _save(store, raw_text="B", mood_tags=["疲惫"], privacy=PRIVACY_LOCAL_ONLY)
    assert len(store.list_recent()) == 2
    assert [r["raw_text"] for r in store.list_recent(mood="开心")] == ["A"]
    assert [r["raw_text"] for r in store.list_recent(privacy=PRIVACY_LOCAL_ONLY)] == ["B"]
    assert [r["raw_text"] for r in store.list_recent(topic="工作")] == ["B", "A"]


def test_list_recent_pagination(store: DiaryStore) -> None:
    for i in range(3):
        _save(store, raw_text=f"第{i}篇")
    page1 = store.list_recent(limit=2)
    page2 = store.list_recent(limit=2, offset=2)
    assert len(page1) == 2 and len(page2) == 1
    assert {r["raw_text"] for r in page1} & {r["raw_text"] for r in page2} == set()


# ── ★ 隐私档位变更（联动的依据）─────────────────────────────────────────────
def test_set_privacy_returns_old_value(store: DiaryStore) -> None:
    """★ 返回旧档位 —— 上层据此**补写或删除记忆**（改档位不同步 = 谎报隐私）。"""
    did = _save(store, privacy=PRIVACY_SHARED)
    ok, old = store.set_privacy(did, PRIVACY_LOCAL_ONLY)
    assert ok is True
    assert old == PRIVACY_SHARED
    assert store.get(did)["privacy"] == PRIVACY_LOCAL_ONLY


def test_set_privacy_missing(store: DiaryStore) -> None:
    ok, old = store.set_privacy(9999, PRIVACY_SHARED)
    assert ok is False and old == ""


# ── 总评与标记 ───────────────────────────────────────────────────────────────
def test_closing_review_and_memory_flag(store: DiaryStore) -> None:
    did = _save(store)
    assert store.set_closing_review(did, "这一天你过得很用力。") is True
    assert store.get(did)["closing_review"].startswith("这一天")
    store.mark_memory_written(did)
    assert store.get(did)["memory_written"] is True


def test_stats_shape(store: DiaryStore) -> None:
    _save(store, mood_tags=["疲惫"])
    _save(store, mood_tags=["疲惫"], privacy=PRIVACY_SHARED)
    st = store.stats()
    assert st["total"] == 2
    assert st["by_privacy"][PRIVACY_LOCAL_ONLY] == 1
    assert st["top_moods"][0] == {"mood": "疲惫", "count": 2}
