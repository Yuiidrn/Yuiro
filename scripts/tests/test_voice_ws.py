"""VoicePipeline 端到端链路测试：连 /ws/audio 发合成语音 PCM，观察全链路事件。

用法: & .env-local\engine-venv\Scripts\python.exe scripts\test_voice_ws.py [--url ws://127.0.0.1:8200/ws/audio]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")  # 避免 GBK 控制台编码错误
except Exception:
    pass

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.exit("websockets 未安装")

WS_URL = "ws://127.0.0.1:8200/ws/audio"
SR = 16000


def make_speech(duration: float, freq: float = 180.0) -> np.ndarray:
    """合成一段带包络的"语音"（正弦 + 噪声 + 谐波），模拟说话。"""
    n = int(SR * duration)
    t = np.arange(n, dtype=np.float32) / SR
    # 语声包络：起伏的振幅
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t)
    envelope = np.clip(envelope, 0.15, 1.0)
    voice = (
        0.6 * np.sin(2 * np.pi * freq * t)
        + 0.3 * np.sin(2 * np.pi * freq * 2 * t)
        + 0.15 * np.sin(2 * np.pi * freq * 3 * t)
    )
    noise = np.random.default_rng(7).normal(0, 0.05, n).astype(np.float32)
    sig = (voice * envelope + noise) * 0.7
    return (sig * 32767).astype(np.int16)


async def make_real_chinese_speech(text: str) -> np.ndarray:
    """用 edge-tts 合成真实中文语音，解码为 16kHz int16（模拟真实说话）。"""
    import edge_tts
    import miniaudio

    communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            audio.extend(chunk.get("data") or b"")
    decoded = miniaudio.decode(
        bytes(audio), output_format=miniaudio.SampleFormat.FLOAT32, nchannels=1
    )
    pcm = np.frombuffer(decoded.samples, dtype=np.float32).copy()
    ratio = decoded.sample_rate / SR
    n = math.floor(len(pcm) / ratio)
    a16 = np.array([pcm[math.floor(i * ratio)] for i in range(n)], dtype=np.float32)
    return (np.clip(a16 * 0.9, -1, 1) * 32767).astype(np.int16)


def make_silence(duration: float) -> np.ndarray:
    return np.zeros(int(SR * duration), dtype=np.int16)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=WS_URL, help="WS /ws/audio 地址")
    ap.add_argument("--speech", type=float, default=1.5, help="语音段秒数（正弦模拟）")
    ap.add_argument("--silence", type=float, default=2.5, help="静音段秒数")
    ap.add_argument("--freq", type=float, default=180.0, help="基频 Hz")
    ap.add_argument("--wait", type=float, default=35.0, help="语音结束后等待秒数")
    ap.add_argument("--tts-text", default="", help="用 edge-tts 合成真实中文语音（替代正弦波）")
    args = ap.parse_args()

    if args.tts_text:
        speech = await make_real_chinese_speech(args.tts_text)
        print(f"[tts] 合成中文语音: {args.tts_text!r} -> {speech.size / SR:.2f}s")
    else:
        speech = make_speech(args.speech, args.freq)
    silence = make_silence(args.silence)

    events: list[dict] = []
    t0 = time.perf_counter()

    def log(kind: str, msg: str) -> None:
        print(f"[{time.perf_counter() - t0:7.2f}s] {kind:12s} {msg}", flush=True)

    async with websockets.connect(args.url) as ws:
        log("sys", f"已连接 {args.url}")

        async def pump(name: str, data: np.ndarray, chunk: int = 4096) -> None:
            log("pump", f"发送 {name}: {data.size} 采样 ({data.size / SR:.2f}s, {chunk} 采样/帧)")
            for i in range(0, data.size, chunk):
                frame = data[i : i + chunk]
                await ws.send(frame.tobytes())
                await asyncio.sleep(chunk / SR)  # 实时速率发送

        # 语音段 → 期望 VAD SpeechStart → vad:state active
        await pump("语音段", speech)
        await asyncio.sleep(1.5)

        # 静音段 → 期望 SpeechEnd → vad:state inactive → asr:start → asr:text → llm:start → llm:text → tts:*
        await pump("静音段", silence)
        await asyncio.sleep(args.wait)  # 等 ASR(首载 ~14s)+LLM+TTS 完成

        # 收集剩余事件
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                events.append(msg)
                if msg.get("type") in ("tts:end", "tts:audio"):
                    pass
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            pass

    print("\n===== 收到的事件 =====", flush=True)
    if not events:
        print("(无任何事件——链路未通)", flush=True)
    for e in events:
        t = e.get("type")
        if t == "tts:audio":
            wav = e.get("wav", "")
            print(f"  {t:12s} session={str(e.get('session_id'))[:8]} wav={len(wav)}B "
                  f"rate={e.get('sample_rate')} volumes={len(e.get('volumes') or [])}", flush=True)
        elif t in ("vad:state", "asr:start", "asr:text", "asr:error", "llm:start",
                   "llm:text", "tts:start", "tts:synthesize", "tts:ready", "tts:end"):
            print(f"  {t:12s} {json.dumps(e, ensure_ascii=False)[:220]}", flush=True)
        else:
            print(f"  {t:12s} {json.dumps(e, ensure_ascii=False)[:220]}", flush=True)

    kinds = {e.get("type") for e in events}
    print(f"\n===== 覆盖事件类型: {sorted(kinds)} =====", flush=True)
    expected = {"vad:state", "asr:start", "asr:text", "llm:start", "llm:text",
                "tts:start", "tts:synthesize", "tts:ready", "tts:audio"}
    missing = expected - kinds
    print(f"期望 {sorted(expected)}", flush=True)
    if missing:
        print(f"缺失: {sorted(missing)}", flush=True)
        sys.exit(2)
    print("全链路事件齐备", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
