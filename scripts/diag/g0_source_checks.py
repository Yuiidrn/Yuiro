"""G0 AST landmarks and isolated lifespan-tail characterization, no app import."""
from __future__ import annotations

import ast
import asyncio
import importlib.metadata
import json
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/plan/G0-baseline-artifacts"


def save(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def shutdown_probe(tree):
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    yield_index = next(i for i, n in enumerate(fn.body)
                       if isinstance(n, ast.Expr) and isinstance(n.value, ast.Yield))
    # Execute the exact production teardown statements against empty fake state.
    probe = ast.AsyncFunctionDef(name="probe", args=fn.args, body=fn.body[yield_index+1:],
                                 decorator_list=[], returns=None)
    module = ast.fix_missing_locations(ast.Module(body=[probe], type_ignores=[]))
    namespace = {}
    exec(compile(module, "<actual lifespan teardown AST>", "exec"), namespace)
    try:
        await namespace["probe"](SimpleNamespace(state=SimpleNamespace(system_daemon=None)))
        return {"error": None}
    except Exception as exc:
        return {"error": type(exc).__name__, "message": str(exc), "source_line": 860,
                "scope": "exact teardown AST, fake app state; startup/real service not executed"}


def main():
    landmarks = {}
    paths = ["engine/yuiro/main.py", "engine/yuiro/debug_api.py", "engine/yuiro/agent/__init__.py",
             "engine/yuiro/audio/__init__.py", "engine/yuiro/runtime/session.py",
             "engine/yuiro/runtime/contract.py", "engine/yuiro/runtime/adapters.py",
             "engine/yuiro/avatar/runtime.py", "engine/yuiro/memory/__init__.py"]
    for p in paths:
        tree = ast.parse((ROOT/p).read_text(encoding="utf-8-sig"))
        landmarks[p] = [{"symbol": n.name, "line": n.lineno, "kind": type(n).__name__}
                        for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    save("source-landmarks.json", landmarks)
    main_tree = ast.parse((ROOT/paths[0]).read_text(encoding="utf-8-sig"))
    result = asyncio.run(shutdown_probe(main_tree))
    save("shutdown-characterization.json", result)
    config = tomllib.loads((ROOT/"engine/config.toml").read_text(encoding="utf-8-sig"))
    package_versions = {}
    for name in ("pytest", "fastapi", "numpy", "ruff", "openai", "httpx", "sqlite-vec"):
        try:
            package_versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            package_versions[name] = None
    package_versions["persona_model_path_from_TOML_only"] = config.get("persona", {}).get("model_path")
    save("package-versions.json", package_versions)
    sys.path.insert(0, str(ROOT/"engine"))
    from yuiro.config import active_profile, effective_motion_slots, effective_persona_maps, load_config
    cfg = load_config(ROOT/"engine/config.toml")
    expression, motion, performance = effective_persona_maps(cfg.persona)
    save("effective-avatar-profile.json", {
        "model_path": cfg.persona.model_path,
        "active_profile": active_profile(cfg.persona),
        "expression_map": expression, "motion_map": motion, "performance_map": performance,
        "motion_slots": effective_motion_slots(cfg.persona),
        "review_status": "existing_mapping_only_no_visual_approval",
    })
    junit = ET.parse(OUT/"pytest.xml").getroot()
    suite = junit.find("testsuite")
    by_file = {}
    for case in suite.findall("testcase"):
        file = ".".join(case.get("classname", "").split(".")[:2])
        rec = by_file.setdefault(file, {"tests": 0, "duration_s": 0.0})
        rec["tests"] += 1
        rec["duration_s"] += float(case.get("time", "0"))
    save("regression-summary.json", {"suite": suite.attrib, "by_file": by_file,
         "limits": "pytest time includes execution/import/model work; not conversational latency"})
    lint = subprocess.run([str(ROOT/".env-local/engine-venv2/Scripts/python.exe"), "-m", "ruff", "check",
                           "engine/yuiro/main.py", "--select", "F821", "--output-format", "json"],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    save("main-f821.json", {"exit_code": lint.returncode, "diagnostics": json.loads(lint.stdout),
         "limits": "scoped F821 only, not whole-repository lint"})
    print(json.dumps({"shutdown": result, "test_files": len(by_file), "lint_exit": lint.returncode}))


if __name__ == "__main__":
    main()
