import asyncio,json,urllib.request,websockets
from pathlib import Path
async def main():
 page=json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list'))[0]
 async with websockets.connect(page['webSocketDebuggerUrl'],max_size=20000000) as ws:
  seq=0
  async def call(method,params):
   nonlocal seq;seq+=1;await ws.send(json.dumps(dict(id=seq,method=method,params=params)))
   while True:
    r=json.loads(await ws.recv())
    if r.get('id')==seq:return r['result']
  async def ev(expr):
   r=await call('Runtime.evaluate',dict(expression=expr,awaitPromise=True,returnByValue=True))
   if 'exceptionDetails' in r:raise RuntimeError(str(r['exceptionDetails'])[:300])
   return r.get('result',{}).get('value')
  await call('Page.navigate',dict(url='http://localhost:5173/'))
  await call('Page.bringToFront',{})
  await asyncio.sleep(3)
  find="const v=[...document.querySelectorAll('*')].find(e=>e.__vueParentComponent?.type.__file?.includes('Live2DCanvas')).__vueParentComponent.setupState;"
  original=await ev('(()=>{'+find+'return v.currentModelPath})()')
  rows=[]
  try:
   for name,path in [('hiyori','/live2d/hiyori/Hiyori.model3.json'),('hotaru','/live2d/Hotaru Shiomi/016_casual_spring_01/016_casual_spring_01.model3.json')]:
    r=await ev('(async()=>{'+find+'await v.switchModel('+json.dumps(path)+');await new Promise(r=>setTimeout(r,800));const m=await window.yuiro.inspectPetModel('+json.dumps(path)+');const choices=m.motions.filter(x=>x.durationMs>0&&x.durationMs<4000&&x.group!=="Extra").sort((a,b)=>a.durationMs-b.durationMs);const pick=choices[0];if(!pick)throw Error("no short motion");const events=[],mm=v.model.internalModel.motionManager,t=performance.now(),before={elapsed:v.model.elapsedTime,delta:v.model.deltaTime,ticker:v.app.ticker.started,visible:v.model.visible,renderable:v.model.renderable};const originalStart=mm.startMotion;mm.startMotion=async function(...args){const ok=await originalStart.apply(this,args);events.push({event:"resolved",ok,ms:performance.now()-t});return ok};const start=()=>events.push({event:"start",ms:performance.now()-t});const finish=()=>events.push({event:"finish",ms:performance.now()-t});mm.on("motionStart",start);mm.on("motionFinish",finish);try{v.applyAvatarIntent({expression_slot:"happy"});v.applyAvatarIntent({motion:pick.group,motion_index:pick.index,duration_ms:100,priority:3});await new Promise(r=>setTimeout(r,pick.durationMs+1800));return {loaded:!!v.model,error:v.loadError,pick,events,before,after:{elapsed:v.model.elapsedTime,delta:v.model.deltaTime,playing:mm.playing,finished:mm.isFinished(),state:JSON.stringify(mm.state)},state:{...v.avatarState},expressions:v.listExpressions()}}finally{mm.startMotion=originalStart;mm.off("motionStart",start);mm.off("motionFinish",finish)}})()')
    rows.append(dict(model=name,**r));print(json.dumps(dict(model=name,loaded=r['loaded'],error=r['error'],expressions=len(r['expressions']))),flush=True)
  finally:
   await ev('(async()=>{'+find+'await v.switchModel('+json.dumps(original)+');return true})()')
  Path('docs/plan/avatar-sdk-foreground-check.json').write_text(json.dumps(dict(scope='real foreground Electron renderer; SDK start/resolve/finish and clock diagnostics; not conversation or visual approval',results=rows,restored=original),ensure_ascii=False,indent=2),encoding='utf-8')
asyncio.run(main())
