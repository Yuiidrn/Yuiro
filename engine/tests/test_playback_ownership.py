"""已下发完但前端仍播放时，仍属于可打断的语音占用。"""
import numpy as np
import pytest

from yuiro.audio import VADEvent, VoicePipeline
from yuiro.audio.playback import PlaybackLeases


def test_late_duplicate_and_foreign_receipts_cannot_release_successor():
    leases = PlaybackLeases()
    old = leases.offer('s', 'hotaru', 1, 2)
    new = leases.offer('s', 'hotaru', 2, 3)
    assert not leases.receipt('s', {**new, 'character_id': 'hiyori',
                                   'type': 'audio:playback_finished'})
    assert not leases.receipt('other', {**new, 'type': 'audio:playback_finished'})
    assert leases.receipt('s', {**old, 'type': 'audio:playback_finished'})
    assert not leases.receipt('s', {**old, 'type': 'audio:playback_finished'})
    assert leases.busy('s')
    assert leases.receipt('s', {**new, 'type': 'audio:playback_finished'})
    assert not leases.busy('s')


def test_lost_receipts_expire_and_disconnect_cleanup_is_session_scoped():
    now = [0.0]
    leases = PlaybackLeases(clock=lambda: now[0])
    leases.offer('s', 'hotaru', 1, 2)
    leases.offer('s', 'hotaru', 1, 3)
    leases.offer('other', 'hiyori', 1, 20)
    now[0] = 14
    assert leases.busy('s')
    now[0] = 15
    assert not leases.busy('s')
    assert leases.busy('other')
    leases.clear('s')
    assert leases.busy('other')
    leases.clear('other')
    assert not leases.busy('other')


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True])
async def test_vad_while_generation_finished_but_renderer_has_audio(enabled):
    class VAD:
        def feed(self, chunk):
            return VADEvent.SpeechStart

    called = []
    pipe = VoicePipeline(vad=VAD(), barge_in_enabled=enabled,
                         barge_in_callback=lambda sid: called.append(sid))
    pipe._set_state(pipe.STATE_READY, 'ready', 1)
    pipe._speaking['s'] = False  # 合成和下发已结束，SDK队列仍有一段。
    pipe.playback.offer('s', 'hotaru', 1, 4)
    await pipe.on_audio(np.zeros(512, dtype=np.int16).tobytes(), 's')
    assert called == (['s'] if enabled else [])
    if not enabled:
        assert not pipe._audio.get('s')
    pipe.interrupt('s')
    assert not pipe.playback.busy('s')


@pytest.mark.asyncio
@pytest.mark.parametrize('send_fails', [False, True])
async def test_production_audio_adapter_registers_before_send_and_releases_failure(monkeypatch, send_fails):
    import ast
    import base64
    import io
    import wave
    from pathlib import Path
    from types import SimpleNamespace

    from yuiro import approval
    from yuiro.audio import AudioSegment

    leases = PlaybackLeases()
    frames = []

    class WS:
        async def send_json(self, frame):
            assert leases.busy('s'), '登记必须发生在发送前，不能漏掉快速回执'
            if send_fails:
                raise RuntimeError('disconnected')
            frames.append(frame)

    monkeypatch.setattr(approval, 'get_audio_conn', lambda sid: WS())
    state = SimpleNamespace(sessions=SimpleNamespace(get=lambda sid: SimpleNamespace(generation=7)),
                            app_config=SimpleNamespace(_character_id='hotaru'),
                            voice_pipeline=SimpleNamespace(playback=leases))
    source = Path(__file__).parents[1] / 'yuiro/main.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == '_play_audio')
    namespace = {'AudioSegment': AudioSegment, 'app': SimpleNamespace(state=state),
                 'base64': base64, 'vlog': lambda *args: None}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)  # noqa: S102 — 执行仓库函数，避免main启动模型
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * 1600)
    await namespace['_play_audio']('s', AudioSegment(wav=buf.getvalue(), sample_rate=16000,
                                                   volumes=[], slice_ms=20))
    assert leases.busy('s') is not send_fails
    if frames:
        assert frames[0]['character_id'] == 'hotaru'
        assert frames[0]['generation'] == 7
        assert leases.receipt('s', {**frames[0], 'type': 'audio:playback_finished'})
        assert not leases.busy('s')
