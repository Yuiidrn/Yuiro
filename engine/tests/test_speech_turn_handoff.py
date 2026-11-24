"""生产输出交接与统一取消函数：真实管线，无麦克风/云端请求。"""
import ast
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from yuiro.audio import VoicePipeline
from yuiro.runtime.adapters import SpeechRuntimeAdapter
from yuiro.runtime.contract import RuntimeRegistry
from yuiro.runtime.session import SessionManager


def production(pipe, tasks, **state):
    tree = ast.parse(Path('yuiro/main.py').read_text(encoding='utf-8'))
    names = {'_cancel_reply_speech', '_prepare_text_turn', '_cancel_turn', '_start_preconnected_reply'}
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name in names]
    scope = {'asyncio':asyncio, '_reply_speak_tasks':tasks, '_reply_agent_tasks': {},
             'app':SimpleNamespace(state=SimpleNamespace(voice_pipeline=pipe, **state)),
             'AgentEvent':lambda **kwargs:kwargs, 'vlog':lambda *args:None}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'production handoff', 'exec'), scope)  # noqa: S102
    return scope


@pytest.mark.asyncio
async def test_text_entry_joins_old_voice_and_reply_before_new_agent():
    started, voice_closed, reply_closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    events = []

    class TTS:
        async def synthesize_segment(self, text):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                voice_closed.set()

    async def emit(sid, kind, payload):
        events.append(kind)

    async def reply():
        try:
            await asyncio.Event().wait()
        finally:
            reply_closed.set()

    pipe = VoicePipeline(tts=TTS(), event_callback=emit)
    assert await pipe.speak_text('s', '旧主动发言')
    await asyncio.wait_for(started.wait(), 1)
    old_reply = asyncio.create_task(reply())
    other = asyncio.create_task(asyncio.Event().wait())
    await asyncio.sleep(0)
    tasks = {'s':old_reply, 'other':other}
    scope = production(pipe, tasks)
    try:
        await asyncio.wait_for(scope['_prepare_text_turn']('s'), 1)
        assert voice_closed.is_set() and reply_closed.is_set()
        assert events[-1] == 'tts:interrupted'
        assert not pipe._speaking['s'] and not pipe._asr_locked['s']
        assert 's' not in tasks and tasks['other'] is other and not other.done()
    finally:
        other.cancel()
        await asyncio.gather(other, old_reply, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('registered', [False, True])
async def test_unified_cancel_stops_reply_and_dispatches_voice_before_joining(registered):
    stopping, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    events = []

    async def reply():
        try:
            await asyncio.Event().wait()
        finally:
            stopping.set()
            await release.wait()
            closed.set()

    class Pipe:
        def interrupt(self, sid):
            events.append('voice-stop')

    async def publish(event):
        events.append(event['type'])

    sessions = SessionManager()
    session = sessions.attach_control(object())
    old = asyncio.create_task(reply())
    await asyncio.sleep(0)
    pipe = Pipe()
    registry = RuntimeRegistry()
    registry.register(SpeechRuntimeAdapter(pipe))
    scope = production(pipe, {session.session_id:old}, sessions=sessions,
                       events=SimpleNamespace(publish=publish),
                       runtimes=registry if registered else None)
    task = asyncio.create_task(scope['_cancel_turn'](session.session_id, 'fixture'))
    try:
        await asyncio.wait_for(stopping.wait(), 1)
        assert events == ['voice-stop'] and not task.done()
        assert session.generation == 1
        release.set()
        await asyncio.wait_for(task, 1)
        assert closed.is_set() and events[-1] == 'session.cancelled'
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, old, return_exceptions=True)


@pytest.mark.asyncio
async def test_handoff_parent_cancel_propagates_and_cleans_notification():
    entered, closed = asyncio.Event(), asyncio.Event()

    class Pipe:
        def interrupt(self, sid):
            async def notify():
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    closed.set()
            return asyncio.create_task(notify())

    scope = production(Pipe(), {})
    task = asyncio.create_task(scope['_prepare_text_turn']('s'))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize('stream_reply', [False, True])
@pytest.mark.parametrize('invalidate_before_start', [False, True])
async def test_real_chat_worker_waits_for_speech_handoff_before_agent(stream_reply, invalidate_before_start):
    tree = ast.parse(Path('yuiro/main.py').read_text(encoding='utf-8'))
    worker = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == 'chat_worker')
    entered, release, agent_started = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Pipe:
        def interrupt(self, sid):
            async def notify():
                entered.set()
                await release.wait()
            return asyncio.create_task(notify())

    async def agent(*args, **kwargs):
        assert callable(kwargs['on_sentence']) is stream_reply
        agent_started.set()
        raise asyncio.CancelledError()  # 停在真实Agent调用边界，不请求供应商。

    queue = asyncio.Queue()
    await queue.put({'type':'chat:user', 'text':'你好', 'stream_reply':stream_reply})
    scope = production(Pipe(), {}, agent_loop=SimpleNamespace(_llm=None))
    gate = asyncio.Event()
    gate.set()
    scope.update(chat_queue=queue, control_gate=gate, control_epoch=0, session_id='s', session=object(), ws=object(), time=time,
                 _agent_reply=agent, log_ring=SimpleNamespace(emit=lambda *args:None),
                 TraceContext=lambda **kwargs:SimpleNamespace(mark=lambda *args:None))
    exec(compile(ast.Module(body=[worker], type_ignores=[]), 'production chat_worker', 'exec'), scope)  # noqa: S102
    task = asyncio.create_task(scope['chat_worker']())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert not agent_started.is_set()
        if invalidate_before_start:
            scope['control_epoch'] = 1
        release.set()
        if invalidate_before_start:
            for _ in range(20):
                await asyncio.sleep(0)
            assert not agent_started.is_set(), '交接期间取消后，已取出的旧请求也不能启动'
            await queue.put({'type':'chat:user','text':'新请求','stream_reply':stream_reply,
                             '_queue_epoch':1})
        await asyncio.wait_for(agent_started.wait(), 1)
        await asyncio.sleep(0)
        assert not task.done(), '单轮取消不能杀掉处理后续聊天的worker'
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert agent_started.is_set()
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
