"""首句翻译慢时不能被后句抢合成名额；取消回收投喂任务。"""
import asyncio

import pytest

from yuiro.audio import AudioSegment, VoicePipeline


@pytest.mark.asyncio
async def test_later_translation_cannot_take_first_synthesis_slots():
    first_translation = asyncio.Event()
    later_translated = asyncio.Event()
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    first_played = asyncio.Event()
    finish_later = asyncio.Event()
    calls, played = [], []

    class Renderer:
        async def render_speak(self, text):
            if text == 'first':
                await first_translation.wait()
            if text == 'third':
                later_translated.set()
            return text

    class TTS:
        async def synthesize_segment(self, text):
            calls.append(text)
            if text == 'first':
                first_started.set()
            else:
                second_started.set()
                await finish_later.wait()
            return AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[])

    async def play(sid, segment):
        played.append(segment.wav.decode())
        if played[-1] == 'first':
            first_played.set()

    pipe = VoicePipeline(tts=TTS(), renderer=Renderer(), play_callback=play, asr_lock_cool_ms=0)
    task = asyncio.create_task(pipe._speak_impl('s', sentences=['first', 'second', 'third']))
    try:
        await asyncio.wait_for(later_translated.wait(), 1)
        await asyncio.sleep(0)
        assert calls == [], '后句不能在首句译文就绪前先占满名额'
        first_translation.set()
        await asyncio.wait_for(first_started.wait(), 1)
        await asyncio.wait_for(second_started.wait(), 1)
        await asyncio.wait_for(first_played.wait(), 1)
        assert calls[0] == 'first'
        assert played == ['first'], '首句应在后句合成未结束时交付'
        finish_later.set()
        await asyncio.wait_for(task, 1)
        assert played == ['first', 'second', 'third']
    finally:
        finish_later.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_punctuation_only_fragments_skip_translation_and_cloud():
    translated, synthesized = [], []

    class Renderer:
        async def render_speak(self, text):
            translated.append(text)
            return text

    class TTS:
        async def synthesize_segment(self, text):
            synthesized.append(text)
            return AudioSegment(wav=b'audio', sample_rate=24000, volumes=[])

    async def play(sid, segment):
        pass

    pipe = VoicePipeline(tts=TTS(), renderer=Renderer(), play_callback=play, asr_lock_cool_ms=0)
    await pipe._speak_impl('s', sentences=['“', '**', '你好。', '”'])
    assert translated == synthesized == ['你好。']


@pytest.mark.asyncio
async def test_cancel_during_open_sentence_stream_joins_translation_children():
    translating, cancelled = asyncio.Event(), asyncio.Event()

    class Renderer:
        async def render_speak(self, text):
            translating.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    async def sentences():
        yield 'first'
        await asyncio.Event().wait()  # 尚未进入_feed内的gather。

    pipe = VoicePipeline(renderer=Renderer(), asr_lock_cool_ms=0)
    task = asyncio.create_task(pipe._speak_impl('s', sentence_iter=sentences()))
    await asyncio.wait_for(translating.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert cancelled.is_set()
    assert 's' not in pipe._tts_managers
