"""验证本地 CosyVoice2 音色克隆（中英两段合成）。

须在 tts-server 已启动后运行：
    & .env-local/engine-venv2/Scripts/python.exe -m yuiro.tts_server.test_voice
"""

import io
import sys
from pathlib import Path

import httpx
import soundfile as sf

# Windows 控制台 GBK 编码会报错/乱码（中文与 ✓），强制 stdout 走 UTF-8
# 用 getattr 规避类型检查（reconfigure 运行时一定存在）
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

URL = "http://127.0.0.1:5005/tts"
REF_WAV = "D:/Project/Yuii/desktop-pet/Yuiro/assets/voices/neuro_prompt.wav"
REF_TEXT = "嗯，你说什么？我刚才在想别的事情，你再说一遍试试看。"


def synth(text: str, instruct: str = "") -> None:
    with httpx.Client(timeout=120) as c:
        r = c.post(
            URL,
            json={
                "text": text,
                "reference_wav": REF_WAV,
                "reference_text": REF_TEXT,
                "instruct": instruct,
            },
        )
        r.raise_for_status()
        wav_bytes = r.content  # 服务端返回原始 wav 字节
    data, sr = sf.read(io.BytesIO(wav_bytes))
    out = f"{Path(__file__).parent}/samples/sample_{'zh' if any('一' <= ch <= '鿿' for ch in text) else 'en'}.wav"
    with open(out, "wb") as f:
        f.write(wav_bytes)
    print(f"[OK] {text[:20]!r} -> {out} ({len(wav_bytes)} bytes, {sr}Hz, {len(data)} samples)")


if __name__ == "__main__":
    Path(__file__).parent.joinpath("samples").mkdir(exist_ok=True)
    synth("你好，我是幽萝，今天也要好好欺负一下 Yui 呢。", "用自然、慵懒又带点毒舌的中文语气说。")
    synth("Hey Yui, stop debugging me and get some sleep already.",
          "Speak in a natural, slightly sarcastic English tone.")
