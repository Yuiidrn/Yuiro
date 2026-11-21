"""Yuiro engine — audio package (VAD/ASR/TTS/voice pipeline)."""
from __future__ import annotations

import asyncio
import contextlib
import math
import os
import sys
import time
from enum import Enum
from collections import deque
from pathlib import Path

import numpy as np

from yuiro.logger import vlog
from yuiro.runtime.trace import TraceContext
from yuiro.audio.playback import PlaybackLeases
from yuiro.audio.ownership import capture_owner, check_owner, emit_owned, owned_speech


class VADEvent(Enum):
    SpeechStart = "speech_start"
    SpeechEnd = "speech_end"
    Silence = "silence"


class VADEngine:
    """silero-vad 状态机：IDLE/ACTIVE/INACTIVE + 双阈值 + 平滑窗口。

    feed() 处理 512 采样（32ms @16kHz）窗口并发出状态迁移事件。
    语音命中需同时满足概率阈值与能量（dBFS）阈值；平滑窗口对最近
    ``smoothing_window`` 帧取平均以抑制抖动。
    """

    def __init__(
        self,
        probability_threshold: float = 0.4,
        db_threshold: float = 60.0,
        smoothing_window: int = 5,
        required_hits: int = 3,
        required_misses: int = 24,
    ) -> None:
        self.probability_threshold = probability_threshold
        self.db_threshold = db_threshold
        self.smoothing_window = smoothing_window
        self.required_hits = required_hits
        self.required_misses = required_misses
        self._model = None
        self._state = "IDLE"
        self._hits = 0
        self._misses = 0
        self._prob_buffer: list[float] = []
        self._db_buffer: list[float] = []
        # 最近一帧的语音概率与能量（dBFS），供事件上报/调试观察
        self.last_prob = 0.0
        self.last_db = float("-inf")
        # 不足 512 采样的残留缓存，供下次 feed 拼接
        self._pcm = np.zeros(0, dtype=np.float32)

    def _load_model(self):
        if self._model is None:
            from silero_vad import load_silero_vad

            self._model = load_silero_vad()
        return self._model

    def _speech_frame(self, chunk: np.ndarray) -> tuple[bool, float, float]:
        """返回 (是否语音, 语音概率, 帧能量 dBFS)。"""
        model = self._load_model()
        audio = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return False, 0.0, float("-inf")
        rms = float(np.sqrt(np.mean(audio * audio) + 1e-12))
        db = 20.0 * math.log10(rms + 1e-12)
        try:
            import torch

            out = model(torch.from_numpy(audio), 16000)
        except ImportError:
            out = model(audio, 16000)
        prob = float(out.item()) if hasattr(out, "item") else float(out)
        is_speech = prob >= self.probability_threshold and db >= -self.db_threshold
        return is_speech, prob, db

    def _smoothed_speech(self, prob: float, db: float) -> bool:
        self._prob_buffer.append(prob)
        self._db_buffer.append(db)
        if len(self._prob_buffer) > self.smoothing_window:
            self._prob_buffer.pop(0)
            self._db_buffer.pop(0)
        avg_prob = sum(self._prob_buffer) / len(self._prob_buffer)
        avg_db = sum(self._db_buffer) / len(self._db_buffer)
        return avg_prob >= self.probability_threshold and avg_db >= -self.db_threshold

    def feed(self, chunk: np.ndarray) -> VADEvent:
        """接受任意长度 float32 输入，内部按 512 采样（16kHz）切窗逐个喂模型。

        不足 512 采样的残留缓存到下一次 feed；一次调用可能处理多个窗口，
        返回本次处理中优先级最高的事件（SpeechStart > SpeechEnd > Silence）。
        这样无论调用方（WS 上行、调试测试）传多长的帧都不会触发 silero 的
        固定窗口 ValueError。
        """
        audio = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if self._pcm.size:
            audio = np.concatenate([self._pcm, audio])
            self._pcm = np.zeros(0, dtype=np.float32)

        best = VADEvent.Silence
        idx = 0
        n = audio.size
        while idx + 512 <= n:
            best = self._merge_event(best, self._step(audio[idx : idx + 512]))
            idx += 512
        if idx < n:
            self._pcm = audio[idx:].copy()
        return best

    @staticmethod
    def _merge_event(current: VADEvent, incoming: VADEvent) -> VADEvent:
        if incoming == VADEvent.SpeechStart:
            return VADEvent.SpeechStart
        if incoming == VADEvent.SpeechEnd and current == VADEvent.Silence:
            return VADEvent.SpeechEnd
        return current

    def _step(self, chunk: np.ndarray) -> VADEvent:
        """处理单个 512 采样窗口，走状态机并返回该窗口的状态迁移事件。"""
        _is_speech, prob, db = self._speech_frame(chunk)
        self.last_prob = prob
        self.last_db = db
        speech = self._smoothed_speech(prob, db)
        if self._state == "IDLE":
            if speech:
                self._hits += 1
                if self._hits >= self.required_hits:
                    self._state = "ACTIVE"
                    self._hits = 0
                    self._misses = 0
                    return VADEvent.SpeechStart
            else:
                self._hits = 0
        elif self._state == "ACTIVE":
            if not speech:
                self._misses += 1
                if self._misses >= self.required_misses:
                    self._state = "INACTIVE"
                    self._misses = 0
                    return VADEvent.SpeechEnd
            else:
                self._misses = 0
        elif self._state == "INACTIVE":
            if speech:
                self._state = "ACTIVE"
                self._hits = 0
                self._misses = 0
                return VADEvent.SpeechStart
            self._misses += 1
            if self._misses >= self.required_misses:
                self._state = "IDLE"
                self._misses = 0
        return VADEvent.Silence

    def reset(self) -> None:
        self._state = "IDLE"
        self._hits = 0
        self._misses = 0
        self._prob_buffer.clear()
        self._db_buffer.clear()
        self._pcm = np.zeros(0, dtype=np.float32)


class ASRProvider:
    """faster-whisper 转写。

    准确率相关参数（均可经 config.toml [asr] 配置）：
    - ``language``: 指定识别语言（如 "zh"），留空则自动检测——短音频自动检测
      常误判，中文场景建议显式指定。
    - ``beam_size``: 束搜索宽度，越大越准但越慢（默认 5）。
    - ``vad_filter``: 先过滤非语音片段再识别，减少幻觉。
    - ``initial_prompt``: 引导性提示（如 "以下是普通话的句子。"），可提升领域准确率。
    """

    def __init__(
        self,
        model: str = "small",
        device: str = "auto",
        compute_type: str = "int8",
        language: str | None = None,
        beam_size: int = 5,
        vad_filter: bool = False,
        initial_prompt: str | None = None,
    ) -> None:
        self._model_name = model
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._beam_size = beam_size
        self._vad_filter = vad_filter
        self._initial_prompt = initial_prompt
        self._model = None
        self._dll_directory_handles: list[object] = []

    def _configure_cuda_runtime(self) -> None:
        """注册 venv 内 NVIDIA wheel 提供的 DLL 目录。"""
        if os.name != "nt" or self._device not in {"auto", "cuda"}:
            return
        nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
        runtime_dirs = [
            nvidia_root / "cuda_runtime" / "bin",
            nvidia_root / "cublas" / "bin",
            nvidia_root / "cudnn" / "bin",
        ]
        for directory in runtime_dirs:
            if not directory.is_dir():
                continue
            directory_str = str(directory)
            if directory_str not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = directory_str + os.pathsep + os.environ.get("PATH", "")
            self._dll_directory_handles.append(os.add_dll_directory(directory_str))

    def _load_model(self):
        if self._model is None:
            self._configure_cuda_runtime()
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._model_name, device=self._device, compute_type=self._compute_type
            )
        return self._model

    def warmup(self) -> None:
        """预加载模型到内存，消除首次转写的模型加载延迟。

        幂等：已加载则直接返回；加载失败会重置 _model，转写时重试。
        """
        try:
            self._load_model()
        except Exception:
            self._model = None
            raise

    def _transcribe_kwargs(self) -> dict:
        """构造 faster-whisper transcribe 参数（剔除 None）。"""
        kwargs = {
            "language": self._language,
            "beam_size": self._beam_size,
            "vad_filter": self._vad_filter,
            "initial_prompt": self._initial_prompt,
        }
        return {k: v for k, v in kwargs.items() if v is not None}

    def transcribe(self, audio: np.ndarray, **overrides) -> str:
        """转写音频为文本。``overrides`` 可临时覆盖实例参数（测试/联调用）。"""
        audio_np = np.asarray(audio, dtype=np.float32).reshape(-1)
        kwargs = self._transcribe_kwargs()
        kwargs.update({k: v for k, v in overrides.items() if v is not None})
        try:
            model = self._load_model()
            segments, _info = model.transcribe(audio_np, **kwargs)
        except RuntimeError:
            if self._device != "auto":
                raise
            # ``auto`` 可能在仅有显卡驱动、缺少 CUDA runtime DLL 的环境中选中 CUDA。
            # 此时回退到 CPU，保证语音链路仍可用；显式指定 cuda 时则保留原始错误。
            self._device = "cpu"
            self._compute_type = "int8"
            self._model = None
            model = self._load_model()
            segments, _info = model.transcribe(audio_np, **kwargs)
        return "".join(getattr(seg, "text", "") for seg in segments).strip()


