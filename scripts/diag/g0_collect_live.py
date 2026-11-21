"""Freeze nonsecret live evidence and integrity after G0 diagnostics."""
import hashlib
import json
from datetime import datetime, timezone

import httpx

from g0_baseline import ROOT, metadata

OUT = ROOT / "docs/plan/G0-live-artifacts"


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    save("environment-live.json", metadata())
    with httpx.Client(base_url="http://127.0.0.1:8200") as client:
        save("health-runtime.json", {"health": client.get("/health").json(),
             "runtime": client.get("/api/runtime").json(),
             "limits": "Runtime state reports registered adapters; not proof registry references equal active request objects"})
        logs = client.get("/api/logs/tail", params={"n": 2000, "source": "trace"}).json()
        save("trace-live.json", logs)
    baseline = json.loads((ROOT / "docs/plan/G0-baseline-artifacts/source-hashes.json").read_text(encoding="utf-8"))
    changed = [p for p, digest in baseline.items()
               if not (ROOT / p).is_file() or hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != digest]
    save("source-integrity-live.json", {"changed": changed, "checked": len(baseline),
                                       "limits": "Original 236 source files, not binary assets or user data"})
    files = [p for p in OUT.iterdir() if p.is_file() and p.name != "artifact-manifest.json"]
    save("artifact-manifest.json", {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
         "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}})
    print(json.dumps({"source_changed": changed, "artifacts": len(files), "traces": logs.get("count")}))


if __name__ == "__main__":
    main()
