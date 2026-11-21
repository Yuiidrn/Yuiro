import asyncio,json
from pathlib import Path
exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])
async def main():
 pet=next(p for p in pages() if 'index.html' in p['url']);dev=next(p for p in pages() if 'dev.html' in p['url'])
 async def reload(c,e):await c('Page.reload');await asyncio.sleep(3)
 await connect(pet,reload);await connect(dev,reload)
 async def edit(c,e):
  await e('[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="外观").click()');await asyncio.sleep(.7)
  await e('[...document.querySelectorAll(".studio-tabs button")].find(x=>x.textContent.trim()==="互动节奏").click()');await asyncio.sleep(.7)
  value=await e('document.querySelector("[aria-label=待机动作选择]").value')
  assert value in ['Idle#0','Idle#1'],value
  await e('(()=>{const s=document.querySelector("[aria-label=待机动作选择]");s.value="Idle#1";s.dispatchEvent(new Event("change",{bubbles:true}))})()')
 await connect(dev,edit)
 async def sample(c,e):
  await c('Page.bringToFront');await asyncio.sleep(1)
  rows=[]
  for _ in range(12):
   rows.append(await e("JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}')"));await asyncio.sleep(1)
  return rows
 rows=await connect(pet,sample)
 assert any(r['motion']=='Idle' and r['motionIndex']==1 for r in rows),rows
 assert all(not r['motion'] or r['motion']=='Idle' and r['motionIndex']==1 for r in rows),rows
 async def restore(c,e):
  await e('(()=>{const s=document.querySelector("[aria-label=待机动作选择]");s.value="Idle#0";s.dispatchEvent(new Event("change",{bubbles:true}))})()');await asyncio.sleep(.7)
 await connect(dev,restore)
 async def read(c,e):return await e("({fixed:localStorage.getItem('yuiro-avatar-idle-fixed-motion'),hotaru:localStorage.getItem('yuiro-avatar-idle-fixed-motion:hotaru'),state:JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}')})")
 hiyori=await connect(pet,read);assert hiyori['state']['motionIndex']==0,hiyori
 async def switch(c,e):await e('(()=>{const s=document.querySelector(".character-picker select");s.value="hotaru";s.dispatchEvent(new Event("change",{bubbles:true}))})()')
 await connect(dev,switch);await asyncio.sleep(4)
 hotaru=await connect(pet,read);assert hotaru['hotaru']=='',hotaru
 Path('docs/plan/avatar-fixed-idle-live.json').write_text(json.dumps(dict(scope='actual built desktop and debug UI, role-aware local settings; 12s selected-motion observation',hiyoriSamples=rows,hiyoriRestored=hiyori,hotaruRestored=hotaru),ensure_ascii=False,indent=2),encoding='utf-8')
 print('PASS: Idle#1 remained selected across 12 samples; restored Hiyori Idle#0 and active Hotaru; Hotaru random setting unchanged.')
asyncio.run(main())
