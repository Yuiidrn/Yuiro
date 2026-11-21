"""真实VoicePipeline重叠取消：旧清理不能拥有新回合的状态。"""
import asyncio

import pytest

from yuiro.audio import AudioSegment, VoicePipeline


@pytest.mark.asyncio
async def test_cancelled_cleanup_preserves_successor_manager(monkeypatch):
    old_started, new_started = asyncio.Event(), asyncio.Event()
    old_audio, new_audio = asyncio.Event(), asyncio.Event()
    cleanup_started, release_cleanup = asyncio.Event(), asyncio.Event()
    events = []

    class TTS:
        async def synthesize_segment(self, text):
            started, gate = (old_started, old_audio) if text == "old" else (new_started, new_audio)
            started.set()
            await gate.wait()
            return AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[], slice_ms=20)

    async def emit(sid, kind, payload):
        events.append(kind)

    async def play(sid, segment):
        pass

    pipe = VoicePipeline(tts=TTS(), event_callback=emit, play_callback=play, asr_lock_cool_ms=0)
    old = asyncio.create_task(pipe._speak("session", "old"))
    new = None
    try:
        await asyncio.wait_for(old_started.wait(), 1)
        old_manager = pipe._tts_managers["session"]
        original = old_manager.interrupt

        async def delayed_cleanup():
            cleanup_started.set()
            await release_cleanup.wait()
            await original()

        monkeypatch.setattr(old_manager, "interrupt", delayed_cleanup)
        old.cancel()
        await asyncio.wait_for(cleanup_started.wait(), 1)
        new = asyncio.create_task(pipe._speak("session", "new"))
        await asyncio.wait_for(new_started.wait(), 1)
        successor = pipe._tts_managers["session"]
        assert successor is not old_manager
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await old
        assert pipe._tts_managers["session"] is successor
        assert pipe._speaking["session"]
        assert pipe._asr_locked["session"]
        assert "tts:end" not in events
        new_audio.set()
        await asyncio.wait_for(new, 1)
        assert events.count("tts:end") == 1
        assert "session" not in pipe._tts_managers
        assert not pipe._asr_locked["session"]
    finally:
        old_audio.set()
        new_audio.set()
        release_cleanup.set()
        for task in (old, new):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in (old, new) if t is not None), return_exceptions=True)
