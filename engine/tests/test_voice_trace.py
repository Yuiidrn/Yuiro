"""S01：语音链路 trace 打点（Scenario，Fake 组件，不加载真实模型）。

覆盖：语音阶段打点、前端 playback_started 回执、finalize、interrupt 丢弃。
"""
from __future__ import annotations

import numpy as np
import pytest

from yuiro.audio import AudioSegment, VADEvent, VoicePipeline


class FakeASR:
    def transcribe(self, audio: np.ndarray) -> str:
        del audio
        return "你好"


class FakeTTS:
    async def synthesize_segment(self, text: str) -> AudioSegment:
        return AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[0.1], slice_ms=20)


class SeqVAD:
    def __init__(self, events: list[VADEvent]) -> None:
        self.events = list(events)

    def feed(self, chunk: np.ndarray) -> VADEvent:
        del chunk
        if self.events:
            return self.events.pop(0)
        return VADEvent.Silence

    def reset(self) -> None:
        self.events.clear()


@pytest.mark.asyncio
async def test_voice_trace_collects_stages() -> None:
    """一次语音问答（ASR→LLM→TTS）应产出含各阶段时刻的 trace。"""

    async def llm(text: str, session_id: str) -> str:
        del session_id
        return f"回复:{text}"

    async def play(session_id: str, segment: AudioSegment) -> None:
        del session_id, segment

    pipe = VoicePipeline(
        llm_callback=llm,
        asr=FakeASR(),
        tts=FakeTTS(),
        play_callback=play,
        asr_lock_cool_ms=0,
    )
    sid = "s001"
    # ⚠ 假音频必须够长：`on_speech_end` 有"**极短音频（<0.25s）不送识别**"的防护
    #   （见 audio/__init__.py 的「噪音防护①」）。用 1 采样（≈0.06ms）会被直接忽略，
    #   后面的 ASR/LLM/TTS 阶段压根不会发生 —— 本测试断言"各阶段都有打点"必然失败。
    pipe._audio[sid] = [np.zeros(8000, dtype=np.int16).tobytes()]
    await pipe.on_speech_end(sid)
    speak_task = pipe._speak_tasks.get(sid)
    if speak_task is not None:
        await speak_task

    trace = pipe.get_trace(sid)
    assert trace is not None
    for stage in (
        "speech_end",
        "asr_final",
        "llm_start",
        "llm_final",
        "tts_start",
        "tts_first_audio",
        "tts_end",
    ):
        assert trace.get(stage) is not None, f"缺少阶段: {stage}"


@pytest.mark.asyncio
async def test_speech_start_creates_trace() -> None:
    """VAD SpeechStart 即创建 trace（交互起点），不依赖后续 ASR。"""
    pipe = VoicePipeline(vad=SeqVAD([VADEvent.SpeechStart]))
    pipe._set_state(pipe.STATE_READY, "ready", 1.0)
    sid = "s"
    await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), sid)
    trace = pipe.get_trace(sid)
    assert trace is not None
    assert trace.get("speech_start") is not None


def test_playback_started_marks_trace() -> None:
    """前端回执（真正出声）写到当前 trace。"""
    pipe = VoicePipeline()
    sid = "s"
    trace = pipe._start_trace(sid)
    pipe.mark_playback_started(sid)
    assert trace.get("playback_started") is not None


@pytest.mark.asyncio
async def test_finalize_removes_trace() -> None:
    """延迟汇总后 trace 从注册表移除（不泄漏）。"""
    pipe = VoicePipeline()
    sid = "s"
    pipe._start_trace(sid)
    await pipe._finalize_trace(sid, delay=0.0)
    assert pipe.get_trace(sid) is None


@pytest.mark.asyncio
async def test_finalize_emits_summary(capsys: pytest.CaptureFixture[str]) -> None:
    """DoD：日志可读出一行完整汇总（含前端播放回执阶段）。"""
    pipe = VoicePipeline()
    sid = "s"
    trace = pipe._start_trace(sid)
    trace.mark("speech_start")
    trace.mark("speech_end")
    pipe.mark_playback_started(sid)
    await pipe._finalize_trace(sid, delay=0.0)
    out = capsys.readouterr().out
    assert "[yuiro][trace]" in out
    assert "mode=voice" in out
    assert "playback_started" in out


def test_interrupt_drops_trace() -> None:
    """barge-in 打断时丢弃当前 trace（不输出半途汇总）。"""
    pipe = VoicePipeline()
    sid = "s"
    pipe._start_trace(sid)
    pipe.interrupt(sid)
    assert pipe.get_trace(sid) is None
