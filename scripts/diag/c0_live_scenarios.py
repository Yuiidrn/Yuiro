"""Real C0 configuration, voice and presentation scenarios through Electron.

No provider substitution. Temporary configuration edits are restored in finally.
Never print full config, credentials, user history or raw audio base64.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time

from c0_live_acceptance import DEV, OUT, PET, Page, pages, save, snapshot

FINGERPRINT = """(async()=>{""" + DEV + """
const hash=async v=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(v))))].map(x=>x.toString(16).padStart(2,'0')).join('');
const roles=['llm','tts','persona','language','memory','agent','context'];
const digests={};for(const k of roles){const value=JSON.parse(JSON.stringify(s.sections[k]??null));if(k==='tts'&&value)delete value.siliconflow_key;digests[k]=await hash(value)}
return {id:s.character.active_id,revision:s.character.revision,digests,
 shared:await hash(['server','vad','asr','systemd','capability','search','diary'].map(k=>s.sections[k])),
 llm:{provider:s.sections.llm.provider,model:s.sections.llm.model},tts:s.sections.tts.provider,
 voice:s.sections.persona.voice,model:s.sections.persona.model_path};})()"""

RECORDER = """(()=>{""" + PET + r"""
if(window.__c0Voice)return false;
const g=window.__c0Voice={active:null,events:[],case:null,sources:new Map(),buffers:new WeakMap(),fixture:null};
let next=0;
const decode=BaseAudioContext.prototype.decodeAudioData;
BaseAudioContext.prototype.decodeAudioData=function(...args){
 const origin={role:app.activeCharacter,case:g.case,at:performance.now()};
 return decode.apply(this,args).then(buffer=>{g.buffers.set(buffer,origin);return buffer});
};
const start=AudioBufferSourceNode.prototype.start,stop=AudioBufferSourceNode.prototype.stop;
AudioBufferSourceNode.prototype.start=function(...args){
 const origin=g.buffers.get(this.buffer)||{};
 const r={type:'start',id:++next,role:app.activeCharacter,origin_role:origin.role,case:origin.case,
 at:performance.now(),duration_s:this.buffer?.duration};
 const result=start.apply(this,args);g.events.push(r);g.sources.set(this,r);
 this.addEventListener('ended',()=>{g.events.push({type:'ended',id:r.id,at:performance.now(),role:app.activeCharacter});g.sources.delete(this)});
 return result;
};
AudioBufferSourceNode.prototype.stop=function(...args){
 const r=g.sources.get(this);g.events.push({type:'stop',id:r?.id,at:performance.now(),role:app.activeCharacter});
 return stop.apply(this,args);
};
const seen=new WeakSet();
g.timer=setInterval(()=>{const ws=app.socket;if(!ws||seen.has(ws))return;seen.add(ws);
ws.addEventListener('message',e=>{let m;try{m=JSON.parse(e.data)}catch{return}
 const r={type:m.type,role:app.activeCharacter,case:g.case,at:performance.now()};
 if(m.type==='chat:assistant')r.chars=String(m.text||'').length;
 if(m.type==='tts:reply_audio'){g.fixture=m.wav;r.wav_chars=String(m.wav||'').length}
 if(m.type==='avatar:intent'){r.expression=m.expression;r.motion=m.motion;r.motion_index=m.motion_index;r.source=m.source}
 if(['chat:assistant','tts:reply_audio','tts:reply_end','character:switching','avatar:intent','approval:required'].includes(m.type))g.events.push(r);
});},20);
return true;})()"""


async def wait_role(pet, dev, role):
    started = time.perf_counter()
    while time.perf_counter() - started < 15:
        p = await snapshot(pet)
        d = await snapshot(dev, True)
        if (p.get("role") == role and p.get("ws") == 1 and p.get("modelPresent")
                and p.get("canvasPath") == p.get("model") and not p.get("loadError")
                and d.get("role", {}).get("active_id") == role):
            return p
        await asyncio.sleep(.08)
    raise RuntimeError(f"role readiness timeout: {role}")


async def switch(pet, dev, role):
    await dev.evaluate("(async()=>{" + DEV + "await s.switchCharacter(" + json.dumps(role) + ");return {error:s.saveError};})()")
    return await wait_role(pet, dev, role)


async def config_checks(pet, dev):
    report = {"kind": "real_config_roundtrip_and_stale_save", "checks": []}
    await dev.evaluate("(()=>{window.__c0Original={};return true;})()")
    try:
        for role in ("hiyori", "hotaru"):
            await switch(pet, dev, role)
            await dev.evaluate("(()=>{"+DEV+"__c0Original["+json.dumps(role)+"]={llm:JSON.parse(JSON.stringify(s.sections.llm)),persona:JSON.parse(JSON.stringify(s.sections.persona))};return true;})()")
            report[role] = await dev.evaluate(FINGERPRINT)
        await switch(pet, dev, "hiyori")
        changed = await dev.evaluate("(async()=>{"+DEV+r"""
