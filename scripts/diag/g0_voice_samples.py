"""Replay a fixed real PCM utterance through VAD/ASR/Agent/TTS/audio WS.

Uses the running configured services, then the existing renderer reply player.
The diagnostic WS bridge bypasses microphone capture and the frontend audio-WS
message handler; report this distinction explicitly. Never auto-approves tools.
"""
import argparse
import asyncio
import json
import os
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import websockets

from g0_browser_samples import stats

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/plan/G0-live-artifacts"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    with wave.open(str(OUT / "voice-input-fixture.wav"), "rb") as wav:
        assert wav.getsampwidth() == 2 and wav.getnchannels() == 1
        source_rate = wav.getframerate()
        source = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    pcm = np.interp(np.arange(round(len(source)*16000/source_rate))*source_rate/16000,
                    np.arange(len(source)), source).astype("<i2").tobytes()
    frames = [pcm[i:i+1024].ljust(1024, b"\0") for i in range(0, len(pcm), 1024)]
    silence = b"\0"*1024
    secret = os.environ.get("YUIRO_SHARED_SECRET", "")
    async with httpx.AsyncClient() as client:
        preflight = (await client.post("http://127.0.0.1:8200/api/diary/transcribe",
            content=pcm, headers={"Content-Type": "application/octet-stream"}, timeout=30)).json()
        (OUT / "voice-fixture-asr-preflight.json").write_text(json.dumps({
            "fixture_duration_s": len(pcm)/32000, "result": preflight,
            "scope": "actual already-warm ASR only; no diary save or Agent turn"}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ASR_preflight": preflight}, ensure_ascii=False), flush=True)
        if args.preflight_only:
            return
        transcript = "".join(c for c in preflight.get("text", "") if c.isalnum())
        if not preflight.get("ok") or transcript not in ("你好呀", "你好啊", "你好", "你好请只回复你好"):
            raise RuntimeError("Fixture transcript is not the expected benign greeting; not replaying into Agent")
        pages = (await client.get("http://127.0.0.1:9222/json/list")).json()
    page = next(p for p in pages if p["title"] == "Yuiro" and p["type"] == "page")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=20_000_000) as cdp:
        seq = 0

        async def evaluate(code):
            nonlocal seq
            seq += 1
            await cdp.send(json.dumps({"id": seq, "method": "Runtime.evaluate", "params": {
                "expression": code, "awaitPromise": True, "returnByValue": True,
                "userGesture": True}}))
            while True:
                reply = json.loads(await cdp.recv())
                if reply.get("id") == seq:
                    if reply.get("result", {}).get("exceptionDetails"):
                        raise RuntimeError(reply["result"]["exceptionDetails"])
                    return reply.get("result", {}).get("result", {}).get("value")

        report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
                  "kind": "real_PCM_VAD_ASR_Agent_TTS_WS_renderer_diagnostic_bridge",
                  "fixture_duration_s": len(pcm)/32000,
                  "limits": "Prerecorded generated utterance, not live microphone/physical speaker measurement. Audio WS to existing renderer enqueueReplyAudio diagnostic bridge; does not exercise production audio-WS handler. Client latency uses Python perf_counter from last speech frame send to first TTS receipt; browser timing separate.",
                  "samples": []}
        async with websockets.connect("ws://127.0.0.1:8200/ws/control",
                additional_headers={"x-yuiro-secret": secret}, max_size=20_000_000) as control:
            ready = json.loads(await control.recv())
            sid = ready["session_id"]
            report["session_id"] = sid
            async with websockets.connect(f"ws://127.0.0.1:8200/ws/audio?session={sid}",
                    additional_headers={"x-yuiro-secret": secret}, max_size=20_000_000) as audio:
                ready_audio = json.loads(await audio.recv())
                report["pipeline_state"] = ready_audio
                for index in range(args.samples+1):
                    row = {"sample": index, "events": [], "audio_segments": 0}
                    t0 = time.perf_counter()
                    last_speech = t0
                    await evaluate("__g0.app.beginReplyPlayback();__g0.active={sample:"+str(index)+",t0:performance.now(),starts:0,ended:0,pending:0,events:[]};true")

                    async def feed():
                        nonlocal last_speech
                        for frame in frames:
                            await audio.send(frame)
                            last_speech = time.perf_counter()
                            await asyncio.sleep(.032)
                        for _ in range(64):
                            await audio.send(silence)
                            await asyncio.sleep(.032)

                    feeder = asyncio.create_task(feed())
                    try:
                        async with asyncio.timeout(90):
                            while True:
                                msg = json.loads(await audio.recv())
                                kind = msg.get("type")
                                row["events"].append({"type": kind, "from_input_start_ms": (time.perf_counter()-t0)*1000})
                                if kind == "asr:text":
                                    row["asr_text"] = msg.get("text")
                                if kind == "tts:audio":
                                    row.setdefault("first_receive_ms", (time.perf_counter()-last_speech)*1000)
                                    row["audio_segments"] += 1
                                    # Encode only this known audio payload, never config/secrets.
                                    payload = json.dumps(msg, ensure_ascii=False)
                                    await evaluate(f"__g0.active.received_segments=(__g0.active.received_segments||0)+1;__g0.app.enqueueReplyAudio({payload});true")
                                if kind == "tts:end":
                                    await evaluate("__g0.active.sent_all=true;__g0.app.endReplyAudio();true")
                                    break
                                if kind in ("asr:error", "asr:dropped"):
                                    row["error"] = kind
                                    break
                        await feeder
                        playback = await evaluate("(async()=>{let t=performance.now();while((__g0.active.pending>0||__g0.active.ended<"+str(row["audio_segments"])+")&&performance.now()-t<30000)await new Promise(r=>setTimeout(r,50));const r={...__g0.active};delete r.t0;__g0.active=null;return r;})()")
                        row["renderer"] = playback
                        if not row["audio_segments"]:
                            row.setdefault("error", "no_audio")
                    except Exception as exc:
                        row["error"] = type(exc).__name__
                        feeder.cancel()
                        await audio.send(json.dumps({"type": "interrupt"}))
                    row["total_ms"] = (time.perf_counter()-t0)*1000
                    if index == 0:
                        report["warmup"] = row
                    else:
                        report["samples"].append(row)
                    report["first_receive"] = stats(report["samples"], "first_receive_ms")
                    report["failures"] = sum(bool(r.get("error")) for r in report["samples"])
                    (OUT / "real-voice-latency.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps({"sample": index, "asr": row.get("asr_text"),
                                      "first_receive_ms": row.get("first_receive_ms"),
                                      "error": row.get("error")}, ensure_ascii=False), flush=True)
                    if row.get("error"):
                        break


if __name__ == "__main__":
    asyncio.run(main())
