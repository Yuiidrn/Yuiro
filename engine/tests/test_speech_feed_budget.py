"""真实 VoicePipeline 的长回复投喂预算，无云端/设备副作用。"""
import asyncio

import pytest

from yuiro.audio import AudioSegment, VoicePipeline


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('streaming', [False, True])
async def test_long_reply_limits_translation_tasks_and_joins_on_cancel(cancel, streaming):
    release, started = asyncio.Event(), asyncio.Event()
    active = peak = total = 0
    played = []

    class Renderer:
        async def render_speak(self, text):
            nonlocal active, peak, total
            active += 1
            total += 1
            peak = max(peak, active)
            if active >= 4:
                started.set()
            try:
                await release.wait()
                return text
            finally:
                active -= 1

    class TTS:
        async def synthesize_segment(self, text):
            return AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[])

    async def play(sid, segment):
        played.append(segment.wav.decode())

    pipe = VoicePipeline(tts=TTS(), renderer=Renderer(), play_callback=play,
                         asr_lock_cool_ms=0)
    sentences = [f'第{i}句' for i in range(64)]
    async def source():
        for sentence in sentences:
            yield sentence

    kwargs = {'sentence_iter': source()} if streaming else {'sentences': sentences}
    task = asyncio.create_task(pipe._speak_impl('s', **kwargs))
    try:
        await asyncio.wait_for(started.wait(), 1)
        for _ in range(20):
            await asyncio.sleep(0)
        print(f'blocked_translation_peak={peak} admitted={total}')
        assert peak <= 4
        assert total == 4, '翻译未就绪时，不得创建后面60句的投喂任务'
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
            assert played == []
        else:
            release.set()
            await asyncio.wait_for(task, 2)
            assert played == sentences
        assert active == 0
        assert 's' not in pipe._tts_managers
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_window_refills_without_waiting_for_whole_batch_or_delaying_first_audio():
    fifth_started, first_played = asyncio.Event(), asyncio.Event()
    active = 0

    class Renderer:
        async def render_speak(self, text):
            nonlocal active
            if text == 'first':
                return text
            active += 1
            if text == 'fifth':
                fifth_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1

    class TTS:
        async def synthesize_segment(self, text):
            return AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[])

    async def play(sid, segment):
        assert segment.wav == b'first'
        first_played.set()

    pipe = VoicePipeline(tts=TTS(), renderer=Renderer(), play_callback=play,
                         asr_lock_cool_ms=0)
    task = asyncio.create_task(pipe._speak_impl(
        's', sentences=['first', 'second', 'third', 'fourth', 'fifth', 'sixth']))
    try:
        await asyncio.wait_for(first_played.wait(), 1)
        await asyncio.wait_for(fifth_started.wait(), 1)
        assert active == 4 and not task.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert active == 0
