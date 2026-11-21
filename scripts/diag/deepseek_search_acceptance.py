"""DeepSeek Search 实机联调；不导出密钥/配置全文或用户历史。"""
import asyncio
import json

from c0_live_acceptance import DEV, PET, ROOT, Page, pages


async def main():
    available = await pages()
    async with Page(next(p for p in available if "dev.html" in p.get("url", ""))) as dev:
        await dev.call("Page.reload")
        await asyncio.sleep(2)
        result = await dev.evaluate("(async()=>{" + DEV + """
const {api}=await import('/src/dev/api.ts?search='+Date.now());
const originalEnabled=s.sections.search.enabled;
try {
await s.applySection('search',{provider:'deepseek',enabled:true,refine_results:false});
d.active='search';await new Promise(r=>setTimeout(r,300));
const el=document.querySelector('.ss-card');const c=el.__vueParentComponent.setupState;
await c.refresh();c.query='DeepSeek API 官方文档';await c.test();
return {status:await api.getSearchStatus(),search:JSON.parse(JSON.stringify(c.result)),error:c.error,
provider_options:JSON.parse(JSON.stringify(s.schema.search.provider.options)),
old_endpoint_editable:!!s.schema.search.endpoint};
} finally {if(!originalEnabled)await s.applySection('search',{enabled:false});}
})()""")
        out = ROOT / "docs/plan/deepseek-search-artifacts"
        out.mkdir(parents=True, exist_ok=True)
        (out / "live-search.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    async with Page(next(p for p in available if p["title"] == "Yuiro")) as pet:
        await pet.evaluate("(()=>{" + PET + """
window.__dsSearchReply=null;
app.socket.addEventListener('message',function listener(event){
let m;try{m=JSON.parse(event.data)}catch{return}
if(m.type==='chat:assistant'){window.__dsSearchReply={chars:String(m.text||'').length,has_source_url:/https?:\\/\\//.test(String(m.text||''))};this.removeEventListener('message',listener);}
});
app.socket.send(JSON.stringify({type:'chat:user',text:'请调用 web_search 搜索 DeepSeek 官方 API 文档，回复一个官网来源链接即可。',web_search:true}));return true;})()""")
        for _ in range(250):
            reply = await pet.evaluate("window.__dsSearchReply")
            if reply:
                break
            await asyncio.sleep(.2)
        else:
            reply = {"error": "reply timeout"}
        logs = (ROOT / ".env-local/deepseek-search.out.log").read_text(encoding="utf-8", errors="replace")
        receipt = {"reply": reply, "web_search_called": "收到 tool_call chunk: web_search" in logs,
                   "deepseek_result_logged": "DeepSeek 完成 count=" in logs}
        (out / "agent-search.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
