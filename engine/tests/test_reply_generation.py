"""执行生产_speak_reply函数，不导入会启动模型的main模块。"""
import ast
import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from yuiro.audio import AudioSegment


def harness():
    source = Path(__file__).parents[1] / "yuiro" / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_speak_reply")
    generation = {"value": 1}
    frames = []

    async def synthesize(tts, text):
        return AudioSegment(wav=b"wave", sample_rate=24000, volumes=[.1], slice_ms=20)

    class WS:
        async def send_json(self, frame):
            frames.append(frame)

    namespace = {
        "WebSocket": object, "asyncio": asyncio, "base64": base64,
        "app": SimpleNamespace(state=SimpleNamespace(
            app_config=SimpleNamespace(tts=SimpleNamespace(reply_tts_enabled=True)),
            voice_pipeline=SimpleNamespace(_tts=object()),
        )),
        "_avatar_generation": lambda sid: generation["value"],
        "_synthesize_reply_sentence": synthesize,
        "split_sentences": lambda text: [text], "vlog": lambda *args: None,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)  # noqa: S102 — 编译仓库函数，避免启动模型
    return namespace, generation, frames, WS()


@pytest.mark.asyncio
async def test_reply_frames_carry_frozen_generation():
    ns, _generation, frames, ws = harness()
    await ns["_speak_reply"](ws, "session", "你好。", generation=1)
    assert [f["type"] for f in frames] == ["tts:reply_audio", "tts:reply_end"]
    assert all(f["session_id"] == "session" and f["generation"] == 1 for f in frames)


@pytest.mark.asyncio
async def test_late_synthesis_cannot_emit_old_audio_or_end():
    ns, generation, frames, ws = harness()
    original = ns["_synthesize_reply_sentence"]

    async def delayed(tts, text):
        generation["value"] = 2
        return await original(tts, text)

    ns["_synthesize_reply_sentence"] = delayed
    await ns["_speak_reply"](ws, "session", "你好。", generation=1)
    assert frames == []


@pytest.mark.asyncio
async def test_reply_cancellation_propagates_without_end_frame():
    ns, _generation, frames, ws = harness()

    async def cancelled(tts, text):
        raise asyncio.CancelledError

    ns["_synthesize_reply_sentence"] = cancelled
    with pytest.raises(asyncio.CancelledError):
        await ns["_speak_reply"](ws, "session", "你好。", generation=1)
    assert frames == []


@pytest.mark.asyncio
async def test_unloaded_session_drops_pending_reply():
    ns, generation, frames, ws = harness()
    generation["value"] = None
    await ns["_speak_reply"](ws, "session", "你好。", generation=1)
    assert frames == []


@pytest.mark.asyncio
async def test_reply_stream_sends_prefix_then_closes_on_generation_change():
    ns, generation, frames, ws = harness()
    gate, first_sent, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Provider:
        async def synthesize_stream(self, text):
            try:
                yield AudioSegment(wav=b'prefix', sample_rate=24000, volumes=[], streaming=True)
                first_sent.set()
                await gate.wait()
                yield AudioSegment(wav=b'stale-tail', sample_rate=24000, volumes=[], streaming=True)
            finally:
                closed.set()

    provider = Provider()
    ns['app'].state.voice_pipeline._tts = provider
    source = Path(__file__).parents[1] / 'yuiro/main.py'
    helpers = [n for n in ast.parse(source.read_text(encoding='utf-8')).body
               if isinstance(n, ast.AsyncFunctionDef)
               and n.name in ('_synthesize_reply_sentence', '_render_reply_sentence')]
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(source), 'exec'), ns)  # noqa: S102
    task = asyncio.create_task(ns['_speak_reply'](ws, 'session', '你好。', generation=1))
    try:
        await asyncio.wait_for(first_sent.wait(), 1)
        assert len(frames) == 1 and frames[0]['streaming'] is True
        assert frames[0]['type'] == 'tts:reply_audio'
        generation['value'] = 2
        gate.set()
        await asyncio.wait_for(task, 1)
        assert len(frames) == 1, '旧尾片和结束帧都不能下发'
        assert closed.is_set(), '换代后必须关闭HTTP迭代器'
    finally:
        gate.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
