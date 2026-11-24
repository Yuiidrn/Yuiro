"""将HTTP中的PCM16 WAV逐步封装成独立可解码片段；不丢样本、不伪造补零。"""
import io
import struct
import wave


class WavStreamSplitter:
    def __init__(self, chunk_ms=480, *, first_chunk_ms=None):
        self._header = bytearray()
        self._pcm = bytearray()
        self.rate = 0
        self._chunk_ms = chunk_ms
        self._first_chunk_ms = first_chunk_ms if first_chunk_ms is not None else chunk_ms
        if not 40 <= self._first_chunk_ms <= 2000 or not 40 <= chunk_ms <= 2000:
            raise ValueError('WAV分块时长超出预算')
        self._emitted = False
        self._remaining = None
        self._ready = False

    def feed(self, data: bytes) -> list[bytes]:
        if not self._ready:
            self._header.extend(data)
            if len(self._header) < 12:
                return []
            if self._header[:4] != b'RIFF' or self._header[8:12] != b'WAVE':
                raise ValueError('Fish流式响应不是WAV')
            pos = 12
            while pos + 8 <= len(self._header):
                kind = self._header[pos:pos+4]
                size = struct.unpack_from('<I', self._header, pos+4)[0]
                if kind == b'data':
                    if not self.rate:
                        raise ValueError('WAV缺少PCM格式')
                    self._ready = True
                    self._remaining = None if size >= 0xF0000000 else size
                    data = bytes(self._header[pos+8:])
                    self._header.clear()
                    break
                if pos + 8 + size > 65536:
                    raise ValueError('WAV头超出限制')
                if pos + 8 + size > len(self._header):
                    return []
                if kind == b'fmt ':
                    if size < 16:
                        raise ValueError('WAV格式头不完整')
                    fmt, channels, rate, _, align, bits = struct.unpack_from('<HHIIHH', self._header, pos+8)
                    if (fmt, channels, align, bits) != (1, 1, 2, 16) or not 8000 <= rate <= 96000:
                        raise ValueError('流式播放仅接受单声道PCM16 WAV')
                    self.rate = rate
                pos += 8 + size + size % 2
            if not self._ready:
                return []
        if self._remaining is not None:
            data = data[:self._remaining]
            self._remaining -= len(data)
        self._pcm.extend(data)
        chunks = []
        while True:
            duration = self._chunk_ms if self._emitted else self._first_chunk_ms
            size = max(1, self.rate * duration // 1000) * 2
            if len(self._pcm) < size:
                break
            chunks.append(self._wrap(bytes(self._pcm[:size])))
            del self._pcm[:size]
            self._emitted = True
        return chunks

    def finish(self) -> list[bytes]:
        if not self._ready or self._remaining not in (None, 0) or len(self._pcm) % 2:
            raise ValueError('Fish WAV响应截断')
        if not self._pcm:
            return []
        tail = self._wrap(bytes(self._pcm))
        self._pcm.clear()
        return [tail]

    def _wrap(self, pcm: bytes) -> bytes:
        output = io.BytesIO()
        with wave.open(output, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(self.rate)
            audio.writeframes(pcm)
        return output.getvalue()
