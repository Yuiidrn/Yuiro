"""Refresh focus inventory without overwriting the earlier G0 snapshot."""
import json

from g0_baseline import ROOT, inventory

result = inventory()
result["scope"] = "2026-10-23 user focus: Hiyori + Hotaru Shiomi"
result["out_of_scope_registry_errors"] = [
    {"model": m["model"], "errors": m["errors"]} for m in result["models"]
    if not m["model"].startswith(("hiyori/", "Hotaru Shiomi/"))]
result["models"] = [m for m in result["models"]
                    if m["model"].startswith(("hiyori/", "Hotaru Shiomi/"))]
out = ROOT / "docs/plan/G0-live-artifacts/focus-inventory.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"models": len(result["models"]),
                  "focus_errors": sum(len(m["errors"]) for m in result["models"]),
                  "out_of_scope_registry_errors": result["out_of_scope_registry_errors"]}, ensure_ascii=False))
