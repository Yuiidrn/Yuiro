"""S28 测试：Memory Consolidation（支持度驱动 + 安全阀）。

关键护栏：
1. **支持度**：只有反复出现的画像才升级为事实（避免一次推断就写库）；
2. **不降级已有**：用户亲口说的（高置信）不被推断覆盖；
3. **显式记忆不参与**归纳（它是用户的直接意图）；
4. **推断衰减更快**（错的会自然淡出），且归纳**不阻塞、不污染**会话状态。
"""
from __future__ import annotations

import os
import tempfile

import pytest

from yuiro.memory import MemorySystem
from yuiro.memory.consolidation import Consolidator


def _mem(db: str) -> MemorySystem:
    return MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")


# ── 候选收集（支持度）─────────────────────────────────────────────────────
def test_collect_candidates_counts_support() -> None:
    cons = Consolidator(min_support=3)
    extractor = lambda _t: [("宠物", "猫")]
    counter = cons.collect_candidates(["a", "b", "c"], extractor)
    assert counter[("宠物", "猫")] == 3


def test_same_episode_counts_once() -> None:
    """同一条 episode 内重复出现同一对 → 只计一次（否则支持度可被单句刷高）。"""
    cons = Consolidator(min_support=2)
    extractor = lambda _t: [("宠物", "猫"), ("宠物", "猫")]
    counter = cons.collect_candidates(["a"], extractor)
    assert counter[("宠物", "猫")] == 1


def test_extractor_failure_is_isolated() -> None:
    cons = Consolidator(min_support=1)

    def bad(_t: str):
        raise RuntimeError("boom")

    assert cons.collect_candidates(["a"], bad) == {}


# ── 安全阀 ────────────────────────────────────────────────────────────────
def test_min_support_filters_low_support() -> None:
    cons = Consolidator(min_support=3)
    counter = cons.collect_candidates(["a", "b", "c", "d"], lambda t: [(t, "v")])
    accepted, _, skipped_low = cons.apply_safety(counter, [])
    assert accepted == []  # 每个 key 只出现 1 次 < 3
    assert skipped_low == 4


def test_does_not_overwrite_higher_confidence() -> None:
    """用户亲口说的（0.9）不被推断（0.7）覆盖。"""
    cons = Consolidator(min_support=2)
    counter = cons.collect_candidates(["a", "b"], lambda _t: [("职业", "程序员")])
    existing = [{"key": "职业", "value": "设计师", "effective_confidence": 0.9}]
    accepted, skipped_existing, _ = cons.apply_safety(counter, existing)
    assert accepted == []
    assert skipped_existing == 1


def test_overwrites_lower_confidence() -> None:
    """旧的弱事实（0.5）可以被更强的推断更新。"""
    cons = Consolidator(min_support=2)
    counter = cons.collect_candidates(["a", "b"], lambda _t: [("职业", "程序员")])
    existing = [{"key": "职业", "value": "设计师", "effective_confidence": 0.5}]
    accepted, _, _ = cons.apply_safety(counter, existing)
    assert accepted == [("职业", "程序员", cons.confidence_cap)]


def test_same_value_is_skipped() -> None:
    cons = Consolidator(min_support=2)
    counter = cons.collect_candidates(["a", "b"], lambda _t: [("宠物", "猫")])
    existing = [{"key": "宠物", "value": "猫", "effective_confidence": 0.5}]
    accepted, skipped_existing, _ = cons.apply_safety(counter, existing)
    assert accepted == []
    assert skipped_existing == 1


def test_one_value_per_key() -> None:
    """同一 key 有多个候选值时只采纳支持度最高的一个（不留冲突事实）。"""
    cons = Consolidator(min_support=2)

    def extractor(text: str):
        return [("宠物", "猫")] if text.startswith("c") else [("宠物", "狗")]

    counter = cons.collect_candidates(["c1", "c2", "c3", "d1", "d2"], extractor)
    accepted, _, _ = cons.apply_safety(counter, [])
    assert len(accepted) == 1
    assert accepted[0][:2] == ("宠物", "猫")


# ── LLM 路径 ──────────────────────────────────────────────────────────────
def test_parse_llm_json_variants() -> None:
    assert Consolidator.parse_llm_json('{"facts":[{"key":"职业","value":"程序员"}]}') == [
        ("职业", "程序员")
    ]
    # 带 markdown 包裹也能提取
    assert Consolidator.parse_llm_json(
        '好的：\n```json\n{"facts":[{"key":"技能","value":"Python"}]}\n```'
    ) == [("技能", "Python")]
    # 非法 / 空 / 结构不符 → 一律放弃（不猜）
    assert Consolidator.parse_llm_json("我不知道") == []
    assert Consolidator.parse_llm_json("") == []
    assert Consolidator.parse_llm_json('{"facts":"nope"}') == []


