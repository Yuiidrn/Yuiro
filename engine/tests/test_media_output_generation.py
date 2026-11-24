"""新媒体意图推进代际，避免停播准入误拦新确认；不调用真实媒体后端。"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('official', [False, True])
async def test_media_play_is_new_generation_before_its_output(monkeypatch, official):
    from yuiro.netease import official_client

    generation, spoken = [5], []

    def next_generation():
        generation[0] += 1

    async def release():
        pass

    async def direct(item):
        assert generation[0] == 6
        return True, '测试确认'

    async def official_reply(*args):
        assert generation[0] == 6

    async def render(text):
        return text

    async def speak(*args, **kwargs):
        spoken.append(kwargs['generation'])

    class WS:
        async def send_json(self, frame):
            pass

    monkeypatch.setattr(official_client, 'release', release)
    tree = ast.parse(Path('yuiro/main.py').read_text(encoding='utf-8'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                and n.name == 'chat_worker')
    queue = asyncio.Queue()
    await queue.put({'type':'media:play','backend':'netease_client' if official else 'builtin'})
    await queue.put(None)
    gate = asyncio.Event()
    gate.set()
    tasks = {}
    scope = {'asyncio':asyncio,'chat_queue':queue,'control_gate':gate,'control_epoch':0,
             'session':SimpleNamespace(next_generation=next_generation),
             'session_id':'s','ws':WS(),'_reply_speak_tasks':tasks,
             '_media_identity':lambda sid: ('role',1,'s'),
             '_direct_media_play':direct,'_reply_official_media':official_reply,
             '_render_display_text':render,'_speak_reply':speak,
             '_avatar_generation':lambda sid:generation[0],'vlog':lambda *args:None}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'production media worker', 'exec'), scope)  # noqa: S102
    await scope['chat_worker']()
    await asyncio.gather(*tasks.values())
    assert generation[0] == 6
    assert spoken == ([] if official else [6])