const llm={...s.sections.llm,temperature:Number(s.sections.llm.temperature)+.01};
await s.applySection('llm',llm);
const p=JSON.parse(JSON.stringify(s.sections.persona));p.display_name+=' [C0临测]';
const hit=Object.values(p.profiles||{}).find(x=>x.model===p.model_path);
if(hit)hit.performance_map={...(hit.performance_map||{}),c0_hiyori_probe:'happy'};
else p.performance_map={...p.performance_map,c0_hiyori_probe:'happy'};
await s.applySection('persona',p);return true;})()""")
        expected = await dev.evaluate(FINGERPRINT)
        await switch(pet, dev, "hotaru")
        other = await dev.evaluate(FINGERPRINT)
        response = await dev.evaluate("(async()=>{"+DEV+r"""
const secret=await window.yuiro.getEngineSecret();const r=await fetch('http://127.0.0.1:8200/api/config',{
method:'PUT',headers:{'Content-Type':'application/json','x-yuiro-secret':secret},
body:JSON.stringify({character_id:'hiyori',character_revision:0,patch:{persona:{display_name:'MUST_NOT_SAVE'}}})});return {status:r.status};})()""")
        report["checks"].append({"name": "hotaru_unchanged_after_hiyori_edits", "passed": other["digests"] == report["hotaru"]["digests"]})
        report["checks"].append({"name": "stale_hiyori_save_rejected", "passed": response["status"] == 409, **response})
        hotaru_names = await dev.evaluate("(async()=>{const r=await fetch('http://127.0.0.1:8200/api/avatar/performances');return (await r.json()).performances.map(p=>p.name)})()")
        report["checks"].append({"name": "hiyori_custom_performance_absent_in_hotaru", "passed": "c0_hiyori_probe" not in hotaru_names})
        await switch(pet, dev, "hiyori")
        restored = await dev.evaluate(FINGERPRINT)
        report["checks"].append({"name": "hiyori_saved_edits_restored_on_return", "passed": expected["digests"] == restored["digests"]})
        hiyori_names = await dev.evaluate("(async()=>{const r=await fetch('http://127.0.0.1:8200/api/avatar/performances');return (await r.json()).performances.map(p=>p.name)})()")
        report["checks"].append({"name": "hiyori_custom_performance_restored", "passed": "c0_hiyori_probe" in hiyori_names})
        report["checks"].append({"name": "shared_settings_unchanged", "passed": restored["shared"] == report["hiyori"]["shared"] == other["shared"]})
    finally:
        for role in ("hiyori", "hotaru"):
            await switch(pet, dev, role)
            await dev.evaluate("(async()=>{"+DEV+"const old=__c0Original["+json.dumps(role)+"];if(old){await s.applySection('llm',old.llm);await s.applySection('persona',old.persona)}return true;})()")
        await switch(pet, dev, "hiyori")
        final = await dev.evaluate(FINGERPRINT)
        report["checks"].append({"name": "temporary_hiyori_edits_removed", "passed": final["digests"] == report["hiyori"]["digests"]})
        save("config-roundtrip.json", report)
    print(json.dumps({"checks": report["checks"]}, ensure_ascii=False), flush=True)


async def voices(pet, dev):
    await switch(pet, dev, "hotaru")
    await switch(pet, dev, "hiyori")
    await pet.evaluate(RECORDER)
    report = {"kind": "real_configured_LLM_TTS_renderer_playback_and_switch",
              "limits": "AudioContext application playback, not physical speaker measurement or subjective approval", "samples": []}
    try:
        for index, role in enumerate(("hiyori", "hotaru", "hiyori"), 1):
            await switch(pet, dev, role)
            case = f"voice-{index}-{role}"
            print(json.dumps({"playing": role, "case": case}, ensure_ascii=False), flush=True)
            await pet.evaluate("(()=>{"+PET+"__c0Voice.case="+json.dumps(case)+r""";__c0Voice.events=[];__c0Voice.fixture=null;
