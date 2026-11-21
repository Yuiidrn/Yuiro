import pytest

from yuiro.avatar.intent import AvatarIntent, AvatarPriority
from yuiro.avatar.runtime import AvatarRuntime


@pytest.mark.asyncio
async def test_actual_duration_receipt_and_stale_completion():
    runtime = AvatarRuntime()
    first = AvatarIntent(source='agent', session_id='one', priority=AvatarPriority.ACTION,
                         duration_ms=1000)
    await runtime._apply(first)
    assert runtime.playback_receipt('one', first.intent_id, 'started', 5000)
    assert runtime.current('one').duration_ms == 5000
    second = AvatarIntent(source='agent', session_id='one', priority=AvatarPriority.ACTION,
                          duration_ms=2000)
    await runtime._apply(second)
    assert not runtime.playback_receipt('one', first.intent_id, 'finished')
    assert not runtime.playback_receipt('other', second.intent_id, 'finished')
    assert runtime.current('one') is second
    assert runtime.playback_receipt('one', second.intent_id, 'finished')
    assert runtime.current('one') is None


@pytest.mark.asyncio
async def test_receipt_limits_and_persistent_emotion():
    runtime = AvatarRuntime()
    intent = AvatarIntent(source='emotion', session_id='one')
    await runtime._apply(intent)
    assert not runtime.playback_receipt('one', intent.intent_id, 'started', 200)
    assert runtime.current('one') is intent
    assert runtime.playback_receipt('one', intent.intent_id, 'cancelled')
    action = AvatarIntent(source='agent', session_id='one', duration_ms=200)
    await runtime._apply(action)
    assert runtime.playback_receipt('one', action.intent_id, 'started', 999999)
    assert action.duration_ms == 60000


@pytest.mark.asyncio
async def test_agent_duplicate_performance_is_coalesced_until_finished():
    runtime = AvatarRuntime()
    assert await runtime.perform('one', 'greet')
    first = runtime.current('one')
    assert not await runtime.perform('one', 'greet')
    assert runtime.current('one') is first
    assert runtime.playback_receipt('one', first.intent_id, 'finished')
    assert await runtime.perform('one', 'greet')
    assert await runtime.perform('one', 'comfort')  # 新语义仍可接管，不冻结整个表演入口。
