"""Fish C0 实机验收；安全元数据，不包含密钥或完整角色卡。"""
import argparse
import asyncio
import hashlib
import json
import sys

import c0_live_acceptance as live
import c0_live_scenarios as scenarios

ROOT = live.ROOT
OUT = ROOT / "docs/plan/C0-fish-artifacts"


def hiyori_digest():
    import tomllib
    card = tomllib.loads((ROOT / "engine/characters/hiyori.toml").read_text(encoding="utf-8"))
    card["tts"] = {k: v for k, v in card["tts"].items() if not k.startswith("fish_")}
    return hashlib.sha256(json.dumps(card, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def audit_baseline():
    """只报告导致指纹差异的字段名，不输出配置或凭证。"""
    import copy
    import tomllib
    card = tomllib.loads((ROOT / "engine/characters/hiyori.toml").read_text(encoding="utf-8"))
    card["tts"] = {k: v for k, v in card["tts"].items() if not k.startswith("fish_")}
    expected = json.loads((OUT / "hiyori-baseline.json").read_text())["sha256"]
    alternatives = [tomllib.loads(p.read_text(encoding="utf-8")) for p in
                    [ROOT / "engine/config.toml", ROOT / ".env-local/c0-live-backup-20261023/hiyori.toml"]]
    matches = []
    for key, value in card["tts"].items():
        options = [(False, None)] + [(True, a.get("tts", {}).get(key)) for a in alternatives]
        if isinstance(value, bool):
            options.append((True, not value))
        if isinstance(value, str):
            options.extend([(True, value.replace("\\", "/")), (True, value.replace("/", "\\")), (True, "")])
        for present, replacement in options:
            trial = copy.deepcopy(card)
            if present:
                trial["tts"][key] = replacement
            else:
                trial["tts"].pop(key)
            digest = hashlib.sha256(json.dumps(trial, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if digest == expected:
                matches.append({"field": key, "baseline_field_present": present,
                                "baseline_value_equals_shared": present and replacement == alternatives[0].get("tts", {}).get(key)})
    print(json.dumps({"single_field_baseline_matches": matches}, ensure_ascii=False))
    live.OUT = OUT
    live.save("baseline-audit.json", {"single_field_baseline_matches": matches})


async def main(command):
    OUT.mkdir(parents=True, exist_ok=True)
    baseline = OUT / "hiyori-baseline.json"
    if command == "audit":
        audit_baseline()
        return
    if command == "baseline":
        baseline.write_text(json.dumps({"sha256": hiyori_digest()}), encoding="utf-8")
        print("Hiyori semantic baseline saved (no config disclosed)")
        return
    before_run = hiyori_digest()
    live.OUT = scenarios.OUT = OUT
    available = await live.pages()
    async with live.Page(next(p for p in available if p["title"] == "Yuiro")) as pet:
        async with live.Page(next(p for p in available if "dev.html" in p.get("url", ""))) as dev:
            if command == "configure":
                await scenarios.switch(pet, dev, "hotaru")
                result = await dev.evaluate("(async()=>{" + live.DEV + """
await s.applySection('tts',{...s.sections.tts,provider:'fish',
fish_reference_id:'ad0099b0c27a470eb2a11e9a37b14e4c',fish_model:'s2.1-pro',
fish_latency:'balanced',fish_speed:1,reply_tts_enabled:true,segment_streaming:true});
const {api}=await import('/src/dev/api.ts?c0='+Date.now());const key=await api.getFishKey();
return {error:s.saveError,provider:s.sections.tts.provider,reference_id:s.sections.tts.fish_reference_id,key_status:key};})()""")
                live.save("configuration.json", result)
                print(json.dumps(result, ensure_ascii=False))
                await scenarios.switch(pet, dev, "hiyori")
            elif command == "voices":
                await scenarios.voices(pet, dev)
            elif command == "cancel":
                await scenarios.switch(pet, dev, "hotaru")
                await pet.evaluate(scenarios.RECORDER)
                await pet.evaluate("(()=>{" + live.PET + "__c0Voice.events=[];__c0Voice.case='cancel-pending-fish';app.sendText('请只说：这是切换取消验证，请不要调用工具。');return true;})()")
                for _ in range(400):
                    events = await pet.evaluate("__c0Voice.events")
                    if any(e["type"] == "chat:assistant" for e in events):
                        break
                    await asyncio.sleep(.05)
                else:
                    raise RuntimeError("LLM response timeout before cancellation check")
                await asyncio.sleep(.15)
                before = await pet.evaluate("__c0Voice.events")
                await scenarios.switch(pet, dev, "hiyori")
                await asyncio.sleep(3)
                after = await pet.evaluate("__c0Voice.events")
                logs = (ROOT / ".env-local/c0-fish-final.out.log").read_text(encoding="utf-8", errors="replace")
                result = {"audio_started_before_switch": any(e["type"] == "start" for e in before),
                          "events": after, "fish_cancellation_logged": "Fish HTTP 已取消" in logs,
                          "late_audio_starts": [e for e in after if e["type"] == "start"]}
                live.save("cancel-pending.json", result)
                print(json.dumps(result, ensure_ascii=False))
            elif command == "config":
                await scenarios.config_checks(pet, dev)
            elif command == "restore-hiyori":
                await scenarios.switch(pet, dev, "hiyori")
                await dev.evaluate("(async()=>{" + live.DEV + "await s.applySection('tts',{reply_tts_enabled:false});return {error:s.saveError};})()")
                if hiyori_digest() != json.loads(baseline.read_text())["sha256"]:
                    raise RuntimeError("Original Hiyori baseline was not restored")
                before_run = hiyori_digest()
            elif command == "selftest":
                await scenarios.switch(pet, dev, "hotaru")
                try:
                    result = await dev.evaluate("(async()=>{const {api}=await import('/src/dev/api.ts?c0='+Date.now());const r=await api.testProvider('tts',{lang:'ja'});delete r.audio_base64;return r;})()")
                    live.save("debug-selftest.json", result)
                    print(json.dumps(result, ensure_ascii=False))
                    await dev.screenshot("hotaru-debug.png")
                finally:
                    await scenarios.switch(pet, dev, "hiyori")
            elif command == "ui":
                await dev.call("Page.reload")
                await asyncio.sleep(2)
                await scenarios.switch(pet, dev, "hotaru")
                try:
                    await dev.evaluate("(()=>{" + live.DEV + "d.active='speech';return true;})()")
                    await asyncio.sleep(1)
                    result = await dev.evaluate("""(async()=>{
const el=[...document.querySelectorAll('.self-test')].find(e=>e.textContent.includes('当前角色语音试听'));
if(!el)throw Error('speech test card missing');
const c=el.__vueParentComponent.setupState;c.lang='ja';await c.run();
await new Promise(resolve=>setTimeout(resolve,100));
const r={...c.result};delete r.audio_base64;
window.__fishUi={events:[]};
const audio=el.querySelector('audio');
if(audio){audio.addEventListener('pause',()=>__fishUi.events.push('pause'));await audio.play();
__fishUi.audio=audio;r.playing=!audio.paused;r.duration=audio.duration;}
return r;})()""")
                    await asyncio.sleep(.3)
                    try:
                        await dev.screenshot("hotaru-speech-settings.png")
                        result["screenshot_captured"] = True
                    except RuntimeError:
                        result["screenshot_captured"] = False
                    await scenarios.switch(pet, dev, "hiyori")
                    result["after_switch"] = await dev.evaluate("({paused:window.__fishUi.audio?.paused,events:window.__fishUi.events,old_audio_removed:!document.contains(window.__fishUi.audio)})")
                    live.save("ui-audition.json", result)
                    print(json.dumps(result, ensure_ascii=False))
                finally:
                    await scenarios.switch(pet, dev, "hiyori")
    match = hiyori_digest() == before_run
    pre_topup_match = hiyori_digest() == json.loads(baseline.read_text())["sha256"]
    live.save(f"hiyori-preserved-{command}.json", {"unchanged_during_this_run": match,
              "matches_pre_topup_baseline": pre_topup_match})
    print("Hiyori unchanged during this run:", match, "matches pre-topup baseline:", pre_topup_match)
    if not match:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["baseline", "configure", "voices", "config", "selftest", "ui", "cancel", "audit", "restore-hiyori"])
    asyncio.run(main(parser.parse_args().command))
