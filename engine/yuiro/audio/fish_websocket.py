"""单轮Fish连接：无跨角色状态，借用既有PCM分块与播放器契约。"""
from __future__ import annotations

import asyncio
import contextlib
import io
import struct
import time
import wave
from uuid import uuid4

import msgpack
import numpy as np
import websockets

from yuiro.audio.providers import AudioSegment, TTSProvider
from yuiro.audio.wav_stream import WavStreamSplitter
from yuiro.logger import vlog


class FishWebSocketSession:
    def __init__(self, *, key_loader, reference_id, model, latency, speed, connector=None,
                 first_chunk_ms=480):
        self._reference = reference_id
        self._model, self._latency, self._speed = model, latency, speed
        self._key_loader = key_loader
        self._connector = connector or websockets.connect
        self._socket = None
        self._closed = False
        self._used = False
        self._close_task = None
        self._writer = None
        self._receiver = None
        self._started = time.perf_counter()
        self.timings = {'first_chunk_ms': first_chunk_ms, 'pcm_transcode_ms': 0,
                        'split_cpu_ms': 0.0, 'rms_cpu_ms': 0.0}
        self._first_chunk_ms = first_chunk_ms
        self._connection = asyncio.create_task(self._connect())

    def _mark(self, name):
        self.timings.setdefault(name, round((time.perf_counter()-self._started)*1000, 3))

    async def _connect(self):
        self._mark('connect_task_enter_ms')
        before = time.perf_counter()
        key = self._key_loader()
        self.timings['key_lookup_ms'] = round((time.perf_counter()-before)*1000, 3)
        self._mark('key_loaded_ms')
        if not key or not self._reference:
            raise RuntimeError('Fish密钥或音色未配置')
        vlog('tts', 'Fish WS 提前连接开始')
        self._mark('connection_start_ms')
        socket = await self._connector('wss://api.fish.audio/v1/tts/live',
            additional_headers={'Authorization': f'Bearer {key}', 'model': self._model},
            open_timeout=10, max_size=8_000_000)
        self._socket = socket
        self._mark('connected_ms')
        vlog('tts', f'Fish WS 连接就绪 ms={(time.perf_counter()-self._started)*1000:.1f}')
        return socket

    async def stream(self, sentences):
        if self._closed or self._used:
            raise RuntimeError('Fish WS单轮会话已使用或关闭')
        self._used = True
        stream_id = uuid4().hex
        splitter = WavStreamSplitter(first_chunk_ms=self._first_chunk_ms)
        header = io.BytesIO()
        with wave.open(header, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(44100)
        raw = bytearray(header.getvalue())
        struct.pack_into('<I', raw, 4, 0xFFFFFFFF)
        struct.pack_into('<I', raw, 40, 0xFFFFFFFF)
        splitter.feed(raw)

        def segment(wav):
            before = time.perf_counter()
            pcm = np.frombuffer(wav[44:], dtype='<i2').astype(np.float32) / 32768
            volumes = TTSProvider._slice_rms(pcm, 44100, 20)
            self.timings['rms_cpu_ms'] += round((time.perf_counter()-before)*1000, 3)
            return AudioSegment(wav, 44100, volumes, streaming=True, stream_id=stream_id,
                                timings=dict(self.timings) if count == 1 else None)

        count = 0
        try:
            socket = await self._connection

            async def send(payload):
                await socket.send(msgpack.packb(payload, use_bin_type=True))

            async def write():
                try:
                    await send({'event': 'start', 'request': {'text': '', 'reference_id': self._reference,
                        'format': 'pcm', 'sample_rate': 44100, 'latency': self._latency,
                        'prosody': {'speed': self._speed}}})
                    async for text in sentences:
                        if text.strip():
                            await send({'event': 'text', 'text': text})
                            self._mark('first_text_sent_ms')
                            await send({'event': 'flush'})
                            self._mark('first_flush_sent_ms')
                    await send({'event': 'stop'})
                    self._mark('input_finished_ms')
                finally:
                    closer = getattr(sentences, 'aclose', None)
                    if closer is not None:
                        await closer()

            self._writer = asyncio.create_task(write())
            while True:
                if self._writer.done():
                    self._writer.result()
                self._receiver = asyncio.create_task(socket.recv())
                waiting = {self._receiver}
                if not self._writer.done():
                    waiting.add(self._writer)
                done, _ = await asyncio.wait(waiting, timeout=60,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    raise TimeoutError('Fish WS响应超时')
                if self._writer.done():
                    self._writer.result()  # 写入/翻译失败不得留下recv永久等待。
                packet = await asyncio.wait_for(self._receiver, 60)
                event = msgpack.unpackb(packet, raw=False)
                kind = event.get('event')
                if kind == 'audio':
                    audio = event.get('audio')
                    if not isinstance(audio, bytes):
                        raise RuntimeError('Fish WS音频格式无效')
                    if audio:
                        self._mark('raw_first_audio_ms')
                        self.timings.setdefault('raw_first_packet_bytes', len(audio))
                    before = time.perf_counter()
                    chunks = splitter.feed(audio)
                    self.timings['split_cpu_ms'] += round((time.perf_counter()-before)*1000, 3)
                    for wav in chunks:
                        count += 1
                        if count == 1:
                            self._mark('first_playable_ms')
                            vlog('tts', f'Fish WS 首片 ms={(time.perf_counter()-self._started)*1000:.1f}')
                        yield segment(wav)
                elif kind == 'finish':
                    if event.get('reason') != 'stop' or not self._writer.done():
                        raise RuntimeError('Fish WS提前结束或服务错误')
                    self._writer.result()
                    for wav in splitter.finish():
                        count += 1
                        if count == 1:
                            self._mark('first_playable_ms')
                            self.timings['first_from_finish'] = True
                        yield segment(wav)
                    if not count:
                        raise RuntimeError('Fish WS返回空音频')
                    return
                elif kind == 'error':
                    raise RuntimeError('Fish WS服务错误；未重试或切换音色')
        except asyncio.CancelledError:
            vlog('tts', 'Fish WS单轮已取消')
            raise
        except Exception as exc:  # noqa: BLE001 — 脱敏所有外部异常；取消单独传播。
            raise RuntimeError(f'Fish WS失败 [{type(exc).__name__}]；未重试或切换音色') from None
        finally:
            await self.close()

    async def close(self):
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._cleanup())
        await asyncio.shield(self._close_task)

    async def _cleanup(self):
        tasks = [t for t in (self._writer, self._receiver, self._connection) if t is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._socket is not None:
            with contextlib.suppress(Exception):
                await self._socket.close()
        vlog('tts', 'Fish WS单轮连接已释放')
