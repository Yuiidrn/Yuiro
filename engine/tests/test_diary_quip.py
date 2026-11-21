"""S51 吐槽模式测试：门控 + 情绪安全阀。

这里最值钱的不是"能吐槽"，而是**"什么时候闭嘴"**：
- 心流中（还在快速输入）不说话；
- 频率过高不说话；
- 同一段不重复说；
- ★ **情绪负面时一律沉默**（在用户难过时吐槽是产品灾难）。
"""
from __future__ import annotations

import pytest

from yuiro.agent import LLMChunk, LLMProvider
from yuiro.diary.quip import QuipGate, QuipService, mood_is_safe


class _FakeLLM(LLMProvider):
    def __init__(self, reply: str = "这话我记住了。") -> None:
        self._reply = reply
        self.calls = 0

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        del messages, tools, kwargs
        self.calls += 1
        yield LLMChunk(kind="token", content=self._reply)
        yield LLMChunk(kind="done")


# ── 门控（纯逻辑）────────────────────────────────────────────────────────────
def test_gate_requires_idle_window() -> None:
    """还在写（idle 不足）→ 不说话（心流优先）。"""
    g = QuipGate(min_idle_s=3.0)
    assert g.should_quip(text="今天去公园跑步了", idle_s=0.5) is False
    assert g.should_quip(text="今天去公园跑步了", idle_s=3.5) is True


def test_gate_requires_min_chars() -> None:
    g = QuipGate(min_chars=6)
    assert g.should_quip(text="嗯", idle_s=9) is False


def test_gate_rate_limit_and_no_repeat() -> None:
    g = QuipGate(min_interval_s=60.0)
    assert g.should_quip(text="今天去公园跑步了", idle_s=9, now=100.0) is True
    g.note_quip(text="今天去公园跑步了", now=100.0)
    # 频率上限
    assert g.should_quip(text="晚上又去吃了火锅", idle_s=9, now=110.0) is False
    # 同一段不重复
    assert g.should_quip(text="今天去公园跑步了", idle_s=9, now=200.0) is False
    # 换一段且间隔够 → 可以
    assert g.should_quip(text="晚上又去吃了火锅", idle_s=9, now=200.0) is True


def test_gate_reset_allows_again() -> None:
    g = QuipGate(min_interval_s=600.0)
    g.note_quip(text="x" * 10, now=1.0)
    assert g.should_quip(text="x" * 10, idle_s=9, now=2.0) is False
    g.reset()
    assert g.should_quip(text="x" * 10, idle_s=9, now=2.0) is True


# ── ★ 情绪安全阀（红线）─────────────────────────────────────────────────────
def test_mood_safe_detects_negative() -> None:
    assert mood_is_safe("今天去公园跑步，很轻松") is True
    assert mood_is_safe("今天特别难过，什么都不想做") is False
    assert mood_is_safe("又失眠了") is False
    assert mood_is_safe("") is False, "空文本也视为不安全（保守）"


@pytest.mark.asyncio
async def test_negative_mood_never_calls_llm() -> None:
    """★ 情绪安全阀**优先于一切门控**：内容难过时连 LLM 都不调。"""
    llm = _FakeLLM()
    svc = QuipService(llm=llm, gate=QuipGate(min_idle_s=0, min_interval_s=0))
    out = await svc.maybe_quip("今天真的很难过，什么都做不好", idle_s=99)
    assert out is None
    assert llm.calls == 0, "负面内容不该把私密心事交给模型去『吐槽』"


# ── 生成与校验 ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_quip_returned_when_allowed() -> None:
    llm = _FakeLLM("跑步好，比躺着强。")
    svc = QuipService(llm=llm, gate=QuipGate(min_idle_s=0, min_interval_s=0))
    out = await svc.maybe_quip("今天去公园跑了五公里，很舒服", idle_s=9)
    assert out == "跑步好，比躺着强。"


@pytest.mark.asyncio
async def test_model_may_choose_silence() -> None:
    """模型回答"（不说话）"= 它选择沉默（给它一个出口，比硬憋一句好）。"""
    svc = QuipService(llm=_FakeLLM("（不说话）"), gate=QuipGate(min_idle_s=0, min_interval_s=0))
    assert await svc.maybe_quip("今天去公园跑步了", idle_s=9) is None


@pytest.mark.asyncio
async def test_overlong_quip_is_dropped() -> None:
    """超过 30 字就不是"极短"了 → 丢弃（那是抢戏，不是吐槽）。"""
    svc = QuipService(llm=_FakeLLM("啊" * 50), gate=QuipGate(min_idle_s=0, min_interval_s=0))
    assert await svc.maybe_quip("今天去公园跑步了", idle_s=9) is None


@pytest.mark.asyncio
async def test_llm_failure_is_silent() -> None:
    """生成失败静默（吐槽绝不能干扰写日记本身）。"""

    class _Boom(LLMProvider):
        async def stream_text(self, messages, tools=None, **kwargs):
            raise RuntimeError("boom")
            yield LLMChunk(kind="done")  # pragma: no cover

    svc = QuipService(llm=_Boom(), gate=QuipGate(min_idle_s=0, min_interval_s=0))
    assert await svc.maybe_quip("今天去公园跑步了", idle_s=9) is None


@pytest.mark.asyncio
async def test_no_llm_means_no_quip() -> None:
    """未注入 LLM（如精简部署）→ 功能自然不生效，而不是报错。"""
    assert await QuipService(llm=None).maybe_quip("今天去公园跑步了", idle_s=9) is None


@pytest.mark.asyncio
async def test_gate_is_updated_after_quip() -> None:
    """吐槽后要记账，否则频率门控失效（连续刷屏）。"""
    svc = QuipService(
        llm=_FakeLLM("记住了。"), gate=QuipGate(min_idle_s=0, min_interval_s=600)
    )
    assert await svc.maybe_quip("今天去公园跑步了", idle_s=9) is not None
    assert await svc.maybe_quip("换一段内容继续写", idle_s=9) is None
