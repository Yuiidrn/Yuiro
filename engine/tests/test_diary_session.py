"""S51 日记模式会话测试：草稿 / 控制意图 / 吐槽门控接线。

最容易出错的两处：
- **控制意图的保守性**：正文里出现"写完了"不能被当成退出指令（宁可漏判）；
- **提交用多段拼接**、提交后复位（否则下一篇会带上上一篇的内容）。
"""
from __future__ import annotations

import pytest

from yuiro.agent import LLMChunk, LLMProvider
from yuiro.diary import PRIVACY_LOCAL_ONLY, PRIVACY_SHARED, DiaryStore
from yuiro.diary.quip import QuipGate, QuipService
from yuiro.diary.service import DiaryService
from yuiro.diary.session import DiarySession, detect_control_intent


class _FakeLLM(LLMProvider):
    def __init__(self, reply: str = "明白了。") -> None:
        self._reply = reply
        self.calls = 0

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        del messages, tools, kwargs
        self.calls += 1
        yield LLMChunk(kind="token", content=self._reply)
        yield LLMChunk(kind="done")


# ── 控制意图（保守优先）─────────────────────────────────────────────────────
def test_detect_control_intent_basic() -> None:
    assert detect_control_intent("退出日记") == "exit"
    assert detect_control_intent("写完了") == "exit"
    assert detect_control_intent("删掉刚才那句") == "undo"
    assert detect_control_intent("看看我上周写的") == "recall"


def test_detect_control_intent_ignores_long_text() -> None:
    """★ 长句一律当**正文** —— 日记里写"今天终于把报告写完了"不是退出指令。"""
    assert detect_control_intent("今天终于把报告写完了，感觉轻松多了") is None
    assert detect_control_intent("") is None
    assert detect_control_intent("跑步") is None


# ── 草稿 ─────────────────────────────────────────────────────────────────────
def test_append_and_undo() -> None:
    s = DiarySession()
    s.start()
    s.append("今天去了公园")
    s.append("然后吃了火锅")
    assert s.segments == ["今天去了公园", "然后吃了火锅"]
    assert "公园" in s.draft() and "火锅" in s.draft()
    s.undo()
    assert s.segments == ["今天去了公园"]
    s.undo()
    s.undo()  # 空草稿 undo 不炸
    assert s.segments == []


def test_start_clears_draft() -> None:
    s = DiarySession()
    s.start()
    s.append("上一篇的内容")
    s.start()  # 重新开始
    assert s.segments == []


# ── 吐槽接线 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_quip_disabled_returns_none() -> None:
    s = DiarySession()
    s.start()
    s.append("今天去公园跑步了")
    assert await s.maybe_quip(idle_s=99) is None


@pytest.mark.asyncio
async def test_quip_respects_gate_and_safety_valve() -> None:
    llm = _FakeLLM("跑步比躺着强。")
    quip = QuipService(llm=llm, gate=QuipGate(min_idle_s=3.0, min_interval_s=0))
    s = DiarySession(quip=quip)
    s.start()
    s.append("今天去公园跑了五公里，很舒服")
    # 还在写（idle 不足）→ 不说话（心流优先）
    assert await s.maybe_quip(idle_s=1.0) is None
    assert await s.maybe_quip(idle_s=5.0) == "跑步比躺着强。"
    assert llm.calls == 1

    # ★ 情绪安全阀：难过时不吐槽，且**不调用 LLM**
    s.append("后来听到一个很糟糕的消息，特别难过")
    assert await s.maybe_quip(idle_s=9.0) is None
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_quip_without_draft_is_none() -> None:
    quip = QuipService(llm=_FakeLLM(), gate=QuipGate(min_idle_s=0, min_interval_s=0))
    s = DiarySession(quip=quip)
    s.start()
    assert await s.maybe_quip(idle_s=9) is None


# ── 提交 ─────────────────────────────────────────────────────────────────────
@pytest.fixture()
def session(tmp_path):
    store = DiaryStore(tmp_path / "d.db")
    svc = DiaryService(store, memory=None, llm=None)
    yield DiarySession(service=svc), store
    store.close()


