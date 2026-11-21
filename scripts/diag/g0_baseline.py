"""G0 read-only inventory + explicitly synthetic pipeline measurements.

Run from repository root using the existing engine venv. Never imports main,
reads keychain, starts services, calls cloud APIs, or writes user databases.
JSON outputs are restricted to docs/plan/G0-baseline-artifacts.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import io
import json
import math
import platform
import socket
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/plan/G0-baseline-artifacts"


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def git(*args):
    return subprocess.check_output(
        ["git", "-c", "core.quotepath=false", *args], cwd=ROOT, encoding="utf-8"
    ).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    result = {}
    for folder in ("engine/yuiro", "engine/tests", "shell/src", "system-daemon/src"):
        for p in (ROOT / folder).rglob("*"):
            if p.is_file() and p.suffix in {".py", ".ts", ".vue", ".cpp", ".hpp"}:
                result[p.relative_to(ROOT).as_posix()] = digest(p)
    return result


def metadata():
    safe_fields = {
        "server": ["host", "port"], "llm": ["provider", "model"],
        "vad": ["provider", "barge_in_enabled"],
        "hard_of_hearing": ["provider", "barge_in_enabled"],
        "asr": ["provider", "model", "device"],
        "tts": ["provider", "stream_llm", "segment_streaming", "reply_tts_enabled"],
        "language": ["internal_language", "display_language", "speak_language", "mode"],
        "memory": ["embedder", "backend"], "systemd": ["backend", "approval_mode"],
    }
    config_path = ROOT / "engine/config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
    ports = {}
    for port in (8200, 5000, 5005, 9100):
        with socket.socket() as sock:
            sock.settimeout(0.25)
            ports[str(port)] = {"tcp_listening": sock.connect_ex(("127.0.0.1", port)) == 0}
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "head": git("rev-parse", "HEAD"), "dirty": git("status", "--porcelain=v1"),
        "python": sys.version, "platform": platform.platform(), "ports": ports,
        "config_file_present": config_path.exists(),
        "config_nonsecret_allowlist": {
            sec: {k: config[sec][k] for k in keys if k in config[sec]}
            for sec, keys in safe_fields.items() if sec in config
        },
        "limits": "TOML values only; env overrides, credentials and live app state not inspected",
    }


def inventory():
    root = ROOT / "shell/src/renderer/public/live2d"
    registry = json.loads((root / "model_dict.json").read_text(encoding="utf-8-sig"))
    models = set(root.rglob("*.model3.json"))
    for entry in registry.get("models", {}).values():
        path = str(entry.get("modelPath", ""))
        if path.startswith("/live2d/"):
            models.add(root / path.removeprefix("/live2d/"))
    results = []
    for model in sorted(models):
        item = {"model": model.relative_to(root).as_posix(), "reviewed": False,
                "review_status": "candidate_only_visual_review_pending", "errors": []}
        if not model.is_file():
            item["errors"].append("model3 missing")
            results.append(item)
            continue
        data = json.loads(model.read_text(encoding="utf-8-sig"))
        refs = data.get("FileReferences", {})
        item["model3_sha256"] = digest(model)
        item["groups"] = data.get("Groups", [])
        resources = []
        for kind in ("Moc", "Physics", "Pose", "DisplayInfo", "UserData"):
            if refs.get(kind):
                resources.append((kind, refs[kind]))
        resources.extend(("Texture", x) for x in refs.get("Textures", []))
        resources.extend(("Expression", e["File"]) for e in refs.get("Expressions", []) if e.get("File"))
        motions = []
        for group, entries in refs.get("Motions", {}).items():
            for index, motion in enumerate(entries):
                file = motion.get("File", "")
                resources.append(("Motion", file))
                mp = model.parent / file
                rec = {"group": group, "index": index, "file": file, "reviewed": False}
                if mp.is_file():
                    raw = json.loads(mp.read_text(encoding="utf-8-sig"))
                    meta = raw.get("Meta", {})
                    ids = [c.get("Id", "") for c in raw.get("Curves", []) if c.get("Target") == "Parameter"]
                    rec.update(duration_s=meta.get("Duration"), loop=meta.get("Loop"),
                               sha256=digest(mp), parameter_ids=sorted(set(ids)),
                               mouth_open_curve="ParamMouthOpenY" in ids)
                motions.append(rec)
        moc = model.parent / refs.get("Moc", "")
        if moc.is_file():
            with moc.open("rb") as f:
                item["moc_version_byte"] = list(f.read(5))[-1]
        item["references"] = [
            {"kind": kind, "file": file, "exists": (model.parent / file).is_file()}
            for kind, file in resources
        ]
        item["errors"].extend(f"missing {r['kind']}: {r['file']}" for r in item["references"] if not r["exists"])
        item["expressions"] = refs.get("Expressions", [])
        item["motions"] = motions
        item["counts"] = {"expressions": len(item["expressions"]), "motions": len(motions),
                          "loop_true": sum(m.get("loop") is True for m in motions),
                          "mouth_open_curves": sum(m.get("mouth_open_curve", False) for m in motions)}
        results.append(item)
    return {"registry_default": registry.get("default"), "models": results,
            "selection": {"primary": "hiyori/Hiyori.model3.json",
                          "co_primary": "Hotaru Shiomi/016_casual_spring_01/016_casual_spring_01.model3.json",
                          "sparse_variant": "Hotaru Shiomi/016_child_casual_spring_01_still/016_child_casual_spring_01_still.model3.json"},
            "selection_note": "G0 engineering sample selection, not changing active model or visually approving assets"}


def stats(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    return {"n": len(values), "p50_ms": round(values[math.ceil(len(values) * .5)-1], 3),
            "p95_ms": round(values[math.ceil(len(values) * .95)-1], 3), "max_ms": round(values[-1], 3)}


async def synthetic(samples):
    sys.path.insert(0, str(ROOT / "engine"))
    import numpy as np
    from yuiro.agent import AgentLoop, LLMChunk, LLMProvider
    from yuiro.audio import AudioSegment, VoicePipeline
    from yuiro.runtime import SessionManager
    from yuiro.runtime.adapters import AgentRuntimeAdapter

    class FakeLLM(LLMProvider):
        async def stream_text(self, messages, tools=None, **kwargs):
            await asyncio.sleep(.005)
            yield LLMChunk(kind="token", content="你好，今天也一起慢慢来。")
            await asyncio.sleep(.005)
            yield LLMChunk(kind="token", content="我正在这里认真听你说话。")
            yield LLMChunk(kind="done")

    class Registry:
        def schemas(self, toolset=None):
            return []

    class Memory:
        async def retrieve(self, text, top_k=3):
            await asyncio.sleep(0)
            return []

    class ASR:
        def transcribe(self, audio, **kwargs):
            return "你好，今天怎么样？"

    class TTS:
        async def synthesize_segment(self, text):
            await asyncio.sleep(.005)
            # Deliberately NOT a WAV: callback sink, no physical or browser playback.
            return AudioSegment(wav=text.encode(), sample_rate=24000, volumes=[.1], slice_ms=20)

    sessions = SessionManager()
    session = sessions.create()
    loop = AgentLoop(FakeLLM(), Registry(), Memory())
    rows = []
    pipe = None
    active = {}

    async def sentence_llm(text, sid, on_sentence):
        trace = pipe.get_trace(sid)
        trace.mark("agent_start")
        chunks = []
        async for chunk in loop.send(sid, text, session=session, trace=trace):
            if chunk.kind == "token":
                trace.mark("llm_first_token")
                chunks.append(chunk.content)
                await on_sentence(chunk.content)
        trace.mark("agent_end")
        return "".join(chunks)

    async def play(sid, segment):
        active.setdefault("first_callback_ms", (time.perf_counter()-active["start"])*1000)
        active["segments"] = active.get("segments", 0)+1

    pipe = VoicePipeline(asr=ASR(), tts=TTS(), sentence_llm_callback=sentence_llm,
                         play_callback=play, asr_lock_cool_ms=0)
    for index in range(samples+1):
        active = {"start": time.perf_counter()}
        trace = pipe._start_trace(session.session_id)
        pipe._audio[session.session_id] = [np.zeros(8000, dtype=np.int16).tobytes()]
        failure = None
        try:
            await asyncio.wait_for(pipe.on_speech_end(session.session_id), 3)
            task = pipe._speak_tasks.get(session.session_id)
            if task:
                await asyncio.wait_for(task, 3)
            if active.get("segments", 0) != 2:
                failure = "expected_two_callback_segments"
        except Exception as exc:
            failure = type(exc).__name__
        marks = dict(trace._marks)
        pipe._traces.pop(session.session_id, None)
        if index:
            rows.append({"sample": index, "trace_id": trace.trace_id, "error": failure,
                         "first_callback_ms": active.get("first_callback_ms"),
                         "pipeline_done_ms": round((time.perf_counter()-active["start"])*1000, 3),
                         "segments": active.get("segments", 0), "marks_ms": marks})

    # Characterization only: demonstrate Adapter still points at the original object.
    adapter = AgentRuntimeAdapter(loop)
    replacement = AgentLoop(FakeLLM(), Registry(), Memory())
    await adapter.cancel("g0-probe", "g0")
    retention = {"old_generation_changed": loop._generations.get("g0-probe") == 1,
                 "replacement_generation_unchanged": "g0-probe" not in replacement._generations,
                 "scope": "actual adapter with replacement simulated; not invoking FastAPI lifespan"}
    return {"measurement_kind": "synthetic_dependency_pipeline_callback_NOT_real_TTFA",
            "warmup_excluded": 1, "samples": rows,
            "injected_delays_ms": {"LLM_chunk": 5, "TTS_segment": 5},
            "limits": "Fake ASR/LLM/TTS, direct on_speech_end, real AgentLoop/VoicePipeline/manager; no VAD/WS/renderer/audio device",
            "failures": sum(r["error"] is not None for r in rows),
            "first_callback": stats([r["first_callback_ms"] for r in rows if r["first_callback_ms"] is not None]),
            "pipeline_done": stats([r["pipeline_done_ms"] for r in rows]),
            "adapter_characterization": retention,
            "real_hot_samples": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.samples <= 100:
        parser.error("samples must be 1..100")
    before = source_hashes()
    save("environment.json", metadata())
    save("source-hashes.json", before)
    assets = inventory()
    save("live2d-inventory.json", assets)
    with contextlib.redirect_stdout(io.StringIO()):
        results = asyncio.run(synthetic(args.samples))
    save("synthetic-latency.json", results)
    changed = [p for p, h in before.items() if not (ROOT/p).is_file() or digest(ROOT/p) != h]
    save("source-integrity.json", {"changed_existing_files": changed, "checked": len(before)})
    print(json.dumps({"models": len(assets["models"]), "missing_refs": sum(len(m["errors"]) for m in assets["models"]),
                      "synthetic": results["first_callback"], "failures": results["failures"],
                      "existing_sources_changed": changed}, ensure_ascii=False))
    return int(bool(changed) or results["failures"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
