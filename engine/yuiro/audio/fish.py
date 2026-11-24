"""Fish HTTP 句级适配器；沿用 VoicePipeline 的取消、分句及 RMS 嘴型。"""
from __future__ import annotations

import asyncio
import contextlib
import struct
import time
from uuid import uuid4

import httpx
import numpy as np

from yuiro.audio.fish_transport import fish_http_client
from yuiro.audio.providers import AudioSegment, TTSProvider
from yuiro.audio.wav_stream import WavStreamSplitter
from yuiro.logger import vlog


def finalize_wav(raw: bytes) -> bytes:
    """完整 HTTP 响应的流式 WAV 长度占位符修正，避免 HTML audio 拒播。"""
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise RuntimeError("Fish 未返回有效 WAV 音频")
    data = bytearray(raw)
    struct.pack_into("<I", data, 4, len(data) - 8)
    offset = 12
    while offset + 8 <= len(data):
        size = struct.unpack_from("<I", data, offset + 4)[0]
        available = len(data) - offset - 8
        if data[offset:offset + 4] == b"data":
            if size > available:
                struct.pack_into("<I", data, offset + 4, available)
            return bytes(data)
        if size > available:
            break
        offset += 8 + size + (size % 2)
    raise RuntimeError("Fish WAV 缺少有效音频数据块")


