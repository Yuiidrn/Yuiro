import asyncio,json
from pathlib import Path
exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])
async def main():
 async def test(call,ev):
  await call('Page.enable')
  role=await ev("localStorage.getItem('yuiro-active-character')")
  hook=await call('Page.addScriptToEvaluateOnNewDocument',{'source':"window.__controlProbe=[];window.WebSocket=new Proxy(window.WebSocket,{construct(T,args){const w=Reflect.construct(T,args);if(String(args[0]).includes('/ws/control'))window.__controlProbe.push(w);return w}})"})
  try:
   await call('Page.reload');await asyncio.sleep(4)
   before=await ev("({tracked:__controlProbe.length,open:__controlProbe.at(-1)?.readyState===1,session:!!localStorage.getItem('yuiro.session_id')})")
   assert before['open'] and before['session'],before
   await ev("window.__oldControl=__controlProbe.at(-1);__oldControl.close(1000,'controlled lifecycle verification')")
   reconnected=False
   for _ in range(50):
    reconnected=await ev("__controlProbe.length>1&&__controlProbe.at(-1).readyState===1&&!!localStorage.getItem('yuiro.session_id')")
    if reconnected:break
    await asyncio.sleep(.2)
   assert reconnected,'No reconnection'
   await ev("window.__sessionBefore=localStorage.getItem('yuiro.session_id');__oldControl.onclose({code:1012});__oldControl.onerror({});__oldControl.onopen({})")
   await asyncio.sleep(.5)
   result=await ev("({reconnected:__controlProbe.at(-1).readyState===1,staleClosePreservesSession:__sessionBefore===localStorage.getItem('yuiro.session_id'),roleUnchanged:localStorage.getItem('yuiro-active-character')==="+json.dumps(role)+",presence:JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}').presence,model:JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}').model})")
   assert result['reconnected'] and result['staleClosePreservesSession'] and result['roleUnchanged'],result
   report=dict(date='2026-11-09',scope='actual built Electron control socket close and engine reconnect; manually replayed stale lifecycle callbacks; no chat or TTS',**result)
   Path('docs/plan/avatar-control-reconnect-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(report)
  finally:
   await call('Page.removeScriptToEvaluateOnNewDocument',{'identifier':hook['identifier']})
   await call('Page.reload');await asyncio.sleep(3)
 await connect(next(p for p in pages() if 'index.html' in p['url']),test)
asyncio.run(main())