class _FakeLLM:
    def __init__(self, reply: str, *, fail: bool = False) -> None:
        self._reply = reply
        self._fail = fail

    async def stream_text(self, messages):
        del messages
        if self._fail:
            raise RuntimeError("llm down")

        class _Chunk:
            kind = "token"
            content = self._reply

        yield _Chunk()


@pytest.mark.asyncio
async def test_llm_candidates_and_failure_fallback() -> None:
    cons = Consolidator()
    good = _FakeLLM('{"facts":[{"key":"技术栈","value":"Python"}]}')
    assert await cons.llm_candidates(good, ["学过 Python"]) == [("技术栈", "Python")]
    bad = _FakeLLM("", fail=True)
    assert await cons.llm_candidates(bad, ["学过 Python"]) == []


# ── 端到端（真实 MemorySystem）────────────────────────────────────────────
@pytest.mark.asyncio
async def test_consolidate_end_to_end() -> None:
    """L2 里反复出现但 L3 没有的画像 → 归纳后成为稳定事实。

    这正是 consolidation 的价值场景：直接写 L2（绕过 remember 的规则抽取），
    模拟"用户多次提到同一件事，但从未被抽成事实"。
    """
    with tempfile.TemporaryDirectory() as tmp:
        mem = _mem(os.path.join(tmp, "m.db"))
        for _ in range(3):
            await mem.retriever.add("我养了一只猫")
        result = await mem.consolidate(min_support=3, use_llm=False)
        assert result["written"] >= 1
        facts = await mem._facts.query(mem.facts_subject)
        assert any(f["key"] == "宠物" and f["value"] == "猫" for f in facts)
        mem.close()


@pytest.mark.asyncio
async def test_consolidate_skips_explicit_memories() -> None:
    """显式记忆（带 EXPLICIT_PREFIX 的条目）不参与归纳。

    注意：``remember("记住 X")`` 除显式条目外还会写一条普通 episode 副本（供检索），
    因此"被扫描"的只有那条副本——显式条目本身必须被排除。
    """
    from yuiro.memory import EXPLICIT_PREFIX

    with tempfile.TemporaryDirectory() as tmp:
        mem = _mem(os.path.join(tmp, "m.db"))
        try:
            await mem.retriever.add(
                f"{EXPLICIT_PREFIX}我养了一只猫（用户原话：记住我养了一只猫）"
            )
            await mem.retriever.add("我养了一只猫")
            result = await mem.consolidate(min_support=3, use_llm=False)
            assert result["scanned"] == 1  # 只扫到普通那条
            assert result["written"] == 0  # 支持度不足
        finally:
            mem.close()


@pytest.mark.asyncio
async def test_consolidate_is_idempotent() -> None:
    """重复归纳不产生重复写入（第二次因"已有同值"跳过）。"""
    with tempfile.TemporaryDirectory() as tmp:
        mem = _mem(os.path.join(tmp, "m.db"))
        for _ in range(3):
            await mem.retriever.add("我养了一只猫")
        first = await mem.consolidate(min_support=3, use_llm=False)
        second = await mem.consolidate(min_support=3, use_llm=False)
        assert first["written"] >= 1
        assert second["written"] == 0
        assert second["skipped_existing"] >= 1
        mem.close()


@pytest.mark.asyncio
async def test_consolidate_with_llm_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mem = _mem(os.path.join(tmp, "m.db"))
        mem._fact_llm = _FakeLLM('{"facts":[{"key":"技术栈","value":"Python"}]}')
        await mem.retriever.add("我最近在写 Python 脚本")
        result = await mem.consolidate(min_support=3, use_llm=True)
        assert result["llm_used"] is True
        assert any(d["key"] == "技术栈" for d in result["details"])
        mem.close()


@pytest.mark.asyncio
async def test_consolidate_does_not_touch_episodes() -> None:
    """规范红线：归纳只写 L3 facts，不改动 L2（不污染当前状态）。"""
    with tempfile.TemporaryDirectory() as tmp:
        mem = _mem(os.path.join(tmp, "m.db"))
        for _ in range(3):
            await mem.retriever.add("我养了一只猫")
        before = mem.store.conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
        await mem.consolidate(min_support=3, use_llm=False)
        after = mem.store.conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
        assert before == after
        mem.close()


# ── 衰减来源 ──────────────────────────────────────────────────────────────
def test_consolidation_decays_faster_than_normal_facts() -> None:
    normal = MemorySystem._decay_for("rule")
    cons = MemorySystem._decay_for("consolidation")
    explicit = MemorySystem._decay_for("explicit")
    assert explicit == 0.0
    assert cons > normal > 0.0
