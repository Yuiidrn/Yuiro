"""Preset voices remain role-configurable without changing clone payloads."""
import httpx
import pytest

from yuiro.audio.providers import SiliconFlowProvider
from yuiro.config import FIELD_META, TTSConfig


def test_preset_voice_config_metadata():
    assert TTSConfig().siliconflow_voice == SiliconFlowProvider.FALLBACK_VOICE
    assert ":" in TTSConfig().siliconflow_voice
    assert "siliconflow_voice" in FIELD_META["tts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("clone", [False, True])
async def test_preset_and_clone_payloads_are_exclusive(monkeypatch, clone):
    captured = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, *, headers, json):
            captured.append(json)
            return httpx.Response(200, content=b"wav", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    voice = "FunAudioLLM/CosyVoice2-0.5B:claire"
    provider = SiliconFlowProvider(api_key="test", voice=voice)
    if clone:
        provider._reference_data_url = "data:audio/wav;base64,dGVzdA=="
    assert await provider._synth_one("你好") == b"wav"
    payload = captured[0]
    assert ("references" in payload) is clone
    assert ("voice" in payload) is not clone
    if not clone:
        assert payload["voice"] == voice
