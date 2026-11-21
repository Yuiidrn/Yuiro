"""真实VoicePipeline的任务入口身份，外部线程/翻译延迟返回也不能重新认领新epoch。"""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from yuiro.audio import VoicePipeline


@pytest.mark.asyncio
@pytest.mark.parametrize('result', ['你好', '', RuntimeError('fixture failure')])
async def test_asr_return_after_interrupt_cannot_write_successor_state(result):
    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), threading.Event()
    events, llm_calls = [], []

    class ASR:
        def transcribe(self, audio):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(3)
            if isinstance(result, Exception):
                raise result
            return result

    async def emit(sid, kind, payload):
        events.append(kind)

    async def llm(text, sid):
        llm_calls.append(text)
        return ''

    pipe = VoicePipeline(asr=ASR(), llm_callback=llm, event_callback=emit)
    pipe._audio['s'] = [b'\0\0' * 8000]
    task = asyncio.create_task(pipe.on_speech_end('s'))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        pipe.interrupt('s')
        pipe._speaking['s'] = True  # 后继任务已取得状态所有权。
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert pipe._speaking['s']
        assert llm_calls == []
        assert not any(kind in events for kind in ['asr:text', 'asr:error', 'asr:dropped', 'llm:start'])
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_display_translation_after_interrupt_does_not_start_old_tts():
    entered, release = asyncio.Event(), asyncio.Event()
    events, played = [], []

    class Renderer:
        async def render_display(self, text):
            entered.set()
            await release.wait()
            return text

    async def emit(sid, kind, payload):
        events.append(kind)

    async def llm(text, sid):
        return '你好。'

    async def play(sid, segment):
        played.append(segment)

    pipe = VoicePipeline(asr=SimpleNamespace(transcribe=lambda audio:'你好'),
                         llm_callback=llm, event_callback=emit, play_callback=play,
                         renderer=Renderer())
    pipe._audio['s'] = [b'\0\0' * 8000]
    task = asyncio.create_task(pipe.on_speech_end('s'))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        pipe.interrupt('s')
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert 'llm:text' not in events and 'tts:start' not in events
        assert played == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_deferred_interrupt_captures_epoch_when_scheduled():
    events = []

    async def emit(sid, kind, payload):
        events.append(kind)

    pipe = VoicePipeline(event_callback=emit)
    pipe.interrupt('s')
    pipe.interrupt('s')
    for _ in range(3):
        await asyncio.sleep(0)
    assert events == ['tts:interrupted']


@pytest.mark.asyncio
@pytest.mark.parametrize('replace', [False, True])
async def test_delayed_trace_cleanup_only_owns_original_trace(replace):
    emitted = []
    pipe = VoicePipeline()
    original = SimpleNamespace(emit=lambda: emitted.append('original'))
    successor = SimpleNamespace(emit=lambda: emitted.append('successor'))
    pipe._traces['s'] = original
    task = asyncio.create_task(pipe._finalize_trace('s', delay=0, trace=original))
    await asyncio.sleep(0)
    if replace:
        pipe._traces['s'] = successor
    await task
    if replace:
        assert pipe._traces['s'] is successor and emitted == []
    else:
        assert 's' not in pipe._traces and emitted == ['original']
