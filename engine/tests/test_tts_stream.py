"""A1：LLM 流式接 TTS —— 句子一到就合成，首句不必等整段回复。

**为什么这个改动值得测试**：它是"用户最能直接感知"的一条延迟优化。
此前链路是 ``await LLM(完整回复) → 分句 → TTS``，首句出声 =
**LLM 全量耗时 + TTS 首段耗时**；一段 120 字的回复要好几秒，而用户其实
听到第一句就够了。

核心断言只有一条，但它就是这件事的全部意义：

> **第一句必须在句子流"尚未结束"时就已经播出去。**

若这条不成立（例如播放侧要等流结束才开始），
那这个"流式"就只是换了个写法，收益为零。

另外钉住两个易错点：
- ``TTSTaskManager.finish()``：流式路径句子数未知，缺了这个结束信号，
  ``wait_next`` 会**永久挂住**（表现为"说话没声音也不报错"）；
- ``interrupt()`` 后 ``_done`` 必须复位（manager 声明可复用）。
"""
from __future__ import annotations

import asyncio

import pytest

from yuiro.audio import AudioSegment, TTSTaskManager, VoicePipeline


class _RecordingTTS:
    """把合成结果编码成文本，便于断言播放顺序。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def synthesize_segment(self, text: str) -> AudioSegment:
        self.calls.append(text)
        return AudioSegment(
            wav=text.encode("utf-8"), sample_rate=24000, volumes=[], slice_ms=20
        )


# ---- TTSTaskManager：结束信号 -------------------------------------------------
@pytest.mark.asyncio
async def test_wait_next_returns_none_after_finish() -> None:
    """finish 之后 wait_next 必须返回 None，而不是永远等一个不会来的 seq。"""
    mgr = TTSTaskManager(_RecordingTTS())
    await mgr.enqueue(1, "甲")
    first = await mgr.wait_next()
    assert first is not None and first.wav.decode() == "甲"
    await mgr.finish()
    assert await asyncio.wait_for(mgr.wait_next(), timeout=1) is None


@pytest.mark.asyncio
async def test_interrupt_resets_done_flag() -> None:
    """interrupt 后 manager 可复用（_done 必须复位，否则复用时会立刻返回 None）。"""
    mgr = TTSTaskManager(_RecordingTTS())
    await mgr.finish()
    await mgr.interrupt()
    await mgr.enqueue(1, "乙")
    seg = await asyncio.wait_for(mgr.wait_next(), timeout=1)
    assert seg is not None and seg.wav.decode() == "乙"


# ---- ★ 核心：首句在流结束前播出 ----------------------------------------------
@pytest.mark.asyncio
async def test_first_sentence_plays_before_stream_ends() -> None:
    """★ 第一句必须在句子流**尚未结束**时就播出去（这就是 A1 的全部意义）。"""
    gate = asyncio.Event()
    stream_state: list[str] = []

    async def sentences():
        yield "第一句。"
        stream_state.append("awaiting-second")
        await gate.wait()  # 第二句迟迟不来 —— 模拟 LLM 还在生成
        yield "第二句。"
        stream_state.append("done")

    played: list[str] = []

    async def play(_sid: str, segment: AudioSegment) -> None:
        played.append(segment.wav.decode("utf-8"))

    pipe = VoicePipeline(
        vad=None, asr=None, tts=_RecordingTTS(), play_callback=play,
        asr_lock_cool_ms=0,
    )
    task = asyncio.create_task(pipe._speak_stream("s", sentences()))

    for _ in range(200):
        if played:
            break
        await asyncio.sleep(0.01)

    assert played == ["第一句。"], (
        "第一句必须在句子流结束前播出；若为空，说明播放侧仍在等整段回复 —— "
        "那样流式就白做了"
    )
    assert stream_state == ["awaiting-second"], (
        f"此刻句子流应仍处于等待第二句的状态，实际 {stream_state}"
    )
    assert not task.done(), "句子流未结束，播放任务不应提前结束"

    gate.set()
    await asyncio.wait_for(task, timeout=5)
    assert played == ["第一句。", "第二句。"]
    assert stream_state == ["awaiting-second", "done"]


@pytest.mark.asyncio
async def test_stream_path_cleans_up_and_unlocks() -> None:
    """流式路径结束后：ASR 锁释放、speaking 复位（否则麦克风会被永久锁住）。"""

    async def sentences():
        yield "只有一句。"

    pipe = VoicePipeline(
        vad=None, asr=None, tts=_RecordingTTS(), play_callback=lambda *_: asyncio.sleep(0),
        asr_lock_cool_ms=0,
    )
    await asyncio.wait_for(pipe._speak_stream("s", sentences()), timeout=5)
    assert pipe._speaking["s"] is False
    assert pipe._asr_locked["s"] is False
    assert "s" not in pipe._tts_managers


@pytest.mark.asyncio
async def test_sentence_split_thresholds() -> None:
    """整段路径的分句仍走原策略（首段偏长时再切一刀，决定 TTFA）。"""
    pipe = VoicePipeline(vad=None, asr=None, tts=_RecordingTTS(), asr_lock_cool_ms=0)
    # 长首段应被进一步切分（_FIRST_SEG_MAX=28）
    out = pipe._sentences_for("啊" * 60 + "。" + "第二句内容比较长一些。")
    assert len(out) >= 2
    assert all(len(s) <= 60 for s in out)
    # 短句保持单段
    assert pipe._sentences_for("嗯。") == ["嗯。"]


class _SlowTTS:
    """合成有真实延迟 —— 用来暴露 finish 时序竞态。

    此前的 `_RecordingTTS` 瞬间返回，掩盖了一个 bug：fire-and-forget 的 enqueue
    还没合成完就被 `finish` 掐断，真实 CosyVoice（几百 ms）下表现就是 0B 无声音。
    """

    def __init__(self, delay: float = 0.03) -> None:
        self._delay = delay

    async def synthesize_segment(self, text: str) -> AudioSegment:
        await asyncio.sleep(self._delay)
        return AudioSegment(
            wav=text.encode("utf-8"), sample_rate=24000, volumes=[], slice_ms=20
        )


@pytest.mark.asyncio
async def test_speak_plays_all_segments_with_slow_synthesis() -> None:
    """★ 回归护栏：合成有延迟时，所有段都必须被播放（不能 0B）。"""
    played: list[str] = []

    async def play(_sid: str, segment: AudioSegment) -> None:
        played.append(segment.wav.decode("utf-8"))

    pipe = VoicePipeline(
        vad=None, asr=None, tts=_SlowTTS(0.03), play_callback=play, asr_lock_cool_ms=0
    )
    # 句子要足够长：split_sentences 的 min_len=12 会把短句合并成一段（那不是我们要测的）
    await asyncio.wait_for(
        pipe._speak(
            "s",
            "这是第一句足够长的测试内容。这是第二句足够长的测试内容。这是第三句足够长的测试内容。",
        ),
        timeout=5,
    )
    assert played == [
        "这是第一句足够长的测试内容。",
        "这是第二句足够长的测试内容。",
        "这是第三句足够长的测试内容。",
    ], f"应播放全部 3 段，实际 {played}"


@pytest.mark.asyncio
async def test_speak_stream_plays_with_slow_synthesis() -> None:
    """流式路径同样必须等合成完成（同一竞态的另一半）。"""

    async def sentences():
        yield "第一句。"
        yield "第二句。"

    played: list[str] = []

    async def play(_sid: str, segment: AudioSegment) -> None:
        played.append(segment.wav.decode("utf-8"))

    pipe = VoicePipeline(
        vad=None, asr=None, tts=_SlowTTS(0.03), play_callback=play, asr_lock_cool_ms=0
    )
    await asyncio.wait_for(pipe._speak_stream("s", sentences()), timeout=5)
    assert played == ["第一句。", "第二句。"]
