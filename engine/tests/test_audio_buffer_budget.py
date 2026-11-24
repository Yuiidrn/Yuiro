"""慢播放器、有序窗口与打断时的音频缓存预算。"""
import asyncio

import pytest

from yuiro.audio import AudioSegment, TTSTaskManager


@pytest.mark.asyncio
async def test_slow_consumer_bounds_bytes_preserves_order_and_cancels_waiters():
    class Provider:
        async def synthesize_stream(self, text):
            for index in range(50):
                yield AudioSegment(wav=bytes([int(text), index]) * 10,
                                   sample_rate=16000, volumes=[])

    manager = TTSTaskManager(Provider(), buffer_items=2, buffer_bytes=40, sequence_window=2)
    tasks = [asyncio.create_task(manager.enqueue(i, str(i))) for i in range(1, 7)]
    try:
        await asyncio.sleep(.02)
        assert manager.buffer_peak_bytes <= 80
        received = []
        for _ in range(60):
            part = await asyncio.wait_for(manager.wait_next(), 1)
            received.append(part.wav[:2])
        assert received == [bytes([1, i]) for i in range(50)] + [bytes([2, i]) for i in range(10)]
        await manager.interrupt()
        await asyncio.wait_for(asyncio.gather(*tasks), 1)
        assert not manager._buffer
        assert manager.buffer_peak_bytes <= 80
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_oversize_segment_explicitly_skips_without_hanging_next_sentence():
    class Provider:
        async def synthesize_segment(self, text):
            return AudioSegment(wav=b'x' * int(text), sample_rate=16000, volumes=[])

    manager = TTSTaskManager(Provider(), buffer_bytes=20)
    await manager.enqueue(1, '100')
    await manager.enqueue(2, '10')
    await manager.finish()
    assert not (await manager.wait_next()).wav
    assert len((await manager.wait_next()).wav) == 10
    assert await manager.wait_next() is None


@pytest.mark.asyncio
async def test_later_translations_cannot_take_head_synthesis_slot():
    class Provider:
        async def synthesize_stream(self, text):
            for _ in range(10):
                yield AudioSegment(wav=text.encode(), sample_rate=16000, volumes=[])
    manager = TTSTaskManager(Provider(), buffer_items=1)
    later = [asyncio.create_task(manager.enqueue(i, str(i))) for i in (2, 3, 4)]
    await asyncio.sleep(.01)
    head = asyncio.create_task(manager.enqueue(1, '1'))
    try:
        values = []
        for _ in range(40):
            values.append((await asyncio.wait_for(manager.wait_next(), 1)).wav)
        await asyncio.wait_for(asyncio.gather(head, *later), 1)
        assert values == [str(i).encode() for i in range(1, 5) for _ in range(10)]
    finally:
        for task in [head, *later]:
            task.cancel()
        await asyncio.gather(head, *later, return_exceptions=True)
