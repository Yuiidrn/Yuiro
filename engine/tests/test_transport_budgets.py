import ast
import asyncio
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_production_chat_admission_rejects_full_without_blocking_control():
    tree = ast.parse(Path('yuiro/main.py').read_text(encoding='utf-8'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                and n.name == 'admit_chat')
    frames = []

    class WS:
        async def send_json(self, frame):
            frames.append(frame)

    queue = asyncio.Queue(maxsize=4)
    scope = {'asyncio': asyncio, 'chat_queue': queue, 'control_epoch': 0, 'ws': WS()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'production admit', 'exec'), scope)  # noqa: S102
    for i in range(5):
        await asyncio.wait_for(scope['admit_chat']({'text': str(i)}), 1)
    assert queue.qsize() == 4 and frames[0]['type'] == 'chat:busy'


@pytest.mark.asyncio
async def test_pcm_rejects_oversize_and_backlog_without_silent_frame_loss():
    tree = ast.parse(Path('yuiro/main.py').read_text(encoding='utf-8'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                and n.name == 'admit_pcm')
    closes = []

    class WS:
        async def close(self, **kwargs):
            closes.append(kwargs['code'])

    queue = asyncio.Queue(maxsize=32)
    scope = {'asyncio': asyncio, 'pcm_queue': queue, 'ws': WS(), 'session_id': 's',
             'vlog': lambda *args: None}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'production pcm', 'exec'), scope)  # noqa: S102
    assert not await scope['admit_pcm'](b'a' * 64001)
    for _ in range(32):
        assert await scope['admit_pcm'](b'a')
    assert not await scope['admit_pcm'](b'b')
    assert closes == [1009, 1013] and queue.qsize() == 32
