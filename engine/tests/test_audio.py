"""M2 audio package unit tests (mock external models / network)."""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from yuiro.audio import (
    ASRProvider,
    AudioSegment,
    TranscriptBuffer,
    TTSProvider,
    TTSTaskManager,
    VADEngine,
    VADEvent,
    VoicePipeline,
)

# 0.5s 静音（16k / mono / int16）—— 喂给 `on_speech_end` 的假音频。
#
# ⚠ 必须够长，这不是凑数：`on_speech_end` 有一条"**极短音频（<0.25s）不送识别**"
#   的防护（见 audio/__init__.py 的「噪音防护①」）。此前这些测试喂 `[b"\x00\x00"]`
#   （1 采样 ≈0.06ms），回合在**识别之前就 return**，后面的步骤压根不会发生 ——
#   轻则断言失败（要素缺失），重则**永久挂死**在 `await playing.wait()` 这类
#   等待上（等一个永远不会被 set 的事件），把整个测试会话拖住。
_SPEECH_STUB = np.zeros(8000, dtype=np.int16).tobytes()


class FakeVADModel:
    """Return a fixed speech probability, bypassing the silero download."""

    def __init__(self, prob: float) -> None:
        self.prob = prob

    def __call__(self, audio, sr):
        del audio, sr
        return self.prob


def _speech_chunk() -> np.ndarray:
    return np.full(512, 0.5, dtype=np.float32)


def _silence_chunk() -> np.ndarray:
    return np.zeros(512, dtype=np.float32)


class TestVADEngine:
    def test_idle_to_active_requires_hits(self) -> None:
        vad = VADEngine(
            probability_threshold=0.4,
            db_threshold=60.0,
            smoothing_window=1,
            required_hits=2,
            required_misses=3,
        )
        vad._model = FakeVADModel(0.9)
        chunk = _speech_chunk()
        assert vad.feed(chunk) == VADEvent.Silence
        assert vad.feed(chunk) == VADEvent.SpeechStart

    def test_active_to_end_requires_misses(self) -> None:
        vad = VADEngine(
            probability_threshold=0.4,
            db_threshold=60.0,
            smoothing_window=1,
            required_hits=1,
            required_misses=2,
        )
        vad._model = FakeVADModel(0.9)
        assert vad.feed(_speech_chunk()) == VADEvent.SpeechStart

        vad._model = FakeVADModel(0.1)
        assert vad.feed(_silence_chunk()) == VADEvent.Silence
        assert vad.feed(_silence_chunk()) == VADEvent.SpeechEnd

    def test_reset_returns_to_idle(self) -> None:
        vad = VADEngine(
            probability_threshold=0.4,
            db_threshold=60.0,
            smoothing_window=1,
            required_hits=1,
            required_misses=2,
        )
        vad._model = FakeVADModel(0.9)
        assert vad.feed(_speech_chunk()) == VADEvent.SpeechStart
        vad.reset()
        assert vad.feed(_speech_chunk()) == VADEvent.SpeechStart


class TestASRProvider:
    def test_transcribe_joins_segments(self) -> None:
        class FakeSeg:
            def __init__(self, text: str) -> None:
                self.text = text

        class FakeASRModel:
            def transcribe(self, audio, **kwargs):
                del audio, kwargs
                return iter([FakeSeg("你好 "), FakeSeg("世界")]), {}

        provider = ASRProvider()
        provider._model = FakeASRModel()
        assert provider.transcribe(np.zeros(512, dtype=np.float32)) == "你好 世界"

    def test_auto_falls_back_to_cpu_when_cuda_inference_fails(self) -> None:
        class FailingCudaModel:
            def transcribe(self, audio, **kwargs):
                del audio, kwargs
                raise RuntimeError("Library cublas64_12.dll is not found")

        class FakeSeg:
            text = "CPU 结果"

        class CpuModel:
            def transcribe(self, audio, **kwargs):
                del audio, kwargs
                return iter([FakeSeg()]), {}

        provider = ASRProvider(device="auto")
        models = iter([FailingCudaModel(), CpuModel()])
        provider._load_model = lambda: next(models)

        assert provider.transcribe(np.zeros(512, dtype=np.float32)) == "CPU 结果"
        assert provider._device == "cpu"
        assert provider._compute_type == "int8"


