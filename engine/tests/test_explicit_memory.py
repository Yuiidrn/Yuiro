"""S07：显式记忆（"记住 X"）—— 识别 / 立即写入 / 常驻注入 / Context 分段。

对应 docs/plan/S07-explicit-memory.md。
"""
from __future__ import annotations

import os
import tempfile

import pytest

from yuiro.context import ContextBudget, ContextEngine
from yuiro.memory import MemorySystem


def _mem(db: str) -> MemorySystem:
    return MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")


# ---- 显式句式识别 -----------------------------------------------------------
def test_extract_explicit_variants() -> None:
    f = MemorySystem._extract_explicit
    assert f("记住我下周要参加算法竞赛") == "我下周要参加算法竞赛"
    assert f("帮我记一下：我对花生过敏") == "我对花生过敏"
    assert f("别忘了明天叫我起床") == "明天叫我起床"
    assert f("记牢我的锁屏密码是 1234") == "我的锁屏密码是 1234"
    assert f("请记住，我喜欢喝美式") == "我喜欢喝美式"


def test_extract_explicit_negative() -> None:
    f = MemorySystem._extract_explicit
    assert f("今天天气不错") is None
    assert f("你记住了吗？") is None  # 纯指令词，无内容
    assert f("记住") is None
    assert f("") is None
    assert f(None) is None  # type: ignore[arg-type]


# ---- 写入与检索 -------------------------------------------------------------
@pytest.mark.asyncio
async def test_remember_explicit_then_retrieve() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        m = _mem(os.path.join(tmp, "m.db"))
        try:
            await m.remember("记住我下周要参加算法竞赛", "好的，我记住了！")
            hits = await m.retrieve("我下周要干什么")
            explicit = [h for h in hits if h.meta.get("kind") == "explicit"]
            assert explicit, "显式记忆必须被检索注入"
            assert "算法竞赛" in explicit[0].text
        finally:
            m.close()


@pytest.mark.asyncio
async def test_explicit_always_injected_even_when_irrelevant() -> None:
    """显式记忆不受 top_k / 相关性限制：无关查询也应常驻注入。"""
    with tempfile.TemporaryDirectory() as tmp:
        m = _mem(os.path.join(tmp, "m.db"))
        try:
            await m.remember("记住我的生日是 3 月 6 日", "记住啦")
            hits = await m.retrieve("今天吃什么", top_k=1)
            assert any(h.meta.get("kind") == "explicit" for h in hits)
        finally:
            m.close()


@pytest.mark.asyncio
async def test_no_explicit_when_not_requested() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        m = _mem(os.path.join(tmp, "m.db"))
        try:
            await m.remember("今天天气不错", "是呀")
            hits = await m.retrieve("天气")
            assert not [h for h in hits if h.meta.get("kind") == "explicit"]
        finally:
            m.close()


@pytest.mark.asyncio
async def test_explicit_persists_across_instances() -> None:
    """跨实例（模拟重启）：显式记忆仍能被常驻注入。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "m.db")
        m1 = _mem(db)
        await m1.remember("记住我下周三要去体检", "好的")
        m1.close()
        m2 = _mem(db)
        try:
            hits = await m2.retrieve("随便聊聊")
            assert any("体检" in h.text for h in hits if h.meta.get("kind") == "explicit")
        finally:
            m2.close()


# ---- ContextEngine 分段 -----------------------------------------------------
class _M:
    def __init__(self, text: str, kind: str, score: float = 1.0) -> None:
        self.text = text
        self.meta = {"kind": kind}
        self.score = score


@pytest.mark.asyncio
async def test_context_explicit_segment_before_facts() -> None:
    engine = ContextEngine(
        system_prompt="SYS", persona_prompt="PERS", budget=ContextBudget(total=6000)
    )
    msgs = await engine.build(
        session_id="s",
        user_text="hi",
        memory_items=[
            _M("（用户要求记住）我下周要参加算法竞赛", "explicit"),
            _M("（Yui的事实）喜欢: 钢琴", "fact"),
        ],
    )
    joined = "\n".join(m["content"] for m in msgs if m["role"] == "system")
    assert "你答应用户记住的事" in joined
    assert "算法竞赛" in joined
    # 显式记忆段应排在事实段之前
    assert joined.index("你答应用户记住的事") < joined.index("已知事实")


def test_context_priority_explicit_above_fact() -> None:
    from yuiro.context import engine as eng

    assert eng.P_EXPLICIT > eng.P_FACT
