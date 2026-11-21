"""生产WS单轮/VoicePipeline/文字出口，协议由假socket驱动。"""
import ast
import asyncio
import io
import wave
from pathlib import Path
from types import SimpleNamespace

import msgpack
import pytest
from test_reply_generation import harness

from yuiro.audio import VoicePipeline
from yuiro.audio.fish import FishAudioProvider
from yuiro.audio.fish_websocket import FishWebSocketSession


class Socket:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.pcm = b'\xe8\x03' * 25000

    async def send(self, packet):
        event = msgpack.unpackb(packet, raw=False)
        self.sent.append(event)
        if event['event'] == 'flush':
            await self.queue.put(msgpack.packb({'event': 'audio', 'audio': self.pcm[:123]}))
            await self.queue.put(msgpack.packb({'event': 'audio', 'audio': self.pcm[123:]}))
        elif event['event'] == 'stop':
            await self.queue.put(msgpack.packb({'event': 'finish', 'reason': 'stop'}))

    async def recv(self):
        return await self.queue.get()

    async def close(self):
        self.closed = True


def session(socket, **kwargs):
    async def connect(*args, **kw):
        return socket

    return FishWebSocketSession(key_loader=lambda: 'fixture', reference_id='test', model='s2.1-pro',
                               latency='balanced', speed=1, connector=connect, **kwargs)


@pytest.mark.asyncio
async def test_stream_before_input_complete_exact_pcm_and_single_identity():
    sock = Socket()
    ws = session(sock)
    release = asyncio.Event()

    async def texts():
        yield '第一句'
        await release.wait()
        yield '第二句'

    stream = ws.stream(texts())
    first = await asyncio.wait_for(anext(stream), 1)
    assert first.streaming and first.volumes and not release.is_set()
    release.set()
    rest = [s async for s in stream]
    assert b''.join(s.wav[44:] for s in [first, *rest]) == sock.pcm * 2
    assert len({s.stream_id for s in [first, *rest]}) == 1
    assert [s['text'] for s in sock.sent if s['event'] == 'text'] == ['第一句', '第二句']
    assert sock.closed
    await ws.close()


@pytest.mark.asyncio
async def test_close_pending_connection_cancels_and_joins():
    entered, ended = asyncio.Event(), asyncio.Event()

    async def connect(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    ws = FishWebSocketSession(key_loader=lambda: 'fixture', reference_id='t', model='s2.1-pro',
                             latency='balanced', speed=1, connector=connect)
    await entered.wait()
    await ws.close()
    await ws.close()
    assert ended.is_set() and ws._connection.done()


@pytest.mark.asyncio
async def test_cancel_stream_closes_input_writer_and_socket():
    sock = Socket()
    ws = session(sock)
    source_closed = asyncio.Event()

    async def texts():
        try:
            yield '第一句'
            await asyncio.Event().wait()
        finally:
            source_closed.set()

    stream = ws.stream(texts())
    await asyncio.wait_for(anext(stream), 1)
    await stream.aclose()
    assert source_closed.is_set() and sock.closed
    assert ws._writer.done() and ws._receiver.done()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['input', 'server', 'empty'])
async def test_failures_close_without_retry_or_hang(kind):
    sock = Socket()
    if kind == 'server':
        await sock.queue.put(msgpack.packb({'event': 'finish', 'reason': 'error'}))
    ws = session(sock)

    async def texts():
        if kind == 'input':
            raise ValueError('translation fixture')
        if kind == 'server':
            await asyncio.Event().wait()
        if False:
            yield ''

    async def consume():
        return [s async for s in ws.stream(texts())]

    with pytest.raises(RuntimeError):
        await asyncio.wait_for(consume(), 1)
    assert sock.closed
    assert sum(e['event'] == 'start' for e in sock.sent) <= 1