@pytest.mark.asyncio
async def test_submit_joins_segments_and_resets(session) -> None:
    s, store = session
    s.start()
    s.append("今天去了公园")
    s.append("晚上吃了火锅")
    res = await s.submit(privacy=PRIVACY_SHARED)
    assert res["ok"] and res["diary_id"] > 0
    row = store.get(res["diary_id"])
    assert "公园" in row["raw_text"] and "火锅" in row["raw_text"]
    assert s.segments == [], "提交后必须复位（否则下一篇会带上上一篇）"
    assert s.active is False


@pytest.mark.asyncio
async def test_submit_empty_draft_fails(session) -> None:
    s, _store = session
    s.start()
    res = await s.submit(privacy=PRIVACY_LOCAL_ONLY)
    assert res["ok"] is False


@pytest.mark.asyncio
async def test_submit_bad_privacy_fails(session) -> None:
    s, _store = session
    s.start()
    s.append("今天去公园跑步")
    res = await s.submit(privacy="nonsense")
    assert res["ok"] is False


@pytest.mark.asyncio
async def test_submit_without_service_fails() -> None:
    s = DiarySession()  # 无 service（日记未启用）
    s.start()
    s.append("今天去公园跑步")
    assert (await s.submit(privacy=PRIVACY_LOCAL_ONLY))["ok"] is False


# ── ★ 审阅编辑态（§2.1）────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_preview_does_not_persist_until_confirm(tmp_path) -> None:
    """★ 审阅阶段**绝不落库**；确认才落库，且**不重复解构**（省一次 LLM 调用）。"""
    store = DiaryStore(tmp_path / "d.db")
    llm = _FakeLLM('{"polished_text":"润色后的话","summary":"摘要"}')
    svc = DiaryService(store, memory=None, llm=llm)
    s = DiarySession(service=svc)
    s.start()
    s.append("今天去公园跑步")

    prev = await s.preview()
    assert prev["ok"] is True
    assert prev["polished_text"] == "润色后的话"
    assert store.stats()["total"] == 0, "审阅阶段不能落库（用户还没确认）"
    calls_after_preview = llm.calls

    res = await s.confirm(privacy=PRIVACY_LOCAL_ONLY, use_polished=True)
    assert res["ok"] is True
    assert store.get(res["diary_id"])["polished_text"] == "润色后的话"
    assert llm.calls == calls_after_preview, "confirm 不该重复解构"
    assert s.segments == []
    store.close()


@pytest.mark.asyncio
async def test_confirm_use_polished_false_keeps_raw_text(tmp_path) -> None:
    """★ "存原文"：润色稿被丢弃，但 summary/标签保留（索引不改用户的话）。"""
    store = DiaryStore(tmp_path / "d.db")
    svc = DiaryService(
        store, memory=None, llm=_FakeLLM('{"polished_text":"被改写的版本","summary":"摘要"}')
    )
    s = DiarySession(service=svc)
    s.start()
    s.append("我的原话")
    await s.preview()
    res = await s.confirm(privacy=PRIVACY_LOCAL_ONLY, use_polished=False)
    row = store.get(res["diary_id"])
    assert row["polished_text"] == "我的原话"
    assert row["summary"] == "摘要"
    store.close()


@pytest.mark.asyncio
async def test_confirm_without_preview_falls_back_to_submit(session) -> None:
    """没走过审阅就确认（旧客户端/异常）→ 退回普通提交，不报错。"""
    s, store = session
    s.start()
    s.append("今天去公园跑步")
    res = await s.confirm(privacy=PRIVACY_LOCAL_ONLY)
    assert res["ok"] is True
    assert store.stats()["total"] == 1


@pytest.mark.asyncio
async def test_preview_empty_draft_fails(session) -> None:
    s, _store = session
    s.start()
    assert (await s.preview())["ok"] is False
