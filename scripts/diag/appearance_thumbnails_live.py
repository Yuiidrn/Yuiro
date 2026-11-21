import asyncio,json,urllib.request,websockets,base64,time
from pathlib import Path
OUT=Path('docs/plan/appearance-studio-artifacts')
def pages():return json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list'))
async def connect(page,work):
 async with websockets.connect(page['webSocketDebuggerUrl'],max_size=30000000) as ws:
  seq=0
  async def call(method,params={}):
   nonlocal seq
   seq+=1;await ws.send(json.dumps(dict(id=seq,method=method,params=params)))
   while True:
    r=json.loads(await ws.recv())
    if r.get('id')==seq:
     if 'error' in r:raise RuntimeError(r['error'])
     return r['result']
  async def ev(s):
   r=await call('Runtime.evaluate',dict(expression=s,returnByValue=True,awaitPromise=True))
   if 'exceptionDetails' in r:raise RuntimeError(str(r['exceptionDetails'])[:350])
   return r.get('result',{}).get('value')
  return await work(call,ev)
async def main():
 await connect(next(p for p in pages() if 'index.html' in p['url']),lambda c,e:e("window.yuiro.openDev('settings')"))
 await asyncio.sleep(2)
 async def check(call,ev):
  await call('Page.bringToFront')
  await ev('[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="外观").click()')
  await asyncio.sleep(1)
  snapshot="(async()=>{const r=await fetch('http://127.0.0.1:8200/api/config',{headers:{'x-yuiro-secret':await window.yuiro.getEngineSecret(),'x-yuiro-character':localStorage.getItem('yuiro-active-character')||'hotaru'}});return JSON.stringify(await r.json())})()"
  before=await ev(snapshot)
  async def waitReady():
   for _ in range(120):
    state=await ev('({loading:!!document.querySelector(".stage-loading"),cards:document.querySelectorAll(".resource-tile").length,images:[...document.querySelectorAll(".resource-tile img")].filter(x=>x.complete&&x.naturalWidth).length,error:document.querySelector(".studio-error")?.textContent||""})')
    if not state['loading'] and state['cards']>0 and state['images']==state['cards']:return state
    await asyncio.sleep(.25)
   raise RuntimeError('Thumbnail timeout: '+str(state))
  results=[]
  for mi,name in enumerate(['hiyori','hotaru']):
   start=time.perf_counter()
   await ev(f'document.querySelectorAll(".model-tile")[{mi}].click()')
   pageIndex=0
   while True:
    await ev('document.querySelector(".resource-pages").scrollIntoView({block:"end"})')
    state=await waitReady()
    bounds=await ev('''[...document.querySelectorAll('.resource-tile img')].map(img=>{const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;const ctx=c.getContext('2d');ctx.drawImage(img,0,0);const d=ctx.getImageData(0,0,c.width,c.height).data;let top=c.height,bottom=0,n=0;for(let y=0;y<c.height;y++)for(let x=0;x<c.width;x++)if(d[(y*c.width+x)*4+3]>20){top=Math.min(top,y);bottom=Math.max(bottom,y);n++}return {top,bottom,pixels:n}})''')
    assert all(b['top']<60 and b['bottom']>170 for b in bounds),bounds
    results.append(dict(model=name,page=pageIndex+1,cards=state['cards'],bounds=bounds))
    if pageIndex==0:
     data=await ev('''(()=>{const images=[...document.querySelectorAll('.resource-tile img')],c=document.createElement('canvas');c.width=720;c.height=Math.ceil(images.length/4)*260;const x=c.getContext('2d');x.fillStyle='#edf1ee';x.fillRect(0,0,c.width,c.height);images.forEach((img,i)=>{x.drawImage(img,(i%4)*180,Math.floor(i/4)*260);x.fillStyle='#30443b';x.font='12px sans-serif';x.fillText(String(i+1),(i%4)*180+8,Math.floor(i/4)*260+254)});return c.toDataURL('image/png')})()''')
     (OUT/f'{name}-thumbs-fixed.png').write_bytes(base64.b64decode(data.split(',')[1]))
    more=await ev('!document.querySelector(".resource-pages button:last-child").disabled')
    if not more:break
    await ev('document.querySelector(".resource-pages button:last-child").click()');pageIndex+=1
   print(name,'pages',pageIndex+1,'seconds',round(time.perf_counter()-start,2),flush=True)
  assert before==await ev(snapshot),'Preview changed active configuration'
  await ev('document.querySelectorAll(".model-tile")[1].click()')
  await call('Page.reload');await asyncio.sleep(2)
  await ev('[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="外观").click()')
  start=time.perf_counter();await waitReady();warm=round((time.perf_counter()-start)*1000,1)
  await ev('document.querySelector(".preview-pane").scrollIntoView({block:"start"})')
  shot=await call('Page.captureScreenshot',{'format':'png'});(OUT/'studio-fixed.png').write_bytes(base64.b64decode(shot['data']))
  report=dict(date='2026-11-09',surface='actual built Electron dev.html',pages=results,configurationUnchanged=True,warmReadyObservationMs=warm,limitations=['Warm observation begins after fixed 2s reload delay; not total reload latency','Bounds prove complete figure capture, not animation naturalness'])
  (OUT/'thumbnail-live-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
  print('PASS',len(results),'pages; configuration unchanged; warm observation',warm,flush=True)
 await connect(next(p for p in pages() if 'dev.html' in p['url']),check)
if __name__ == '__main__':
 asyncio.run(main())
