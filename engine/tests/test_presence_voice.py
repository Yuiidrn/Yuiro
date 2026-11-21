"""S22 测试：Presence 深化（voice 通道 / 系统事件入口 / Intervention quality）。

补 S20 的三项遗留：
1. ``Channel.VOICE`` 真正出声（不再一律降级为气泡）；
2. ``system.*`` 事件通用入口（spec 的「Build completed → 刚编译成功了」）；
3. Intervention quality（主动表达后用户是否响应 → 近似"有用率"）。
"""
from __future__ import annotations

import asyncio
import time

import pytest

from yuiro.presence import AttentionPolicy, Channel, PresenceRuntime, ProactiveIntent, Urgency


class _FakeBroadcast:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def __call__(self, payload: dict) -> None:
        self.sent.append(payload)


class _Spoken:
    """记录主动说话调用（模拟 voice_speaker）。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    async def __call__(self, session_id: str, text: str) -> None:
        if self.fail:
            raise RuntimeError("tts down")
        self.calls.append((session_id, text))


class _Event:
    def __init__(self, type_: str, payload: dict | None = None, session_id: str = "s1") -> None:
        self.type = type_
        self.payload = payload or {}
        self.session_id = session_id


def _rt(**kw) -> tuple[PresenceRuntime, _FakeBroadcast]:
    bc = _FakeBroadcast()
    policy = kw.pop("policy", AttentionPolicy(cooldown_s=0, max_urgency=Urgency.HIGH))
    return (
        PresenceRuntime(policy=policy, broadcast=bc, idle_trigger_s=0.0, **kw),
        bc,
    )


# ── voice 通道 ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_voice_channel_speaks() -> None:
    """HIGH urgency 才允许真正出声（NORMAL 会被"用户活跃"降级为气泡，见 S20）。"""
    spoken = _Spoken()
    rt, bc = _rt(voice_speaker=spoken)
    d = await rt.submit(
        ProactiveIntent(
            text="刚编译成功了。",
            reason="system.build",
            channel=Channel.VOICE,
            urgency=Urgency.HIGH,
        )
    )
    assert d.act is True
    assert spoken.calls == [("", "刚编译成功了。")]
    # 气泡同样送达（内容不丢：听到也看得到）
    assert bc.sent[0]["channel"] == "voice"


@pytest.mark.asyncio
async def test_voice_failure_falls_back_to_bubble() -> None:
    rt, bc = _rt(voice_speaker=_Spoken(fail=True))
    d = await rt.submit(
        ProactiveIntent(text="想说但设备忙", reason="t", channel=Channel.VOICE)
    )
    assert d.act is True  # 出声失败不影响交付（气泡已发）
    assert len(bc.sent) == 1


@pytest.mark.asyncio
async def test_voice_without_speaker_is_bubble_only() -> None:
    rt, bc = _rt()
    d = await rt.submit(ProactiveIntent(text="x", reason="t", channel=Channel.VOICE))
    assert d.act is True
    assert len(bc.sent) == 1


# ── 系统事件入口 ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_system_event_produces_intent() -> None:
    rt, bc = _rt()
    await rt.on_event(_Event("system.build_finished", {"hint": "欸，刚刚编译成功了。"}))
    assert len(bc.sent) == 1
    assert bc.sent[0]["text"] == "欸，刚刚编译成功了。"
    assert bc.sent[0]["reason"] == "system.build_finished"


@pytest.mark.asyncio
async def test_system_event_without_hint_is_ignored() -> None:
    rt, bc = _rt()
    await rt.on_event(_Event("system.something", {"other": 1}))
    assert bc.sent == []


@pytest.mark.asyncio
async def test_system_event_respects_urgency_field() -> None:
    """事件的 urgency/channel 能被策略正确降级（想说"出声"→ 只给气泡）。"""
    rt, bc = _rt(policy=AttentionPolicy(cooldown_s=0, max_urgency=Urgency.LOW))
    await rt.on_event(
        _Event(
            "system.alert",
            {"hint": "注意！", "urgency": "high", "channel": "voice"},
        )
    )
    assert bc.sent[0]["channel"] == "bubble"  # 降级为气泡
    assert rt.state()["counters"]["downgraded"] == 1


@pytest.mark.asyncio
async def test_system_event_bubble_intent_is_not_downgraded() -> None:
    """本来就是气泡的 intent 无需降级（避免"降级了个寂寞"）。"""
    rt, bc = _rt(policy=AttentionPolicy(cooldown_s=0, max_urgency=Urgency.LOW))
    await rt.on_event(_Event("system.alert", {"hint": "注意！", "urgency": "high"}))
    assert bc.sent[0]["channel"] == "bubble"
    assert rt.state()["counters"]["downgraded"] == 0


# ── Intervention quality ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_responded_counted_when_user_replies_within_window() -> None:
    rt, _ = _rt(respond_window_s=120)
    await rt.submit(ProactiveIntent(text="回来啦。", reason="idle_return"))
    rt.note_user_activity()  # 用户立刻回应
    quality = rt.state()["intervention_quality"]
    assert quality == {"delivered": 1, "responded": 1, "useful_rate": 1.0}


@pytest.mark.asyncio
async def test_no_response_outside_window() -> None:
    rt, _ = _rt(respond_window_s=0.01)
    await rt.submit(ProactiveIntent(text="回来啦。", reason="idle_return"))
    rt._pending_response = time.monotonic() - 5  # 模拟用户很久以后才说话
    rt.note_user_activity()
    quality = rt.state()["intervention_quality"]
    assert quality["delivered"] == 1
    assert quality["responded"] == 0
    assert quality["useful_rate"] == 0.0


@pytest.mark.asyncio
async def test_useful_rate_zero_without_delivery() -> None:
    rt, _ = _rt()
    assert rt.state()["intervention_quality"]["useful_rate"] == 0.0


# ── VoicePipeline.speak_text 边界 ─────────────────────────────────────────
def test_speak_text_skips_empty_and_busy() -> None:
    from yuiro.audio import VoicePipeline

    pipe = object.__new__(VoicePipeline)  # 仅测边界分支，不构造完整管线
    pipe._speaking = {"s1": True}
    pipe._speak_tasks = {}
    assert asyncio.run(pipe.speak_text("s1", "嗨")) is False  # 正在说话 → 跳过
    assert asyncio.run(pipe.speak_text("s1", "   ")) is False  # 空文本
