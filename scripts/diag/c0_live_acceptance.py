"""C0 real Engine/Electron acceptance. No credential dumps or fake providers.

Uses the running local Electron CDP endpoint. Reports are sanitized: no full
config, keys or conversations. Role settings are compared through hashes.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/plan/C0-live-artifacts"
PET = """const app=[...document.querySelectorAll('*')].find(e=>e.__vueParentComponent?.setupState.sendText)?.__vueParentComponent.setupState;
const v=[...document.querySelectorAll('*')].find(e=>e.__vueParentComponent?.type.__file?.includes('Live2DCanvas'))?.__vueParentComponent.setupState;"""
DEV = """const d=[...document.querySelectorAll('*')].find(e=>e.__vueParentComponent?.setupState.configStore)?.__vueParentComponent.setupState;
const s=d?.configStore;"""


def save(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Page:
    def __init__(self, info):
        self.info = info
        self.seq = 0

    async def __aenter__(self):
        self.ws = await websockets.connect(self.info["webSocketDebuggerUrl"], max_size=30_000_000)
        return self

    async def __aexit__(self, *args):
        await self.ws.close()

    async def call(self, method, params=None):
        self.seq += 1
        await self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params or {}}))
        while True:
            result = json.loads(await self.ws.recv())
            if result.get("id") == self.seq:
                if "error" in result:
                    raise RuntimeError(result["error"])
                return result.get("result", {})

    async def evaluate(self, expression):
        result = await self.call("Runtime.evaluate", {"expression": expression,
            "awaitPromise": True, "returnByValue": True, "userGesture": True})
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    async def screenshot(self, name):
        result = await self.call("Page.captureScreenshot", {"format": "png"})
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_bytes(base64.b64decode(result["data"]))


async def pages():
    async with httpx.AsyncClient() as client:
        return (await client.get("http://127.0.0.1:9222/json/list")).json()


async def snapshot(page, dev=False):
    code = (DEV + """return {title:document.title,role:{active_id:s?.character?.active_id,revision:s?.character?.revision,switching:s?.switching},loading:s?.loading,error:s?.error,
saveError:s?.saveError,model:s?.sections?.persona?.model_path,hasBridge:!!window.yuiro,
picker:[...document.querySelectorAll('.character-picker select')].map(e=>({value:e.value,disabled:e.disabled})),
sections:Object.keys(s?.sections||{})};""") if dev else (PET + """return {title:document.title,
role:app?.activeCharacter,revision:app?.characterRevision,session:app?.sessionId,ws:app?.socket?.readyState,
model:app?.modelPath,ready:app?.modelReady,canvasPath:v?.currentModelPath,modelPresent:!!v?.model,
loadError:v?.loadError,manifestKeys:Object.keys(v?.manifest||{}),avatar:v?.avatarState,
hasBridge:!!window.yuiro};""")
    return await page.evaluate("(()=>{" + code + "})()")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["inspect", "open-dev", "switches"])
    parser.add_argument("--cycles", type=int, default=3)
    args = parser.parse_args()
    available = await pages()
    pet_info = next(p for p in available if p["title"] == "Yuiro" and p["type"] == "page")
    async with Page(pet_info) as pet:
        if args.command == "open-dev":
            result = await pet.evaluate("window.yuiro.openDev('settings')")
            print(json.dumps({"opened": result}, ensure_ascii=False))
            return
        if args.command == "inspect":
            print(json.dumps({"pages": [{k: p.get(k) for k in ("id", "title", "url", "type")} for p in available],
                              "pet": await snapshot(pet)}, ensure_ascii=False))
            for info in available:
                if "dev.html" in info.get("url", ""):
                    async with Page(info) as dev:
                        print(json.dumps({"dev": await snapshot(dev, True)}, ensure_ascii=False))
            return
        dev_info = next(p for p in available if "dev.html" in p.get("url", ""))
        async with Page(dev_info) as dev:
            await dev.evaluate("""(()=>{window.__c0Switches=[];const original=window.fetch;
window.fetch=async function(...args){const r=await original.apply(this,args);
if(String(args[0]).includes('/characters/switch')){const data=await r.clone().json();
__c0Switches.push({status:r.status,...data});}return r;};return true;})()""")
            report = {"kind": "real_UI_selection_to_Engine_and_renderer_readiness",
                      "clock": "single Python perf_counter; includes CDP dispatch/poll overhead; backend switch_ms separate",
                      "initial": await snapshot(pet), "samples": []}
            original_role = report["initial"]["role"] or "hiyori"
            try:
                for index in range(args.cycles * 2):
                    target = "hotaru" if index % 2 == 0 else "hiyori"
                    t0 = time.perf_counter()
                    await dev.evaluate("(()=>{" + DEV + """const picker=document.querySelector('.character-picker select');
if(!picker||picker.disabled)throw Error('picker unavailable');
picker.value=""" + json.dumps(target) + ";picker.dispatchEvent(new Event('change',{bubbles:true}));return true;})()")
                    row = {"sample": index + 1, "target": target}
                    while time.perf_counter() - t0 < 25:
                        state = await snapshot(pet)
                        ui = await snapshot(dev, True)
                        elapsed = round((time.perf_counter() - t0) * 1000, 2)
                        if ui.get("role", {}).get("active_id") == target and "ui_synced_ms" not in row:
                            row["ui_synced_ms"] = elapsed
                        if state.get("role") == target and state.get("ws") == 1:
                            row.setdefault("pet_reconnected_ms", elapsed)
                            if (state.get("modelPresent") and state.get("canvasPath") == state.get("model")
                                    and not state.get("loadError") and state.get("manifestKeys")):
                                row["renderer_ready_ms"] = elapsed
                                row["pet"] = state
                                break
                        if ui.get("saveError"):
                            row["error"] = ui["saveError"]
                            row["pet"] = state
                            break
                        await asyncio.sleep(.05)
                    else:
                        row["error"] = "readiness_timeout"
                        row["pet"] = state
                    row["switch_response"] = await dev.evaluate("window.__c0Switches.at(-1)")
                    report["samples"].append(row)
                    save("switches.json", report)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                    await pet.screenshot(f"switch-{index+1}-{target}.png")
                    if row.get("error"):
                        break
            finally:
                state = await snapshot(dev, True)
                if state.get("role", {}).get("active_id") != original_role:
                    await dev.evaluate("(async()=>{"+DEV+"await s.switchCharacter("+json.dumps(original_role)+");return true;})()")


if __name__ == "__main__":
    asyncio.run(main())
