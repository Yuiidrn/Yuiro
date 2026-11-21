"""S14：AvatarIntent 动作通道（motion / push_action / 优先级）。"""
from __future__ import annotations

import pytest

from yuiro.avatar import AvatarIntent, AvatarPriority, AvatarRuntime


def test_intent_motion_payload() -> None:
    it = AvatarIntent(source="agent", motion="TapBody", motion_index=2)
    p = it.to_payload()
    assert p["motion"] == "TapBody"
    assert p["motion_index"] == 2
    # 不带索引时 payload 不含 motion_index
    it2 = AvatarIntent(source="agent", motion="TapBody")
    assert "motion_index" not in it2.to_payload()


@pytest.mark.asyncio
async def test_push_action_broadcasts() -> None:
    sent: list[dict] = []

    async def bc(msg: dict) -> None:
        sent.append(msg)

    rt = AvatarRuntime(expression_map={}, broadcast=bc)
    assert await rt.push_action("s1", "TapBody", 3) is True
    assert sent[-1]["type"] == "avatar:intent"
    assert sent[-1]["motion"] == "TapBody"
    assert sent[-1]["motion_index"] == 3
    assert sent[-1]["priority"] == int(AvatarPriority.ACTION)


@pytest.mark.asyncio
async def test_action_does_not_override_user() -> None:
    sent: list[dict] = []

    async def bc(msg: dict) -> None:
        sent.append(msg)

    rt = AvatarRuntime(expression_map={}, broadcast=bc)
    await rt._apply(
        AvatarIntent(source="user", priority=AvatarPriority.USER, session_id="s")
    )
    # ACTION(3) < USER(4) → 不覆盖
    assert await rt.push_action("s", "TapBody") is False
    assert len(sent) == 1