app.sendText('请用中文只说：你好，我在这里。不要调用工具。');return true;})()""")
            t0 = time.perf_counter()
            row = {"case": case, "role": role, "config": await dev.evaluate(FINGERPRINT)}
            switched = False
            while time.perf_counter() - t0 < 55:
                events = await pet.evaluate("window.__c0Voice.events")
                starts = [e for e in events if e["type"] == "start"]
                if starts and index < 3 and not switched:
                    await asyncio.sleep(.5)
                    before = await pet.evaluate("performance.now()")
                    target = "hotaru" if role == "hiyori" else "hiyori"
                    await switch(pet, dev, target)
                    row["switch_trigger_pet_clock_ms"] = before
                    row["switch_target"] = target
                    switched = True
                    await asyncio.sleep(1.0)
                    break
                if starts and index == 3 and time.perf_counter() - t0 > 8:
                    await pet.evaluate("(()=>{"+PET+"app.stopPlayback();return true;})()")
                    row["diagnostic_stop"] = True
                    break
                # reply_end may arrive while decodeAudioData is still pending;
                # only the playback deadline can establish absence of a start.
                await asyncio.sleep(.1)
            else:
                row["error"] = "timeout"
            row["events"] = await pet.evaluate("window.__c0Voice.events")
            row["cross_role_starts"] = [e for e in row["events"] if e["type"] == "start" and e.get("origin_role") != e.get("role")]
            row["final"] = await snapshot(pet)
            fixture = await pet.evaluate("window.__c0Voice.fixture")
            if fixture:
                OUT.mkdir(parents=True, exist_ok=True)
                (OUT / f"{case}.wav").write_bytes(base64.b64decode(fixture))
            report["samples"].append(row)
            save("voices.json", report)
            print(json.dumps({"case": case, "starts": len([e for e in row["events"] if e["type"] == "start"]),
                              "error": row.get("error"), "cross_role_starts": len(row["cross_role_starts"])}, ensure_ascii=False), flush=True)
    finally:
        await switch(pet, dev, "hiyori")
        await pet.evaluate("(()=>{"+PET+"app.stopPlayback();return true;})()")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["config", "voices", "enable-hotaru-voice"])
    args = parser.parse_args()
    available = await pages()
    async with Page(next(p for p in available if p["title"] == "Yuiro")) as pet:
        async with Page(next(p for p in available if "dev.html" in p.get("url", ""))) as dev:
            if args.command == "config":
                await config_checks(pet, dev)
            elif args.command == "enable-hotaru-voice":
                await switch(pet, dev, "hotaru")
                print(await dev.evaluate("(async()=>{" + DEV + "await s.applySection('tts',{...s.sections.tts,reply_tts_enabled:true});return {enabled:s.sections.tts.reply_tts_enabled,voice:s.sections.tts.siliconflow_voice,error:s.saveError};})()"))
                await switch(pet, dev, "hiyori")
            else:
                await voices(pet, dev)


if __name__ == "__main__":
    asyncio.run(main())
