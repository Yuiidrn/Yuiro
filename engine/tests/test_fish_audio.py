"""Fish HTTP 契约、安全存储、角色隔离与取消回归（不调用云服务）。"""
import asyncio
import io
import wave
from dataclasses import asdict

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yuiro.audio import TTSTaskManager
from yuiro.audio.fish import FishAudioProvider, build_fish_provider, finalize_wav
from yuiro.characters import CharacterStore
from yuiro.config import AppConfig, save_config
from yuiro.debug_api import router


def wav_bytes():
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\0\0" * 4410)
    return out.getvalue()


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        **kw, transport=httpx.MockTransport(handler)))


def test_streaming_wav_header_is_finalized_without_changing_samples():
    import struct
    original = wav_bytes()
    streamed = bytearray(original)
    struct.pack_into("<I", streamed, 4, 0xFFFFFF24)
    struct.pack_into("<I", streamed, 40, 0xFFFFFF00)
    result = finalize_wav(bytes(streamed))
    assert result == original
    with wave.open(io.BytesIO(result)) as audio:
        assert audio.getnframes() == 4410


@pytest.mark.parametrize("body", [b"", b"{}", b"RIFF" + b"\0" * 60])
def test_invalid_wav_rejected(body):
    with pytest.raises(RuntimeError):
        finalize_wav(body)


@pytest.mark.asyncio
async def test_request_contract_and_rms(monkeypatch):
    import json
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=wav_bytes())

    mock_http(monkeypatch, handler)
    provider = FishAudioProvider(reference_id="hotaru-id", key_loader=lambda: "secret")
    segment = await provider.synthesize_segment("你好。")
    body = json.loads(calls[0].content)
    assert calls[0].headers["model"] == "s2.1-pro"
    assert calls[0].headers["authorization"] == "Bearer secret"
    assert body["reference_id"] == "hotaru-id"
    assert body["format"] == "wav" and "references" not in body
    assert segment.sample_rate == 44100 and segment.volumes


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 403, 429, 500, 503])
async def test_errors_are_sanitized_and_not_retried(monkeypatch, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, content=b"secret echoed non-json edge error")

    mock_http(monkeypatch, handler)
    with pytest.raises(RuntimeError, match=f"Fish HTTP {status}") as error:
        await FishAudioProvider(reference_id="id", key_loader=lambda: "secret")._synthesize_audio("text")
    assert "secret" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cancel_closes_http_and_no_late_tts_delivery(monkeypatch):
    entered, closed = asyncio.Event(), asyncio.Event()

    async def handler(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    mock_http(monkeypatch, handler)
    provider = FishAudioProvider(reference_id="id", key_loader=lambda: "secret")
    manager = TTSTaskManager(provider)
    task = asyncio.create_task(manager.enqueue(1, "旧角色语音"))
    await entered.wait()
    task.cancel()
    await manager.interrupt()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and not manager._buffer


@pytest.mark.asyncio
async def test_missing_key_or_voice_no_request():
    with pytest.raises(RuntimeError, match="Key 未配置"):
        await FishAudioProvider(reference_id="id", key_loader=lambda: None)._synthesize_audio("text")
    with pytest.raises(RuntimeError, match="音色 ID"):
        await FishAudioProvider(reference_id="", key_loader=lambda: "secret")._synthesize_audio("text")


def test_role_roundtrip_and_restart_preserve_hiyori(tmp_path):
    cfg = AppConfig()
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    store = CharacterStore(path)
    store.ensure(cfg)
    before = (store.root / "hiyori.toml").read_bytes()
    hotaru = store.resolve("hotaru", cfg)
    hotaru.tts.provider = "fish"
    hotaru.tts.fish_reference_id = "ad0099b0c27a470eb2a11e9a37b14e4c"
    hotaru.tts.fish_transport = 'websocket'
    store.save("hotaru", hotaru)
    assert (store.root / "hiyori.toml").read_bytes() == before
    assert store.resolve("hiyori", hotaru).tts.provider == cfg.tts.provider
    restored = CharacterStore(path).resolve("hotaru", cfg)
    assert restored.tts.fish_reference_id == hotaru.tts.fish_reference_id
    assert restored.tts.fish_transport == 'websocket'
    assert store.resolve('hiyori', hotaru).tts.fish_transport == 'http'
    assert isinstance(build_fish_provider(restored.tts), FishAudioProvider)
    assert not any("fish" in k and "key" in k for k in asdict(restored.tts))


def test_key_api_authenticated_no_echo_no_config(monkeypatch):
    from yuiro import keychain
    saved = []
    monkeypatch.setattr(keychain, "save_fish_key", lambda key: saved.append(key) or True)
    monkeypatch.setattr(keychain, "load_fish_key", lambda: saved[-1] if saved else None)
    monkeypatch.setattr(keychain, "clear_fish_key", lambda: saved.clear() or True)
    app = FastAPI()
    app.state.app_config = AppConfig()
    app.state.app_config.server.shared_secret = "local-test-auth"
    app.include_router(router)
    client = TestClient(app)
    endpoint = "/api/providers/fish/key"
    assert client.put(endpoint, json={"key": "secret"}).status_code == 401
    headers = {"x-yuiro-secret": app.state.app_config.server.shared_secret}
    response = client.put(endpoint, headers=headers, json={"key": "secret"})
    assert response.status_code == 200 and "secret" not in response.text
    assert client.get(endpoint, headers=headers).json()["status"] == "set"
    assert client.delete(endpoint, headers=headers).json()["status"] == "unset"
    assert "fish_key" not in asdict(app.state.app_config.tts)


def test_key_store_failure_is_explicit(monkeypatch):
    from yuiro import keychain
    monkeypatch.setattr(keychain, "save_fish_key", lambda key: False)
    app = FastAPI()
    app.state.app_config = AppConfig()
    app.state.app_config.server.shared_secret = "local-test-auth"
    app.include_router(router)
    response = TestClient(app).put("/api/providers/fish/key", json={"key": "secret"},
        headers={"x-yuiro-secret": app.state.app_config.server.shared_secret})
    assert response.status_code == 503 and "secret" not in response.text
