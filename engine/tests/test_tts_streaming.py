"""S04：分段流式 TTS（Unit + Scenario，Fake 组件，不加载真实模型）。

对应 docs/plan/S04-streaming-tts.md。末尾一节是 S52（输出语言解耦）的
pipeline 级用例：默认不注入 renderer 时行为与引入前完全一致（回归护栏）。
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from yuiro.audio import AudioSegment, TTSTaskManager, VoicePipeline, split_sentences

# 0.5s 静音（16k / mono / int16）—— 见 test_audio.py 的说明：用 1 采样的假音频
# 会被"极短音频不送识别"的防护拦下，导致后续步骤不发生（断言失败或永久挂死）。
_SPEECH_STUB = np.zeros(8000, dtype=np.int16).tobytes()

# ---- Unit：split_sentences ---------------------------------------------------


def test_split_by_sentence_punctuation() -> None:
    # min_len=6：本例句子较短，显式放宽合并阈值以验证纯标点切分
    parts = split_sentences("今天天气不错。我们去公园吧！你说呢？", min_len=6)
    assert len(parts) == 3
    assert parts[0].endswith("。")
    assert parts[1].endswith("！")


def test_short_sentences_merged() -> None:
    """过短片段向后合并（避免"嗯。"单独请求）。"""
    parts = split_sentences("嗯。好的。今天天气非常不错，我们出去走走吧。")
    assert len(parts) <= 2
    assert parts[-1].endswith("。")


def test_long_sentence_soft_cut() -> None:
    text = "这是一段很长的句子，" + "很长的内容" * 12 + "。"
    parts = split_sentences(text, max_len=30)
    assert len(parts) >= 2
    assert all(len(p) <= 31 for p in parts)  # 允许标点带来的 1 字误差


def test_empty_text_returns_empty() -> None:
    assert split_sentences("   ") == []


# ---- Unit：TTSTaskManager（S04 增强） ----------------------------------------


class _RecordingTTS:
    """记录合成调用 + 可注入单句失败与延迟。"""

    def __init__(self, fail_on: str | None = None, delay: float = 0.0) -> None:
        self.calls: list[str] = []
        self._fail_on = fail_on
        self._delay = delay

    async def synthesize_segment(self, text: str) -> AudioSegment:
        self.calls.append(text)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail_on and text == self._fail_on:
            raise RuntimeError("合成失败（测试注入）")
        return AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[0.1], slice_ms=20)


@pytest.mark.asyncio
async def test_manager_orders_and_skips_failure() -> None:
    """按序交付；单句失败放空段占位，不阻塞后续段。"""
    tts = _RecordingTTS(fail_on="第二句。")
    mgr = TTSTaskManager(tts)
    producers = asyncio.gather(
        mgr.enqueue(1, "第一句。"),
        mgr.enqueue(2, "第二句。"),
        mgr.enqueue(3, "第三句。"),
    )
    segs = [await asyncio.wait_for(mgr.wait_next(), timeout=1) for _ in range(3)]
    await asyncio.wait_for(producers, timeout=1)
    assert segs[0].wav == "第一句。".encode()
    assert segs[1].wav == b""  # 失败占位（空段）
    assert segs[2].wav == "第三句。".encode()


# ---- Scenario：_speak 分句流式 ------------------------------------------------


class FakeASR:
    def transcribe(self, audio: np.ndarray) -> str:
        del audio
        return "你好"


@pytest.mark.asyncio
async def test_speak_streams_in_order() -> None:
    """分句 → 全部按序播放（播放顺序 == 分句顺序）。"""
    played: list[str] = []

    async def llm(text: str, session_id: str) -> str:
        del session_id
        return (
            "这是第一句比较长的话，用来验证分段流式的播放顺序。"
            "这是第二句也比较长的话，确保能够被单独切分。"
            "这是第三句话，长度同样足够。"
        )

    async def play(session_id: str, segment: AudioSegment) -> None:
        del session_id
        played.append(segment.wav.decode())

    pipe = VoicePipeline(
        llm_callback=llm,
        asr=FakeASR(),
        tts=_RecordingTTS(),
        play_callback=play,
        asr_lock_cool_ms=0,
    )
    pipe._audio["s"] = [_SPEECH_STUB]
    await pipe.on_speech_end("s")
    task = pipe._speak_tasks.get("s")
    if task is not None:
        await task
    assert played == [
        "这是第一句比较长的话，用来验证分段流式的播放顺序。",
        "这是第二句也比较长的话，确保能够被单独切分。",
        "这是第三句话，长度同样足够。",
    ]


@pytest.mark.asyncio
async def test_segment_streaming_disabled_plays_whole() -> None:
    """segment_streaming=False 回退整段（行为同旧）。"""
    played: list[str] = []

    async def llm(text: str, session_id: str) -> str:
        del session_id
        return "第一句话。第二句话。"

    async def play(session_id: str, segment: AudioSegment) -> None:
        del session_id
        played.append(segment.wav.decode())

    pipe = VoicePipeline(
        llm_callback=llm,
        asr=FakeASR(),
        tts=_RecordingTTS(),
        play_callback=play,
        asr_lock_cool_ms=0,
        segment_streaming=False,
    )
    pipe._audio["s"] = [_SPEECH_STUB]
    await pipe.on_speech_end("s")
    task = pipe._speak_tasks.get("s")
    if task is not None:
        await task
    assert played == ["第一句话。第二句话。"]  # 单段


@pytest.mark.asyncio
async def test_interrupt_discards_inflight_segments() -> None:
    """打断后：在途/未播段全部作废（epoch 丢弃 + task cancel），不播放任何段。"""
    played: list[str] = []
    release = asyncio.Event()

    async def llm(text: str, session_id: str) -> str:
        del session_id
        return "第一句话。第二句话。"

    class SlowTTS:
        async def synthesize_segment(self, text: str) -> AudioSegment:
            await release.wait()  # 所有段都慢：制造"在途"状态
            return AudioSegment(
                wav=text.encode(), sample_rate=24000, volumes=[], slice_ms=20
            )

    async def play(session_id: str, segment: AudioSegment) -> None:
        del session_id
        played.append(segment.wav.decode())

    pipe = VoicePipeline(
        llm_callback=llm,
        asr=FakeASR(),
        tts=SlowTTS(),
        play_callback=play,
        asr_lock_cool_ms=0,
    )
    pipe._audio["s"] = [_SPEECH_STUB]
    await pipe.on_speech_end("s")  # _speak 进入 wait_next 等待
    await asyncio.sleep(0.01)
    pipe.interrupt("s")  # 打断（取消 _speak + epoch++）
    release.set()  # 让在途合成返回（应被 epoch 丢弃）
    await asyncio.sleep(0.05)
    assert played == []


# ---- Scenario：S52 输出语言解耦（展示语言 / 朗读语言分开） -------------------


class _FakeRenderer:
    """假渲染器：不发 LLM 请求，只加可辨认前缀并记录调用（便于断言"渲染发生在哪一层"）。"""

    def __init__(self, mode: str = "sentence") -> None:
        self.mode = mode
        self.display_calls: list[str] = []
        self.speak_calls: list[str] = []

    async def render_display(self, text: str) -> str:
        self.display_calls.append(text)
        return f"DISPLAY::{text}"

    async def render_speak(self, text: str) -> str:
        self.speak_calls.append(text)
        return f"SPEAK::{text}"


# 每句都 > split_sentences 的 min_len(12)，否则会被合并成一段（那测不出分句渲染）
_S1 = "这是第一句话，用来验证语言渲染的接线是否正确。"
_S2 = "这是第二句话，同样足够长以便被单独切分。"


@pytest.mark.asyncio
async def test_no_renderer_keeps_original_text() -> None:
    """回归护栏：不注入 renderer 时，送进 TTS 的就是 LLM 原文（与 S52 前一致）。"""
    tts = _RecordingTTS()

    async def llm(text: str, session_id: str) -> str:
        del text, session_id
        return f"{_S1}{_S2}"

    pipe = VoicePipeline(
        llm_callback=llm, asr=FakeASR(), tts=tts, asr_lock_cool_ms=0,
    )
    pipe._audio["s"] = [_SPEECH_STUB]
    await pipe.on_speech_end("s")
    task = pipe._speak_tasks.get("s")
    if task is not None:
        await task
    assert tts.calls == [_S1, _S2]


@pytest.mark.asyncio
async def test_renderer_decouples_display_and_speech() -> None:
    """S52：朗读走 render_speak、气泡走 render_display（同一段原文，两路出口互不影响）。"""
    events: list[tuple[str, dict]] = []
    renderer = _FakeRenderer()
    tts = _RecordingTTS()

    async def llm(text: str, session_id: str) -> str:
        del text, session_id
        return f"{_S1}{_S2}"

    async def emit(session_id: str, event_type: str, payload: dict) -> None:
        del session_id
        events.append((event_type, payload))

    pipe = VoicePipeline(
        llm_callback=llm, asr=FakeASR(), tts=tts, event_callback=emit,
        asr_lock_cool_ms=0, renderer=renderer,
    )
    pipe._audio["s"] = [_SPEECH_STUB]
    await pipe.on_speech_end("s")
    task = pipe._speak_tasks.get("s")
    if task is not None:
        await task
    # ① 送进 TTS 的每一段都是 render_speak 的结果（逐段渲染）
    #（注：渲染发生在分句之后，段落数是"分句 + S37 首段细分"的结果，故不写死段数）
    assert tts.calls, "应有段送进 TTS"
    assert all(call.startswith("SPEAK::") for call in tts.calls)
    assert "".join(call[len("SPEAK::"):] for call in tts.calls) == f"{_S1}{_S2}"
    assert renderer.speak_calls
    # ② 气泡文本是 render_display 的结果，且带上内部中文原文
    llm_text = [p for t, p in events if t == "llm:text"][-1]
    assert llm_text["text"] == f"DISPLAY::{_S1}{_S2}"
    assert llm_text["source_text"] == f"{_S1}{_S2}"
    # ③ 逐段模式下整段 text 仍是内部原文（译文在投喂侧逐段产生），
    #    此时 display_text 与 text 相同 → 不带该字段（避免冗余）
    synth = [p for t, p in events if t == "tts:synthesize"][-1]
    assert synth["text"] == f"{_S1}{_S2}"
    assert "display_text" not in synth


@pytest.mark.asyncio
async def test_streaming_path_renders_each_sentence() -> None:
    """A1 流式路径：句子一到就渲染再入队（保住"首句先出声"）。"""
    tts = _RecordingTTS()
    renderer = _FakeRenderer()

    async def stream_llm(text: str, session_id: str, on_sentence) -> str:
        del text, session_id
        for sentence in (_S1, _S2):
            await on_sentence(sentence)
        return f"{_S1}{_S2}"

    pipe = VoicePipeline(
        asr=FakeASR(), tts=tts, asr_lock_cool_ms=0,
        sentence_llm_callback=stream_llm, renderer=renderer,
    )
    pipe._audio["s"] = [_SPEECH_STUB]
    await pipe.on_speech_end("s")
    task = pipe._speak_tasks.get("s")
    if task is not None:
        await task
    assert tts.calls == [f"SPEAK::{_S1}", f"SPEAK::{_S2}"]
    assert renderer.speak_calls == [_S1, _S2]


@pytest.mark.asyncio
async def test_full_mode_renders_whole_reply_once() -> None:
    """整段模式：整段渲染**一次**，再按译文分句合成（不重复渲染）。"""
    tts = _RecordingTTS()
    renderer = _FakeRenderer(mode="full")

    async def llm(text: str, session_id: str) -> str:
        del text, session_id
        return f"{_S1}{_S2}"

    pipe = VoicePipeline(
        llm_callback=llm, asr=FakeASR(), tts=tts, asr_lock_cool_ms=0, renderer=renderer,
    )
    pipe._audio["s"] = [_SPEECH_STUB]
    await pipe.on_speech_end("s")
    task = pipe._speak_tasks.get("s")
    if task is not None:
        await task
    assert renderer.speak_calls == [f"{_S1}{_S2}"]  # 只渲染整段一次
    # 送进 TTS 的仍是**同一份整段译文**（只是被分句后逐段先播，顺序不变）
    assert "".join(tts.calls) == f"SPEAK::{_S1}{_S2}"


@pytest.mark.asyncio
async def test_interrupt_during_render_discards_translation() -> None:
    """渲染期间被打断：译文与音频一起作废（不会冒出上一句的旧语言）。"""
    played: list[str] = []
    release = asyncio.Event()

    class SlowRenderer(_FakeRenderer):
        async def render_speak(self, text: str) -> str:
            await release.wait()  # 渲染慢：制造"在途译文"
            return await super().render_speak(text)

    class SlowTTS:
        async def synthesize_segment(self, text: str) -> AudioSegment:
            return AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[], slice_ms=20)

    async def llm(text: str, session_id: str) -> str:
        del text, session_id
        return f"{_S1}{_S2}"

    async def play(session_id: str, segment: AudioSegment) -> None:
        del session_id
        played.append(segment.wav.decode())

    pipe = VoicePipeline(
        llm_callback=llm, asr=FakeASR(), tts=SlowTTS(), play_callback=play,
        asr_lock_cool_ms=0, renderer=SlowRenderer(),
    )
    pipe._audio["s"] = [_SPEECH_STUB]
    await pipe.on_speech_end("s")
    await asyncio.sleep(0.01)
    pipe.interrupt("s")  # 渲染还没回来就打断
    release.set()  # 让在途渲染返回（应被丢弃）
    await asyncio.sleep(0.05)
    assert played == []
