"""真实双角色来源卡/语音验收；临时语音开关 finally 恢复。"""
import asyncio
import base64
import json
import time

from c0_live_acceptance import DEV, PET, ROOT, Page, pages
from c0_live_scenarios import RECORDER, switch

OUT = ROOT / "docs/plan/search-presentation-artifacts"


def save(report):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "live.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


async def main():
    available = await pages()
    report = {"cases": [], "switch_checks": [], "restored": {}}
    originals = {}
    async with Page(next(p for p in available if p["title"] == "Yuiro")) as pet:
        async with Page(next(p for p in available if "dev.html" in p.get("url", ""))) as dev:
            await pet.call("Page.reload")
            await asyncio.sleep(2)
            try:
                for role in ("hiyori", "hotaru"):
                    await switch(pet, dev, role)
                    originals[role] = await dev.evaluate("(()=>{" + DEV + "return s.sections.tts.reply_tts_enabled;})()")
                    await dev.evaluate("(async()=>{" + DEV + "await s.applySection('tts',{reply_tts_enabled:true});return true;})()")
                    await pet.evaluate(RECORDER)
                    for kind, text in (
                        ("sources", "请调用 web_search 搜索 DeepSeek 官方 API 文档，仅回复“已找到官方文档”加一个链接，不要任何解释。"),
                        ("answer_only", "请联网搜索，只告诉我 Python 当前最新稳定版本号，一句话回答，不要来源卡。"),
                    ):
                        case = f"{role}-{kind}"
                        print("Testing", case, flush=True)
                        await pet.evaluate("(()=>{" + PET + "__c0Voice.case=" + json.dumps(case) + ";__c0Voice.events=[];__c0Voice.fixture=null;window.__searchCase={cards:[],reply:false,end:false};const listener=e=>{let m;try{m=JSON.parse(e.data)}catch{return};if(m.type==='agent:result'&&m.kind==='source')__searchCase.cards.push(m);if(m.type==='chat:assistant')__searchCase.reply=true;if(m.type==='tts:reply_end')__searchCase.end=true;};if(window.__searchListener)app.socket.removeEventListener('message',__searchListener);window.__searchListener=listener;app.socket.addEventListener('message',listener);app.webSearchOn=true;app.sendText(" + json.dumps(text, ensure_ascii=False) + ");return true;})()")
                        started = time.perf_counter()
                        observed = None
                        while time.perf_counter() - started < 65:
                            state = await pet.evaluate("(()=>{" + PET + "return {reply:__searchCase.reply,end:__searchCase.end,starts:__c0Voice.events.filter(e=>e.type==='start').length,card:app.resultCard?JSON.parse(JSON.stringify(app.resultCard)):null};})()")
                            if state["card"] and observed is None:
                                observed = await pet.evaluate("({items:document.querySelectorAll('.rc-source').length,snippets:document.querySelectorAll('.rc-snippet').length,dates:document.querySelectorAll('.rc-date').length})")
                            if state["reply"] and state["end"] and state["starts"]:
                                break
                            await asyncio.sleep(.1)
                        evidence = await pet.evaluate("(()=>{" + PET + "return {cards:__searchCase.cards,rendered:app.resultCard?JSON.parse(JSON.stringify(app.resultCard)):null,source_items:document.querySelectorAll('.rc-source').length,snippets:document.querySelectorAll('.rc-snippet').length,dates:document.querySelectorAll('.rc-date').length,starts:__c0Voice.events.filter(e=>e.type==='start').length,reply:__searchCase.reply,end:__searchCase.end};})()")
                        evidence["case"] = case
                        evidence["expected_card"] = kind == "sources"
                        evidence["observed_before_expiry"] = observed
                        report["cases"].append(evidence)
                        fixture = await pet.evaluate("__c0Voice.fixture")
                        if fixture:
                            OUT.mkdir(parents=True, exist_ok=True)
                            (OUT / f"{case}.wav").write_bytes(base64.b64decode(fixture))
                        if kind == "sources":
                            try:
                                await pet.screenshot(f"{case}.png")
                            except RuntimeError:
                                pass
                            stale = evidence["cards"][-1] if evidence["cards"] else None
                            target = "hotaru" if role == "hiyori" else "hiyori"
                            await switch(pet, dev, target)
                            clean = await pet.evaluate("(()=>{" + PET + "return !app.resultCard;})()")
                            if stale:
                                await pet.evaluate("(()=>{" + PET + "app.socket.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(" + json.dumps(stale, ensure_ascii=False) + ")}));return true;})()")
                            rejected = await pet.evaluate("(()=>{" + PET + "return !app.resultCard;})()")
                            report["switch_checks"].append({"from": role, "to": target,
                                "real_switch_cleared": clean, "synthetic_old_identity_rejected": rejected})
                            await switch(pet, dev, role)
                        save(report)
            finally:
                for role, enabled in originals.items():
                    await switch(pet, dev, role)
                    result = await dev.evaluate("(async()=>{" + DEV + "await s.applySection('tts',{reply_tts_enabled:" + json.dumps(enabled) + "});return {enabled:s.sections.tts.reply_tts_enabled,error:s.saveError};})()")
                    report["restored"][role] = result
                await switch(pet, dev, "hiyori")
                await pet.evaluate("(()=>{" + PET + "app.stopPlayback();return true;})()")
                save(report)
    print(json.dumps({"cases": [{"case": c["case"], "cards": len(c["cards"]), "items": c["source_items"], "starts": c["starts"]} for c in report["cases"]], "switch_checks": report["switch_checks"], "restored": report["restored"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
