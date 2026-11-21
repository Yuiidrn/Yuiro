import asyncio,json,time,urllib.request,websockets,sys
from pathlib import Path
async def main():
 p=next(p for p in json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list')) if 'index.html' in p['url']);frames=[];seq=0;underruns=[];started=time.perf_counter()
 async with websockets.connect(p['webSocketDebuggerUrl'],max_size=30000000) as ws:
  async def call(method,params={}):
   nonlocal seq;seq+=1;await ws.send(json.dumps(dict(id=seq,method=method,params=params)))
   while True:
    r=json.loads(await ws.recv())
    if r.get('method')=='Network.webSocketFrameReceived':
     try:
      d=json.loads(r['params']['response']['payloadData'])
      if d.get('type') in ['tts:reply_audio','tts:reply_end']:
       frames.append({**{k:d.get(k) for k in ['type','session_id','generation','streaming']},'streamIdPresent':bool(d.get('stream_id')),'ms':round((time.perf_counter()-started)*1000,1)})
     except (ValueError,KeyError):pass
    if r.get('method')=='Runtime.consoleAPICalled':
     for arg in r['params'].get('args',[]):
      line=arg.get('value')
      if isinstance(line,str) and line.startswith('[voice] 流式音频缓冲欠载'):
       underruns.append({'message':line,'ms':round((time.perf_counter()-started)*1000,1)})
    if r.get('id')==seq:return r['result']
  async def ev(s):
   r=await call('Runtime.evaluate',dict(expression=s,awaitPromise=True,returnByValue=True));return r.get('result',{}).get('value')
  await call('Page.enable');await call('Network.enable');await call('Runtime.enable');await call('Page.reload');await asyncio.sleep(3)
  sid=await ev("localStorage.getItem('yuiro.session_id')")
  initial=await ev("({role:localStorage.getItem('yuiro-active-character'),recording:!!document.querySelector('.mic-btn.recording')})")
  assert not initial['recording'],'Do not run while microphone is active'
  # Runtime.enable会重放旧console；建立请求前屏障并清空，不能算入本次朗读。
  await call('Runtime.discardConsoleEntries')
  frames.clear();underruns.clear()
  await ev("window.__ttsScheduleAudit={original:AudioBufferSourceNode.prototype.start,rows:[]};AudioBufferSourceNode.prototype.start=function(...args){const result=Reflect.apply(__ttsScheduleAudit.original,this,args);__ttsScheduleAudit.rows.push({when:args[0]??this.context.currentTime,clock:this.context.currentTime,duration:this.buffer?.duration??0});return result}")
  started=time.perf_counter()
  assert await ev("window.yuiro.relayChat('请只说一句简短的晚安。')")
  states=[]
  for _ in range(220):
   state=await ev("JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}').presence");states.append(state)
   if frames and frames[-1]['type']=='tts:reply_end' and 'speaking' in states and state=='idle':break
   await asyncio.sleep(.25)
  report={'scope':'real text reply with paired updated engine/renderer; no microphone or stale injection; event timing includes LLM and translation, not acoustic first sound','initial':initial,'events':[{'type':f['type'],'sessionMatches':f['session_id']==sid,'generation':f['generation'],'streaming':f['streaming'],'streamIdPresent':f['streamIdPresent'],'ms':f['ms']} for f in frames],'presence':list(dict.fromkeys(states)),'finalPresence':states[-1],'observedUnderruns':underruns}
  report['passed']=bool(frames) and all(f['session_id']==sid and isinstance(f['generation'],int) for f in frames) and 'speaking' in states
  report['audioGraphSchedule']=await ev("(()=>{const rows=__ttsScheduleAudit.rows;AudioBufferSourceNode.prototype.start=__ttsScheduleAudit.original;delete window.__ttsScheduleAudit;return rows})()")
  report['audioGraphGapsMs']=[round((b['when']-a['when']-a['duration'])*1000,2) for a,b in zip(report['audioGraphSchedule'],report['audioGraphSchedule'][1:])]
  if '--streaming' in sys.argv:
   report['passed']=report['passed'] and all(f['streaming'] is True for f in frames if f['type']=='tts:reply_audio') and states[-1]=='idle'
  target='avatar-reply-http-stream-live.json' if '--streaming' in sys.argv else 'avatar-reply-generation-live.json'
  if '--rebuffer' in sys.argv:
   target='avatar-reply-http-rebuffer-live.json'
   report['passed']=report['passed'] and all(f['streamIdPresent'] for f in frames if f['type']=='tts:reply_audio')
  Path('docs/plan',target).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(report);assert report['passed']
asyncio.run(main())
