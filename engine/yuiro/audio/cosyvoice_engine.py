"""本地 CosyVoice2 推理引擎（独立进程侧使用的共享核心）。

本模块只被 **独立 tts 进程**（uvicorn yuiro.tts_server.server）import，
**engine 主进程的 CosyVoiceProvider 只走 HTTP，绝不 import 本模块**，
借此保持进程隔离：避免 CosyVoice2（~4.8GB 显存）与 SenseVoice ASR 抢显存 / GIL。

所有 torch / cosyvoice / modelscope 的 import 都放在函数内部惰性执行，
确保即便本文件被引擎主进程误 import，也不会在顶层拉起 torch。
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import soundfile as sf


import os

# 仓库根 = engine/yuiro/audio -> 上溯 4 级（audio -> yuiro -> engine -> 仓库根）
_REPO_ROOT = Path(__file__).resolve().parents[3]

COSYVOICE_REPO = os.environ.get(
    "COSYVOICE_REPO",
    str(Path(os.environ.get("YUIRO_MODELS_DIR", "")).parent / "models" / "CosyVoice")
    if os.environ.get("YUIRO_MODELS_DIR")
    else str(_REPO_ROOT / ".env-local" / "models" / "CosyVoice"),
)
MODEL_DIR = os.environ.get(
    "COSYVOICE_MODEL_DIR",
    str(Path(COSYVOICE_REPO).parent / "CosyVoice2-0.5B"),
)


@dataclass
class TTSRequest:
    text: str
    prompt_wav: str          # 参考音频【路径字符串】，frontend 内部用 soundfile 读
    prompt_text: str         # 参考音频转写（zero-shot 必需）
    instruct: str = ""       # 非空时走 inference_instruct2
    language: str = "auto"


def _ensure_sys_path() -> None:
    """把 CosyVoice 仓库与 Matcha-TTS 加入 sys.path（仅需一次）。"""
    repo = Path(COSYVOICE_REPO)
    matcha = repo / "third_party" / "Matcha-TTS"
    for p in (str(repo), str(matcha)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _load_model(fp16: bool = True):
    """惰性加载 CosyVoice2 模型，返回 (model, sample_rate)。"""
    _ensure_sys_path()
    # 以下 import 故意放函数内：避免顶层拉起 torch（引擎主进程零污染）
    from cosyvoice.cli.cosyvoice import CosyVoice2  # type: ignore

    model = CosyVoice2(MODEL_DIR, fp16=fp16)
    return model, model.sample_rate


def _infer_one(model, req: TTSRequest) -> tuple[bytes, int]:
    """合成单条文本，返回 (wav_bytes_pcm16, sample_rate)。

    关键修正（均已踩坑验证）：
    - 参考音频传【路径字符串】，不是 tensor（frontend 内部 load_wav 自行读文件）
    - inference_zero_shot 第 4 参是 zero_shot_spk_id，传 ""（不指定固定说话人）
    - 推理结果是生成器，用 next(iter(...)) 取首段
    - 有 instruction 走 inference_instruct2（原版 inference_instruct 不存在于 v2）
    """
    sample_rate = model.sample_rate
    prompt_wav = str(req.prompt_wav)
    if req.instruct:
        result = model.inference_instruct2(
            req.text, req.instruct, prompt_wav, ""
        )
    else:
        result = model.inference_zero_shot(
            req.text, req.prompt_text, prompt_wav, ""
        )
    first = next(iter(result))
    speech = first["tts_speech"].squeeze(0).detach().cpu().numpy()  # (T,)
    buf = io.BytesIO()
    sf.write(buf, speech, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue(), sample_rate


def synthesize(req: TTSRequest, fp16: bool = True) -> tuple[bytes, int]:
    """对外统一入口：加载模型 + 合成。短生命周期脚本用；常驻服务见 ServerState。"""
    model, _ = _load_model(fp16=fp16)
    return _infer_one(model, req)


class ServerState:
    """常驻 tts 服务持有的单例模型状态（避免每次请求重载）。"""

    def __init__(self, fp16: bool = True):
        self.fp16 = fp16
        self._model = None
        self.sample_rate = 24000

    @property
    def model(self):
        if self._model is None:
            self._model, self.sample_rate = _load_model(fp16=self.fp16)
        return self._model

    def infer(self, req: TTSRequest) -> tuple[bytes, int]:
        return _infer_one(self.model, req)
