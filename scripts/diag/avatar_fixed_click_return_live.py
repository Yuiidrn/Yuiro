import asyncio,json,time
from pathlib import Path
exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])
async def main():
 dev=next(p for p in pages() if 'dev.html' in p['url']);pet=next(p for p in pages() if 'index.html' in p['url'])
 async def setup(c,e):
  original=await e("localStorage.getItem('yuiro-avatar-click-pools-v1')")
  await e('(()=>{const s=document.querySelector(".character-picker select");s.value="hiyori";s.dispatchEvent(new Event("change",{bubbles:true}))})()');await asyncio.sleep(3)
  await e('(()=>{const k="yuiro-avatar-click-pools-v1",pool=JSON.parse(localStorage.getItem(k)||"{}");pool["hiyori:/live2d/hiyori/Hiyori.model3.json"]={enabled:true,motions:["Idle#6"]};localStorage.setItem(k,JSON.stringify(pool))})()')
  return original
 original=await connect(dev,setup)
 try:
  async def click(c,e):
   await c('Page.reload');await asyncio.sleep(3);await c('Page.bringToFront')
   await e('''(()=>{const canvas=document.querySelector('canvas.live2d-canvas'),c=document.createElement('canvas');c.width=160;c.height=200;const x=c.getContext('2d');x.drawImage(canvas,0,0,160,200);const d=x.getImageData(0,0,160,200).data;let minY=200,maxY=0;for(let y=0;y<200;y++)for(let z=0;z<160;z++)if(d[(y*160+z)*4+3]>200){minY=Math.min(minY,y);maxY=Math.max(maxY,y)}const y=Math.round(minY+(maxY-minY)*.4);let px=80;for(let z=0;z<160;z++)if(d[(y*160+z)*4+3]>220){px=z+4;break}const r=canvas.getBoundingClientRect(),args={bubbles:true,button:0,clientX:r.left+px/160*r.width,clientY:r.top+y/200*r.height,screenX:100,screenY:100};canvas.dispatchEvent(new MouseEvent('mousedown',args));window.dispatchEvent(new MouseEvent('mouseup',args))})()''')
   rows=[];started=False;returned=False;t=time.perf_counter()
   for _ in range(90):
    s=await e("JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}')");rows.append(dict(ms=round((time.perf_counter()-t)*1000),**s))
    started|=s.get('motion')=='Idle' and s.get('motionIndex')==6 and s.get('until',0)>0
    if started and s.get('motion')=='Idle' and s.get('motionIndex')==0 and s.get('until')==0:returned=True;break
    await asyncio.sleep(.25)
   return dict(started=started,returnedToFixed=returned,samples=rows)
  result=await connect(pet,click)
  Path('docs/plan/avatar-fixed-click-return-live.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  print({k:v for k,v in result.items() if k!='samples'});assert result['started'] and result['returnedToFixed']
 finally:
  async def restore(c,e):
   await e(('localStorage.removeItem("yuiro-avatar-click-pools-v1")' if original is None else 'localStorage.setItem("yuiro-avatar-click-pools-v1",'+json.dumps(original)+')'))
   await e('(()=>{const s=document.querySelector(".character-picker select");s.value="hotaru";s.dispatchEvent(new Event("change",{bubbles:true}))})()')
  await connect(dev,restore)
asyncio.run(main())
