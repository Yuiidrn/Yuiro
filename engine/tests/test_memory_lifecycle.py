"""S13：记忆生命周期（衰减生效 / 遗忘 / 显式记忆管理）。

对应 docs/plan/S13-memory-lifecycle.md。
"""
from __future__ import annotations

import os
import tempfile
import time

import pytest

from yuiro.memory import EXPLICIT_PREFIX, MemorySystem


@pytest.fixture()
def mem():
    with tempfile.TemporaryDirectory() as tmp:
        m = MemorySystem(os.path.join(tmp, "m.db"), rrf_k=60, top_k=3, embedder_model="md5")
        yield m
        m.close()


def test_decay_for_by_source() -> None:
    assert MemorySystem._decay_for("explicit") == 0.0
    assert MemorySystem._decay_for("rule") > 0
    assert MemorySystem._decay_for("llm") > 0


@pytest.mark.asyncio
async def test_fact_decay_persisted(mem) -> None:
    """写入的事实带衰减率（S13 前写死 0）。"""
    await mem._apply_facts([("喜欢", "钢琴")], source="rule")
    facts = await mem._facts.query(mem.facts_subject)
    assert facts and facts[0]["decay"] > 0


@pytest.mark.asyncio
async def test_explicit_fact_no_decay(mem) -> None:
    await mem._apply_facts([("爱好", "编程")], source="explicit")
    facts = await mem._facts.query(mem.facts_subject)
    assert facts and facts[0]["decay"] == 0.0


@pytest.mark.asyncio
async def test_forget_removes_stale_low_confidence_fact(mem) -> None:
    await mem._apply_facts([("旧事", "很久以前")], source="rule", confidence=0.05)
    mem.store.conn.execute("UPDATE facts SET updated_at = ?", (time.time() - 200 * 86400,))
    mem.store.conn.commit()
    result = await mem.forget()
    assert result["facts_removed"] >= 1
    assert await mem._facts.query(mem.facts_subject) == []


@pytest.mark.asyncio
async def test_forget_keeps_recent_fact(mem) -> None:
    await mem._apply_facts([("新事", "刚刚说的")], source="rule")
    result = await mem.forget()
    assert result["facts_removed"] == 0
    assert len(await mem._facts.query(mem.facts_subject)) == 1


@pytest.mark.asyncio
async def test_forget_removes_old_episode_but_keeps_explicit(mem) -> None:
    await mem.remember("今天天气不错", "是呀")  # 普通情景（低显著性）
    await mem.remember("记住我的生日是 3 月 6 日", "记住啦")  # 显式记忆（永不删除）
    mem.store.conn.execute("UPDATE messages SET ts = ?", (time.time() - 100 * 86400,))
    mem.store.conn.commit()
    result = await mem.forget()
    assert result["episodes_removed"] >= 1
    texts = " ".join(r["text"] for r in mem.store.conn.execute("SELECT text FROM messages"))
    assert EXPLICIT_PREFIX in texts  # 显式记忆仍在
    assert mem.list_explicit()


@pytest.mark.asyncio
async def test_delete_explicit(mem) -> None:
    await mem.remember("记住我下周要参赛", "好")
    items = mem.list_explicit()
    assert items
    rowid = int(items[0]["rowid"])
    assert mem.delete_explicit(rowid) is True
    assert mem.list_explicit() == []


@pytest.mark.asyncio
async def test_forget_empty_is_noop(mem) -> None:
    result = await mem.forget()
    assert result == {"facts_removed": 0, "episodes_removed": 0}
