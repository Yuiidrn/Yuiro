"""本地 CosyVoice2 TTS 服务（独立进程薄壳）。

真实推理逻辑在 yuiro.audio.cosyvoice_engine（与引擎共享同一份代码），
本文件只负责：HTTP 接口 / 模型常驻 / CORS。

启动（须在仓库根目录，用 venv2）：
    . ./config/env.ps1
    & .env-local/engine-venv2/Scripts/python.exe -m yuiro.tts_server.server

或走封装脚本：./engine/tts_server/start_tts_server.ps1
"""

from __future__ import annotations

import logging
import os
import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from yuiro.audio.cosyvoice_engine import ServerState, TTSRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [tts-server] %(levelname)s %(message)s",
)
logger = logging.getLogger("tts-server")

# 仓库根 = tts_server -> yuiro -> engine -> 仓库根（parents[3]）
_REPO_ROOT = Path(__file__).resolve().parents[3]
FP16 = (_REPO_ROOT / ".env-local").exists()
state = ServerState(fp16=FP16)


class TTSReq(BaseModel):
    text: str
    reference_wav: Optional[str] = None
    reference_text: Optional[str] = None
    instruct: Optional[str] = None
    language: str = "auto"


app = FastAPI(title="Yuiro Local TTS", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_loaded": state._model is not None}


@app.post("/tts")
def tts(req: TTSReq) -> Response:
    """合成文本为 wav 字节（标准 RIFF，24kHz PCM16）。

    返回**原始 wav 字节**（media_type=audio/wav），与 engine 侧 CosyVoiceProvider
    期望的 ``resp.content`` 语义一致（父类 synthesize_segment 用 miniaudio 解码算口型）。
    字段：reference_wav / reference_text / instruct / language。
    """
    ref_wav = req.reference_wav or os.environ.get(
        "COSYVOICE_REF_WAV",
        # 仓库根 = tts_server -> yuiro -> engine -> 仓库根（parents[3]）
        str(Path(__file__).resolve().parents[3] / "assets" / "voices" / "neuro_prompt.wav"),
    )
    if not Path(ref_wav).exists():
        raise HTTPException(400, f"参考音频不存在: {ref_wav}")
    ref_text = req.reference_text or os.environ.get("COSYVOICE_REF_TEXT", "")
    try:
        r = TTSRequest(
            text=req.text,
            prompt_wav=ref_wav,
            prompt_text=ref_text,
            instruct=req.instruct or "",
            language=req.language,
        )
        wav_bytes, _sr = state.infer(r)
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as e:  # noqa: BLE001
        logger.error("TTS 合成失败: %s", e)
        traceback.print_exc()
        raise HTTPException(500, f"TTS 合成失败: {e}")


def main() -> None:
    """启动 uvicorn（供 `python -m yuiro.tts_server.server` 使用）。"""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5005)


if __name__ == "__main__":
    main()
