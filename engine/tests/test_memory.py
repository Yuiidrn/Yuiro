"""Unit tests for the M3 memory module."""
from __future__ import annotations

import asyncio
import math
import tempfile
from pathlib import Path

import pytest

from yuiro.memory import (
    DIM,
    Embedder,
    FactsStore,
    Memory,
    Retriever,
    SQLiteVecStore,
    _fallback_vector,
)


def test_memory_defaults():
    m = Memory(text="hello")
    assert m.text == "hello"
    assert m.score == 0.0
    assert m.meta == {}
    m2 = Memory(text="x", score=0.5, meta={"a": 1})
    assert m2.score == 0.5
    assert m2.meta == {"a": 1}


def test_fallback_vector_shape_and_determinism():
    v1 = _fallback_vector("深度学习")
    v2 = _fallback_vector("深度学习")
    v3 = _fallback_vector("今天天气")
    assert len(v1) == DIM
    assert v1 == v2
    assert v1 != v3
    norm = math.sqrt(sum(x * x for x in v1))
    assert abs(norm - 1.0) < 1e-6


def test_embedder_fallback_mode():
    emb = Embedder(model_name=None)
    try:
        assert emb.is_ready() is False
        vec = asyncio.run(emb.embed("测试"))
        assert len(vec) == DIM
        assert vec == asyncio.run(emb.embed("测试"))
    finally:
        emb.close()


@pytest.fixture
def vec_store():
    with tempfile.TemporaryDirectory() as d:
        store = SQLiteVecStore(str(Path(d) / "m.db"))
        yield store
        store.close()


def test_vec_store_add_and_fts(vec_store):
    rid = vec_store.add_message("深度学习是机器学习的分支", _fallback_vector("深度学习"))
    assert rid > 0
    hits = vec_store.fts_search("深度学习")
    assert hits and hits[0]["rowid"] == rid
    recent = vec_store.recent_search(5)
    assert any(h["rowid"] == rid for h in recent)


def test_vec_store_vector_search(vec_store):
    if not vec_store.vec_available:
        pytest.skip("sqlite-vec 不可用")
    v = _fallback_vector("深度学习")
    rid = vec_store.add_message("深度学习是机器学习的分支", v)
    hits = vec_store.vector_search(v, k=5)
    assert any(h["rowid"] == rid for h in hits)


def test_vec_store_salient_search(vec_store):
    vec_store.add_message("普通记忆", _fallback_vector("普通记忆"), salience=0.5)
    rid = vec_store.add_message("重要记忆", _fallback_vector("重要记忆"), salience=9.0)
    hits = vec_store.salient_search(5)
    assert hits[0]["rowid"] == rid


def test_migrations_idempotent(tmp_path):
    p = str(tmp_path / "m.db")
    s1 = SQLiteVecStore(p)
    s1.close()
    s2 = SQLiteVecStore(p)  # 重复打开不应报错
    s2.close()


def test_facts_upsert_overwrite(vec_store):
    vec_store.upsert_fact("小明", "城市", "北京", 1.0)
    vec_store.upsert_fact("小明", "城市", "上海", 0.9)
    rows = vec_store.query_facts("小明")
    assert len(rows) == 1
    assert rows[0]["value"] == "上海"
    assert rows[0]["confidence"] == 0.9
    assert rows[0]["effective_confidence"] == 0.9


@pytest.mark.asyncio
async def test_facts_store_async():
    fs = FactsStore()
    try:
        await fs.upsert("老王", "年龄", "30", 0.7)
        await fs.upsert("老王", "城市", "上海", 0.9)
        rows = await fs.query("老王")
        assert {r["key"]: r["value"] for r in rows} == {"年龄": "30", "城市": "上海"}
    finally:
        fs.close()


@pytest.mark.asyncio
async def test_retriever_rrf():
    emb = Embedder(model_name=None)
    ret = Retriever(emb)
    try:
        await ret.add("深度学习使用神经网络", salience=2.0)
        await ret.add("今天中午吃了面条")
        await ret.add("深度学习需要大量数据", salience=1.5)
        results = await ret.retrieve("深度学习", top_k=3)
        assert len(results) == 3
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
        texts = [r.text for r in results]
        assert any("深度学习" in t for t in texts[:2])
    finally:
        ret.close()


@pytest.mark.asyncio
async def test_retriever_top_k_limit():
    emb = Embedder(model_name=None)
    ret = Retriever(emb)
    try:
        for i in range(10):
            await ret.add(f"记忆条目 {i}")
        results = await ret.retrieve("记忆", top_k=4)
        assert len(results) == 4
    finally:
        ret.close()
