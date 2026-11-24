import asyncio

import pytest

from yuiro.audio.output import ReplyStream, SentenceChannel, translated_sentences
from yuiro.runtime.trace import TraceContext


@pytest.mark.asyncio
async def test_first_sentence_delivered_while_producer_waits_for_tail():
    delivered, tail = asyncio.Event(), asyncio.Event()
    received, tasks = [], []

    async def speak(channel, generation, prepared):
        async for text in channel:
            received.append((generation, text))
            delivered.set()

    bridge = ReplyStream(speak, tasks.append, lambda: 7, TraceContext('s', 'chat'))

    async def producer():
        await bridge.send('这是第一句。')
        await tail.wait()
        await bridge.send('这是第二句。')
        await bridge.finish('不应重复完整回复。')

    task = asyncio.create_task(producer())
    try:
        await asyncio.wait_for(delivered.wait(), 1)
        assert not task.done() and received == [(7, '这是第一句。')]
        tail.set()
        await task
        await bridge.task
        assert received == [(7, '这是第一句。'), (7, '这是第二句。')]
    finally:
        tail.set()
        await bridge.abort()
        await task


@pytest.mark.asyncio
async def test_full_channel_finish_never_waits_for_sentinel_and_wakes_producer():
    channel = SentenceChannel(capacity=1)
    await channel.put('first')
    blocked = asyncio.create_task(channel.put('second'))
    await asyncio.sleep(0)
    assert not blocked.done()
    await asyncio.wait_for(channel.finish(), 1)
    with pytest.raises(RuntimeError, match='closed'):
        await blocked
    assert [text async for text in channel] == ['first']


@pytest.mark.asyncio
async def test_channel_wait_budget_and_character_limit():
    channel = SentenceChannel(capacity=1, wait_s=.01)
    await channel.put('first')
    with pytest.raises(TimeoutError):
        await channel.put('blocked')
    await channel.finish(discard=True)
    channel = SentenceChannel()
    with pytest.raises(ValueError):
        await channel.put('a' * 16001)


@pytest.mark.asyncio
async def test_preconnection_without_sentence_is_joined_on_abort():
    closed = asyncio.Event()

    class Prepared:
        async def close(self):
            closed.set()

    async def speak(*args):
        pytest.fail('没有句子时不能合成')

    bridge = ReplyStream(speak, lambda t: None, lambda: 1, prepare=Prepared)
    await asyncio.sleep(0)
    await bridge.abort()
    assert closed.is_set() and bridge.task.done()


@pytest.mark.asyncio
async def test_translation_stale_result_cannot_reach_provider():
    current = True

    def check():
        if not current:
            raise asyncio.CancelledError()

    async def source():
        yield '完整句子。'

    async def render(text):
        nonlocal current
        current = False
        return text

    with pytest.raises(asyncio.CancelledError):
        _ = [text async for text in translated_sentences(source(), render, check)]


@pytest.mark.asyncio
async def test_shared_http_single_failure_skips_without_retry_or_losing_later_sentence():
    from yuiro.audio.output import sentence_audio

    calls = []

    class Provider:
        async def synthesize_segment(self, text):
            calls.append(text)
            if text == 'bad':
                raise RuntimeError('fixture')
            return text

    async def source():
        yield 'bad'
        yield 'good'

    assert [part async for part in sentence_audio(Provider(), source())] == ['good']
    assert calls == ['bad', 'good']
