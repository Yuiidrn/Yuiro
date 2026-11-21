"""S12：EventLog（落盘 / 回放 / 轮转）+ EventBus 全局订阅。

对应 docs/spec/README.md §3（Event 可持久化、可回放）。
"""
from __future__ import annotations

import tempfile

import pytest

from yuiro.runtime import AgentEvent, EventBus
from yuiro.runtime.event_log import EventLog


def _ev(session: str = "s1", type_: str = "agent.stale_discarded", gen: int = 1) -> AgentEvent:
    return AgentEvent(
        type=type_, source="test", session_id=session, generation=gen, payload={"k": "v"}
    )


@pytest.fixture()
def logdir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


def _log(tmp: str, **kw) -> EventLog:
    return EventLog(store_dir=f"{tmp}/events", **kw)


def test_append_and_load(logdir) -> None:
    log = _log(logdir)
    for i in range(3):
        log.append(_ev(gen=i))
    events = log.load("s1")
    assert len(events) == 3
    assert [e["generation"] for e in events] == [0, 1, 2]
    assert events[0]["payload"] == {"k": "v"}
    assert events[0]["source"] == "test"


def test_load_filter_and_limit(logdir) -> None:
    log = _log(logdir)
    log.append(_ev(type_="a"))
    log.append(_ev(type_="b"))
    log.append(_ev(type_="a"))
    assert len(log.load("s1", event_type="a")) == 2
    assert len(log.load("s1", limit=1)) == 1


def test_replay_alias(logdir) -> None:
    log = _log(logdir)
    log.append(_ev())
    assert log.replay("s1") == log.load("s1")


def test_missing_session_returns_empty(logdir) -> None:
    assert _log(logdir).load("nope") == []
    assert _log(logdir).replay("nope") == []


def test_corrupt_lines_skipped(logdir) -> None:
    log = _log(logdir)
    log.append(_ev())
    path = log._path("s1")  # 测试需注入损坏行
    with open(path, "a", encoding="utf-8") as f:
        f.write("{not-json}\n\n")
    log.append(_ev(gen=9))
    events = log.load("s1")
    assert len(events) == 2
    assert events[-1]["generation"] == 9


def test_trim_on_max_lines(logdir) -> None:
    log = _log(logdir, max_lines=100)
    for i in range(150):
        log.append(_ev(gen=i))
    events = log.load("s1", limit=2000)
    assert 0 < len(events) <= 100  # 触发轮转后保留约一半
    assert events[-1]["generation"] == 149


def test_sessions_and_stats(logdir) -> None:
    log = _log(logdir)
    log.append(_ev(session="a"))
    log.append(_ev(session="b"))
    assert set(log.sessions()) == {"a", "b"}
    st = log.stats()
    assert st["sessions"] == 2
    assert st["lines"] == 2


def test_append_failure_silent(logdir) -> None:
    """落盘失败（无效目录）不得抛出——事件日志不能影响主链路。"""
    log = EventLog(store_dir="\0invalid")
    log.append(_ev())  # 不应抛


@pytest.mark.asyncio
async def test_event_bus_subscribe_all(logdir) -> None:
    log = _log(logdir)
    bus = EventBus()
    bus.subscribe_all(log.sink)
    await bus.publish(_ev())
    assert len(log.load("s1")) == 1


@pytest.mark.asyncio
async def test_subscribe_all_failure_does_not_break_publish() -> None:
    async def bad(_e: AgentEvent) -> None:
        raise RuntimeError("boom")

    bus = EventBus()
    bus.subscribe_all(bad)
    await bus.publish(_ev())  # 不应抛