class FishAudioProvider(TTSProvider):
    def __init__(self, *, reference_id: str, model: str = "s2.1-pro",
                 latency: str = "balanced", speed: float = 1.0,
                 segment_streaming: bool = True, key_loader=None, http_client=None,
                 transport: str = "http", first_chunk_ms: int = 400):
        super().__init__(segment_streaming=segment_streaming)
        from yuiro.keychain import load_fish_key

        if model not in {"s2.1-pro", "s2.1-pro-free", "s2-pro", "drama-3"}:
            raise ValueError("不支持的 Fish 合成引擎")
        if latency not in {"normal", "balanced", "low"} or not 0.5 <= speed <= 2.0:
            raise ValueError("Fish 延迟模式或语速无效")
        if transport not in {'http', 'websocket'}:
            raise ValueError('Fish传输方式无效')
        self.transport = transport
        if type(first_chunk_ms) is not int or not 80 <= first_chunk_ms <= 960:
            raise ValueError('Fish首块时长超出范围')
        self._first_chunk_ms = first_chunk_ms
        self._ws_session_factory = None
        if transport == 'websocket':
            # 模式装配时准备协议依赖，不在LLM/TTS首轮关键路径同步导入。
            from yuiro.audio.fish_websocket import FishWebSocketSession

            self._ws_session_factory = FishWebSocketSession
        self._reference_id = reference_id.strip()
        self._model = model
        self._latency = latency
        self._speed = speed
        # 每次请求读取安全存储，缓存角色也不会保留旧 key。
        self._key_loader = key_loader or load_fish_key
        # 外部注入仅用于显式传输验证；生命周期由调用方拥有。
        self._http_client = http_client

    def _client(self):
        return self._http_client if self._http_client is not None else fish_http_client()

    def open_sentence_session(self):
        if self.transport != 'websocket' or not self._segment_streaming:
            return None
        return self._ws_session_factory(key_loader=self._key_loader, reference_id=self._reference_id,
            model=self._model, latency=self._latency, speed=self._speed,
            first_chunk_ms=self._first_chunk_ms)

    async def _websocket_stream(self, text):
        session = self._ws_session_factory(key_loader=self._key_loader, reference_id=self._reference_id,
            model=self._model, latency=self._latency, speed=self._speed,
            first_chunk_ms=self._first_chunk_ms)

        async def texts():
            yield text

        try:
            async with contextlib.aclosing(session.stream(texts())) as stream:
                async for segment in stream:
                    yield segment
        finally:
            await session.close()

    async def synthesize_stream(self, text: str):
        """同一次HTTP响应内提前交付PCM片段，不重发或重复朗读原句。"""
        if not self._segment_streaming:
            yield await self.synthesize_segment(text)
            return
        if self.transport == 'websocket':
            async with contextlib.aclosing(self._websocket_stream(text)) as stream:
                async for part in stream:
                    yield part
            return
        key = self._key_loader()
        if not key:
            raise RuntimeError("Fish API Key 未配置，请在语音安全设置中填写")
        if not self._reference_id:
            raise RuntimeError("当前角色未配置 Fish 音色 ID")
        splitter = WavStreamSplitter(first_chunk_ms=self._first_chunk_ms)
        started = time.perf_counter()
        timings = {'first_chunk_ms': self._first_chunk_ms, 'pcm_transcode_ms': 0,
                   'split_cpu_ms': 0.0, 'rms_cpu_ms': 0.0}
        count = 0
        stream_id = uuid4().hex  # 同一次合成的子块身份；不含朗读内容。

        def segment(wav):
            before = time.perf_counter()
            samples = np.frombuffer(wav[44:], dtype='<i2').astype(np.float32) / 32768
            volumes = self._slice_rms(samples, splitter.rate, 20)
            timings['rms_cpu_ms'] += round((time.perf_counter()-before)*1000, 3)
            return AudioSegment(wav=wav, sample_rate=splitter.rate,
                                volumes=volumes, streaming=True, stream_id=stream_id,
                                timings=dict(timings) if count == 1 else None)

        vlog('tts', f'Fish HTTP 流开始 chars={len(text)} model={self._model}')
        try:
            async with self._client().stream('POST', 'https://api.fish.audio/v1/tts',
                    headers={'Authorization': f'Bearer {key}', 'model': self._model},
                    json={'text': text, 'reference_id': self._reference_id,
                          'format': 'wav', 'sample_rate': 44100, 'latency': self._latency,
                          'prosody': {'speed': self._speed}}) as response:
                if response.status_code != 200:
                    raise RuntimeError(f'Fish HTTP {response.status_code}；未切换为其他音色')
                timings['headers_ms'] = round((time.perf_counter()-started)*1000, 3)
                async for raw in response.aiter_bytes():
                    if raw:
                        timings.setdefault('raw_first_audio_ms', round((time.perf_counter()-started)*1000, 3))
                        timings.setdefault('raw_first_packet_bytes', len(raw))
                    before = time.perf_counter()
                    chunks = splitter.feed(raw)
                    timings['split_cpu_ms'] += round((time.perf_counter()-before)*1000, 3)
                    for wav in chunks:
                        count += 1
                        if count == 1:
                            timings['first_playable_ms'] = round((time.perf_counter()-started)*1000, 3)
                            vlog('tts', f'Fish HTTP 首片 ms={(time.perf_counter()-started)*1000:.1f}')
                        yield segment(wav)
                for wav in splitter.finish():
                    count += 1
                    if count == 1:
                        timings['first_playable_ms'] = round((time.perf_counter()-started)*1000, 3)
                        timings['first_from_finish'] = True
                    yield segment(wav)
            if not count:
                raise RuntimeError('Fish 返回空音频')
            vlog('tts', f'Fish HTTP 流完成 ms={(time.perf_counter()-started)*1000:.1f} chunks={count}')
        except asyncio.CancelledError:
            vlog('tts', 'Fish HTTP 流已取消')
            raise
        except httpx.HTTPError as exc:
            raise RuntimeError(f'Fish 流传输失败 [{type(exc).__name__}]；未重试或切换音色') from None

    async def _synthesize_audio(self, text: str) -> bytes:
        if self.transport == 'websocket':
            parts = [part.wav async for part in self._websocket_stream(text)]
            if not parts:
                raise RuntimeError('Fish WS返回空音频')
            raw = bytearray(parts[0][:44] + b''.join(part[44:] for part in parts))
            struct.pack_into('<I', raw, 4, len(raw)-8)
            struct.pack_into('<I', raw, 40, len(raw)-44)
            return bytes(raw)
        key = self._key_loader()
        if not key:
            raise RuntimeError("Fish API Key 未配置，请在语音安全设置中填写")
        if not self._reference_id:
            raise RuntimeError("当前角色未配置 Fish 音色 ID")
        started = time.perf_counter()
        vlog("tts", f"Fish HTTP 合成开始 chars={len(text)} model={self._model}")
        try:
            response = await self._client().post(
                    "https://api.fish.audio/v1/tts",
                    headers={"Authorization": f"Bearer {key}", "model": self._model},
                    json={"text": text, "reference_id": self._reference_id,
                          "format": "wav", "sample_rate": 44100,
                          "latency": self._latency, "prosody": {"speed": self._speed}},
                )
            # 不透传云端错误正文（可能反射文本/凭证），不自动重试计费请求。
            if response.status_code != 200:
                vlog("tts", f"Fish HTTP 拒绝 status={response.status_code} model={self._model}")
                raise RuntimeError(f"Fish HTTP {response.status_code}；请检查密钥、额度和音色权限")
            audio = finalize_wav(response.content)
            vlog("tts", f"Fish HTTP 完成 ms={(time.perf_counter()-started)*1000:.1f} bytes={len(response.content)}")
            return audio
        except asyncio.CancelledError:
            vlog("tts", "Fish HTTP 已取消")
            raise
        except httpx.HTTPError as exc:
            kind = type(exc).__name__
            cause = type(exc.__cause__).__name__ if exc.__cause__ else "none"
            elapsed = (time.perf_counter()-started)*1000
            vlog("tts", f"Fish 传输失败 kind={kind} cause={cause} elapsed_ms={elapsed:.0f}")
            hint = ("连接建立超时" if isinstance(exc, httpx.ConnectTimeout) else
                    "等待音频响应超时" if isinstance(exc, httpx.ReadTimeout) else
                    "代理连接失败" if isinstance(exc, httpx.ProxyError) else
                    "连接建立失败（需检查DNS、TLS或代理）" if isinstance(exc, httpx.ConnectError) else
                    "音频传输失败")
            raise RuntimeError(f"Fish {hint} [{kind}]；未切换为其他音色") from None


def build_fish_provider(tts):
    """主链、热重载与调试台试听共用同一装配入口。"""
    return FishAudioProvider(reference_id=tts.fish_reference_id, model=tts.fish_model,
                             latency=tts.fish_latency, speed=tts.fish_speed,
                             segment_streaming=tts.segment_streaming,
                             transport=getattr(tts, 'fish_transport', 'http'),
                             first_chunk_ms=getattr(tts, 'fish_first_chunk_ms', 400))
