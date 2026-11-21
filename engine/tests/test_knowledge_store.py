"""S51 知识库：导入 / 检索 / **清除必须三表齐删**。

为什么单独建这个文件：知识库此前**一个测试都没有** —— 所以 ``clear()`` 漏删
``knowledge_vec`` 一直没被发现（实测生产库里就有 9 条孤儿向量）。

清除这条是重点，它与 S50 在情景记忆上踩过的坑**完全同款**：
只删 chunks + fts、漏掉 vec → 语义检索仍可能命中孤儿向量；更隐蔽的是清空后
新导入的 chunk rowid 从头编号，会与旧向量**错位关联**（新文本拿到旧语义）。
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from yuiro.memory import KnowledgeStore


def _kb(tmp: str) -> KnowledgeStore:
    # md5 降级向量：测试不依赖 BGE-M3 权重，也不 spawn 子进程
    return KnowledgeStore(str(Path(tmp) / "kb.db"), rrf_k=60, embedder_model="md5")


def test_ingest_and_retrieve_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kb = _kb(tmp)
        n = asyncio.run(
            kb.ingest("量子计算利用量子叠加与纠缠来加速特定类型的计算。", source="demo")
        )
        assert n >= 1
        assert kb.stats()["chunks"] == n

        hits = asyncio.run(kb.retrieve("量子计算", top_k=3))
        assert hits, "刚导入的内容应当能被检索到"
        assert "量子" in str(hits[0]["text"])
        assert hits[0]["source"] == "demo"
        kb.close()


def test_clear_removes_all_three_tables() -> None:
    """★ 清除必须**三表齐删**（chunks / fts / vec）—— S50 同款教训。"""
    with tempfile.TemporaryDirectory() as tmp:
        kb = _kb(tmp)
        asyncio.run(kb.ingest("记忆整理只在会话间隙做，不占回复时间。", source="demo"))
        conn = kb.store.conn
        for t in ("knowledge_chunks", "knowledge_fts", "knowledge_vec"):
            assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] > 0, t

        kb.clear()
        for t in ("knowledge_chunks", "knowledge_fts", "knowledge_vec"):
            assert (
                conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
            ), f"{t} 未清空（清除漏表 = 孤儿向量）"
        assert kb.stats()["chunks"] == 0
        kb.close()


def test_empty_knowledge_skips_embedding_and_ingest_is_immediate(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        kb = _kb(tmp)
        calls = []
        original = kb.embedder.embed

        async def tracked(text):
            calls.append(text)
            return await original(text)

        monkeypatch.setattr(kb.embedder, "embed", tracked)
        try:
            assert asyncio.run(kb.retrieve("空库查询")) == []
            assert calls == []
            asyncio.run(kb.ingest("量子计算说明文档", source="test"))
            calls.clear()
            assert asyncio.run(kb.retrieve("量子计算"))
            assert calls == ["量子计算"]
            kb.clear()
            calls.clear()
            assert asyncio.run(kb.retrieve("清除后查询")) == []
            assert calls == []
        finally:
            kb.close()
