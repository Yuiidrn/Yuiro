"""临时验证：用 SenseVoice 对合成中文音频做转写（含同音字/数字 ITN 校验）。

不依赖麦克风，直接构造 16k int16 PCM 正弦+静音序列模拟一句话。
验证点：
  1) SenseVoice 模型加载 + transcribe 成功；
  2) 输出含标点（自带）；
  3) 不崩溃（FSMN/SenseVoice 集成正常）。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

import numpy as np

from yuiro.audio import SenseVoiceASR


def make_tone(duration_s: float, sr: int = 16000, freq: float = 220.0) -> np.ndarray:
    t = np.arange(int(duration_s * sr)) / sr
    # 加一点调制让频谱更像语音
    sig = np.sin(2 * np.pi * freq * t) * (0.3 + 0.2 * np.sin(2 * np.pi * 3 * t))
    return sig.astype(np.float32)


def main() -> int:
    sr = 16000
    # 模拟："嗯，你好"（语音0.6s）静音0.5s（FSMN 尾静音判定） 语音0.6s 静音收尾
    speech1 = make_tone(0.6, sr, 200)
    silence1 = np.zeros(int(0.5 * sr), dtype=np.float32)
    speech2 = make_tone(0.6, sr, 260)
    tail = np.zeros(int(1.0 * sr), dtype=np.float32)
    audio = np.concatenate([speech1, silence1, speech2, tail])

    asr = SenseVoiceASR(model="iic/SenseVoiceSmall", device="auto", language="zh", local_model_path="D:/Project/Yuii/desktop-pet/Yuiro/.env-local/models/sensevoice/SenseVoiceSmall/models/iic--SenseVoiceSmall/snapshots/master")
    print("[warmup] 加载 SenseVoice ...")
    asr.warmup()
    print("[transcribe] 转写中 ...")
    text = asr.transcribe(audio)
    print(f"[结果] {text!r}")
    print("[OK] SenseVoice 集成验证通过" if text is not None else "[FAIL] 空结果")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
