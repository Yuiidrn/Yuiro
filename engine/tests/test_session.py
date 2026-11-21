"""S02：SessionManager / AgentSession / generation 统一（Unit + Scenario）。

对应 docs/plan/S02-session-generation-unify.md。
"""
from __future__ import annotations

import asyncio

import pytest

from yuiro.runtime.events import AgentEvent, EventBus
from yuiro.runtime.session import AgentSession, SessionManager, SessionState


class _FakeWS:
    """占位传输对象（只用身份判断，不做真实发送）。"""


# ---- Unit：SessionManager 生命周期 -----------------------------------------


def test_create_and_get() -> None:
    mgr = SessionManager()
    s = mgr.create()
    assert mgr.get(s.session_id) is s
    assert s.state is SessionState.ACTIVE


def test_attach_control_then_audio_binds_same_session() -> None:
    """S02 核心：audio 带 session_id 绑定 control 创建的同一会话。"""
    mgr = SessionManager()
    ctrl = mgr.attach_control(_FakeWS())
    audio = mgr.attach_audio(_FakeWS(), session_id=ctrl.session_id)
    assert audio is ctrl
    assert audio.audio_ws is not None and audio.control_ws is not None


def test_attach_without_session_creates_new() -> None:
    """不带 session_id（旧前端）→ 独立新会话（向后兼容）。"""
    mgr = SessionManager()
    a = mgr.attach_control(_FakeWS())
    b = mgr.attach_audio(_FakeWS())
    assert a is not b


def test_resume_by_session_id() -> None:
    mgr = SessionManager()
    s1 = mgr.attach_control(_FakeWS())
    mgr.detach_control(s1.session_id)
    assert s1.state is SessionState.SUSPENDED
    s2 = mgr.attach_control(_FakeWS(), session_id=s1.session_id)
    assert s2 is s1
    assert s2.state is SessionState.ACTIVE


def test_close_marks_closed_and_removes() -> None:
    mgr = SessionManager()
    s = mgr.create()
    mgr.close(s.session_id)
    assert mgr.get(s.session_id) is None
    assert s.state is SessionState.CLOSED


# ---- Unit：Generation 语义 ---------------------------------------------------


def test_generation_next_and_invalidate() -> None:
    s = AgentSession(session_id="x")
    assert s.generation == 0
    assert s.next_generation() == 1
    assert s.next_generation() == 2
    assert s.invalidate("barge-in") == 3
    assert s.generation == 3


def test_same_session_generation_is_continuous() -> None:
    """Scenario：文字与语音回合共用同一 AgentSession → generation 连续（同一个"我"）。"""
    mgr = SessionManager()
    session = mgr.attach_control(_FakeWS())
    g1 = session.next_generation()  # 文字回合
    audio = mgr.attach_audio(_FakeWS(), session_id=session.session_id)
    g2 = audio.next_generation()  # 语音回合（绑定同一会话）
    assert (g1, g2) == (1, 2)


# ---- Unit：EventBus 与单点映射 -----------------------------------------------


@pytest.mark.asyncio
async def test_event_bus_publish_and_wire() -> None:
    bus = EventBus()
    seen: list[AgentEvent] = []

    async def handler(ev: AgentEvent) -> None:
        seen.append(ev)

    bus.subscribe("session.started", handler)
    ev = AgentEvent(
        type="session.started", source="SessionManager", session_id="s1", generation=0
    )
    await bus.publish(ev)
    assert seen and seen[0] is ev

    wire = EventBus.to_wire(ev)
    assert wire["type"] == "session:ready"  # 内部点分 → 对外冒号（单点映射）
    assert wire["session_id"] == "s1"
    assert wire["generation"] == 0


# ---- Scenario：AgentLoop 接入 Session 与代际作废可观测 ------------------------


class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def stream_text(self, messages, tools=None, **kwargs):
        from yuiro.agent import LLMChunk

        del messages, tools, kwargs
        yield LLMChunk(kind="token", content=self._reply)
        yield LLMChunk(kind="done")


class _NoopRegistry:
    def schemas(self) -> list:
        return []

    async def execute(self, name, args, task_id, approval_callback=None):
        del name, args, task_id, approval_callback
        return "{}"


@pytest.mark.asyncio
async def test_agentloop_generation_follows_session() -> None:
    """传 session 时：generation 权威在 AgentSession（不再用内部 dict）。"""
    from yuiro.agent import AgentLoop

    loop = AgentLoop(
        llm=_FakeLLM("你好"),
        tools_registry=_NoopRegistry(),
        memory_retriever=None,
    )
    session = AgentSession(session_id="s1")
    parts: list[str] = []
    async for chunk in loop.send("s1", "hi", session=session):
        if chunk.kind == "token":
            parts.append(chunk.content)
    assert "".join(parts) == "你好"
    assert session.generation == 1
    assert loop._generations.get("s1") is None  # 未写内部 dict（权威已收敛）


@pytest.mark.asyncio
async def test_should_abort_emits_stale_event() -> None:
    """代际作废：返回 True 且发 agent:stale_discarded 事件（不再静默）。"""
    from yuiro.agent import AgentLoop

    bus = EventBus()
    seen: list[dict] = []

    async def on_stale(ev: AgentEvent) -> None:
        seen.append(ev.payload)

    bus.subscribe("agent.stale_discarded", on_stale)
    loop = AgentLoop(
        llm=None, tools_registry=None, memory_retriever=None, events=bus
    )
    session = AgentSession(session_id="s1")
    session.generation = 5

    assert loop._should_abort("s1", 3, session, "tool_round") is True
    await asyncio.sleep(0.01)  # 等待 fire-and-forget 事件发布
    assert seen and seen[0]["stage"] == "tool_round"
    assert seen[0]["stale_generation"] == 3

    # 同代际 → 不中止、不发事件
    assert loop._should_abort("s1", 5, session, "tool_round") is False
    await asyncio.sleep(0.01)
    assert len(seen) == 1
