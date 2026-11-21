"""S20 测试：Presence（AttentionPolicy 裁决 + 事件驱动 Runtime）。

覆盖 spec 的克制要求：Quiet Hours / Cooldown / 用户偏好 / 上下文感知 / Confidence，
以及"降级而非丢弃"的核心取舍。
"""
# ruff: noqa: DTZ001 — 静默时段按本地墙上时间构造（与生产语义一致）
from __future__ import annotations

import json
import time
from datetime import datetime

import pytest

from yuiro.presence import (
    AttentionPolicy,
    Channel,
    PresenceRuntime,
    ProactiveIntent,
    Urgency,
    in_quiet_hours,
    parse_quiet_hours,
    parse_urgency,
)


@pytest.fixture(autouse=True)
def _no_quiet_hours(monkeypatch) -> None:
    """默认让策略运行在"非静默时刻"，避免测试受真实时钟影响。"""
    monkeypatch.setattr(
        "yuiro.presence.attention.AttentionPolicy.quiet_now", lambda self, now=None: False
    )


# ── Quiet Hours 解析（含跨午夜）─────────────────────────────────────────────
def test_parse_quiet_hours() -> None:
    assert parse_quiet_hours("23:00-08:00") is not None
    assert parse_quiet_hours("") is None
    assert parse_quiet_hours("乱写的") is None


def test_in_quiet_hours_cross_midnight() -> None:
    assert in_quiet_hours(datetime(2026, 9, 13, 23, 30), "23:00-08:00") is True
    assert in_quiet_hours(datetime(2026, 9, 13, 7, 0), "23:00-08:00") is True
    assert in_quiet_hours(datetime(2026, 9, 13, 12, 0), "23:00-08:00") is False
    # 非跨午夜区间
    assert in_quiet_hours(datetime(2026, 9, 13, 13, 0), "12:00-14:00") is True
    assert in_quiet_hours(datetime(2026, 9, 13, 15, 0), "12:00-14:00") is False


def test_parse_urgency_lenient() -> None:
    assert parse_urgency("HIGH") is Urgency.HIGH
    assert parse_urgency(3) is Urgency.HIGH
    assert parse_urgency("不认识") is Urgency.NORMAL
    assert parse_urgency(None) is Urgency.NORMAL


# ── AttentionPolicy 裁决 ──────────────────────────────────────────────────
def _intent(urgency=Urgency.NORMAL, confidence=1.0, channel=Channel.BUBBLE) -> ProactiveIntent:
    return ProactiveIntent(text="嗨", urgency=urgency, confidence=confidence, channel=channel)


def test_quiet_hours_suppresses(monkeypatch) -> None:
    monkeypatch.setattr(
        "yuiro.presence.attention.AttentionPolicy.quiet_now", lambda self, now=None: True
    )
    policy = AttentionPolicy(quiet_hours="23:00-08:00")
    d = policy.decide(_intent(Urgency.HIGH), mono_now=1000.0)
    assert d.act is False
    assert "静默" in d.reason


def test_high_urgency_can_break_quiet_when_allowed(monkeypatch) -> None:
    monkeypatch.setattr(
        "yuiro.presence.attention.AttentionPolicy.quiet_now", lambda self, now=None: True
    )
    policy = AttentionPolicy(quiet_hours="23:00-08:00", allow_high_in_quiet=True)
    assert policy.decide(_intent(Urgency.HIGH), mono_now=1000.0).act is True
    assert policy.decide(_intent(Urgency.LOW), mono_now=1000.0).act is False


def test_cooldown_suppresses() -> None:
    policy = AttentionPolicy(cooldown_s=900)
    d = policy.decide(_intent(), mono_now=1000.0, last_intervention=500.0)
    assert d.act is False
    assert "冷却" in d.reason
    # 冷却已过
    assert policy.decide(_intent(), mono_now=1500.0, last_intervention=500.0).act is True


def test_low_confidence_suppresses() -> None:
    policy = AttentionPolicy(min_confidence=0.6)
    d = policy.decide(_intent(confidence=0.4), mono_now=1000.0)
    assert d.act is False
    assert "置信度" in d.reason


def test_active_user_downgrades_to_bubble() -> None:
    """核心取舍：用户刚活跃 → 不丢弃内容，而是把"出声"降级为气泡。"""
    policy = AttentionPolicy(suppress_if_active_s=120)
    d = policy.decide(
        _intent(Urgency.NORMAL, channel=Channel.VOICE), mono_now=1000.0, last_activity=950.0
    )
    assert d.act is True
    assert d.downgraded is True
    assert d.intent is not None and d.intent.channel is Channel.BUBBLE
    assert "活跃" in d.reason


def test_already_bubble_is_not_marked_downgraded() -> None:
    """已是气泡形态无需降级（且保留原始 reason 以便观测触发原因）。"""
    policy = AttentionPolicy(suppress_if_active_s=120, max_urgency=Urgency.LOW)
    d = policy.decide(
        _intent(Urgency.HIGH, channel=Channel.BUBBLE), mono_now=1000.0, last_activity=950.0
    )
    assert d.act is True
    assert d.downgraded is False
    assert "最低打扰通道" in d.reason


def test_high_urgency_ignores_active_window() -> None:
    policy = AttentionPolicy(suppress_if_active_s=120)
    d = policy.decide(_intent(Urgency.HIGH), mono_now=1000.0, last_activity=950.0)
    assert d.act is True
    assert d.downgraded is False


