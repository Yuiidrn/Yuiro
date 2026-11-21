"""S03：真 Barge-in —— 取消传播（Scenario，Fake 组件，不加载真实模型）。

对应 docs/plan/S03-real-barge-in.md。
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from yuiro.audio import AudioSegment, VADEvent, VoicePipeline
from yuiro.runtime.session import SessionManager


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
        return self.events.pop(0) if self.events else VADEvent.Silence

    def reset(self) -> None:
        self.events.clear()


# 0.5s 静音（16k / mono / int16）—— 送进 on_speech_end 的假音频。
#
# ⚠ 必须够长，这不是凑数：`on_speech_end` 有一条"**极短音频不送识别**"的防护
#   （<0.25s 直接 return，见 yuiro/audio/__init__.py 的「噪音防护①」）。
#   用 `[b"\x00\x00"]`（1 采样）这种假数据，回合会在**识别之前就 return**，
#   于是测试里那段"等 LLM 启动"的 await **永远不会被唤醒** —— 表现为测试**挂死**
#   （而不是失败）。全量回归之所以还能跑完，只是靠 pytest-timeout 兜底，
#   代价是白白拖长整个测试时间。
_SPEECH_STUB = np.zeros(8000, dtype=np.int16).tobytes()


# ---- Unit：SessionManager.cancel（统一入口语义） -----------------------------


def test_session_cancel_bumps_generation() -> None:
    """S03：SessionManager.cancel 是统一入口（代际作废）；不存在时返回 0。"""
    mgr = SessionManager()
    s = mgr.attach_control(object())
    assert mgr.cancel(s.session_id, "barge-in") == 1
    assert s.generation == 1
    assert mgr.cancel("不存在", "x") == 0


# ---- Scenario：打断立即取消 LLM 回合并通知前端 --------------------------------


@pytest.mark.asyncio
async def test_interrupt_cancels_llm_turn_and_emits_interrupted() -> None:
    """S03 核心：打断立即取消 LLM 回合（不进入 TTS）并发出 tts:interrupted。"""
    events: list[tuple[str, dict]] = []
    llm_started = asyncio.Event()
    llm_finished = False

    async def cb(session_id: str, event_type: str, payload: dict) -> None:
        del session_id
        events.append((event_type, payload))

    async def play(session_id: str, segment: AudioSegment) -> None:
        del session_id, segment

    async def llm(text: str, session_id: str) -> str:
        nonlocal llm_finished
        del text, session_id
        llm_started.set()
        await asyncio.Event().wait()  # 永久阻塞：模拟长 LLM 请求
        llm_finished = True
        return "不应出现"

    pipe = VoicePipeline(
        llm_callback=llm,
        asr=FakeASR(),
        tts=FakeTTS(),
        play_callback=play,
        event_callback=cb,
        asr_lock_cool_ms=0,
    )
    pipe._audio["s"] = [_SPEECH_STUB]
    turn = asyncio.create_task(pipe.on_speech_end("s"))
    # ⚠ 必须带超时：这是"等外部条件被满足"的等待，一旦上游（如"极短音频不送识别"）
    #   让它永远不会被 set，无超时的 wait 会让整个测试**永久挂起**、拖死整个测试会话。
    #   宁可 2 秒后明确失败，也不要挂死 —— 这才是能被发现的失败。
    await asyncio.wait_for(llm_started.wait(), timeout=2.0)

    pipe.interrupt("s")
    await asyncio.wait_for(turn, timeout=1.0)  # 回合应立即结束（而非等 LLM 返回）
    await asyncio.sleep(0.01)  # 等待 fire-and-forget 事件发出

    assert any(e[0] == "tts:interrupted" for e in events)
    assert llm_finished is False  # LLM 未跑完（被取消）
    assert pipe._turn_tasks.get("s") is None  # 回合登记已清理
    assert pipe._speak_tasks.get("s") is None  # 未进入 TTS


@pytest.mark.asyncio
async def test_pipeline_usable_after_interrupt() -> None:
    """打断后同一 session 可继续下一轮（不卡死、能正常出声）。"""
    played: list[str] = []

    async def llm(text: str, session_id: str) -> str:
        del session_id
        return f"回复:{text}"

    async def play(session_id: str, segment: AudioSegment) -> None:
        del session_id
        played.append(segment.wav.decode())

    pipe = VoicePipeline(
        llm_callback=llm,
        asr=FakeASR(),
        tts=FakeTTS(),
        play_callback=play,
        asr_lock_cool_ms=0,
    )
    # 第一轮：正常完成后再打断（幂等）
    pipe._audio["s"] = [_SPEECH_STUB]
    await pipe.on_speech_end("s")
    t1 = pipe._speak_tasks.get("s")
    if t1 is not None:
        await asyncio.wait_for(t1, timeout=2.0)  # 同上：带超时，避免挂死
    pipe.interrupt("s")

    # 第二轮：应正常完成
    pipe._audio["s"] = [_SPEECH_STUB]
    await pipe.on_speech_end("s")
    t2 = pipe._speak_tasks.get("s")
    if t2 is not None:
        await asyncio.wait_for(t2, timeout=2.0)
    assert played and played[-1] == "回复:你好"


@pytest.mark.asyncio
async def test_barge_in_callback_preferred_over_local_interrupt() -> None:
    """注入 barge_in_callback 时，VAD SpeechStart 走统一入口（不走本地 interrupt）。"""
    called: list[str] = []

    def on_barge(session_id: str) -> None:
        called.append(session_id)

    # 打断总开关**默认关闭** → 这个测试要显式打开才会走 barge-in 路径
    pipe = VoicePipeline(
        vad=SeqVAD([VADEvent.SpeechStart]),
        barge_in_callback=on_barge,
        barge_in_enabled=True,
    )
    pipe._set_state(pipe.STATE_READY, "ready", 1.0)
    pipe._speaking["s"] = True
    await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), "s")
    assert called == ["s"]
    # 本地不再直接改状态（由统一的 _cancel_turn 路径处理）
    assert pipe._speaking["s"] is True


@pytest.mark.asyncio
async def test_barge_in_disabled_blocks_input_entirely() -> None:
    """打断关闭 = 她说话期间**完全屏蔽输入**：不打断、不收音、不排队。

    用户明确要求的效果就是半双工："屏蔽桌宠说话时的收音和请求都暂时屏蔽"。
    所以这里连音频都不该被累积 —— **不是**"录下来等她说完再回应"那种语义。
    """
    called: list[str] = []

    def on_barge(session_id: str) -> None:
        called.append(session_id)

    pipe = VoicePipeline(vad=SeqVAD([VADEvent.SpeechStart]), barge_in_callback=on_barge)
    pipe._set_state(pipe.STATE_READY, "ready", 1.0)
    pipe._speaking["s"] = True

    await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), "s")

    assert called == [], "默认关闭时不应触发打断"
    assert pipe._speaking["s"] is True, "她应当继续把话说完"
    assert not pipe._audio.get("s"), "关闭打断时她说话期间**不收音**（帧被直接丢弃）"


# ---- 护栏：打断后**不许**再白跑识别与生成（实测"卡顿/延迟严重"的根治点） ------


class _CountingASR:
    """记录 transcribe 被调用次数 —— 用来断言"这一回合确实没跑"。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def transcribe(self, audio: np.ndarray) -> str:
        del audio
        self.calls.append("asr")
        return "你好"