class TestTranscriptBuffer:
    @pytest.mark.asyncio
    async def test_flush_groups_nearby_fragments(self) -> None:
        flushed: list[str] = []
        buf = TranscriptBuffer(flush_delay_ms=20, flush=lambda text: flushed.append(text))
        await buf.push("你好")
        await buf.push("世界")
        await asyncio.sleep(0.05)
        assert flushed == ["你好世界"]
        await buf.dispose()

    @pytest.mark.asyncio
    async def test_char_limit_evicts_oldest(self) -> None:
        buf = TranscriptBuffer(flush_delay_ms=1000)
        await buf.push("a" * 100)
        await buf.push("b" * 10)
        assert buf._parts == ["b" * 10]
        await buf.dispose()

    @pytest.mark.asyncio
    async def test_generation_cancels_stale_flush(self) -> None:
        flushed: list[str] = []
        buf = TranscriptBuffer(flush_delay_ms=30, flush=lambda text: flushed.append(text))
        await buf.push("第一")
        await asyncio.sleep(0.01)
        await buf.push("第二")
        await asyncio.sleep(0.06)
        assert flushed == ["第一第二"]
        await buf.dispose()


class FakeTTSProvider(TTSProvider):
    def __init__(self, delays: dict[str, float] | None = None) -> None:
        super().__init__()
        self.delays = delays or {}
        self.calls: list[str] = []

    async def synthesize_segment(self, text: str) -> AudioSegment:
        self.calls.append(text)
        delay = self.delays.get(text, 0)
        if delay:
            await asyncio.sleep(delay)
        return AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[], slice_ms=20)


class TestTTSProvider:
    def test_slice_rms(self) -> None:
        sr = 24000
        audio = np.zeros(sr, dtype=np.float32)
        audio[0:480] = 1.0
        volumes = TTSProvider._slice_rms(audio, sr, 20)
        assert len(volumes) == 50
        assert volumes[0] == pytest.approx(1.0, abs=1e-3)
        assert volumes[1] == pytest.approx(0.0, abs=1e-3)


class TestTTSTaskManager:
    @pytest.mark.asyncio
    async def test_ordered_delivery(self) -> None:
        provider = FakeTTSProvider({"seq1": 0.05, "seq2": 0.0})
        mgr = TTSTaskManager(provider)
        await asyncio.gather(
            mgr.enqueue(1, "seq1"),
            mgr.enqueue(2, "seq2"),
        )
        first = await asyncio.wait_for(mgr.wait_next(), timeout=1)
        second = await asyncio.wait_for(mgr.wait_next(), timeout=1)
        assert first.wav == b"seq1"
        assert second.wav == b"seq2"

    @pytest.mark.asyncio
    async def test_interrupt_drops_pending(self) -> None:
        provider = FakeTTSProvider({"old": 0.1})
        mgr = TTSTaskManager(provider)
        stale = asyncio.create_task(mgr.enqueue(1, "old"))
        await asyncio.sleep(0.01)
        await mgr.interrupt()
        await stale

        await mgr.enqueue(1, "new")
        seg = await asyncio.wait_for(mgr.wait_next(), timeout=1)
        assert seg.wav == b"new"


class FakeASR:
    def transcribe(self, audio: np.ndarray) -> str:
        del audio
        return "你好"


class EmptyASR:
    def transcribe(self, audio: np.ndarray) -> str:
        del audio
        return ""


class FailingASR:
    def transcribe(self, audio: np.ndarray) -> str:
        del audio
        raise RuntimeError("ASR backend unavailable")


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