@pytest.mark.asyncio
async def test_voice_preconnects_before_sentence_and_translates_once(monkeypatch):
    sock, connected, first = Socket(), asyncio.Event(), asyncio.Event()
    text_ready, tail = asyncio.Event(), asyncio.Event()

    async def connect(*args, **kwargs):
        connected.set()
        return sock

    monkeypatch.setattr('websockets.connect', connect)
    provider = FishAudioProvider(reference_id='hotaru', key_loader=lambda: 'fixture', transport='websocket')
    rendered, played = [], []

    class Renderer:
        async def render_speak(self, text):
            rendered.append(text)
            return '訳:' + text

    async def play(sid, part):
        played.append(part)
        first.set()

    async def source():
        await text_ready.wait()
        yield '第一句。'
        await tail.wait()
        yield '第二句。'

    pipe = VoicePipeline(tts=provider, renderer=Renderer(), play_callback=play)
    task = asyncio.create_task(pipe._speak_stream('s', source()))
    try:
        await asyncio.wait_for(connected.wait(), 1)
        assert not any(e['event'] == 'text' for e in sock.sent)
        text_ready.set()
        await asyncio.wait_for(first.wait(), 1)
        assert rendered == ['第一句。'] and not tail.is_set()
        tail.set()
        await asyncio.wait_for(task, 2)
        assert rendered == ['第一句。', '第二句。']
        assert len({p.stream_id for p in played}) == 1 and sock.closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_text_reply_generation_change_closes_pending_translation(monkeypatch):
    sock = Socket()

    async def connect(*args, **kwargs):
        return sock

    monkeypatch.setattr('websockets.connect', connect)
    ns, generation, frames, ws = harness()
    ns['app'].state.voice_pipeline._tts = FishAudioProvider(
        reference_id='hotaru', key_loader=lambda: 'fixture', transport='websocket')
    ns['split_sentences'] = lambda text: ['第一句。', '第二句。']
    translating, release = asyncio.Event(), asyncio.Event()

    async def render(text):
        if text == '第二句。':
            translating.set()
            await release.wait()
        return '訳:' + text

    ns['_render_reply_sentence'] = render
    task = asyncio.create_task(ns['_speak_reply'](ws, 'session', '回复', generation=1))
    try:
        await asyncio.wait_for(translating.wait(), 1)
        for _ in range(100):
            if frames:
                break
            await asyncio.sleep(.001)
        assert frames and frames[0]['type'] == 'tts:reply_audio'
        generation['value'] = 2
        before = len(frames)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert len(frames) == before and sock.closed
        assert [e['text'] for e in sock.sent if e['event'] == 'text'] == ['訳:第一句。']
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel_before_start', [False, True])
async def test_text_preconnect_registered_for_existing_cancellation(cancel_before_start):
    opened, closed = [], []

    class Session:
        async def close(self):
            closed.append(True)

    class Provider:
        transport = 'websocket'
        _segment_streaming = True

        def open_sentence_session(self):
            opened.append(True)
            return Session()

    source = ast.parse(Path('yuiro/main.py').read_text(encoding='utf-8'))
    nodes = [n for n in source.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name in ('_start_preconnected_reply', '_cancel_reply_speech')]
    scope = {'asyncio': asyncio, '_reply_speak_tasks': {},
             'app': SimpleNamespace(state=SimpleNamespace(voice_pipeline=SimpleNamespace(_tts=Provider()),
                 app_config=SimpleNamespace(tts=SimpleNamespace(reply_tts_enabled=True))))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'production preconnect', 'exec'), scope)  # noqa: S102
    ready = scope['_start_preconnected_reply'](None, 's')
    assert ready is not None and 's' in scope['_reply_speak_tasks']
    if not cancel_before_start:
        await asyncio.sleep(0)
        assert opened and not ready.done()
    task = scope['_cancel_reply_speech']('s')
    await asyncio.gather(task, return_exceptions=True)
    assert len(closed) == len(opened)
    assert not opened if cancel_before_start else bool(closed)


@pytest.mark.asyncio
async def test_nonstream_websocket_provider_returns_complete_valid_wav(monkeypatch):
    sock = Socket()

    async def connect(*args, **kwargs):
        return sock

    monkeypatch.setattr('websockets.connect', connect)
    provider = FishAudioProvider(reference_id='hotaru', key_loader=lambda: 'fixture',
                                 transport='websocket', segment_streaming=False)
    assert provider.open_sentence_session() is None
    raw = await provider._synthesize_audio('测试')
    with wave.open(io.BytesIO(raw)) as audio:
        assert audio.getframerate() == 44100 and audio.getnframes() == len(sock.pcm) // 2
        assert audio.readframes(audio.getnframes()) == sock.pcm
    assert sock.closed
