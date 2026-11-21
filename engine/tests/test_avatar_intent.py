"""S05：AvatarIntent / AvatarRuntime（表情通道）。

对应 docs/plan/S05-avatar-intent.md。
"""
from __future__ import annotations

import pytest

from yuiro.avatar import AvatarIntent, AvatarPriority, AvatarRuntime


@pytest.mark.asyncio
async def test_push_emotion_maps_expression_and_broadcasts() -> None:
    sent: list[dict] = []

    async def bc(msg: dict) -> None:
        sent.append(msg)

    rt = AvatarRuntime(expression_map={"happy": "expression2"}, broadcast=bc)
    ok = await rt.push_emotion("s1", "happy")
    assert ok is True
    assert sent and sent[0]["type"] == "avatar:intent"
    assert sent[0]["expression"] == "expression2"
    assert sent[0]["emotion"] == "happy"
    assert sent[0]["priority"] == int(AvatarPriority.EMOTION)


@pytest.mark.asyncio
async def test_unknown_emotion_falls_back_to_reset() -> None:
    """未映射的情绪 → expression="" （前端 reset 语义），不抛错。"""
    sent: list[dict] = []

    async def bc(msg: dict) -> None:
        sent.append(msg)

    rt = AvatarRuntime(expression_map={}, broadcast=bc)
    assert await rt.push_emotion("s", "nonexistent") is True
    assert sent[0]["expression"] == ""


@pytest.mark.asyncio
async def test_none_emotion_means_neutral() -> None:
    sent: list[dict] = []

    async def bc(msg: dict) -> None:
        sent.append(msg)

    rt = AvatarRuntime(expression_map={"neutral": ""}, broadcast=bc)
    await rt.push_emotion("s", None)
    assert sent[0]["emotion"] == "neutral"
    assert sent[0]["expression"] == ""


@pytest.mark.asyncio
async def test_lower_priority_does_not_override() -> None:
    """低优先级不覆盖当前更高优先级的意图（为 ACTION/USER 预留）。"""
    sent: list[dict] = []

    async def bc(msg: dict) -> None:
        sent.append(msg)

    rt = AvatarRuntime(expression_map={}, broadcast=bc)
    await rt._apply(
        AvatarIntent(
            source="user",
            emotion="touch",
            priority=AvatarPriority.USER,
            session_id="s",
        )
    )
    assert await rt.push_emotion("s", "happy") is False
    assert len(sent) == 1  # 只有 USER 那次被广播


@pytest.mark.asyncio
async def test_thinking_roundtrip_overrides_same_priority() -> None:
    """同级意图后者覆盖：thinking → 回落主情绪。"""
    sent: list[dict] = []

    async def bc(msg: dict) -> None:
        sent.append(msg)

    rt = AvatarRuntime(
        expression_map={"thinking": "expression7", "happy": "expression2"},
        broadcast=bc,
    )
    await rt.push_emotion("s", "thinking")
    await rt.push_emotion("s", "happy")
    assert [m["expression"] for m in sent] == ["expression7", "expression2"]
    assert rt.current("s") is not None


@pytest.mark.asyncio
async def test_no_broadcast_does_not_crash() -> None:
    """未配置 broadcast（纯记录模式）时正常返回。"""
    rt = AvatarRuntime(expression_map={"happy": "expression2"})
    assert await rt.push_emotion("s", "happy") is True
    assert rt.current("s") is not None


@pytest.mark.asyncio
async def test_broadcast_failure_is_swallowed() -> None:
    """广播异常不影响主链路（返回 False，不抛出）。"""

    async def bc(_msg: dict) -> None:
        raise RuntimeError("连接已断开")

    rt = AvatarRuntime(expression_map={"happy": "expression2"}, broadcast=bc)
    assert await rt.push_emotion("s", "happy") is False


def test_intent_payload_omits_empty_fields() -> None:
    it = AvatarIntent(source="emotion", emotion="happy", expression="expression2")
    p = it.to_payload()
    assert p["source"] == "emotion"
    assert p["expression"] == "expression2"
    assert "motion" not in p
    assert "duration_ms" not in p
    # expression 显式为空（reset 语义）时仍发送该字段
    it2 = AvatarIntent(source="emotion", emotion="neutral", expression="")
    assert it2.to_payload()["expression"] == ""
