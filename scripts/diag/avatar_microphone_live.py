import asyncio,json,time,urllib.request,websockets,base64,array,math,os
from pathlib import Path
async def main():
 user_start=os.environ.get("YUIRO_MIC_USER_START")=="1"
 p=next(p for p in json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list')) if 'index.html' in p['url'])
 out=Path('docs/plan/avatar-microphone-live.json');events=[];seq=0;t=time.perf_counter();flags={'ready':False};pcm={'frames':0,'bytes':0,'maxRms':0.0};startedAt=time.time()*1000
 async with websockets.connect(p['webSocketDebuggerUrl'],max_size=30000000) as ws:
  def capture(r):
   if r.get('method')=='Runtime.consoleAPICalled':
    text=' '.join(str(a.get('value','')) for a in r['params'].get('args',[]))
    if '已打断，停止播放' in text and r['params'].get('timestamp',0)>=startedAt:events.append({'type':'local:interrupt_logged','epochMs':r['params'].get('timestamp')})
    if '麦克风已开启' in text and r['params'].get('timestamp',0)>=startedAt:flags['ready']=True
   if r.get('method') not in ['Network.webSocketFrameReceived','Network.webSocketFrameSent']:return
   if r['method']=='Network.webSocketFrameSent' and r['params']['response'].get('opcode')==2:
    raw=base64.b64decode(r['params']['response']['payloadData']);pcm['frames']+=1;pcm['bytes']+=len(raw)
    if len(raw)%2==0 and raw:
     samples=array.array('h',raw);pcm['maxRms']=max(pcm['maxRms'],math.sqrt(sum(v*v for v in samples)/len(samples))/32768)
    return
   try:
    data=json.loads(r['params']['response']['payloadData']);kind=data.get('type','')
    if kind and kind not in ['audio:chunk']:
     entry=dict(ms=round((time.perf_counter()-t)*1000),cdpMonotonicSeconds=r['params'].get('timestamp'),direction=r['method'].split('.')[-1],type=kind)
     if kind in ['pipeline:state','vad:state']:entry['state']=data.get('state')
     if kind.endswith('error'):entry['message']=str(data.get('message',''))[:180]
     if kind=='asr:text':entry['text']=data.get('text')
     events.append(entry)
   except (ValueError,TypeError,KeyError):pass
  async def call(method,params={}):
   nonlocal seq;seq+=1;await ws.send(json.dumps(dict(id=seq,method=method,params=params)))
   while True:
    r=json.loads(await ws.recv());capture(r)
    if r.get('id')==seq:return r.get('result',{})
  async def ev(s):
   r=await call('Runtime.evaluate',dict(expression=s,awaitPromise=True,returnByValue=True,userGesture=True))
   if 'exceptionDetails' in r:raise RuntimeError(str(r['exceptionDetails'])[:300])
   return r.get('result',{}).get('value')
  await call('Network.enable');await call('Runtime.enable');await call('Page.bringToFront')
  await ev("(()=>{const r=document.querySelector('canvas.live2d-canvas').getBoundingClientRect();window.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,clientX:r.left+r.width/2,clientY:r.top+r.height*.4}))})()")
  await asyncio.sleep(.2)
  await ev("if(!document.querySelector('.mic-btn'))document.querySelector('[title=聊天]')?.click()");await asyncio.sleep(.4)
  initial=await ev("({role:localStorage.getItem('yuiro-active-character'),recording:!!document.querySelector('.mic-btn.recording')})")
  assert not initial['recording'],'Microphone already active; preserving user state'
  await ev("window.__findMicAvatar=()=>{const seen=new Set();function find(v){if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);if(v.component?.type.__name==='Live2DCanvas')return v.component;return find(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(find).find(Boolean):null)}return find(document.querySelector('#app')._vnode)};window.__micAudit={go:false,states:[],timer:setInterval(()=>{const s=JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}');__micAudit.states.push({ms:performance.now(),epochMs:Date.now(),...s,mouth:__findMicAvatar()?.props.mouthOpen})},50)}")
  ready=False
  try:
   if user_start:print('WAITING_USER_MIC',flush=True)
   else:await ev("document.querySelector('.mic-btn').click()")
   for _ in range(1200 if user_start else 160):
    await ev('0');ready=flags['ready']
    if ready:break
    await asyncio.sleep(.5)
   print('MIC_READY' if ready else 'MIC_NOT_READY',flush=True)
   if not ready:raise RuntimeError('Microphone not ready')
   if os.environ.get('YUIRO_MIC_WAIT_GO')=='1':
    for _ in range(240):
     if await ev('__micAudit.go===true'):break
     await asyncio.sleep(.5)
    else:raise RuntimeError('Start signal timed out; recording will close')
    events.clear();pcm.update(frames=0,bytes=0,maxRms=0.0);await ev('__micAudit.states=[]');t=time.perf_counter()
    print('TEST_WINDOW_STARTED',flush=True)
   # 留给用户正常说话、回复与打断的实录窗口。
   for _ in range(1200 if user_start else 160):
    await asyncio.sleep(.5)
    recording=await ev("!!document.querySelector('.mic-btn.recording')")
    if user_start and not recording:break
   states=await ev('__micAudit.states')
   print('EVENTS',[e['type'] for e in events if e['type'] not in ['vad:state','tts:audio']],flush=True)
  finally:
   if 'states' not in locals():states=await ev('__micAudit.states')
   await ev("clearInterval(__micAudit.timer);delete window.__findMicAvatar;delete window.__micAudit;if(document.querySelector('.mic-btn.recording'))document.querySelector('.mic-btn').click()")
   await asyncio.sleep(.5)
   final=await ev("({recording:!!document.querySelector('.mic-btn.recording'),state:JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}')})")
   out.write_text(json.dumps(dict(scope='actual renderer microphone and engine WS events; audio bytes not persisted; user consented live phrase',initial=initial,userControlledInput=user_start,ready=ready,pcm=pcm,events=events,states=locals().get('states',[]),final=final),ensure_ascii=False,indent=2),encoding='utf-8')
asyncio.run(main())