class SenseVoiceASR:
    """FunASR SenseVoice-Small 转写（中文 SOTA 级，优于 faster-whisper）。

    相对 faster-whisper 的核心提升：
    - 中文 CER 仅 ~7.8%（Whisper-small 的约 1/2.5、large-v3 的 1/2）；
    - **自带标点恢复 + 逆文本归一化(ITN) + 情感标签**，无需额外后处理；
    - 非自回归架构，RTX 3060 上 float16 常驻显存 < 1GB、延迟极低；
    - 权重经 ModelScope 拉取（国内可达，契合镜像优先约定），落到本地目录。

    若需进一步的口语→书面语泛化（同音字纠错），可设 ``llm_polish``，
    在低置信片段由 LLM 二次润色（由调用方注入 ``polish_callback``）。
    """

    def __init__(
        self,
        model: str = "iic/SenseVoiceSmall",
        device: str = "auto",
        compute_type: str = "float16",
        language: str | None = "auto",
        local_model_path: str | None = None,
        llm_polish: bool = False,
        polish_callback=None,
        progress_callback=None,
    ) -> None:
        self._model_name = model
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._local_model_path = local_model_path
        self._llm_polish = llm_polish
        self._polish_callback = polish_callback
        self._progress = progress_callback
        self._model = None
        self._dll_directory_handles: list[object] = []

    def _resolve_device(self) -> str:
        if self._device in ("cpu", "cuda"):
            return self._device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _configure_cuda_runtime(self) -> None:
        """注册 venv 内 NVIDIA wheel 提供的 DLL 目录（SenseVoice 走 torch/cuda）。"""
        if os.name != "nt" or self._resolve_device() != "cuda":
            return
        nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
        runtime_dirs = [
            nvidia_root / "cuda_runtime" / "bin",
            nvidia_root / "cublas" / "bin",
            nvidia_root / "cudnn" / "bin",
        ]
        for directory in runtime_dirs:
            if not directory.is_dir():
                continue
            directory_str = str(directory)
            if directory_str not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = directory_str + os.pathsep + os.environ.get("PATH", "")
            self._dll_directory_handles.append(os.add_dll_directory(directory_str))

    def _load_model(self):
        if self._model is not None:
            return self._model
        self._configure_cuda_runtime()
        if self._progress is not None:
            self._progress("asr", 0.1, "初始化 FunASR AutoModel")
        from funasr import AutoModel

        device = self._resolve_device()
        dtype = "float16" if device == "cuda" and self._compute_type == "float16" else "float32"
        self._model = AutoModel(
            model=self._local_model_path or self._model_name,
            device=device,
            disable_update=True,
            # 中文识别为主，保留标点/ITN； SenseVoice 自带多语种
            trust_remote_code=True,
        )
        # dtype 通过 functorch/torch 精度由模型内部处理；此处仅缓存供 transcribe 使用
        self._resolved_device = device
        self._resolved_dtype = dtype
        if self._progress is not None:
            self._progress("asr", 1.0, "SenseVoice 模型加载完成")
        return self._model

    def warmup(self) -> None:
        """预加载到内存；失败重置以便运行时重试。"""
        try:
            self._load_model()
        except Exception:
            self._model = None
            raise

    def transcribe(self, audio: np.ndarray, **overrides) -> str:
        """转写音频为文本（含标点 + ITN）。"""
        audio_np = np.asarray(audio, dtype=np.float32).reshape(-1)
        model = self._load_model()
        language = overrides.get("language", self._language) or "auto"
        # SenseVoice 要求 16k 单声道；audio_np 已为 [-1,1] float32
        res = model.generate(
            input=audio_np,
            cache={},
            language=language,
            use_itn=True,  # 逆文本归一化：数字/量词规范化
            batch_size_s=60,
        )
        if not res:
            return ""
        text = res[0].get("text", "").strip()
        # SenseVoice 可能返回带情感标签片段（如 "<|NEUTRAL|>..."），剥离标签只留文本
        text = _strip_sensevoice_tags(text)
        if self._llm_polish and self._polish_callback is not None and text:
            try:
                text = self._polish_callback(text)
            except Exception:  # noqa: BLE001 — 润色失败降级为原始文本
                pass
        return text


#: 单字填充词（"嗯""啊"这类）：ASR 对咳嗽、桌椅声、旁人插话常吐出它们。
_FILLER_CHARS = frozenset("嗯呃啊哦噢唉呀诶咦唔咳咳哈哈呵哼")
#: 英文/拟声填充词。
_FILLER_WORDS = frozenset({"hmm", "um", "uh", "ah", "oh", "mm", "emm", "en", "er"})
#: 噪音判定的**长度上限**：只对极短转写作判定，长句一律放行。
_NOISE_MAX_CHARS = 6


def is_noise_transcript(text: str) -> bool:
    """这段转写是不是"噪音"，不该拿去对话（语音链路与日记语音共用）。

    为什么需要它：ASR 对咳嗽、桌椅响、背景音乐、旁人说话常会吐出
    ``"嗯。"`` / ``"(笑声)"`` / ``"[Music]"`` —— 这些**不是空文本**，于是会一路
    走进 LLM，用户侧看到的是"她突然回应了一声响动"。

    ★ 取向是**保守**：只拦"极短且明显无内容"的。凡像一句话的（哪怕很短，
    如"嗯，我知道了"）一律放行 —— **误杀用户的话比放过一次噪音严重得多**。
    """
    import re

    t = (text or "").strip()
    if not t:
        return True
    # 整条都是"括号描述"：(笑声) / [Music] / （咳嗽）
    # **不受长度限制**：正常人说话不会整条被括号包住，那本就是 ASR 对"非语音"的标注方式。
    if re.fullmatch(
        r"(?:[\(\[<（【《][^\)\]>）】》]{0,24}[\)\]>）】》][\s。，、！？…～~,.!?\-—·]*)+",
        t,
    ):
        return True
    if len(t) > _NOISE_MAX_CHARS:
        return False
    # 纯标点（"。。。" / "..."）
    stripped = re.sub(r"[\s。，、！？…～~,.!?\-—·]+", "", t)
    if not stripped:
        return True
    core = stripped.lower()
    if core in _FILLER_WORDS:
        return True
    return bool(core) and all(ch in _FILLER_CHARS for ch in core)


def _strip_sensevoice_tags(text: str) -> str:
    """去除 SenseVoice 输出中的情感/事件标签（<|NEUTRAL|> 等）。"""
    import re

    return re.sub(r"<\|[^|]+\|>", "", text).strip()


class FSMNVAD:
    """FunASR FSMN-VAD 流式端点检测（替代 silero 固定帧计数状态机）。

    解决原 silero ``required_misses=24``（≈0.77s 尾静音）导致的
    "短暂停顿过早截断 vs 延迟高"两难：FSMN 支持自适应尾静音判停，
    关键参数 ``max_end_silence_time``（默认 800ms，可调到 300-500ms 降低延迟），
    ``speech_pad`` 句首/句尾补零避免吞音，``chunk_size`` 控制流式粒度。

    接口与 VADEngine 对齐：``feed(chunk) -> VADEvent``、``reset()``。
    """

    def __init__(
        self,
        max_end_silence_time: int = 800,
        speech_pad: int = 200,
        chunk_size: list[int] | None = None,
        local_model_path: str | None = None,
        progress_callback=None,
    ) -> None:
        self.max_end_silence_time = max_end_silence_time
        self.speech_pad = speech_pad
        self.chunk_size = chunk_size or [0, 10, 24]
        self._local_model_path = local_model_path
        self._progress = progress_callback
        self._model = None
        self._vad = None
        self._state = "IDLE"
        self.last_prob = 0.0
        self.last_db = float("-inf")
        self._pcm = np.zeros(0, dtype=np.float32)
        # FSMN 流式推理状态
        self._cache: dict = {}
        self._speech_buffer: list[np.ndarray] = []
        self._in_speech = False

    def _load_model(self):
        if self._model is not None:
            return self._model
        if self._progress is not None:
            self._progress("vad", 0.2, "初始化 FSMN-VAD")
        from funasr import AutoModel

        self._model = AutoModel(
            model=self._local_model_path or "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            device="cpu",  # VAD 轻量，CPU 即可，避免占用 GPU
            disable_update=True,
            trust_remote_code=True,
        )
        self._vad = self._model
        if self._progress is not None:
            self._progress("vad", 1.0, "FSMN-VAD 加载完成")
        return self._model

    def _speech_frames(self, chunk: np.ndarray) -> list[tuple[int, int]]:
        """调用 FSMN 流式检测，返回 [start_sample, end_sample] 区间（相对本次输入）。"""
        model = self._load_model()
        audio = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return []
        # 抑制 funasr 内部 tqdm 进度条输出（避免 0%|0/1 刷屏）
        import os

        os.environ.setdefault("TQDM_DISABLE", "1")
        res = model.generate(
            input=audio,
            cache=self._cache,
            is_final=False,
            max_end_silence_time=self.max_end_silence_time,
            speech_pad=self.speech_pad,
            chunk_size=self.chunk_size,
        )
        segments: list[tuple[int, int]] = []
        if res:
            for seg in res[0].get("value", []):
                if len(seg) >= 2:
                    segments.append((int(seg[0]), int(seg[1])))
        return segments

    def feed(self, chunk: np.ndarray) -> VADEvent:
        """接受任意长度 float32 输入；FSMN 批量流式检测，返回最高优先级事件。

        与 silero 不同，FSMN 需要足够长的上下文才能可靠判断语音边界。
        此实现先累积音频到 ``_batch``（默认攒够 ~160ms 再调用 generate），
        避免 32ms 单帧频繁调用 generate 导致 tqdm 噪音与 cache 不稳定。
        """
        audio = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if self._pcm.size:
            audio = np.concatenate([self._pcm, audio])
            self._pcm = np.zeros(0, dtype=np.float32)

        # 累积到足够长度再调用 FSMN generate（避免每 32ms 帧都调一次）
        MIN_BATCH_SAMPLES = 2560  # ~160ms @16k，FSMN 最小有效窗口
        self._batch = getattr(self, "_batch", np.zeros(0, dtype=np.float32))
        if audio.size > 0:
            self._batch = np.concatenate([self._batch, audio]) if self._batch.size else audio

        best = VADEvent.Silence
        if self._batch.size >= MIN_BATCH_SAMPLES:
            segments = self._speech_frames(self._batch)
            self._batch = np.zeros(0, dtype=np.float32)  # 消费掉
            if segments:
                if not self._in_speech:
                    self._in_speech = True
                    self._state = "ACTIVE"
                    best = VADEvent.SpeechStart
                self._speech_buffer.append(audio)
            else:
                if self._in_speech:
                    self._in_speech = False
                    self._state = "INACTIVE"
                    best = VADEvent.SpeechEnd
        return best

    def reset(self) -> None:
        self._state = "IDLE"
        self._cache = {}
        self._speech_buffer.clear()
        self._in_speech = False
        self._pcm = np.zeros(0, dtype=np.float32)