class TestVoicePipeline:
    async def _play_noop(self, session_id: str, segment: AudioSegment) -> None:
        del session_id, segment

    @pytest.mark.asyncio
    async def test_asr_lock_during_tts(self) -> None:
        playing = asyncio.Event()
        release = asyncio.Event()

        async def play(session_id: str, segment: AudioSegment) -> None:
            del session_id, segment
            playing.set()
            await release.wait()

        async def llm(text: str, session_id: str) -> str:
            del session_id
            return f"回复:{text}"

        pipe = VoicePipeline(
            llm_callback=llm,
            vad=SeqVAD([]),
            asr=FakeASR(),
            tts=FakeTTSProvider(),
            play_callback=play,
            asr_lock_cool_ms=50,
        )
        pipe._audio["s"] = [_SPEECH_STUB]
        asyncio.create_task(pipe.on_speech_end("s"))
        await playing.wait()
        assert pipe._asr_locked["s"] is True
        assert pipe._speaking["s"] is True

        await pipe.on_speech_end("s")  # 播放期间 ASR 锁应拦截
        release.set()
        await pipe._speak_tasks["s"]
        assert pipe._asr_locked["s"] is False

    @pytest.mark.asyncio
    async def test_interrupt_cancels_tts_and_unlocks(self) -> None:
        playing = asyncio.Event()

        async def play(session_id: str, segment: AudioSegment) -> None:
            del session_id, segment
            playing.set()
            await asyncio.Event().wait()  # 永久阻塞，模拟播放中

        pipe = VoicePipeline(
            llm_callback=None,
            vad=SeqVAD([]),
            asr=FakeASR(),
            tts=FakeTTSProvider(),
            play_callback=play,
        )
        pipe._audio["s"] = [_SPEECH_STUB]
        on_end = asyncio.create_task(pipe.on_speech_end("s"))
        await playing.wait()
        assert pipe._speaking["s"] is True

        pipe.interrupt("s")
        await asyncio.sleep(0.01)
        assert pipe._speaking["s"] is False
        assert pipe._asr_locked["s"] is False
        await on_end

    @pytest.mark.asyncio
    async def test_gates_and_llm_callback(self) -> None:
        calls = {"can": 0, "before": 0, "after": 0}
        spoken: list[str] = []

        def can_start(session_id: str) -> bool:
            del session_id
            calls["can"] += 1
            return calls["can"] > 1

        def inspect_before(text: str, session_id: str) -> str:
            del session_id
            calls["before"] += 1
            return text + "[before]"

        def inspect_after(text: str, session_id: str) -> str:
            del session_id
            calls["after"] += 1
            return text + "[after]"

        async def llm(text: str, session_id: str) -> str:
            del session_id
            return "LLM:" + text

        class RecordingTTS(FakeTTSProvider):
            async def synthesize_segment(self, text: str) -> AudioSegment:
                spoken.append(text)
                return AudioSegment(
                    wav=text.encode(), sample_rate=24000, volumes=[], slice_ms=20
                )

        pipe = VoicePipeline(
            llm_callback=llm,
            vad=SeqVAD([]),
            asr=FakeASR(),
            tts=RecordingTTS(),
            can_start=can_start,
            inspect_before=inspect_before,
            inspect_after=inspect_after,
            play_callback=self._play_noop,
            asr_lock_cool_ms=0,
        )
        pipe._audio["s"] = [_SPEECH_STUB]
        await pipe.on_speech_end("s")  # can_start 首次拒绝
        assert calls == {"can": 1, "before": 0, "after": 0}
        assert spoken == []

        pipe._audio["s"] = [_SPEECH_STUB]
        await pipe.on_speech_end("s")  # can_start 放行
        speak_task = pipe._speak_tasks.get("s")
        if speak_task is not None:
            await speak_task
        assert calls == {"can": 2, "before": 1, "after": 1}
        assert spoken == ["LLM:你好[before][after]"]

    @pytest.mark.asyncio
    async def test_on_audio_speech_start_triggers_barge_in(self) -> None:
        # 打断总开关默认关闭 → 显式打开，才走 barge-in 路径
        pipe = VoicePipeline(vad=SeqVAD([VADEvent.SpeechStart]), barge_in_enabled=True)
        # 冷启动门控：不标记就绪的话，音频只会进冷启动缓冲，根本进不了处理链
        # （同 test_preroll_... 里的做法）——否则本测试断言的是"没发生的事"。
        pipe.is_ready = lambda: True  # type: ignore[method-assign]
        pipe._speaking["s"] = True
        await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), "s")
        assert pipe._speaking["s"] is False

    @pytest.mark.asyncio
    async def test_event_callback_receives_vad_state_events(self) -> None:
        events: list[tuple[str, str, dict]] = []

        async def cb(session_id: str, event_type: str, payload: dict) -> None:
            events.append((session_id, event_type, payload))

        pipe = VoicePipeline(
            vad=SeqVAD([VADEvent.SpeechStart, VADEvent.SpeechEnd]),
            asr=EmptyASR(),
            event_callback=cb,
        )
        pipe.is_ready = lambda: True  # type: ignore[method-assign] —— 见上：就绪门控
        await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), "s")
        await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), "s")
        vad_states = [e[2].get("state") for e in events if e[1] == "vad:state"]
        assert vad_states == ["active", "inactive"]

    @pytest.mark.asyncio
    async def test_on_audio_windows_arbitrary_frame_lengths(self) -> None:
        asr_seen: list[int] = []

        class RecordingASR:
            def transcribe(self, audio: np.ndarray) -> str:
                asr_seen.append(audio.size)
                return "你好"

        events: list[tuple[str, str, dict]] = []

        async def cb(session_id: str, event_type: str, payload: dict) -> None:
            events.append((session_id, event_type, payload))

        pipe = VoicePipeline(
            # 第 1 窗 start；中间静音；**最后一窗**才 end（end 出现得晚，音频才够长）
            vad=SeqVAD(
                [VADEvent.SpeechStart] + [VADEvent.Silence] * 7 + [VADEvent.SpeechEnd]
            ),
            asr=RecordingASR(),
            tts=FakeTTSProvider(),
            llm_callback=None,
            play_callback=self._play_noop,
            asr_lock_cool_ms=0,
            event_callback=cb,
        )
        pipe.is_ready = lambda: True  # type: ignore[method-assign] —— 见上：就绪门控
        # 300 + 300 + 424 = 1024 采样，跨越两次 on_audio 拼成两个 512 采样窗口；
        # 再补 7 个整窗，凑够 9 窗（4608 采样 ≈0.29s）。
        # ⚠ 长度不是凑数：`on_speech_end` 有"**极短音频（<0.25s）不送识别**"的防护，
        #   2 窗（0.064s）会被直接丢弃 → ASR 不会被调用 → 断言的全是"没发生的事"。
        await pipe.on_audio(np.zeros(300, dtype=np.int16).tobytes(), "s")
        await pipe.on_audio(np.zeros(300, dtype=np.int16).tobytes(), "s")
        await pipe.on_audio(np.zeros(424, dtype=np.int16).tobytes(), "s")
        for _ in range(7):
            await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), "s")

        # SpeechEnd 的回合现在是**异步派发**的（见 audio._spawn_speech_end：
        # 否则 pcm worker 会被 LLM 生成占住、VAD 停摆、插话检测失聪），
        # 喂完就取 `_speak_tasks` 会取到 None，必须显式等一次。
        await asyncio.sleep(0.05)

        task = pipe._speak_tasks.get("s")
        if task is not None:
            await task

        assert asr_seen == [4608]
        vad_states = [e[2].get("state") for e in events if e[1] == "vad:state"]
        assert vad_states == ["active", "inactive"]

    @pytest.mark.asyncio
    async def test_preroll_preserves_audio_before_speech_start(self) -> None:
        """回归：VAD 确认"开口"前的音频必须保留，否则会吞掉开头几个字。

        旧实现在 SpeechStart 时执行 self._audio[sid] = [frame]，把判定前累积的
        音频整体丢弃——而用户开口的头几个字正好落在这段里。
        """
        frames: list[int] = []

        class RecordingASR:
            def transcribe(self, audio: np.ndarray) -> str:
                frames.append(len(audio))
                return "你好"

        pipe = VoicePipeline(
            # 第 1 帧静音（判定前）→ 第 2 帧 start → 中间静音 → 第 12 帧 end。
            # end 故意放晚：见下面的长度说明。
            vad=SeqVAD(
                [VADEvent.Silence, VADEvent.SpeechStart]
                + [VADEvent.Silence] * 9
                + [VADEvent.SpeechEnd]
            ),
            asr=RecordingASR(),
            tts=FakeTTSProvider(),
            pre_roll_ms=400,
        )
        pipe._state = pipe.STATE_READY if hasattr(pipe, "STATE_READY") else "ready"
        # 冷启动门控：直接标记为就绪，让音频进入正常处理链
        pipe.is_ready = lambda: True  # type: ignore[method-assign]

        # 12 帧 512 采样（≈0.38s）：必须 ≥「极短音频」下限（0.25s），
        # 否则回合在识别之前就被丢弃 —— 那样测的就不是"pre-roll 有没有保留"，
        # 而是"回合被不要了"（本测试曾因此长期失败）。
        for _ in range(12):
            await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), "s")
        await asyncio.sleep(0.05)

        # 判定前的第 1 帧 + start 帧 + 其余帧都应送到 ASR（pre-roll 未被裁掉）
        assert frames, "ASR 未收到音频"
        assert frames[0] == 12 * 512, (
            f"应保留 SpeechStart 前的前置音频（期望 {12 * 512} 采样），实际 {frames[0]}"
        )

    @pytest.mark.asyncio
    async def test_interrupt_clears_pcm_buffer(self) -> None:
        pipe = VoicePipeline(vad=SeqVAD([]))
        pipe.is_ready = lambda: True  # type: ignore[method-assign] —— 见上：就绪门控
        await pipe.on_audio(np.zeros(300, dtype=np.int16).tobytes(), "s")
        assert len(pipe._pcm_in["s"]) == 600
        pipe.interrupt("s")
        assert len(pipe._pcm_in["s"]) == 0

    @pytest.mark.asyncio
    async def test_speech_end_freezes_audio_against_preroll_trim(self) -> None:
        """SpeechEnd 之后到达的帧**不许**把本句音频裁成 pre-roll。

        回归（实测踩到）：回合被派发成**异步**任务后（见 audio._spawn_speech_end），
        pcm worker 会继续处理后续帧，而那时 `_recording` 已是 False → 那些帧走
        pre-roll 逻辑，把 `_audio` 裁成"只留最近 12 帧"，**等于删掉用户刚说的话**。
        表现：说了 3.4s，ASR 只拿到 0.38s → 转写"。"→ 判为噪音 → 完全无反应。
        """
        seen: list[int] = []

        class RecordingASR:
            def transcribe(self, audio: np.ndarray) -> str:
                seen.append(audio.size)
                return "你好"

        pipe = VoicePipeline(
            # 第 1 窗 start；中间静音；第 11 窗 end
            vad=SeqVAD(
                [VADEvent.SpeechStart] + [VADEvent.Silence] * 9 + [VADEvent.SpeechEnd]
            ),
            asr=RecordingASR(),
            tts=FakeTTSProvider(),
            play_callback=self._play_noop,
            asr_lock_cool_ms=0,
        )
        pipe.is_ready = lambda: True  # type: ignore[method-assign]
        for _ in range(11):
            await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), "s")
        # SpeechEnd 之后再喂 20 帧（模拟 worker 继续收帧）：它们属于"下一句"，
        # **绝不能**把上一句的音频冲掉。
        for _ in range(20):
            await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), "s")
        await asyncio.sleep(0.05)

        assert seen == [11 * 512], f"本句音频被后续帧裁掉了：{seen}"

    @pytest.mark.asyncio
    async def test_event_callback_receives_text_and_tts_events(self) -> None:
        events: list[tuple[str, str, dict]] = []

        async def cb(session_id: str, event_type: str, payload: dict) -> None:
            events.append((session_id, event_type, payload))

        async def llm(text: str, session_id: str) -> str:
            del session_id
            return f"回复:{text}"

        pipe = VoicePipeline(
            llm_callback=llm,
            vad=SeqVAD([]),
            asr=FakeASR(),
            tts=FakeTTSProvider(),
            play_callback=self._play_noop,
            asr_lock_cool_ms=0,
            event_callback=cb,
        )
        pipe._audio["s"] = [_SPEECH_STUB]
        await pipe.on_speech_end("s")
        task = pipe._speak_tasks.get("s")
        if task is not None:
            await task
        # 事件链（含阶段反馈）：asr:start → asr:text → llm:start → llm:text
        # → tts:start → tts:synthesize → tts:ready → tts:end
        types = [e[1] for e in events]
        assert types == [
            "asr:start",
            "asr:text",
            "llm:start",
            "llm:text",
            "tts:start",
            "tts:synthesize",
            "tts:ready",
            "tts:end",
        ]
        assert events[1][2]["text"] == "你好"
        assert events[1][2]["duration_ms"] >= 0
        assert events[2][2] == {"state": "requesting", "input": "你好"}
        assert events[3][2]["text"] == "回复:你好"
        assert events[3][2]["duration_ms"] >= 0
        assert events[4][2] == {"text": "回复:你好"}
        assert events[6][2]["volumes_count"] == 0

    @pytest.mark.asyncio
    async def test_asr_failure_emits_error_without_raising(self) -> None:
        events: list[tuple[str, str, dict]] = []

        async def cb(session_id: str, event_type: str, payload: dict) -> None:
            events.append((session_id, event_type, payload))

        pipe = VoicePipeline(asr=FailingASR(), event_callback=cb)
        pipe._audio["s"] = [_SPEECH_STUB]

        await pipe.on_speech_end("s")

        assert len(events) == 2
        assert events[0][1] == "asr:start"
        assert events[0][2] == {"state": "transcribing"}
        assert events[1][1] == "asr:error"
        assert events[1][2]["message"] == "ASR backend unavailable"
        assert events[1][2]["duration_ms"] >= 0

    def test_default_no_event_callback(self) -> None:
        pipe = VoicePipeline()
        assert pipe._event_callback is None