async def _noop_play(session_id: str, segment: AudioSegment) -> None:
    del session_id, segment


@pytest.mark.asyncio
async def test_stale_generation_is_dropped_before_asr() -> None:
    """代际过期 → `on_speech_end` 拿到锁后立刻丢弃，**一次 ASR 都不跑**。

    这是"打断之后她还在忙、回复迟迟不来"的根治点：SpeechEnd 任务在**等锁期间**
    还没把自己的 LLM 回合登记进 `_turn_tasks`，所以 `interrupt()` 取消不到它；
    没有代际守卫，它拿到锁后就会白跑一遍 ASR + LLM + TTS。
    """
    asr = _CountingASR()
    pipe = VoicePipeline(asr=asr, tts=FakeTTS(), play_callback=_noop_play, asr_lock_cool_ms=0)
    pipe._audio["s"] = [_SPEECH_STUB]
    pipe._turn_gen["s"] = 2  # 假装派发之后发生过一次打断

    await pipe.on_speech_end("s", gen=0)  # 带着**过期**代际进入

    assert asr.calls == []  # 关键：没有白跑识别


@pytest.mark.asyncio
async def test_spawned_turn_dropped_after_interrupt() -> None:
    """真实派发路径：`_spawn_speech_end` 之后立刻打断 → 该任务作废、不跑 ASR。"""
    asr = _CountingASR()
    pipe = VoicePipeline(asr=asr, tts=FakeTTS(), play_callback=_noop_play, asr_lock_cool_ms=0)
    pipe._audio["s"] = [_SPEECH_STUB]

    pipe._spawn_speech_end("s")
    pipe.interrupt("s")  # 派发即打断（等锁中的任务此时不在 _turn_tasks 里，取消不到）
    await asyncio.sleep(0.05)  # 给任务落地（被取消，或自行按代际丢弃）

    assert asr.calls == []