class TranscriptBuffer:
    """将近邻 ASR 片段归组为一个 spoken turn。

    自上次片段起 ``flush_delay_ms`` 静默超时后触发 flush；单个 turn 最多
    ``MAX_CHARS`` 字，超出时淘汰最旧片段；代际计数使过期 flush 定时器失效。
    """

    MAX_CHARS = 90

    def __init__(self, flush_delay_ms: int = 1200, flush=None) -> None:
        """
        flush: async (text: str) -> None callback invoked when a turn completes.
        """
        self.flush_delay_ms = flush_delay_ms
        self._flush = flush
        self._parts: list[str] = []
        self._generation = 0
        self._timer: asyncio.Task | None = None

    def _total_len(self) -> int:
        return sum(len(p) for p in self._parts)

    async def push(self, fragment: str) -> None:
        self._generation += 1
        gen = self._generation
        self._parts.append(fragment)
        while self._total_len() > self.MAX_CHARS and len(self._parts) > 1:
            self._parts.pop(0)
        if self._timer is not None:
            self._timer.cancel()
        self._timer = asyncio.create_task(self._delayed_flush(gen))

    async def _delayed_flush(self, gen: int) -> None:
        try:
            await asyncio.sleep(self.flush_delay_ms / 1000)
        except asyncio.CancelledError:
            return
        if gen != self._generation:
            return
        await self.flush()

    async def flush(self) -> None:
        if not self._parts:
            return
        text = "".join(self._parts)
        self._parts.clear()
        self._generation += 1
        if self._flush is not None:
            await self._flush(text)

    async def dispose(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._parts.clear()


# ---- S04：分句流式工具（供 pipeline / provider 共用） -------------------------
_SENTENCE_END = "。！？!?；;\n"
_SENTENCE_SOFT = "，,、：:"

#: S37：首段（决定 TTFA 的那一段）的字符上限 —— 超过就再切一刀。
#: 端到端首音频 ≈ 首段合成耗时 + 网络往返，首段短一半，出声快一半。
_FIRST_SEG_MAX = 28


def split_sentences(text: str, *, min_len: int = 12, max_len: int = 60) -> list[str]:
    """把文本切成适合逐句合成的片段（首句先出声）。

    - 句末标点（。！？；换行）切分，标点保留作为停顿；
    - 过短片段向后合并（``min_len``，避免"嗯。"这类碎句单独请求）；
    - 过长片段优先按软标点（逗号/顿号/冒号）强切（``max_len``），无软标点则硬切。
    """
    from yuiro.audio.speech_text import speech_body

    raw = speech_body(text)
    if not raw:
        return []

    chunks: list[str] = []
    buf = ""
    for ch in raw:
        buf += ch
        if ch in _SENTENCE_END:
            if buf.strip():
                chunks.append(buf.strip())
            buf = ""
    if buf.strip():
        chunks.append(buf.strip())

    merged: list[str] = []
    for c in chunks:
        if merged and len(merged[-1]) < min_len:
            merged[-1] = f"{merged[-1]}{c}"
        else:
            merged.append(c)

    out: list[str] = []
    for c in merged:
        while len(c) > max_len:
            cut = 0
            for i in range(max_len, 0, -1):
                if c[i - 1] in _SENTENCE_SOFT:
                    cut = i
                    break
            if cut <= 0:
                cut = max_len
            out.append(c[:cut].strip())
            c = c[cut:]
        if c.strip():
            out.append(c.strip())
    return out or [raw]


# ── S16b：TTS 实现层已抽离到 audio/providers.py ──────────────────────────
# 抽离内容：AudioSegment / TTSProvider（基类）/ CosyVoiceProvider /
#          SiliconFlowProvider / GPTSoVITSProvider（逐字保留原实现）。
# 此处 re-export 保持既有 import 路径不变（零行为变化）。
from yuiro.audio.providers import (
    AudioSegment,
    CosyVoiceProvider,
    GPTSoVITSProvider,
    SiliconFlowProvider,
    TTSProvider,
)

# 公开 API（re-export 的名字在此声明，避免"imported but unused"误报）
__all__ = [
    "FSMNVAD",
    "ASRProvider",
    "AudioSegment",
    "CosyVoiceProvider",
    "GPTSoVITSProvider",
    "SenseVoiceASR",
    "SiliconFlowProvider",
    "TTSProvider",
    "TTSTaskManager",
    "TranscriptBuffer",
    "VADEngine",
    "VADEvent",
    "VoicePipeline",
    "split_sentences",
]


class TTSTaskManager:
    """seq 计数 + 缓冲队列的有序流式交付（Open-LLM-VTuber）。

    S04：真正接入 ``_speak``（并行合成 + 按序交付 + 首段先播）。
    - 并发合成任务按 seq 入缓冲，``wait_next`` 严格按序返回，避免队头阻塞；
    - 内置信号量限流（防打爆本地 TTS 服务）；
    - 单句合成失败放**空段占位**（不阻塞整条播放，播放侧跳过空段）；
    - ``interrupt`` 通过代际（epoch）计数丢弃所有进行中/已缓冲的任务，
      并唤醒等待者（等待者由 ``_speak`` 的 task cancel 退出；manager 可继续复用）。
    """

    def __init__(self, provider: TTSProvider, *, max_concurrency: int = 2) -> None:
        self._provider = provider
        self._buffer: dict[int, deque[AudioSegment]] = {}
        self._completed: set[int] = set()
        self._next_seq = 1
        self._epoch = 0
        self._ready = asyncio.Event()
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(max_concurrency)
        # A1：上游是否已声明"不会再有新句子"。流式路径下句子总数事先未知，
        # 缺这个信号，wait_next 会永远等一个不会到来的 seq。
        self._done = False

    async def enqueue(self, seq: int, text: str) -> None:
        from yuiro.audio.speech_text import speech_body

        text = speech_body(text)
        if not any(ch.isalnum() for ch in text):
            text = ""  # 引号/Markdown残片保留空序号，不占用远端合成名额。
        epoch = self._epoch
        async with self._sem:
            if epoch != self._epoch:
                return
            delivered = False
            try:
                stream = getattr(self._provider, 'synthesize_stream', None)
                if text and callable(stream):
                    async with contextlib.aclosing(stream(text)) as fragments:
                        async for segment in fragments:
                            async with self._lock:
                                if epoch != self._epoch:
                                    return
                                self._buffer.setdefault(seq, deque()).append(segment)
                                delivered = True
                                self._ready.set()
                else:
                    segment = (await self._provider.synthesize_segment(text) if text
                               else AudioSegment(wav=b"", sample_rate=0, volumes=[]))
                    async with self._lock:
                        if epoch != self._epoch:
                            return
                        self._buffer.setdefault(seq, deque()).append(segment)
                        delivered = True
            except Exception as exc:  # noqa: BLE001 — 单句失败不阻塞整条播放
                vlog("voice", f"[TTS] 第 {seq} 句合成失败，跳过: {exc}")
        async with self._lock:
            if epoch != self._epoch:
                return
            if not delivered:
                self._buffer.setdefault(seq, deque()).append(
                    AudioSegment(wav=b"", sample_rate=0, volumes=[]))
            self._completed.add(seq)
            self._ready.set()

    async def wait_next(self) -> AudioSegment | None:
        """取下一个该播的段；**上游已结束且无更多段时返回 ``None``**（A1）。"""
        while True:
            async with self._lock:
                queue = self._buffer.get(self._next_seq)
                if queue:
                    segment = queue.popleft()
                    if not queue and self._next_seq in self._completed:
                        self._buffer.pop(self._next_seq, None)
                        self._completed.remove(self._next_seq)
                        self._next_seq += 1
                    return segment
                if self._next_seq in self._completed:
                    self._buffer.pop(self._next_seq, None)
                    self._completed.remove(self._next_seq)
                    self._next_seq += 1
                    continue
                if self._done:
                    return None
                self._ready.clear()
            await self._ready.wait()

    async def finish(self) -> None:
        """声明"不会再有新句子"（A1 流式路径必需）。

        整段路径下句子总数已知（``_speak`` 按 ``range(n)`` 取），不需要它；
        但流式路径的句子数是**边收边变**的，必须显式告知结束，否则等待方挂住。
        """
        async with self._lock:
            self._done = True
            self._ready.set()

    async def interrupt(self) -> None:
        async with self._lock:
            self._epoch += 1
            self._buffer.clear()
            self._completed.clear()
            self._next_seq = 1
            self._done = False  # 复位：manager 可继续复用（见类说明）
            self._ready.set()


class VoicePipeline:
    """编排 VAD→ASR→LLM→TTS 的事件驱动异步管线。

    冷启动优化（2026-08 新增）：
    - ``warmup`` 主动加载 VAD/ASR 并通过 ``progress_callback`` 上报进度
      （'vad'/'asr' 阶段 + 0~1 进度），``state`` 在 loading/ready/error 间迁移；
    - 加载完成前，``on_audio`` 把原始音频写入**有界环形缓冲**而非提交识别任务，
      避免首帧即触发加载 + 后续帧堆积成队列被集中处理；
    - 加载完成后一次性回放缓冲，恢复正常链路；
    - ``on_speech_end`` 用单飞锁保证同一 session 同一时刻仅一处识别，
      避免堆积任务并发累积 ``_audio`` 导致重复响应。

    - TTS 播放期间上 ASR 锁，播放结束后进入冷却期再解锁，避免自激；
    - ``can_start`` / ``inspect_before`` / ``inspect_after`` 阶段 Gate 钩子；
    - barge-in（``interrupt``）取消当前 TTS 并立即解锁处理新输入。
    """

    STATE_INIT = "init"
    STATE_LOADING = "loading"
    STATE_READY = "ready"
    STATE_ERROR = "error"

    def __init__(
        self,
        llm_callback=None,
        *,
        vad=None,
        asr=None,
        tts: TTSProvider | None = None,
        can_start=None,
        inspect_before=None,
        inspect_after=None,
        play_callback=None,
        asr_lock_cool_ms: int = 300,
        event_callback=None,
        progress_callback=None,
        max_buffer_seconds: int = 30,  # 冷启动期原始音频缓冲上限，防内存膨胀
        pre_roll_ms: int = 400,  # VAD 判定开始前保留的音频量，用于补回被吞的开头
        barge_in_callback=None,  # S03：VAD 检测到用户开口时的统一取消回调（main 注入）
        # 播放期判定"用户插话"所需的能量余量（dB）—— 见 `_barge_min_db`
        barge_margin_db: float = 12.0,
        # ★ 打断（barge-in）总开关，默认关（见 VADConfig.barge_in_enabled 的说明）
        barge_in_enabled: bool = False,
        segment_streaming: bool = True,  # S04：分句流式（False = 整段合成，行为同旧）
        # A1：流式 LLM 回调 —— async (text, sid, on_sentence) -> str。
        # 提供它时走"边收边合成"（首句提前 1~3 秒）；不提供则退回整段路径。
        sentence_llm_callback=None,
        # S52：出口语言渲染器（OutputRenderer）。None = 不做展示/朗读语言解耦
        # （行为与引入本模块前完全一致）；注入后朗读文本先渲染再合成、
        # llm:text 下发展示语言文本。
        renderer=None,
        # 统一「语音回复 TTS」开关的**取值器**（可调用，回合时读）——关闭时语音链路
        # 跳过合成（保留 ASR+LLM 文字回复）。传 callable 而非 bool，是让调试台 /api/config
        # 就地 patch 后**立即生效**（不必重启引擎）。None 或缺省 = 恒开启（行为同旧）。
        reply_tts_enabled=None,
    ) -> None:
        self._llm = llm_callback
        self._sentence_llm = sentence_llm_callback
        # S52：出口渲染器（可热重载：见 set_renderer）
        self._renderer = renderer
        self._vad = vad
        self._asr = asr
        self._tts = tts or TTSProvider()
        self._can_start = can_start or (lambda _sid: True)
        self._inspect_before = inspect_before or (lambda _text, _sid: _text)
        self._inspect_after = inspect_after or (lambda _text, _sid: _text)
        self._play_callback = play_callback or self._default_play
        self._event_callback = event_callback
        self._progress_callback = progress_callback
        self._asr_lock_cool_ms = asr_lock_cool_ms
        self._max_buffer_seconds = max_buffer_seconds
        # S03：barge-in 统一取消回调（None 时回退本地 interrupt，行为同旧）
        self._barge_in_callback = barge_in_callback
        self._barge_margin_db = barge_margin_db
        # ★ 运行时可变（debug_api 保存配置后会同步它，不必重启引擎）
        self._barge_in_enabled = barge_in_enabled
        # 统一「语音回复 TTS」开关取值器（callable，回合时读，即时生效）
        self._reply_tts_enabled = reply_tts_enabled or (lambda: True)
        self._segment_streaming = segment_streaming
        self._audio: dict[str, list[bytes]] = {}
        self._pcm_in: dict[str, bytearray] = {}
        self._asr_locked: dict[str, bool] = {}
        self._speaking: dict[str, bool] = {}
        self.playback = PlaybackLeases()
        # 是否正在累积一次有效语音（SpeechStart 后为 True）。
        # 用于区分「判定前的前置缓冲」与「正在说的音频」，避免裁剪时误删后者。
        self._recording: dict[str, bool] = {}
        # 前置缓冲帧数上限：每帧 512 采样 @16kHz = 32ms
        self._pre_roll_frames = max(1, int(pre_roll_ms / 32))
        self._speak_tasks: dict[str, asyncio.Task] = {}
        # S03：LLM 回合 task（barge-in 时立即取消，不等 LLM 返回）
        self._turn_tasks: dict[str, asyncio.Task] = {}
        # ★ 回合**代际**：`interrupt()` 时 ++。SpeechEnd 任务记下自己派发时的代际，
        #   拿到锁之后再比对，过期就**直接丢弃、不做任何计算**。
        #   为什么光 cancel `_turn_tasks` 不够：SpeechEnd 任务在**等锁期间**还没有把
        #   自己的 LLM 回合登记进去（登记发生在拿到锁之后），那时它根本不在
        #   `_turn_tasks` 里 —— 取消不到它，它会拿到锁后照跑 ASR+LLM+TTS。
        #   用户感受就是"打断了，她还在忙，回复迟迟不来"。
        self._turn_gen: dict[str, int] = {}
        # 最近一次 SpeechEnd 派发的任务：新语音到来时直接作废上一个（它的音频已过期）
        self._pending_end: dict[str, asyncio.Task] = {}
        # ★ SpeechEnd 瞬间**摘出来冻结**的那一句音频。
        #   为什么需要：回合被派发成异步任务后，pcm worker 会**继续**处理后续帧，
        #   而那时 `_recording` 已经是 False → 那些帧走 pre-roll 逻辑，会把
        #   `_audio` 裁剪成"只留最近 12 帧"，**等于把用户刚说过的话删掉**
        #   （实测：说了 3.4s，送进 ASR 只剩 0.38s → 转写为"。"→ 判为噪音 → 完全无反应）。
        #   旧实现靠 worker 同步阻塞天然避免了这一点。
        self._frozen_audio: dict[str, list[bytes]] = {}
        # S04：每 session 的 TTS 流式任务管理器（打断时 epoch++ 作废在途段）
        self._tts_managers: dict[str, TTSTaskManager] = {}
        # 冷启动门控状态
        self._state = self.STATE_INIT
        self._loading_stage = ""
        self._loading_progress = 0.0
        self._pending_raw: dict[str, bytearray] = {}  # 加载期累计原始音频（按 session）
        self._process_lock: dict[str, asyncio.Lock] = {}
        # S01：语音交互 trace（只观测；见 docs/plan/S01-voice-latency-observatory.md）
        self._traces: dict[str, TraceContext] = {}

    # ---- S52：出口渲染器（展示语言 / 朗读语言解耦） ---------------------------
    def set_renderer(self, renderer) -> None:
        """热重载渲染器（调试台保存「语言」设置后调用，不必重启引擎）。

        为什么必须有它：语言设置是"改完即生效"的约定之一；若不刷新，用户改完
        展示/朗读语言却发现没反应，只会以为功能坏了（本会话在音色上踩过同样的坑）。
        """
        self._renderer = renderer

    @property
    def renderer(self):
        return self._renderer

    async def _render_text(self, text: str, kind: str) -> str:
        """出口渲染（无渲染器 / 渲染异常时**原样返回**，绝不阻断出声）。"""
        renderer = self._renderer
        if renderer is None or not (text or "").strip():
            return text
        try:
            if kind == "display":
                return await renderer.render_display(text)
            return await renderer.render_speak(text)
        except Exception as exc:  # noqa: BLE001 — 渲染失败回退原文
            vlog("language", f"⚠ {kind} 渲染异常（{type(exc).__name__}: {str(exc)[:120]}），回退原文")
            return text

    async def _default_play(self, session_id: str, segment: AudioSegment) -> None:
        if segment.sample_rate and segment.wav:
            duration = len(segment.wav) / (segment.sample_rate * 2)
            if duration > 0:
                await asyncio.sleep(duration)

    # ---- 冷启动：状态 / 进度 -------------------------------------------------
    def _set_state(self, state: str, stage: str = "", progress: float = 0.0) -> None:
        self._state = state
        self._loading_stage = stage
        self._loading_progress = progress
        if self._progress_callback is not None:
            self._progress_callback(state, stage, progress)

    def is_ready(self) -> bool:
        return self._state == self.STATE_READY

    async def _model_progress(self, stage: str, progress: float, message: str = "") -> None:
        # 供 ASR/VAD 加载回调使用；VoicePipeline 自身合并为整体进度
        # vad 占 0~0.4，asr 占 0.4~1.0
        scale = 0.4 if stage == "vad" else 0.6
        base = 0.0 if stage == "vad" else 0.4
        overall = base + progress * scale
        self._set_state(self.STATE_LOADING, stage, overall)

    async def warmup(self) -> None:
        """预热 VAD 与 ASR 模型并上报进度；任一失败仍尝试另一组件。"""
        self._set_state(self.STATE_LOADING, "vad", 0.0)
        try:
            if self._vad is None:
                self._vad = self._build_vad()
            await asyncio.to_thread(self._vad._load_model)
        except Exception as exc:  # noqa: BLE001
            vlog("voice", f"[warmup] VAD 加载失败（降级）: {exc}")
        self._set_state(self.STATE_LOADING, "asr", 0.4)
        try:
            if self._asr is None:
                self._asr = self._build_asr()
            await asyncio.to_thread(self._asr.warmup)
            self._set_state(self.STATE_READY, "ready", 1.0)
        except Exception as exc:
            vlog("voice", f"[warmup] ASR 加载失败: {exc}")
            self._set_state(self.STATE_ERROR, "asr", 1.0)
            raise

    def _build_vad(self):
        # 由 main.py 注入配置后调用；默认退化为 silero 以保底
        return VADEngine()

    def _build_asr(self):
        return ASRProvider()

    async def _emit(self, session_id: str, event_type: str, payload: dict) -> None:
        """向可选 event_callback 转发中间状态事件（缺省时不发）。"""
        check_owner(self, session_id)
        if self._event_callback is not None:
            await self._event_callback(session_id, event_type, payload)

    # ---- S01：交互 trace（只观测，不改行为） ---------------------------------
    def _start_trace(self, session_id: str) -> TraceContext:
        """开始一条语音 trace；上一条未正常结束的（如空识别）先兜底输出。"""
        old = self._traces.pop(session_id, None)
        if old is not None:
            old.emit()
        trace = TraceContext(session_id=session_id, mode="voice")
        self._traces[session_id] = trace
        return trace

    def get_trace(self, session_id: str) -> TraceContext | None:
        """当前语音 trace（供 main 侧 LLM 回调打点；无则 None）。"""
        return self._traces.get(session_id)

    def mark_playback_started(self, session_id: str) -> None:
        """前端回执：真正开始出声（端到端 TTFA 观测点）。"""
        trace = self._traces.get(session_id)
        if trace is not None:
            trace.mark("playback_started")

    async def _finalize_trace(self, session_id: str, delay: float = 2.0, *, trace=None) -> None:
        """交互结束后延迟输出汇总（容纳前端 playback_started 回执）。"""
        if trace is None:
            trace = self._traces.get(session_id)
        if trace is None:
            return
        with contextlib.suppress(Exception):  # 取消/异常不阻断汇总输出
            await asyncio.sleep(delay)
        if self._traces.get(session_id) is trace:
            self._traces.pop(session_id, None)
            trace.emit()

    async def on_audio(self, chunk: bytes, session_id: str) -> None:
        # 冷启动门控：加载完成前，原始音频进有界环形缓冲，不触发识别任务
        # （避免首帧即触发加载、后续帧堆积成队列被集中处理造成延迟/重复响应）
        if not self.is_ready():
            buf = self._pending_raw.setdefault(session_id, bytearray())
            buf.extend(chunk)
            # 限长：超过最大缓冲时长则截断最旧部分（按 16k int16 ≈ 32KB/s）
            max_bytes = self._max_buffer_seconds * 16000 * 2
            if len(buf) > max_bytes:
                del buf[: len(buf) - max_bytes]
            return
        # 加载完成：先把门控期缓冲的原始音频一次性回放，再处理当前帧
        pending = self._pending_raw.pop(session_id, None)
        if pending:
            vlog("voice", f"[{session_id[:8]}] 回放冷启动缓冲 {len(pending)}B")
            # 直接走处理链，不递归 on_audio（避免潜在递归爆炸）
            await self._process_audio_chunk(bytes(pending), session_id)
        await self._process_audio_chunk(chunk, session_id)

    def _barge_min_db(self) -> float:
        """播放期认作"用户插话"的最低能量（dBFS）。

        取 VAD 静音门槛**上抬 12dB**。为什么需要：见 `_spawn_speech_end` 的说明 ——
        在修复串行阻塞之前，播放期的上行帧根本到不了 VAD，"她自己的声音把她打断"
        这种自激从未暴露；VAD 一旦实时，外放声就会被麦克风收到。AEC（前端已开
        `echoCancellation`）只能压一部分，所以这里要求明显高于静音门槛的能量。

        VAD 若没暴露 `db_threshold`，回退到保守默认；**绝不因为拿不到门槛就让
        barge-in 失效**（宁可不加这道过滤）。
        """
        base = float(getattr(self._vad, "db_threshold", 60.0))
        margin = float(getattr(self, "_barge_margin_db", 12.0))
        return -base + margin

    def _spawn_speech_end(self, session_id: str) -> None:
        """把「说完了 → 识别 → LLM → TTS」整段**摘出 pcm worker**，改为独立 task。

        为什么必须这样（这是"插话顶不掉她正在念的话"的**根因**）：
        `on_speech_end` 在流式路径下会 `await turn` **等完整个 LLM 生成**（见
        `_turn_tasks` 那一段）。而 main 的 `pcm_worker` 是**单串行**的，它一旦
        await 在这里，之后所有上行 PCM 只能堆在队列里、**根本没被送进 VAD**。
        偏偏 TTS 首句早在 LLM 生成中途就开播了 —— 于是"她正在念一段错话、用户
        要插话纠正"这个**最需要打断的场景**，VAD 恰好是停摆的：插话要等她说完
        才被听见（用户实测："下一个请求顶不掉正在播放的错误回复"）。

        改成 task 后：worker 立刻回到收帧循环 → VAD 全程实时 → 插话即时触发
        barge-in。任务登记进 `_turn_tasks`，`interrupt()` 仍能取消它
        （`on_speech_end` 内部随后会把同一 key 覆盖成真正的 LLM 回合 task，
        先后两种时机都取消得到）。
        """
        # 新语音到来 → 上一个待处理的 SpeechEnd 直接作废：它的音频已经过期，
        # 再跑一遍 ASR/LLM 既是白费算力，也正是"打断后还在忙活"的观感来源。
        prev = self._pending_end.get(session_id)
        if prev is not None and not prev.done():
            prev.cancel()
        gen = self._turn_gen.get(session_id, 0)
        task = asyncio.create_task(self._run_speech_end(session_id, gen))
        self._pending_end[session_id] = task
        self._turn_tasks[session_id] = task

        def _reap(t: asyncio.Task) -> None:
            if self._turn_tasks.get(session_id) is t:
                self._turn_tasks.pop(session_id, None)
            # 必须消费异常：否则取消/失败会在事件循环里报 "never retrieved"
            try:
                t.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001 — 语音回合失败不该拖垮通道
                vlog("voice", f"[{session_id[:8]}] 语音回合任务异常: {exc}")

        task.add_done_callback(_reap)

    async def _run_speech_end(self, session_id: str, gen: int) -> None:
        """SpeechEnd 任务体：带**代际守卫**地跑 `on_speech_end`。

        这里的检查挡的是"派发后立刻就被打断"（还没走到等锁那一步）；
        真正关键的是 `on_speech_end` 里**拿到锁之后**的第二次校验 ——
        打断可能发生在等锁的整个期间。
        """
        if self._turn_gen.get(session_id, 0) != gen:
            vlog("voice", f"[{session_id[:8]}] 回合已过期（派发后即被打断），直接丢弃")
            return
        await self.on_speech_end(session_id, gen=gen)

    async def _process_audio_chunk(self, chunk: bytes, session_id: str) -> None:
        # ★★ 打断关闭时：她说话期间**彻底屏蔽输入**（用户明确要求）——
        #    不收音、不累积、不喂 VAD、不产生任何新请求（连"排队等她说完"都不要）。
        #    原话："我需要的是屏蔽桌宠说话时的收音和请求都暂时屏蔽的效果"。
        #    打开打断开关后这里不再拦，改走 barge-in 判定（你一开口就让她让位）。
        if (self._speaking.get(session_id) or self.playback.busy(session_id)) and not self._barge_in_enabled:
            # 连带清掉半窗残字节与已累积音频：否则残留会与新音频拼接，
            # 把她说话期间听到的尾巴掺进你随后说的第一句里。
            self._pcm_in.pop(session_id, None)
            self._audio[session_id] = []
            self._recording[session_id] = False
            return
        # 前端上行帧长不固定（如 1365 采样），先累积字节，再按 512 采样
        # （int16 1024 字节）切窗喂 VAD，避免整帧越界崩溃。
        buf = self._pcm_in.setdefault(session_id, bytearray())
        buf.extend(chunk)
        frame_bytes = 1024  # 512 samples * 2 bytes (int16)
        while len(buf) >= frame_bytes:
            frame = bytes(buf[:frame_bytes])
            del buf[:frame_bytes]
            audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
            try:
                event = self._vad.feed(audio)
            except Exception as exc:  # noqa: BLE001 — VAD 模型异常降级为错误事件
                await self._emit(
                    session_id,
                    "vad:error",
                    {"message": f"VAD 处理失败: {exc}"},
                )
                return
            if event == VADEvent.SpeechStart:
                await self._emit(
                    session_id,
                    "vad:state",
                    {
                        "state": "active",
                        "prob": round(getattr(self._vad, "last_prob", 0.0), 3),
                        "db": round(getattr(self._vad, "last_db", -120.0), 1),
                    },
                )
                vlog(
                    "voice",
                    f"[{session_id[:8]}] VAD 检测到语音 start "
                    f"(prob={getattr(self._vad, 'last_prob', 0.0):.3f}, "
                    f"db={getattr(self._vad, 'last_db', -120.0):.1f})",
                )
                # ★ 打断总开关（默认关）：关掉时她在说话期间**不被打断** ——
                #   这一句仍会被下面的 `_recording` 分支完整累积，等她说完后照常识别
                #   并回应（靠 `on_speech_end` 里"等 _asr_locked 释放"那段兜住）。
                #   为什么默认关：当前识别 / 降噪不够可靠，自动打断容易被旁人说话、
                #   环境噪声误触发，把她正常的回复切碎。
                if (self._speaking.get(session_id) or self.playback.busy(session_id)) and self._barge_in_enabled:
                    # S03：barge-in 走统一取消入口（main 注入）；未注入时回退本地 interrupt。
                    #
                    # ★ 播放期先做**能量二次确认**：见 `_spawn_speech_end` 的说明 ——
                    #   修复串行阻塞前，播放期的帧到不了 VAD，"自激"从未暴露；VAD 实时后，
                    #   外放的她自己的声音也会被麦克风拾到。这里要求能量明显高于静音门槛
                    #   （+12dB）才认作"用户在插话"，否则判为自听、不打断。
                    #   VAD 不提供 `last_db`（如某些变体）时不加这道门槛 ——
                    #   **宁可牺牲过滤，也不能让 barge-in 失效**。
                    db = getattr(self._vad, "last_db", None)
                    if isinstance(db, (int, float)) and db < self._barge_min_db():
                        vlog(
                            "voice",
                            f"[{session_id[:8]}] 播放期疑似人声但能量不足 "
                            f"(db={db:.1f} < {self._barge_min_db():.1f})：判为自听，不打断",
                        )
                    elif self._barge_in_callback is not None:
                        self._barge_in_callback(session_id)
                    else:
                        self.interrupt(session_id)
                # S01：语音交互 trace 起点（只观测；上一条未正常结束的会兜底输出）
                trace = self._start_trace(session_id)
                trace.mark("speech_start")
                # 前置补白：保留 VAD 确认前已累积的音频（用户开口的头几个字）。
                # 旧实现是 self._audio[session_id] = [frame]，会整体丢弃判定前的音频，
                # 导致每次都说漏开头几个字；这里改为拼接并标记为"录音中"。
                _prev = self._audio.get(session_id, [])
                self._audio[session_id] = _prev + [frame]
                self._recording[session_id] = True
                if _prev:
                    vlog(
                        "voice",
                        f"[{session_id[:8]}] VAD start 补回前置音频 "
                        f"{len(_prev)} 帧（≈{len(_prev) * 32}ms）",
                    )
            elif event == VADEvent.SpeechEnd:
                await self._emit(
                    session_id,
                    "vad:state",
                    {
                        "state": "inactive",
                        "prob": round(getattr(self._vad, "last_prob", 0.0), 3),
                        "db": round(getattr(self._vad, "last_db", -120.0), 1),
                    },
                )
                vlog(
                    "voice",
                    f"[{session_id[:8]}] VAD 语音结束 end，进入识别流程",
                )
                self._audio.setdefault(session_id, []).append(frame)
                self._recording[session_id] = False
                # ★★ 先把这一句**摘出来冻结**，再派发异步回合。
                #    否则 worker 继续处理后续帧时，`_recording` 已为 False → 那些帧
                #    触发 pre-roll 裁剪，把用户刚说的话砍掉、只留最近 12 帧
                #    （实测：说 3.4s → ASR 只拿到 0.38s → 转写"。" → 判为噪音 → 无反应）。
                self._frozen_audio[session_id] = self._audio.pop(session_id, [])
                # ★ 不 await：整段识别/LLM/TTS 摘出 pcm worker，否则 worker 会在此期间
                #   收不了帧（VAD 停摆），插话无法被即时检测。详见 `_spawn_speech_end`。
                self._spawn_speech_end(session_id)
            else:
                _lst = self._audio.setdefault(session_id, [])
                _lst.append(frame)
                # 仅在「录音开始前」做有界裁剪，把前置缓冲限制在 pre_roll_ms 内，
                # 防止静音期无限累积内存、也不会给识别输入塞入超长静音前缀。
                # 录音中绝不裁剪——否则会吃掉正在说的音频。
                if not self._recording.get(session_id):
                    if len(_lst) > self._pre_roll_frames:
                        del _lst[: len(_lst) - self._pre_roll_frames]

    @owned_speech
    async def on_speech_end(self, session_id: str, *, gen: int | None = None) -> None:
        # S01：语音 trace（若未经 VAD 路径直接进入，这里补建，保证打点不丢）
        trace = self.get_trace(session_id) or self._start_trace(session_id)
        trace.mark("speech_end")
        # 单飞：同一 session 同一时刻仅一次识别，避免堆积任务并发累积 _audio
        lock = self._process_lock.setdefault(session_id, asyncio.Lock())
        async with lock:
            # ★ 代际守卫**必须在拿到锁之后再查一次**：从"派发任务"到"拿到锁"之间
            #   可能已经发生打断 —— 此时这一回合的音频与意图都已作废，若继续跑，
            #   就是白跑一次 ASR + LLM + TTS，用户侧的感受正是"打断后她还在忙、
            #   回复迟迟不来"（实测反馈的卡顿与延迟）。
            if gen is not None and self._turn_gen.get(session_id, 0) != gen:
                vlog(
                    "voice",
                    f"[{session_id[:8]}] 等待锁期间已被打断，丢弃本回合（不白跑识别与生成）",
                )
                return
            if self._asr_locked.get(session_id):
                if not self._barge_in_enabled:
                    # ★ 打断关闭 = 她说话期间**完全屏蔽输入**：丢弃，不排队。
                    #   （上一版为了让"不打断也不丢话"在这里等 TTS 释放，但那会在
                    #     队列里排出一个新请求 —— 用户实测明确不要这个效果。）
                    vlog(
                        "voice",
                        f"[{session_id[:8]}] 打断已关闭：她说话期间的输入被屏蔽（本句丢弃）",
                    )
                    return
                # ★ 她**正在说话**（TTS 播放中）—— 这里**不能直接丢弃**。
                #
                # 旧实现是靠 pcm worker 被 LLM/TTS 占住，把 SpeechEnd 天然"延后"到
                # 播放结束之后才处理；异步化（见 `_spawn_speech_end`）之后这个延后
                # 消失了，于是这里直接把用户那句**静默吞掉** —— 实测表现就是
                # "连最基本的识别都没反应"。
                #
                # 改为**等这个标志释放**：barge-in 命中会立刻清掉它（interrupt 里
                # `_asr_locked = False`），TTS 自然播完也会清 —— 两种情况这一句都能
                # 被正常处理。超时（约 3s）才放弃，避免把回合任务挂住。
                for _ in range(60):  # 60 × 50ms ≈ 3s
                    if not self._asr_locked.get(session_id):
                        break
                    await asyncio.sleep(0.05)
                if self._asr_locked.get(session_id):
                    vlog(
                        "voice",
                        f"[{session_id[:8]}] 等 TTS 结束超时（≈3s），放弃本回合",
                    )
                    return
            if not self._can_start(session_id):
                return
            # ★★ 从"确定要处理这一轮"就置 `_speaking=True`（而不是等到 `_speak_impl`）。
            #   否则"她正在占用"的窗口不覆盖 ASR + LLM 阶段 —— 这两个阶段你说的话
            #   照样被收音、进队列（用户实测："屏蔽效果还是不太行"）。
            #   `_speak_impl` 会幂等地再设一次，并在 finally 里清；早退分支各自清回 False。
            self._speaking[session_id] = True
            if self._vad is not None and getattr(self._vad, "_in_speech", False):
                # FSMN 流式：SpeechEnd 由尾静音判定，buffer 已在 feed 内累积；
                # 这里用 _speech_buffer（如有）合并，否则走 _audio 字节累积。
                pass
            # ★ 优先用 SpeechEnd 时**冻结**下来的那一句（见 `_frozen_audio` 的说明）；
            #   没有冻结（测试直接调用 `on_speech_end`、或别的入口）才回退到实时缓冲。
            frozen = self._frozen_audio.pop(session_id, None)
            raw = b"".join(frozen if frozen is not None else self._audio.get(session_id, []))
            self._audio[session_id] = []
            if not raw:
                return
            # ★ 噪音防护①：**极短音频不送识别**。VAD 偶尔会被一声响动触发，
            # 0.1s 的音频既不可能是指令，又要白跑一次 GPU 推理（~100-300ms）。
            # 0.25s 是"再快也说不完一个字"的下限。
            if len(raw) < 16000 * 2 * 0.25:  # int16 → 每采样 2 字节
                vlog(
                    "voice",
                    f"[{session_id[:8]}] 语音过短（{len(raw) / 2 / 16000:.2f}s），忽略",
                )
                # ★ 必须**显式收尾**：这是"没有后续事件"的早退分支，不发事件的话
                #   前端会一直停在"识别中…"（用户实测："总是卡住在识别中"）。
                self._speaking[session_id] = False  # 早退：没进 TTS，手动清回
                await self._emit(session_id, "asr:dropped", {"reason": "too_short"})
                return
            await self._emit(session_id, "asr:start", {"state": "transcribing"})
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            vlog(
                "voice",
                f"[{session_id[:8]}] ASR 开始识别（音频 {len(audio)} 采样 = {len(audio) / 16000:.2f}s）",
            )
            t_asr0 = time.monotonic()
            try:
                text = (await asyncio.to_thread(self._asr.transcribe, audio)).strip()
                check_owner(self, session_id)
            except Exception as exc:  # noqa: BLE001 — 外部 ASR 运行时错误不得中断 WebSocket
                check_owner(self, session_id)
                vlog("voice", f"[{session_id[:8]}] ASR 失败: {exc}")
                self._speaking[session_id] = False  # 早退：识别失败，手动清回
                await self._emit(
                    session_id,
                    "asr:error",
                    {"message": str(exc), "duration_ms": int((time.monotonic() - t_asr0) * 1000)},
                )
                return
            if not text:
                vlog("voice", f"[{session_id[:8]}] ASR 无识别结果（空文本）")
                self._speaking[session_id] = False  # 早退：没进 TTS，手动清回
                await self._emit(session_id, "asr:dropped", {"reason": "empty"})
                return
            # ★ 噪音防护②：**"嗯。"／"(咳嗽)"／"[Music]" 这类转写不是空的**，
            # 若放过就会一路走到 LLM —— 用户侧表现为"她突然回应了一声响动"。
            if is_noise_transcript(text):
                vlog(
                    "voice",
                    f"[{session_id[:8]}] 转写判为噪音（{text!r}），跳过本轮对话",
                )
                # ★ 同上：收尾事件，避免前端 UI 卡在"识别中…"
                self._speaking[session_id] = False  # 早退：没进 TTS，手动清回
                await self._emit(
                    session_id, "asr:dropped", {"reason": "noise", "text": text}
                )
                return
            asr_ms = int((time.monotonic() - t_asr0) * 1000)
            trace.mark("asr_final")
            vlog("voice", f"[{session_id[:8]}] ASR 识别: {text!r}（{asr_ms}ms）")
            await self._emit(
                session_id,
                "asr:text",
                {"text": text, "duration_ms": asr_ms},
            )
            text = self._inspect_before(text, session_id)
            trace.mark("llm_start")
            await self._emit(
                session_id, "llm:start", {"state": "requesting", "input": text}
            )
            vlog("voice", f"[{session_id[:8]}] LLM 请求: {text!r}")
            t_llm0 = time.monotonic()
            # ── A1：流式路径 —— 句子一到就送去合成，首句不必等整段回复 ────────
            # 队列既是句子通道，也是**背压点**：TTS 消费不过来时 LLM 侧会 await。
            if self._sentence_llm is not None:
                queue: asyncio.Queue = asyncio.Queue()

                async def on_sentence(sentence: str) -> None:
                    check_owner(self, session_id)
                    # 原 _inspect_after 作用于整段；逐句调用等价，而且**更早生效**
                    #（不合规的内容在合成前就被拦掉，不会先念出来）。
                    clean = self._inspect_after(sentence, session_id)
                    if clean.strip():
                        await queue.put(clean)

                async def _turn() -> str:
                    try:
                        return await self._sentence_llm(text, session_id, on_sentence)
                    finally:
                        await queue.put(None)  # 结束信号（正常/异常/取消都保证发出）

                async def _sentences():
                    while True:
                        item = await queue.get()
                        if item is None:
                            return
                        yield item

                turn = asyncio.create_task(_turn())
                self._turn_tasks[session_id] = turn
                # 先起播放侧：它阻塞等句子，收到一句合成一句（首段先播）
                speak = asyncio.create_task(
                    self._speak_stream(session_id, _sentences(), trace)
                )
                self._speak_tasks[session_id] = speak
                try:
                    reply = await turn
                except asyncio.CancelledError:
                    cur = asyncio.current_task()
                    if cur is not None and cur.cancelling() > 0:
                        raise  # 本任务自身被取消（如 shutdown）→ 继续向上传播
                    vlog("voice", f"[{session_id[:8]}] LLM 流式回合已被打断取消，本回合结束")
                    return
                finally:
                    if self._turn_tasks.get(session_id) is turn:
                        self._turn_tasks.pop(session_id, None)
                llm_ms = int((time.monotonic() - t_llm0) * 1000)
                trace.mark("llm_final")
                vlog(
                    "voice",
                    f"[{session_id[:8]}] LLM 回复: {reply!r}（{llm_ms}ms，已边收边播）",
                )
                # S52：气泡文字走**展示语言**（与朗读语言解耦）；source_text 是内部中文原文。
                # 注意这里是**整段**渲染（一次调用），朗读侧仍是逐句渲染 —— 两者互不影响。
                await self._emit(
                    session_id,
                    "llm:text",
                    {
                        "text": await self._render_text(reply, "display"),
                        "source_text": reply,
                        "duration_ms": llm_ms,
                    },
                )
                return  # 播放已交给 _speak_stream
            if self._llm is not None:
                # S03：回合包成 task，barge-in 可立即取消（不等 LLM 返回、不进入 TTS）
                turn = asyncio.create_task(self._llm(text, session_id))
                self._turn_tasks[session_id] = turn
                try:
                    reply = await turn
                except asyncio.CancelledError:
                    cur = asyncio.current_task()
                    if cur is not None and cur.cancelling() > 0:
                        raise  # 本任务自身被取消（如 shutdown）→ 继续向上传播
                    vlog("voice", f"[{session_id[:8]}] LLM 回合已被打断取消，本回合结束")
                    return
                finally:
                    if self._turn_tasks.get(session_id) is turn:
                        self._turn_tasks.pop(session_id, None)
            else:
                reply = text
            reply = self._inspect_after(reply, session_id)
            if not reply:
                return
            llm_ms = int((time.monotonic() - t_llm0) * 1000)
            trace.mark("llm_final")
            vlog("voice", f"[{session_id[:8]}] LLM 回复: {reply!r}（{llm_ms}ms）")
            # S52：气泡文字走展示语言（内部原文见 source_text）
            await self._emit(
                session_id,
                "llm:text",
                {
                    "text": await self._render_text(reply, "display"),
                    "source_text": reply,
                    "duration_ms": llm_ms,
                },
            )
            # S37：把本轮的 trace 传进去（见 _speak 的说明）
            task = asyncio.create_task(self._speak(session_id, reply, trace))
            self._speak_tasks[session_id] = task

    async def speak_text(self, session_id: str, text: str, *, source: str = "presence") -> bool:
        """S22：外部触发的主动说话（Presence 的 voice 通道）。

        与对话回复共用同一条 TTS 编排（分段流式 + 首段先播 + 口型 + 可中断）。
        克制原则：**该会话正在说话时直接跳过**（不排队、不打断）——
        主动表达永远不该抢占用户正在听的对话。
        """
        if not (text or "").strip():
            return False
        if self._speaking.get(session_id):
            vlog("voice", f"[{session_id[:8]}] 主动说话跳过（该会话正在说话）")
            return False
        task = asyncio.create_task(self._speak(session_id, text))
        self._speak_tasks[session_id] = task
        vlog("voice", f"[{session_id[:8]}] 主动说话（{source}）: {text[:60]!r}")
        return True

    def _sentences_for(self, reply: str) -> list[str]:
        """整段文本 → 待合成句子列表（S04/S37 的切分策略，逐字保留）。

        S37：首段偏长时再切一刀。后续段是并行合成的，只有**第一段**决定 TTFA，
        所以只收紧首段（整体 max_len 不变，避免把语流切得太碎）。
        """
        if not self._segment_streaming:
            return [reply]
        sentences = split_sentences(reply)
        if sentences and len(sentences[0]) > _FIRST_SEG_MAX:
            sentences = (
                split_sentences(sentences[0], max_len=_FIRST_SEG_MAX) + sentences[1:]
            )
        return sentences or [reply]

    @owned_speech
    async def _speak(self, session_id: str, reply: str, trace=None) -> None:
        """合成并播放（S04 分段流式；S37：trace 由**调用方传入**）。

        trace 不能在这里 ``get_trace(session_id)``：用户连续说话时，新一轮
        ``_start_trace`` 会覆盖同一个 session 的 trace，而上一轮的 TTS 仍在进行 ——
        于是 ``tts_start`` 被打在**新一轮**的对象上（实测 ``tts_start=75ms``，
        早于 speech_start，整条 trace 的时序全乱）。由调用方传"本轮的 trace"即无歧义。
        """
        # S52：整段转换模式（``translate_mode="full"``）在这里**一次性**把整段渲染成
        # 朗读语言，再按目标语言标点分句。逐句模式（默认）不在这里渲染 —— 由
        # ``_speak_impl`` 的投喂侧逐句渲染，以保住 A1 的"首句先出声"。
        # 注意 full 模式**只对整段路径生效**：流式路径的句子是边收边到的，
        # 等整段再翻会直接毁掉流式的意义，故流式路径恒逐句。
        text = reply
        rendered = False
        if self._renderer is not None and getattr(self._renderer, "mode", "sentence") == "full":
            text = await self._render_text(reply, "speak")
            rendered = True
            # 整段模式在这里渲染：lang_render 打点也在这里（_speak_impl 不再重复渲染）
            if trace is not None:
                trace.mark("lang_render")
        await self._speak_impl(
            session_id,
            trace=trace,
            text=text,
            display_text=reply,
            sentences=self._sentences_for(text),
            rendered=rendered,
        )

    @owned_speech
    async def _speak_stream(self, session_id, sentence_iter, trace=None) -> None:
        """A1：**边收句子边合成播放** —— 首句不必等整段回复。

        为什么这是体验上最值钱的一条：LLM 出一段 120 字的回复要好几秒，而用户
        其实**听到第一句就够了**。此前链路是 ``await LLM(完整) → 分句 → TTS``，
        首句出声 = LLM 全量耗时 + TTS 首段耗时；现在句子一到就送合成，
        变成 LLM 首句耗时 + TTS 首段耗时，**首句通常能提前 1~3 秒**。
        """
        await self._speak_impl(session_id, trace=trace, sentence_iter=sentence_iter)

    @owned_speech
    async def _speak_impl(
        self,
        session_id: str,
        *,
        sentences: list[str] | None = None,
        sentence_iter=None,
        text: str = "",
        display_text: str = "",
        trace=None,
        rendered: bool = False,
    ) -> None:
        """TTS 合成与播放的**统一实现**（S04 整段路径 / A1 流式路径共用）。

        两条路径的差别**只在"句子从哪来"**：整段是已切好的列表，流式是陆续到达的
        异步迭代器。其余（并行合成、按序播放、统计、trace、finally 清理）完全共用
        —— 刻意不再写两份，避免"两条路径各自漂移"（本会话已在这上面踩过多次：
        提示词三份、上下文注入两条、工具轮绕过预算……）。
        """
        # 统一「语音回复 TTS」开关关闭：语音回复**不出声**，但保留文字回复
        # （llm:text 已在上游发出，气泡按字数估算收起）。仍需发 tts:end 让前端
        # 复位回合状态（turnBusy / pipelineState.tts），否则 UI 会卡在"合成中"。
        if not self._reply_tts_enabled():
            vlog("voice", f"[{session_id[:8]}] TTS 开关关闭，跳过合成（保留文字回复）")
            self._speaking[session_id] = False
            if trace is not None:
                trace.mark("tts_end")
            try:
                await self._emit(session_id, "tts:end", {})
            finally:
                self._asr_locked[session_id] = False
            return
        self._asr_locked[session_id] = True
        self._speaking[session_id] = True
        # 整段路径的段数**事先已知**，先记下来供上报用；流式路径边收边涨。
        n = len(sentences) if sentences is not None else 0
        opener = getattr(self._tts, 'open_sentence_session', None)
        ws_session = opener() if callable(opener) else None
        ws_failed = False

        async def ws_texts():
            nonlocal n
            from yuiro.audio.speech_text import speech_body

            async def source():
                if sentences is not None:
                    for sentence in sentences:
                        yield sentence
                elif sentence_iter is not None:
                    async for sentence in sentence_iter:
                        yield sentence

            marked = False
            async for sentence in source():
                check_owner(self, session_id)
                clean = speech_body(sentence)
                if not any(ch.isalnum() for ch in clean):
                    continue
                value = clean if rendered else await self._render_text(clean, 'speak')
                check_owner(self, session_id)
                if trace is not None and not marked:
                    marked = True
                    trace.mark('lang_render')
                if sentences is None:
                    n += 1
                yield value

        pipeline = self

        class TurnStream:
            async def synthesize_stream(self, _text):
                nonlocal ws_failed
                import contextlib

                try:
                    async with contextlib.aclosing(ws_session.stream(ws_texts())) as stream:
                        async for part in stream:
                            yield part
                except asyncio.CancelledError:
                    raise
                except Exception:
                    ws_failed = True
                    await pipeline._emit(session_id, 'tts:error',
                                         {'message': 'Fish WS合成失败；未重试或切换音色'})
                    raise

        mgr = TTSTaskManager(TurnStream() if ws_session is not None else self._tts)
        self._tts_managers[session_id] = mgr

        async def _feed() -> None:
            """把句子喂进合成队列；**等所有合成完成才 finish**。

            ⚠ ``enqueue`` 是 fire-and-forget 的 ``create_task``，而 ``finish`` 会让
            ``wait_next`` 在 buffer 还空着时就返回 None → 主循环 break，正在合成的
            段被整体丢弃（**实测 0B 无声音**）。所以这里必须 gather 等它们完成后再
            finish，否则真实 TTS（几百 ms 合成）下首段还没合成完就被 finish 掐断。
            """
            nonlocal n
            pending: list[asyncio.Task] = []
            # S52：首个句子"渲染完成"只打一次 trace（落在 tts_start 之后、
            # tts_first_audio 之前，用来区分"慢在翻译"还是"慢在合成"）
            render_state = {"marked": False}
            previous_admission = asyncio.Event()
            previous_admission.set()

            async def _enqueue_one(seq: int, sentence: str, previous, admitted) -> None:
                """清洗（上游已做）→ 渲染朗读语言 → 入队合成。

                渲染刻意放在**投喂侧**：它是 `await` 的 LLM 往返，放在这里既不阻塞
                AgentLoop 出字（投喂是独立 task），也不影响 `TTSTaskManager` 的
                seq 保序（乱序完成、按序交付）。目标语言 == 内部语言时 renderer
                直接透传 → **零额外调用**。

                ``rendered=True``：整段模式已在 ``_speak`` 里渲染过，这里不再重复。
                """
                from yuiro.audio.speech_text import speech_body

                clean = speech_body(sentence)
                if not any(ch.isalnum() for ch in clean):
                    clean = ""
                started = time.monotonic()
                speak_text = clean if rendered else await self._render_text(clean, "speak")
                rendered_at = time.monotonic()
                # 翻译并发，但后句不能先占满两路合成，让首句排在自己的后句后面。
                await previous.wait()
                admitted.set()
                if speak_text and trace is not None and not render_state["marked"]:
                    render_state["marked"] = True
                    trace.mark("lang_render")
                vlog("voice", f"[{session_id[:8]}] TTS 投喂 seq={seq} chars={len(speak_text)} "
                     f"render_ms={(rendered_at-started)*1000:.0f} "
                     f"admission_wait_ms={(time.monotonic()-rendered_at)*1000:.0f}")
                await mgr.enqueue(seq, speak_text)

            def schedule(seq: int, sentence: str) -> None:
                nonlocal previous_admission
                admitted = asyncio.Event()
                pending.append(asyncio.create_task(
                    _enqueue_one(seq, sentence, previous_admission, admitted)))
                previous_admission = admitted

            try:
                if ws_session is not None:
                    await mgr.enqueue(1, '单轮回复')
                elif sentences is not None:
                    for i, sentence in enumerate(sentences, start=1):
                        schedule(i, sentence)
                elif sentence_iter is not None:
                    async for sentence in sentence_iter:
                        n += 1
                        schedule(n, sentence)
                if pending:
                    await asyncio.gather(*pending)
            finally:
                for task in pending:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                await mgr.finish()

        feed_task = asyncio.create_task(_feed())
        cancelled = False
        try:
            if trace is not None:
                trace.mark("tts_start")
            # S52：``text`` 的语义随渲染时机而变——
            #   · 整段/full 模式：整段译文（渲染发生在 _speak，先于本函数）；
            #   · 逐段/sentence 模式：**内部中文原文**（译文在投喂侧逐段产生，
            #     事先拿不到整段译文，也不该为了它去多翻一次）。
            # ``display_text`` 只在"内部原文 ≠ text"时才带上，供调试台对照。
            _extra = {"display_text": display_text} if display_text and display_text != text else {}
            await self._emit(session_id, "tts:start", {"text": text, **_extra})
            await self._emit(
                session_id,
                "tts:synthesize",
                # 流式路径开始时还不知道总段数，用 -1 表示"未知"（前端不读该字段）
                {"text": text, "segments": n if sentences is not None else -1, **_extra},
            )
            vlog(
                "voice",
                f"[{session_id[:8]}] TTS 合成: {text[:60]!r}"
                f"（{'流式' if sentences is None else f'分 {n} 段'}，首段先播）",
            )
            t_tts0 = time.monotonic()
            first = True
            total_bytes = 0
            total_volumes = 0
            while True:
                segment = await mgr.wait_next()
                if self._tts_managers.get(session_id) is not mgr:
                    return  # 后继回合已接管，旧段不再播放或发送ready/end。
                if segment is None:
                    break  # 上游已 finish 且无更多段（整段路径不会走到这，兜底）
                if not segment.wav:
                    continue  # 单句失败的空段：跳过，不阻塞后续
                check_owner(self, session_id)
                await self._play_callback(session_id, segment)
                total_bytes += len(segment.wav)
                total_volumes += len(segment.volumes)
                if first:
                    first = False
                    if trace is not None:
                        trace.mark("tts_first_audio")
            if ws_failed:
                return
            tts_ms = int((time.monotonic() - t_tts0) * 1000)
            vlog(
                "voice",
                f"[{session_id[:8]}] TTS 完成（{tts_ms}ms, {n} 段, {total_bytes}B）",
            )
            await self._emit(
                session_id,
                "tts:ready",
                {
                    "duration_ms": tts_ms,
                    "segments": n,
                    "wav_bytes": total_bytes,
                    "volumes_count": total_volumes,  # 兼容字段（分段后为各段片数之和）
                },
            )
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            if not feed_task.done():
                feed_task.cancel()
            await asyncio.gather(feed_task, return_exceptions=True)
            # 清自己的manager，不能按session误取/取消后继回合的manager。
            try:
                await mgr.interrupt()
            finally:
                try:
                    if ws_session is not None:
                        await ws_session.close()
                finally:
                    if self._tts_managers.get(session_id) is mgr:
                        self._speaking[session_id] = False
                        if trace is not None and not cancelled:
                            trace.mark("tts_end")
                            asyncio.create_task(self._finalize_trace(session_id, trace=trace))
                        try:
                            if not cancelled:
                                await self._emit(session_id, "tts:end", {})
                        finally:
                            try:
                                await asyncio.sleep(self._asr_lock_cool_ms / 1000)
                            finally:
                                if self._tts_managers.get(session_id) is mgr:
                                    self._tts_managers.pop(session_id, None)
                                    self._asr_locked[session_id] = False

    def interrupt(self, session_id: str) -> asyncio.Task | None:
        self.playback.clear(session_id)
        # S03：先取消 LLM 回合（不再后台跑完），再取消 TTS 播放任务
        turn = self._turn_tasks.pop(session_id, None)
        if turn is not None and not turn.done():
            turn.cancel()
        # ★ 代际 ++：让**所有在途**的 SpeechEnd 任务（含正在等锁的那些）在拿到锁后
        #   自行作废。只 cancel `_turn_tasks` 是不够的 —— 等锁中的任务还没登记进去，
        #   取消不到它（见 `_turn_gen` 声明处的说明）。
        self._turn_gen[session_id] = self._turn_gen.get(session_id, 0) + 1
        pending = self._pending_end.pop(session_id, None)
        if pending is not None and not pending.done():
            pending.cancel()
        task = self._speak_tasks.get(session_id)
        if task is not None and not task.done():
            task.cancel()
        # S04：作废在途 TTS 合成段（epoch++，唤醒等待者）
        mgr = self._tts_managers.get(session_id)
        try:
            _loop = asyncio.get_running_loop()
        except RuntimeError:
            _loop = None  # 同步调用场景（如单测）：跳过事件与 epoch 唤醒
        if _loop is not None and mgr is not None:
            _loop.create_task(mgr.interrupt())
        self._speaking[session_id] = False
        self._asr_locked[session_id] = False
        # ★ 关键分支：barge-in 是**发生在用户说话的过程中**的 —— 此刻 VAD 刚在
        #   SpeechStart 分支写入 `_audio`（含补回的前置音频）并置 `_recording=True`。
        #   若在这里无脑清空，用户"用来打断的那句话"的音频就被删掉了：轻则只识别出
        #   半句，重则什么都没有 —— 表现就是"我说了新的，她还在念旧的"。
        #   所以：**录音中 → 保住本句；否则（例如前端主动 interrupt）才清干净。**
        if self._recording.get(session_id):
            _kept = len(self._audio.get(session_id, []))
            vlog(
                "voice",
                f"[{session_id[:8]}] 打断发生在用户说话中：保留本句 {_kept} 帧供识别",
            )
        else:
            self._audio[session_id] = []
            self._pcm_in[session_id] = bytearray()
            self._recording[session_id] = False
            # 连带清掉冻结的那一句（非录音态被中断 = 这句不要了），避免残留污染下一轮
            self._frozen_audio.pop(session_id, None)
        # S01：被中断的交互丢弃 trace（不输出半途汇总）
        self._traces.pop(session_id, None)
        # S03：通知前端立即停播（清播放队列 + 停口型；本地操作，无需等引擎往返）
        notification = None
        if _loop is not None:
            notification = _loop.create_task(
                emit_owned(self, capture_owner(self, session_id),
                           "tts:interrupted", {"reason": "barge-in"})
            )
        vlog(
            "voice",
            f"[{session_id[:8]}] 打断 (barge-in)：LLM 回合与 TTS 已取消，已通知前端停播",
        )
        return notification
