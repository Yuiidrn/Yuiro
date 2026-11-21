"""Real configured Engine+renderer sampling via local CDP; G0 only.

Hooks record real WebSocket/audio operations in the running renderer. No fake
providers, microphone emulation, approval acceptance or production source edits.
"""
import asyncio
import base64
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/plan/G0-live-artifacts"

INSTALL = r"""(() => {
const el=[...document.querySelectorAll('*')].find(e=>e.__vueParentComponent?.setupState.sendText);
const app=el.__vueParentComponent.setupState;
window.__g0={app,rows:[],active:null,fixture:null};
const oldDecode=BaseAudioContext.prototype.decodeAudioData;
BaseAudioContext.prototype.decodeAudioData=function(...args){
 const r=__g0.active; if(r) r.decode_start_ms ??= performance.now()-r.t0;
 const p=oldDecode.apply(this,args);
 return p.then(b=>{if(r)r.decode_end_ms ??=performance.now()-r.t0;return b;},e=>{
 if(r){r.decode_error=String(e);r.decode_finished=true;}throw e;});
};
const oldStart=AudioBufferSourceNode.prototype.start;
AudioBufferSourceNode.prototype.start=function(...args){
 const r=__g0.active;
 const answer=oldStart.apply(this,args);
 if(r){r.first_start_ms ??=performance.now()-r.t0;r.starts++;r.pending++;
 this.addEventListener('ended',()=>{r.pending--;r.ended++;r.last_ended_ms=performance.now()-r.t0;});}
 return answer;
};
const attach=()=>app.socket.addEventListener('message',ev=>{
 let m;try{m=JSON.parse(ev.data)}catch{return}
 const r=__g0.active;if(!r)return;
 r.events.push({type:m.type,ms:performance.now()-r.t0});
 if(m.type==='chat:assistant'){r.reply_ms=performance.now()-r.t0;r.reply_chars=String(m.text||'').length;}
 if(m.type==='tts:reply_audio'){r.received_segments++;r.first_receive_ms ??=performance.now()-r.t0;
 if(!__g0.fixture)__g0.fixture=m.wav;}
 if(m.type==='tts:reply_end')r.sent_all=true;
 if(m.type==='approval:required')r.error='unexpected_approval_not_accepted';
});
attach();return {model:app.modelPath,ready:app.modelReady,session:app.sessionId};
})()"""

SAMPLE = r"""(async()=>{
const g=window.__g0;
const r={sample:SAMPLE_INDEX,t0:performance.now(),starts:0,ended:0,received_segments:0,pending:0,events:[],sent_all:false};
g.active=r;g.app.sendText('请只回复“你好呀。”，不要调用工具。');
while(performance.now()-r.t0<75000){
 if(r.error || (r.sent_all && ((r.received_segments>0 && r.ended>=r.received_segments) || r.decode_finished)))break;
 if(r.sent_all && r.received_segments===1 && r.starts===1 && r.pending===1 && performance.now()-r.t0-r.first_start_ms>1200){
  r.diagnostic_stopped_after_first_audio=true;g.app.stopPlayback();
 }
 await new Promise(ok=>setTimeout(ok,50));
}
if(!r.sent_all&&!r.error)r.error='timeout';
if(!r.first_start_ms&&!r.error)r.error='no_audio_started';
r.total_ms=performance.now()-r.t0;delete r.t0;g.rows.push(r);g.active=null;return r;
})()"""


def stats(rows, key):
    values = sorted(r[key] for r in rows if not r.get("error") and key in r)
    return {"n": len(values), **({
        "p50_ms": values[math.ceil(len(values)*.5)-1],
        "p95_ms": values[math.ceil(len(values)*.95)-1], "max_ms": max(values),
    } if values else {})}


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        pages = (await client.get("http://127.0.0.1:9222/json/list")).json()
    page = next(p for p in pages if p["title"] == "Yuiro" and p["type"] == "page")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=20_000_000) as ws:
        seq = 0

        async def call(method, params):
            nonlocal seq
            seq += 1
            await ws.send(json.dumps({"id": seq, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == seq:
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    return msg["result"]

        async def evaluate(code):
            result = await call("Runtime.evaluate", {"expression": code,
                "awaitPromise": True, "returnByValue": True, "userGesture": True})
            if result.get("exceptionDetails"):
                raise RuntimeError(result["exceptionDetails"])
            return result.get("result", {}).get("value")

        state = await evaluate(INSTALL)
        report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
                  "kind": "real_text_control_to_actual_renderer_AudioContext_start",
                  "input": "请只回复“你好呀。”，不要调用工具。", "state": state,
                  "limits": "Real configured memory/LLM/TTS/WS/decode/player; excludes VAD/ASR and physical speaker delay. Current configured user data retained. Single-segment output may be explicitly stopped 1.2s after first start once Engine sent all; not full playback-duration acceptance.",
                  "samples": [], "warmup": None}
        for index in range(31):
            row = await evaluate(SAMPLE.replace("SAMPLE_INDEX", str(index)))
            if index == 0:
                report["warmup"] = row
            else:
                report["samples"].append(row)
            report["first_start"] = stats(report["samples"], "first_start_ms")
            report["first_receive_all_attempts"] = stats(
                [{**r, "error": None} for r in report["samples"]], "first_receive_ms")
            report["failures"] = sum(bool(r.get("error")) for r in report["samples"])
            (OUT / "real-text-latency.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"sample": index, "first_start_ms": row.get("first_start_ms"),
                              "error": row.get("error")}), flush=True)
        fixture = await evaluate("window.__g0.fixture")
        if fixture:
            (OUT / "generated-input-fixture.wav").write_bytes(base64.b64decode(fixture))
        screenshot = await call("Page.captureScreenshot", {"format": "png"})
        (OUT / "hiyori-renderer.png").write_bytes(base64.b64decode(screenshot["data"]))
        print(json.dumps({"summary": report["first_start"], "failures": report["failures"]}))


if __name__ == "__main__":
    asyncio.run(main())
