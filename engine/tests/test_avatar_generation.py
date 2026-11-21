import pytest
from yuiro.avatar.intent import AvatarIntent, AvatarPriority
from yuiro.avatar.runtime import AvatarRuntime


@pytest.mark.asyncio
async def test_avatar_uses_authoritative_generation_and_rejects_stale():
    generation = {'s': 3}
    sent = []

    async def broadcast(payload):
        sent.append(payload)

    avatar = AvatarRuntime(generation_getter=generation.get, broadcast=broadcast)
    assert await avatar.push_emotion('s', 'happy')
    assert sent[-1]['generation'] == 3
    generation['s'] = 4
    old = AvatarIntent(source='agent', session_id='s', generation=3)
    assert not await avatar._apply(old)
    assert len(sent) == 1
    assert not await avatar.push_emotion('missing', 'happy')
    assert await avatar.push_emotion('', 'happy')  # 全局基础情绪不属于某个回合。


@pytest.mark.asyncio
async def test_new_generation_does_not_wait_for_old_action_lease():
    generation = {'s': 1}
    avatar = AvatarRuntime(generation_getter=generation.get)
    assert await avatar._apply(AvatarIntent(source='agent', session_id='s',
                                           priority=AvatarPriority.ACTION, duration_ms=60000))
    generation['s'] = 2
    assert await avatar.push_emotion('s', 'thinking')
    assert avatar.current('s').generation == 2


@pytest.mark.asyncio
async def test_character_factory_keeps_generation_binding(monkeypatch, tmp_path):
    import copy
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import yuiro.main as main

    cfg = copy.deepcopy(main.app_config)
    cfg.persona.model_path = '/live2d/Hotaru Shiomi/016_casual_spring_01/016_casual_spring_01.model3.json'
    cfg.memory.db_path = str(tmp_path / 'isolated.db')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, '_character_cache', {})
    monkeypatch.setattr(main, '_character_snapshot', lambda: {})
    monkeypatch.setattr(main, '_build_memory', lambda *a, **k: SimpleNamespace(tidy=AsyncMock()))
    monkeypatch.setattr(main, '_build_renderer', lambda *a: None)
    monkeypatch.setattr(main.app.state, 'sessions', SimpleNamespace(
        get=lambda sid: SimpleNamespace(generation=7) if sid == 'test' else None))
    bundle = await main._prepare_character('test-role', cfg)
    avatar = bundle['avatar']
    assert avatar._generation_getter('test') == 7
    assert avatar._generation_getter('gone') is None