def test_over_preference_downgrades() -> None:
    policy = AttentionPolicy(max_urgency=Urgency.LOW)
    d = policy.decide(_intent(Urgency.HIGH, channel=Channel.VOICE), mono_now=1000.0)
    assert d.act is True
    assert d.downgraded is True
    assert d.intent is not None
    assert d.intent.channel is Channel.BUBBLE
    assert d.intent.urgency is Urgency.LOW


def test_allow_when_all_clear() -> None:
    policy = AttentionPolicy()
    d = policy.decide(_intent(Urgency.NORMAL), mono_now=1000.0)
    assert d.act is True
    assert d.downgraded is False
    assert d.intent is not None


# ── PresenceRuntime ───────────────────────────────────────────────────────
class _FakeBroadcast:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def __call__(self, payload: dict) -> None:
        self.sent.append(payload)


class _FakeAvatar:
    def __init__(self) -> None:
        self.performed: list[tuple[str, str]] = []

    async def perform(self, session_id: str, name: str, *, source: str = "agent") -> bool:
        self.performed.append((session_id, name))
        return True


class _FakeEvent:
    def __init__(self, type_: str, payload: dict | None = None, session_id: str = "s1") -> None:
        self.type = type_
        self.payload = payload or {}
        self.session_id = session_id


def _rt(**kw) -> tuple[PresenceRuntime, _FakeBroadcast, _FakeAvatar]:
    bc = _FakeBroadcast()
    avatar = _FakeAvatar()
    return (
        PresenceRuntime(
            policy=kw.pop("policy", AttentionPolicy(cooldown_s=0)),
            broadcast=bc,
            avatar_getter=lambda: avatar,
            idle_trigger_s=kw.pop("idle_trigger_s", 0.0),
            **kw,
        ),
        bc,
        avatar,
    )


@pytest.mark.asyncio
async def test_task_completed_produces_bubble() -> None:
    rt, bc, _ = _rt()
    await rt.on_event(_FakeEvent("task.completed", {"goal": "整理下载文件夹"}))
    assert len(bc.sent) == 1
    msg = bc.sent[0]
    assert msg["type"] == "proactive:intent"
    assert "整理下载文件夹" in msg["text"]
    assert msg["channel"] == "bubble"
    assert msg["urgency"] == "normal"
    assert msg["reason"] == "task_done"
    assert rt.state()["counters"]["delivered"] == 1


@pytest.mark.asyncio
async def test_task_failed_uses_comfort_performance() -> None:
    rt, bc, avatar = _rt()
    await rt.on_event(_FakeEvent("task.failed", {"goal": "写报告"}))
    assert bc.sent[0]["performance"] == "comfort"
    assert avatar.performed == [("s1", "comfort")]


@pytest.mark.asyncio
async def test_cooldown_blocks_second_intent() -> None:
    rt, bc, _ = _rt(policy=AttentionPolicy(cooldown_s=900))
    d1 = await rt.submit(ProactiveIntent(text="一", reason="t1"))
    d2 = await rt.submit(ProactiveIntent(text="二", reason="t2"))
    assert d1.act is True
    assert d2.act is False
    assert len(bc.sent) == 1
    assert rt.state()["counters"]["suppressed"] == 1


@pytest.mark.asyncio
async def test_activity_event_resets_idle() -> None:
    rt, _, _ = _rt(idle_trigger_s=0.05)
    await rt.on_event(_FakeEvent("session.started"))
    assert await rt.check_idle() is None  # 刚活跃 → 不触发
    rt._last_activity = time.monotonic() - 10  # 模拟空闲
    d = await rt.check_idle()
    assert d is not None and d.act is True
    # 同一段空闲只提一次
    assert await rt.check_idle() is None


@pytest.mark.asyncio
async def test_idle_greet_uses_greet_performance() -> None:
    rt, bc, avatar = _rt(idle_trigger_s=0.05)
    rt._last_activity = time.monotonic() - 10
    await rt.check_idle()
    assert bc.sent[0]["text"] == "回来啦。"
    assert avatar.performed == [("", "greet")]


@pytest.mark.asyncio
async def test_disabled_idle_trigger() -> None:
    rt, bc, _ = _rt(idle_trigger_s=0.0)
    rt._last_activity = time.monotonic() - 9999
    assert await rt.check_idle() is None
    assert bc.sent == []


@pytest.mark.asyncio
async def test_broadcast_failure_is_contained() -> None:
    async def _boom(payload: dict) -> None:
        raise RuntimeError("ws down")

    rt = PresenceRuntime(policy=AttentionPolicy(cooldown_s=0), broadcast=_boom)
    d = await rt.submit(ProactiveIntent(text="x", reason="t"))
    assert d.act is True  # 交付失败不影响裁决结果
    assert rt.state()["counters"]["delivered"] == 1


@pytest.mark.asyncio
async def test_disabled_when_quiet(monkeypatch) -> None:
    monkeypatch.setattr(
        "yuiro.presence.attention.AttentionPolicy.quiet_now", lambda self, now=None: True
    )
    rt, bc, _ = _rt(policy=AttentionPolicy(cooldown_s=0, quiet_hours="23:00-08:00"))
    d = await rt.submit(ProactiveIntent(text="x", reason="t", urgency=Urgency.NORMAL))
    assert d.act is False
    assert bc.sent == []
    assert rt.state()["quiet_now"] is True


def test_intent_payload_shape() -> None:
    intent = ProactiveIntent(
        text="嗨", reason="idle_return", urgency=Urgency.LOW, performance="greet", session_id="s1"
    )
    payload = json.loads(json.dumps(intent.to_payload()))
    assert payload["channel"] == "bubble"
    assert payload["urgency"] == "low"
    assert payload["performance"] == "greet"
    assert payload["session_id"] == "s1"
