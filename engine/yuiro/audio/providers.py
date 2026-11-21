"""TTS 实现层（S16b：从 audio/__init__.py 逐字抽离）。

搬运内容（原 audio/__init__.py L628–985，逐字保留实现与注释）：

- ``AudioSegment``：合成结果 + 预计算 RMS 音量数组（驱动口型）；
- ``TTSProvider``：基类（edge-tts 兜底 + 解码/切分/口型计算）；
- ``CosyVoiceProvider`` / ``SiliconFlowProvider`` / ``GPTSoVITSProvider``：三个后端实现，
  只重写 ``_synthesize_audio``，其余（解码 / RMS / 分段流式）全部继承基类。

``audio/__init__.py`` 保留 re-export，既有 import 路径不变。
"""
from __future__ import annotations

import asyncio
import os

import numpy as np

from yuiro.audio.render import detect_language
from yuiro.logger import vlog

#: edge-tts 兜底音色的语种映射（S52：朗读语言不是中文时自动换对应语种音色）。
#: 只在 edge-tts（本文件的 ``TTSProvider``）生效；其它后端各按自己的语种参数走，
#: 空串表示"沿用配置里的 ``[persona].voice``"（默认中文音色，保持现状）。
_EDGE_VOICE_BY_LANG: dict[str, str] = {
    "zh": "",
    "en": "en-US-AriaNeural",
    "ja": "ja-JP-NanamiNeural",
}


class AudioSegment:
    """TTS output segment + precomputed RMS volume array for lipsync."""

    def __init__(
        self, wav: bytes, sample_rate: int, volumes: list[float], slice_ms: int = 20,
        streaming: bool = False, stream_id: str = "",
    ) -> None:
        self.wav = wav
        self.sample_rate = sample_rate
        self.volumes = volumes  # per-slice RMS for client-side mouth drive
        self.slice_ms = slice_ms
        self.streaming = streaming
        self.stream_id = stream_id


class TTSProvider:
    """edge-tts 合成 WAV 并预计算逐 slice RMS 音量数组。"""

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        segment_streaming: bool = True,
        language: str = "zh",
    ) -> None:
        self._voice = voice
        self._segment_streaming = segment_streaming
        # S52：朗读语种（zh/en/ja/auto）。edge-tts 用**音色**表达语种，故这里
        # 按语种换音色（见 _EDGE_VOICE_BY_LANG）；auto = 按文本判定。
        self._language = (language or "zh").lower()

    def _voice_for(self, text: str) -> str:
        """按朗读语种选音色：中文用配置音色，其余语种用内置对应音色。"""
        lang = self._language
        if lang == "auto":
            detected = detect_language(text)
            lang = detected if detected in ("zh", "en", "ja") else "zh"
        if lang == "zh":
            return self._voice
        return _EDGE_VOICE_BY_LANG.get(lang) or self._voice

    async def _synthesize_audio(self, text: str) -> bytes:
        import edge_tts

        communicate = edge_tts.Communicate(text, self._voice_for(text))
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                audio.extend(chunk.get("data") or b"")
        return bytes(audio)

    @staticmethod
    def _slice_rms(audio: np.ndarray, sample_rate: int, slice_ms: int = 20) -> list[float]:
        samples_per_slice = max(1, int(sample_rate * slice_ms / 1000))
        volumes: list[float] = []
        for i in range(0, audio.size, samples_per_slice):
            seg = audio[i : i + samples_per_slice]
            if seg.size == 0:
                continue
            volumes.append(float(np.sqrt(np.mean(seg * seg) + 1e-12)))
        return volumes

    @staticmethod
    def _decode_audio_to_pcm(audio_bytes: bytes) -> tuple[np.ndarray, int]:
        """把 edge-tts 的 mp3 字节解码为 float32 单声道 PCM + 实际采样率。

        edge-tts 只输出 mp3（ID3 头）；miniaudio 纯 Python wheel 解码，
        无 ffmpeg 系统依赖。解码失败返回空数组（volumes 不驱动口型但不崩溃）。
        """
        try:
            import miniaudio

            decoded = miniaudio.decode(
                audio_bytes,
                output_format=miniaudio.SampleFormat.FLOAT32,
                nchannels=1,
            )
            samples = np.frombuffer(decoded.samples, dtype=np.float32).copy()
            return samples, int(decoded.sample_rate)
        except Exception:  # noqa: BLE001 — 解码失败降级为空音量
            return np.zeros(0, dtype=np.float32), 24000

    async def synthesize_segment(self, text: str) -> AudioSegment:
        audio_bytes = await self._synthesize_audio(text)
        # wav 字段保留 mp3 字节（前端 decodeAudioData 可直接播放）；
        # volumes 用真实解码 PCM 计算，驱动口型。
        pcm, sample_rate = await asyncio.to_thread(self._decode_audio_to_pcm, audio_bytes)
        volumes = self._slice_rms(pcm, sample_rate, 20)
        return AudioSegment(wav=audio_bytes, sample_rate=sample_rate, volumes=volumes)


