"""G0 current SDK preview, success receipts and unreviewed screenshots.

Preview changes renderer model only through its existing shell-event entry.
Engine TOML/profile stays unchanged; Hotaru backend profile integration remains
an explicit separate acceptance item. Screenshots are evidence, not visual scores.
"""
import asyncio
import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/plan/G0-live-artifacts"
MODELS = {
    "hiyori": "/live2d/hiyori/Hiyori.model3.json",
    "hotaru": "/live2d/Hotaru Shiomi/016_casual_spring_01/016_casual_spring_01.model3.json",
}
SCENES = [
    ("greet", {"expression_slot": "happy", "motion_slot": "greet"}),
    ("thinking", {"expression_slot": "thinking", "motion_slot": "thinking"}),
    ("comfort", {"expression_slot": "sad", "motion_slot": "comfort"}),
    ("celebrate", {"expression_slot": "playful", "motion_slot": "celebrate"}),
    ("shy", {"expression_slot": "shy"}),
    ("fallback", {"expression_slot": "g0_unsupported", "motion_slot": "g0_unsupported"}),
]
FIND = "const v=[...document.querySelectorAll('*')].find(e=>e.__vueParentComponent?.type.__file?.includes('Live2DCanvas')).__vueParentComponent.setupState;"


async def main():
    async with httpx.AsyncClient() as client:
        pages = (await client.get("http://127.0.0.1:9222/json/list")).json()
    page = next(p for p in pages if p["title"] == "Yuiro" and p["type"] == "page")
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "reviewed": False,
              "scope": "actual renderer model loads and semantic intent previews, 5 repetitions each; not full six conversational Showcases or automatic visual approval",
              "models": []}
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=20_000_000) as ws:
        seq = 0

        async def call(method, params):
            nonlocal seq
            seq += 1
            await ws.send(json.dumps({"id": seq, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == seq:
                    if msg.get("error"):
                        raise RuntimeError(msg["error"])
                    return msg["result"]

        async def evaluate(expression):
            result = await call("Runtime.evaluate", {"expression": expression,
                "returnByValue": True, "awaitPromise": True, "userGesture": True})
            if result.get("exceptionDetails"):
                raise RuntimeError(result["exceptionDetails"])
            return result.get("result", {}).get("value")

        try:
            for key, path in MODELS.items():
                model_record = {"model": key, "path": path, "scenes": []}
                report["models"].append(model_record)
                loaded = await evaluate("(async()=>{"+FIND+f"const t=performance.now();await v.switchModel({json.dumps(path)});return {{load_ms:performance.now()-t,path:v.currentModelPath,error:v.loadError,model_present:!!v.model,expressions:v.listExpressions(),motions:v.listMotions()}};"+"})()")
                model_record["loaded"] = loaded
                print(json.dumps({"model": key, "loaded": loaded.get("model_present"),
                                  "error": loaded.get("error")}), flush=True)
                await evaluate("(()=>{"+FIND+r"""
const mm=v.model?.internalModel?.motionManager;
window.__g0Motion=[];
if(mm){const original=mm.startMotion;mm.startMotion=function(...args){
 const rec={args:args.slice(0,3),at:performance.now(),resolved:null};__g0Motion.push(rec);
 return Promise.resolve(original.apply(this,args)).then(ok=>{rec.resolved=ok;return ok;},e=>{rec.error=String(e);throw e;});
};mm.on('motionFinish',()=>__g0Motion.push({event:'finish',at:performance.now()}));}
return true;})()""")
                for name, intent in SCENES:
                    for repeat in range(1, 6):
                        row = await evaluate("(async()=>{"+FIND+
                            "__g0Motion.length=0;const t=performance.now();v.applyAvatarIntent("+
                            json.dumps({**intent, "duration_ms": 1800})+
                            ");await new Promise(r=>setTimeout(r,2400));return {state:{...v.avatarState},error:v.loadError,model_present:!!v.model,receipts:__g0Motion.map(x=>({...x,at_ms:x.at-t,at:undefined}))};})()")
                        model_record["scenes"].append({"scene": name, "repeat": repeat, "intent": intent, **row})
                        if repeat == 1:
                            shot = await call("Page.captureScreenshot", {"format": "png"})
                            (OUT / f"{key}-{name}.png").write_bytes(base64.b64decode(shot["data"]))
                        (OUT / "avatar-live-checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps({"model": key, "scene": name, "repetitions": 5}), flush=True)
        finally:
            await evaluate("(async()=>{"+FIND+"await v.switchModel("+json.dumps(MODELS["hiyori"])+");return true;})()")
            report["restored_renderer_model"] = MODELS["hiyori"]
            (OUT / "avatar-live-checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
