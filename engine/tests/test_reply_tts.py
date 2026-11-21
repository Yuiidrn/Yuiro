"""统一「语音回复 TTS」开关（tts.reply_tts_enabled）——Unit 级护栏。

覆盖：
- 配置默认值与 FIELD_META 登记（调试台/聊天坞同一份 schema）；
- VoicePipeline 在开关关闭时**跳过合成**但仍发 tts:end 收尾（保留文字回复、不卡 UI）；
- 开关开启（默认）时照常合成（回归护栏：不破坏既有语音链路）。

不加载真实模型：VoicePipeline 用 Fake TTS / 事件回调。
"""
from __future__ import annotations

import pytest

from yuiro.audio import AudioSegment, VoicePipeline
from yuiro.config import FIELD_META, TTSConfig


class _RecordingTTS:
    """记录合成调用，返回带 wav 的最小 AudioSegment。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def synthesize_segment(self, text: str) -> AudioSegment:
        self.calls.append(text)
        return AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[0.1], slice_ms=20)


# ---- 配置默认值 / 元数据 ---------------------------------------------------


def test_reply_tts_defaults_to_enabled() -> None:
    """默认开启（保持现状：语音输入回复出声，文字输入回复新增出声）。"""
    assert TTSConfig().reply_tts_enabled is True


def test_reply_tts_registered_in_field_meta() -> None:
    """FIELD_META 里登记了 tts.reply_tts_enabled（调试台表单 / 聊天坞读的是同一份 schema）。"""
    meta = FIELD_META.get("tts", {}).get("reply_tts_enabled")
    assert meta is not None
    assert meta["type"] == "bool"


# ---- VoicePipeline：开关关闭 → 跳过合成但正常收尾 ---------------------------


@pytest.mark.asyncio
async def test_pipeline_skips_synthesis_when_switch_off() -> None:
    tts = _RecordingTTS()
    events: list[tuple[str, dict]] = []

    async def emit(session_id: str, event_type: str, payload: dict) -> None:
        del session_id
        events.append((event_type, payload))

    pipe = VoicePipeline(
        asr=None,
        tts=tts,
        event_callback=emit,
        asr_lock_cool_ms=0,
        reply_tts_enabled=lambda: False,
    )
    await pipe._speak("s", "你好，世界。")
    # 开关关闭：绝不调 provider 合成（不出声）
    assert tts.calls == []
    # 但必须发 tts:end 收尾（前端靠它复位回合状态，否则 UI 卡在"合成中"）
    assert ("tts:end", {}) in events
    # 不产生任何"要开始合成"的事件
    assert not any(ev == "tts:start" for ev, _ in events)


@pytest.mark.asyncio
async def test_pipeline_synthesizes_when_switch_on() -> None:
    """开关开启（默认路径）时照常合成——回归护栏。"""
    tts = _RecordingTTS()
    events: list[tuple[str, dict]] = []

    async def emit(session_id: str, event_type: str, payload: dict) -> None:
        del session_id
        events.append((event_type, payload))

    pipe = VoicePipeline(
        asr=None,
        tts=tts,
        event_callback=emit,
        asr_lock_cool_ms=0,
        reply_tts_enabled=lambda: True,
    )
    await pipe._speak("s", "你好，世界。")
    assert tts.calls != []
    assert any(ev == "tts:start" for ev, _ in events)
    assert ("tts:end", {}) in events