class CosyVoiceProvider(TTSProvider):
    """本地 TTS 服务客户端（替代 edge-tts 云端）。

    仅重写 ``_synthesize_audio``：通过 httpx POST 到独立 ``tts-server`` 进程
    （加载 CosyVoice2 / GPT-SoVITS 等本地权重，GPU 推理），返回 wav 字节。
    ``synthesize_segment`` / ``_decode_audio_to_pcm`` / ``_slice_rms`` / ``AudioSegment``
    **全部继承父类**——miniaudio 解 wav，volumes 照常计算，口型免费复用。
    不把任何 TTS torch 模型 import 进 engine 主进程（避免与 SenseVoice 抢显存/GIL）。
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5005",
        reference_wav: str = "",
        reference_text: str = "",
        instruct_zh: str = "",
        instruct_en: str = "",
        instruct_ja: str = "",
        default_language: str = "auto",
        backend: str = "cosyvoice2",
        segment_streaming: bool = True,
        language: str = "auto",
    ) -> None:
        # 不调用 super().__init__ 的 voice 语义（CosyVoice 不用 Microsoft 预设名）
        self._base_url = base_url.rstrip("/")
        self._reference_wav = reference_wav
        self._reference_text = reference_text
        self._instruct_zh = instruct_zh
        self._instruct_en = instruct_en
        self._instruct_ja = instruct_ja
        self._default_language = default_language
        # S52：朗读语种（来自 [language].speak_language，装配期注入）。
        # "auto" = 沿用旧行为（老的 default_language → 文本判定）。
        self._language = (language or "auto").lower()
        # backend 透传给 tts-server：cosyvoice2（默认） | cosyvoice3（预留，显存不足时报错指引）
        self._backend = backend
        self._segment_streaming = segment_streaming

    @staticmethod
    def _detect_language(text: str) -> str:
        """语种判定（zh | en | ja）：委托 ``audio.render.detect_language``。

        修掉了旧实现把**假名与汉字混判为 zh** 的问题 —— 那会让日文朗读套上中文
        语气指令（"用中文语气说"），发音与语气都会偏。
        """
        detected = detect_language(text)
        return detected if detected in ("zh", "en", "ja") else "zh"

    def _resolve_language(self, text: str) -> str:
        """本次合成该用哪个语种。

        优先级：``language``（S52 朗读语言设置，非 auto）→ ``default_language``（旧字段，
        非 auto）→ 文本判定。两级都保留是为了**不破坏既有配置**（旧用户只配了
        ``default_language``，升级后行为不变）。
        """
        for want in (self._language, (self._default_language or "").lower()):
            if want in ("zh", "en", "ja"):
                return want
        return self._detect_language(text)

    def _instruct_for(self, lang: str) -> str:
        """按语种选语气指令；未配置日文指令时退回中文指令（比英文指令贴切）。"""
        if lang == "zh":
            return self._instruct_zh
        if lang == "ja":
            return self._instruct_ja or self._instruct_zh
        return self._instruct_en

    async def _synthesize_audio(self, text: str) -> bytes:
        import httpx

        lang = self._resolve_language(text)
        instruction = self._instruct_for(lang)
        # 字段名与 tts-server 的 TTSReq 对齐（reference_wav/reference_text/instruct）；
        # 服务端返回原始 wav 字节（resp.content），父类 synthesize_segment 用 miniaudio 解码。
        payload = {
            "text": text,
            "reference_wav": self._reference_wav,
            "reference_text": self._reference_text,
            "instruct": instruction,
            "language": lang,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self._base_url}/tts", json=payload)
            resp.raise_for_status()
            return resp.content  # wav 字节（标准 RIFF wav，24kHz）


class SiliconFlowProvider(TTSProvider):
    """云端 SiliconFlow TTS 客户端（零样本声音克隆，零本地显存占用）。

    走 SiliconFlow ``/v1/audio/speech`` 端点（已验证）：
    - 零样本克隆：在请求体里带 ``references=[{audio: <data-url>, text: <参考转写>}]``，
      **且不能**同时设 ``voice``（否则 400 "Either voice or reference audio can be set"）。
    - 启动时把参考 wav 读成 base64 data-url 缓存，合成时直接复用（免每次重读/编码）。
    - 返回标准 wav（CosyVoice2 生成，~24kHz），与本地 TTS 一致 → 复用基类流式切分。
    - 无参考音频时退化为 ``voice=<模型内置音色>`` 合成（保证「能出声」）。

    参考：https://api-docs.siliconflow.cn/docs/api/audio-speech-post
    实测结论：/v1/audio/voice-cloning 路径 404（不可用），references 内联克隆可用。
    """

    DEFAULT_API_URL = "https://api.siliconflow.cn"
    CLONE_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
    FALLBACK_VOICE = "FunAudioLLM/CosyVoice2-0.5B:anna"

    def __init__(
        self,
        api_key: str,
        voice: str = FALLBACK_VOICE,
        reference_wav: str | None = None,
        reference_text: str = "",
        model: str = CLONE_MODEL,
        segment_streaming: bool = True,
    ) -> None:
        self._segment_streaming = segment_streaming
        self._api_url = self.DEFAULT_API_URL.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._voice = voice  # 默认/降级音色（模型内置）
        # 参考文本解析：若为 .txt 文件路径则读其内容（与参考音频语种必须一致，
        # 否则克隆对齐错乱——英文音频配中文 text 会让中文回复带夹生腔）。
        self._reference_text = self._resolve_reference_text(reference_text, reference_wav)
        self._reference_data_url: str | None = None  # 缓存的参考音频 data-url

        # 启动阶段：预编码参考音频为 data-url（失败仅降级，不阻断进程）
        if reference_wav and os.path.isfile(reference_wav):
            try:
                import base64

                with open(reference_wav, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                self._reference_data_url = f"data:audio/wav;base64,{b64}"
                vlog("tts", f"SiliconFlow 参考音频已编码（克隆准备就绪）: {reference_wav}")
            except Exception as exc:  # noqa: BLE001
                vlog("tts", f"SiliconFlow 参考音频编码失败，降级模型内置音色: {exc}")
        else:
            vlog("tts", f"SiliconFlow 未提供有效参考音频，使用模型内置音色: {self._voice}")

    @staticmethod
    def _resolve_reference_text(reference_text: str, reference_wav: str | None) -> str:
        """解析参考文本：支持直接文本、.txt 文件路径（优先），否则回退同目录 参考文本.txt。"""
        # 1) 直接传了非空文本（且不是路径）→ 原样用
        if reference_text and not reference_text.lower().endswith(".txt") and not os.path.isfile(reference_text):
            return reference_text
        # 2) 显式给了 .txt 路径 → 读内容
        if reference_text and os.path.isfile(reference_text):
            try:
                with open(reference_text, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception as exc:  # noqa: BLE001
                vlog("tts", f"读取 reference_text 文件失败: {exc}")
                return ""
        # 3) 留空 → 同目录 参考文本.txt
        if reference_wav:
            candidate = os.path.join(os.path.dirname(reference_wav), "参考文本.txt")
            if os.path.isfile(candidate):
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        return f.read().strip()
                except Exception as exc:  # noqa: BLE001
                    vlog("tts", f"读取 {candidate} 失败: {exc}")
        return ""

    async def _synthesize_audio(self, text: str) -> bytes:
        """调用 SiliconFlow /v1/audio/speech，返回 wav 字节。

        中文清晰度优化（CosyVoice2 零样本克隆特性）：
        - 长句一次性合成易「吞字/断句不清」。按标点切短句**逐句合成**再拼接，
          每句克隆更稳、咬字更清；且严格顺序拼接，天然保证语序。
        - 固定 ``seed`` 让同一句输出可复现（避免随机抖动导致时而清晰时而含糊）；
          ``speed=1.0`` 不加速，避免过快导致口齿不清。
        - ``references.text`` 是**参考音频的转写**（克隆音色来源），与目标文本无关，
          务必准确——占位文本与目标不符会拉低保真度（待用户提供准确转写替换）。
        """
        import httpx

        sentences = self._split_sentences(text)
        if len(sentences) == 1:
            return await self._synth_one(sentences[0])
        # 多句：逐句顺序合成并拼接（保证语序，提升清晰度）
        import io
        import wave

        import miniaudio
        import numpy as np

        pcm_chunks: list[np.ndarray] = []
        sr = 24000
        for sent in sentences:
            raw = await self._synth_one(sent)
            if not raw:
                continue
            try:
                dec = miniaudio.decode(raw, output_format=miniaudio.SampleFormat.FLOAT32, nchannels=1)
                pcm_chunks.append(np.frombuffer(dec.samples, dtype=np.float32).copy())
                sr = int(dec.sample_rate)
            except Exception as exc:  # noqa: BLE001 — 单句解码失败跳过该句，不阻断整段
                vlog("tts", f"SiliconFlow 分句解码失败已跳过: {exc}")
        if not pcm_chunks:
            return b""
        pcm = (np.concatenate(pcm_chunks) * 32767).clip(-32768, 32767).astype("<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    def _split_sentences(self, text: str) -> list[str]:
        """按中英文标点切句（保留标点作为断句停顿），过滤空串。"""
        parts = []
        buf = ""
        for ch in text:
            buf += ch
            if ch in "。！？!?；;\n":
                if buf.strip():
                    parts.append(buf.strip())
                buf = ""
        if buf.strip():
            parts.append(buf.strip())
        return parts or [text]

    async def _synth_one(self, text: str) -> bytes:
        """单句合成（含克隆 references / 内置 voice 降级 + seed/speed 稳定性参数）。"""
        import httpx

        payload: dict = {
            "model": self._model,
            "input": text,
            "response_format": "wav",
            "seed": 42,
            "speed": 1.0,
        }
        if self._reference_data_url:
            # 零样本克隆：references 与 voice 互斥，不能同时设
            payload["references"] = [
                {"audio": self._reference_data_url, "text": self._reference_text}
            ]
        else:
            payload["voice"] = self._voice

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._api_url}/v1/audio/speech",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            if resp.status_code != 200:
                vlog("tts", f"speech HTTP {resp.status_code}: {resp.text[:300]}")
                resp.raise_for_status()
            return resp.content  # wav 字节


class GPTSoVITSProvider(TTSProvider):
    """本地 GPT-SoVITS 服务客户端（零样本克隆，替代 edge-tts / CosyVoice）。

    重要前提：my-neuro 仓库**并未提交**训练好的 merge.pth（GPT-SoVITS-Bundle 仅占位），
    Fake Neuro 原始音色只保留在 ``Reference_audio/肥牛.wav``。因此本地走**零样本克隆**：
    每次请求携带 refer_wav_path + prompt_text + prompt_language，由 Bundle 的 api.py
    用 肥牛.wav 即时克隆（与 CosyVoice 零样本同思路，但 GPT-SoVITS 模型更轻、中文更自然）。
    仅重写 ``_synthesize_audio``；synthesize_segment / 口型 / 解码逻辑全部继承父类。
    不把任何 TTS torch 模型 import 进 engine 主进程（避免与 SenseVoice 抢显存/GIL）。

    注：若日后训练出 merge.pth 并把音色固化进服务启动参数，可去掉 refer/prompt 字段。
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5000",
        reference_wav: str = "",
        reference_text: str = "",
        prompt_language: str = "zh",
        text_language: str = "auto",
        segment_streaming: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._reference_wav = reference_wav
        self._reference_text = reference_text
        self._prompt_language = prompt_language
        self._text_language = text_language
        self._segment_streaming = segment_streaming

    @staticmethod
    def _detect_language(text: str) -> str:
        """语种判定（zh | en | ja）：委托 ``audio.render.detect_language``。

        GPT-SoVITS 的 ``text_language`` 原生支持 ja，因此假名必须判为 ja 而不是 zh
        （旧实现混判为 zh，日文会按中文音素念）。
        """
        detected = detect_language(text)
        return detected if detected in ("zh", "en", "ja") else "zh"

    async def _synthesize_audio(self, text: str) -> bytes:
        import httpx

        lang = self._text_language
        if lang == "auto":
            lang = self._detect_language(text)
        # GPT-SoVITS 零样本契约（标准 api.py /tts）：refer_wav_path 为服务端可访问的
        # 文件系统路径；prompt_text 必须是参考音频的真实转写（填错会严重失真）。
        payload = {
            "text": text,
            "text_language": lang,
            "refer_wav_path": self._reference_wav,
            "prompt_text": self._reference_text,
            "prompt_language": self._prompt_language,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self._base_url, json=payload)
            resp.raise_for_status()
            return resp.content
