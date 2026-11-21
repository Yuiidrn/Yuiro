"""测试生产事件转发边界，不加载真实引擎或请求供应商。"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from yuiro import approval


def boundary(monkeypatch, avatar=None):
    sent = []
    session = SimpleNamespace(generation=4)
    state = SimpleNamespace(avatar=avatar, app_config=SimpleNamespace(_character_id='hotaru'))
    state.sessions = SimpleNamespace(get=lambda sid: session)

    class Socket:
        async def send_json(self, message):
            sent.append(message)

    monkeypatch.setattr(approval, 'get_audio_conn', lambda sid: Socket())
    node = next(n for n in ast.parse(Path('yuiro/main.py').read_text(encoding='utf-8')).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == '_emit_event')
    scope = {'app': SimpleNamespace(state=state)}
    # 只执行本仓库被审查的生产函数，避免导入main启动真实服务。
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'production _emit_event', 'exec'), scope)  # noqa: S102
    return scope['_emit_event'], state, session, sent


@pytest.mark.asyncio
async def test_normal_state_carries_authoritative_identity(monkeypatch):
    emit, _, _, sent = boundary(monkeypatch)
    await emit('s', 'tts:end', {'session_id':'foreign', 'generation':99, 'character_id':'wrong'})
    assert sent == [{'type':'tts:end', 'session_id':'s', 'generation':4, 'character_id':'hotaru'}]


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['generation', 'character', 'session'])
async def test_state_waiting_for_avatar_cannot_cross_identity_boundary(monkeypatch, change):
    entered, release = asyncio.Event(), asyncio.Event()

    class Avatar:
        async def push_emotion(self, *args):
            entered.set()
            await release.wait()

    emit, state, session, sent = boundary(monkeypatch, Avatar())
    task = asyncio.create_task(emit('s', 'llm:start', {}))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if change == 'generation':
            session.generation += 1
        elif change == 'character':
            state.app_config._character_id = 'hiyori'
        else:
            state.sessions.get = lambda sid: SimpleNamespace(generation=4)
        release.set()
        await asyncio.wait_for(task, 1)
        assert sent == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_missing_session_never_forwards_state(monkeypatch):
    emit, state, _, sent = boundary(monkeypatch)
    state.sessions.get = lambda sid: None
    await emit('s', 'tts:interrupted', {})
    assert sent == []
