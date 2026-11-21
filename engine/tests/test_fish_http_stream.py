import asyncio
import io
import struct
import wave

import httpx
import pytest

from yuiro.audio import AudioSegment, TTSTaskManager
from yuiro.audio.fish import FishAudioProvider
from yuiro.audio.wav_stream import WavStreamSplitter


def wav_data(samples=32000):
    out = io.BytesIO()
    pcm = b''.join(struct.pack('<h', (i % 4000)-2000) for i in range(samples))
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm)
    return out.getvalue(), pcm


@pytest.mark.parametrize('fragment', [1, 3, 31, 7777, 100000])
def test_network_fragmentation_preserves_every_pcm_sample(fragment):
    raw, pcm = wav_data()
    splitter = WavStreamSplitter()
    chunks = []
    for start in range(0, len(raw), fragment):
        chunks.extend(splitter.feed(raw[start:start+fragment]))
    chunks.extend(splitter.finish())
    decoded = []
    for chunk in chunks:
        with wave.open(io.BytesIO(chunk)) as audio:
            assert audio.getframerate() == 16000
            decoded.append(audio.readframes(audio.getnframes()))
    assert b''.join(decoded) == pcm
    assert len(chunks) > 1


def test_placeholder_header_and_unknown_metadata_are_supported():
    raw, pcm = wav_data()
    raw = raw[:36] + b'JUNK' + struct.pack('<I', 3) + b'abc\0' + raw[36:]
    raw = bytearray(raw)
    struct.pack_into('<I', raw, 4, 0xFFFFFFFF)
    struct.pack_into('<I', raw, 52, 0xFFFFFFFF)
    splitter = WavStreamSplitter()
    chunks = splitter.feed(raw) + splitter.finish()
    assert b''.join(c[44:] for c in chunks) == pcm


def test_truncated_or_unsupported_audio_fails_without_padding():
    raw, _ = wav_data()
    splitter = WavStreamSplitter()
    splitter.feed(raw[:-1])
    with pytest.raises(ValueError, match='截断'):
        splitter.finish()
    raw = bytearray(raw)
    struct.pack_into('<H', raw, 20, 3)  # float32容器不能误当PCM16。
    with pytest.raises(ValueError, match='PCM16'):
        WavStreamSplitter().feed(raw)


@pytest.mark.asyncio
async def test_first_audio_before_http_eof_and_cancel_closes_response(monkeypatch):
    raw, _ = wav_data()
    gate, closed = asyncio.Event(), asyncio.Event()
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw[:18000]
            await gate.wait()
            yield raw[18000:]

        async def aclose(self):
            closed.set()

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(
        **kw, transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Body()))))
    provider = FishAudioProvider(reference_id='hotaru', key_loader=lambda: 'fixture')
    stream = provider.synthesize_stream('你好。')
    first = await asyncio.wait_for(anext(stream), 1)
    assert first.streaming and first.stream_id and first.volumes and not gate.is_set()
    await stream.aclose()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_manager_streams_subchunks_and_keeps_sentence_order():
    gate = asyncio.Event()
    class Provider:
        async def synthesize_stream(self, text):
            yield AudioSegment(wav=(text+'a').encode(), sample_rate=24000, volumes=[])
            if text == 'first':
                await gate.wait()
            yield AudioSegment(wav=(text+'b').encode(), sample_rate=24000, volumes=[])

    manager = TTSTaskManager(Provider())
    first = asyncio.create_task(manager.enqueue(1, 'first'))
    second = asyncio.create_task(manager.enqueue(2, 'second'))
    try:
        assert (await asyncio.wait_for(manager.wait_next(), 1)).wav == b'firsta'
        gate.set()
        await asyncio.gather(first, second)
        await manager.finish()
        assert [(await manager.wait_next()).wav for _ in range(3)] == [b'firstb', b'seconda', b'secondb']
        assert await manager.wait_next() is None
    finally:
        gate.set()
        await asyncio.gather(first, second)


@pytest.mark.asyncio
async def test_cancelled_http_reader_releases_connection_and_propagates(monkeypatch):
    entered, closed = asyncio.Event(), asyncio.Event()
    raw, _ = wav_data()
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw[:18000]
            entered.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(
        **kw, transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=Body()))))
    provider = FishAudioProvider(reference_id='id', key_loader=lambda: 'fixture')
    async def consume():
        async for _ in provider.synthesize_stream('你好。'):
            pass
    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
