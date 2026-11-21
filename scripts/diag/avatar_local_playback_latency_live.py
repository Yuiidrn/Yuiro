import asyncio,json,base64,io,wave,math,argparse
from pathlib import Path
exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])
async def main():
 parser=argparse.ArgumentParser();parser.add_argument("--output",default="docs/plan/avatar-local-playback-latency.json");options=parser.parse_args()
 buffer=io.BytesIO()
 with wave.open(buffer,'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(bytes(14400))
 wav=base64.b64encode(buffer.getvalue()).decode()
 async def test(call,ev):
  assert not await ev("!!document.querySelector('.mic-btn.recording,.bm-icon.recording')"),'Input active'
  await call('Page.enable')
  hook=await call('Page.addScriptToEvaluateOnNewDocument',{'source':"window.__localAudio={clocks:[],contexts:[]};window.AudioContext=new Proxy(window.AudioContext,{construct(T,args){const c=Reflect.construct(T,args);__localAudio.contexts.push(c);const create=c.createBufferSource.bind(c);c.createBufferSource=()=>{const src=create(),start=src.start.bind(src),clock=()=>({wallMs:performance.now(),contextTime:c.currentTime,baseLatency:c.baseLatency,outputLatency:c.outputLatency,outputTimestamp:c.getOutputTimestamp?.()});src.start=(...args)=>{__localAudio.clocks.push({phase:'start',...clock()});return start(...args)};src.addEventListener('ended',()=>__localAudio.clocks.push({phase:'ended',...clock()}));return src};return c}});window.WebSocket=new Proxy(window.WebSocket,{construct(T,args){const w=Reflect.construct(T,args);if(String(args[0]).includes('/ws/control')){__localAudio.ws=w;w.addEventListener('message',e=>{try{const d=JSON.parse(e.data);if(d.type==='session:ready'){__localAudio.sid=d.session_id;__localAudio.generation=d.generation}}catch{}})}return w}})"})
  try:
   await call('Page.reload');await asyncio.sleep(3);await call('Page.bringToFront')
   assert await ev('!!__localAudio.sid'),'Session not ready'
   await ev("(()=>{const seen=new Set();function find(v){if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);if(v.component?.type.__name==='Live2DCanvas')return v.component;return find(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(find).find(Boolean):null)}__localAudio.avatar=find(document.querySelector('#app')._vnode)})()")
   await ev("(()=>{const original=Storage.prototype.setItem;__localAudio.original=original;Storage.prototype.setItem=function(key,value){original.call(this,key,value);if(key==='yuiro-avatar-status'&&__localAudio.active){const d=JSON.parse(value),a=__localAudio.active;if(d.presence==='speaking'&&a.started===null)a.started=performance.now();if(d.presence==='idle'&&a.started!==null&&a.ended===null)a.ended=performance.now()}}})()")
   samples=[]
   for i in range(20):
    result=await ev("(async()=>{const p=__localAudio;const a=p.active={t0:performance.now(),started:null,ended:null,mouths:[]};const mouthTimer=setInterval(()=>{const c=p.contexts.at(-1);a.mouths.push({ms:performance.now()-a.t0,contextTime:c?.currentTime??null,mouth:p.avatar?.props.mouthOpen})},10);const emit=d=>p.ws.onmessage({data:JSON.stringify(d)});emit({type:'chat:assistant',text:'本地无声播放验收'});emit({type:'tts:reply_audio',session_id:p.sid,generation:p.generation,wav:"+json.dumps(wav)+",sample_rate:24000,slice_ms:20,volumes:Array(15).fill(.2)});emit({type:'tts:reply_end',session_id:p.sid,generation:p.generation});await new Promise(resolve=>{const start=performance.now();const timer=setInterval(()=>{if(a.ended!==null||performance.now()-start>3000){clearInterval(timer);resolve()}},5)});clearInterval(mouthTimer);p.active=null;return {mouths:a.mouths,startMs:a.started===null?null:a.started-a.t0,endMs:a.ended===null?null:a.ended-a.t0}})()")
    samples.append(result)
    assert result['startMs'] is not None and result['endMs'] is not None,result
    await asyncio.sleep(.05)
   def stats(key):
    values=sorted(r[key] for r in samples);return {'n':len(values),'p50':values[math.ceil(len(values)*.5)-1],'p95':values[math.ceil(len(values)*.95)-1],'max':max(values)}
   report={'scope':'actual built renderer handler injection with 300ms silent WAV; synthetic nonzero volume envelope with silent WAV; frame to avatar status/props, not acoustic lipsync or end-to-end/visual latency','samples':samples,'frameToSpeakingMs':stats('startMs'),'frameToIdleMs':stats('endMs'),'percentileMethod':'nearest rank; all 20 samples including first','role':await ev("localStorage.getItem('yuiro-active-character')"),'audioClocks':await ev('__localAudio.clocks')}
   Path(options.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print({k:v for k,v in report.items() if k not in ['samples','audioClocks']})
  finally:
   await ev('if(window.__localAudio?.original)Storage.prototype.setItem=__localAudio.original')
   await call('Page.removeScriptToEvaluateOnNewDocument',{'identifier':hook['identifier']});await call('Page.reload');await asyncio.sleep(2)
 await connect(next(p for p in pages() if 'index.html' in p['url']),test)
asyncio.run(main())
