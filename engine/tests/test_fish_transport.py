"""Fish共享连接池的请求隔离与释放，不请求供应商。"""
import asyncio
import json

import httpx
import pytest
from test_fish_http_stream import wav_data

from yuiro.audio.fish import FishAudioProvider
from yuiro.audio.fish_transport import close_fish_http_client, fish_http_client


@pytest.mark.asyncio
async def test_providers_share_only_transport_and_reload_key_per_request(monkeypatch):
    original = httpx.AsyncClient
    made, seen = [], []
    raw, _ = wav_data()

    def handler(request):
        seen.append((request.headers['authorization'], json.loads(request.content)['reference_id']))
        return httpx.Response(200, content=raw)

    def factory(**kwargs):
        made.append(True)
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, 'AsyncClient', factory)
    keys = iter(['first', 'updated'])
    a = FishAudioProvider(reference_id='a', key_loader=lambda: next(keys))
    b = FishAudioProvider(reference_id='b', key_loader=lambda: 'other')
    try:
        await a._synthesize_audio('一')
        await b._synthesize_audio('二')
        await a._synthesize_audio('三')
        assert len(made) == 1
        assert seen == [('Bearer first', 'a'), ('Bearer other', 'b'), ('Bearer updated', 'a')]
        client = fish_http_client()
        await close_fish_http_client()
        await close_fish_http_client()
        assert client.is_closed
    finally:
        await close_fish_http_client()


@pytest.mark.asyncio
async def test_cancel_one_response_preserves_other_request_and_pool(monkeypatch):
    raw, _ = wav_data()
    entered, closed, release_other = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Body(httpx.AsyncByteStream):
        def __init__(self, first):
            self.first = first

        async def __aiter__(self):
            yield raw[:18000]
            if self.first:
                entered.set()
                await asyncio.Event().wait()
            else:
                await release_other.wait()
                yield raw[18000:]

        async def aclose(self):
            if self.first:
                closed.set()

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Body(
            json.loads(r.content)['reference_id'] == 'a')))))
    a = FishAudioProvider(reference_id='a', key_loader=lambda: 'fixture')
    b = FishAudioProvider(reference_id='b', key_loader=lambda: 'fixture')

    async def consume(provider):
        return [segment async for segment in provider.synthesize_stream('测试')]

    first, other = asyncio.create_task(consume(a)), asyncio.create_task(consume(b))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert closed.is_set() and not fish_http_client().is_closed
        release_other.set()
        assert await asyncio.wait_for(other, 1)
        assert await asyncio.wait_for(consume(b), 1)
    finally:
        first.cancel()
        other.cancel()
        await asyncio.gather(first, other, return_exceptions=True)
        await close_fish_http_client()


def test_clients_do_not_cross_event_loops():
    async def run():
        client = fish_http_client()
        await close_fish_http_client()
        return client

    a, b = asyncio.run(run()), asyncio.run(run())
    assert a is not b and a.is_closed and b.is_closed
