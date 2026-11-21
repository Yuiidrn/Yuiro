import asyncio,json,urllib.request,websockets,time,argparse,math
from pathlib import Path
exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])
async def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--seconds',type=int,default=150)
 parser.add_argument('--output',default='docs/plan/avatar-current-idle-soak.json')
 parser.add_argument('--eyes',action='store_true',help='记录原生绘制边界眼睛数值与闭合转换；不等于声学/主观评分')
 options=parser.parse_args()
 if options.seconds<30:raise ValueError('Use at least 30 seconds per role')
 output=Path(options.output)
 ps=pages();pet=next(p for p in ps if 'index.html' in p['url']);dev=next(p for p in ps if 'dev.html' in p['url'])
 async def devWork(call,ev):
  original=await ev('document.querySelector(".character-picker select").value')
  rows=[]
  try:
   for role in ['hotaru','hiyori']:
    await ev(f'(()=>{{const s=document.querySelector(".character-picker select");s.value={json.dumps(role)};s.dispatchEvent(new Event("change",{{bubbles:true}}))}})()')
    await asyncio.sleep(4)
    async def sample(call,ev):
     await call('Page.bringToFront')
     state=await ev("JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}')")
     assert ('hiyori' in state.get('model','').lower())==(role=='hiyori'),state
     assert state.get('presence')=='idle',state
     assert not await ev("!!document.querySelector('.mic-btn.recording')"),'Microphone must remain off'
     if options.eyes:
      await ev("""window.__idleEyeOriginal=Live2DCubismCore.Model.prototype.update;
       window.__idleEyes={frames:0,min:Infinity,max:-Infinity,closures:0,closed:false};
       Live2DCubismCore.Model.prototype.update=function(...args){
        const result=Reflect.apply(__idleEyeOriginal,this,args),p=this.parameters,s=__idleEyes;
        const left=p.ids.indexOf('ParamEyeLOpen'),right=p.ids.indexOf('ParamEyeROpen');
        if(left>=0&&right>=0){const a=p.values[left],b=p.values[right];s.frames++;
         s.min=Math.min(s.min,a,b);s.max=Math.max(s.max,a,b);
         const closed=a<.15&&b<.15;if(closed&&!s.closed)s.closures++;s.closed=closed}
        return result} """)
     await ev('''(()=>{const s=window.__idleSample={start:performance.now(),last:performance.now(),frames:[],states:[],visible:[],pixels:[],done:false};const frame=t=>{if(s.done)return;s.frames.push(t-s.last);s.last=t;requestAnimationFrame(frame)};requestAnimationFrame(frame);s.timer=setInterval(()=>{s.states.push(JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}'));s.visible.push(document.visibilityState);const source=document.querySelector('canvas.live2d-canvas');if(source){const c=document.createElement('canvas');c.width=80;c.height=100;const x=c.getContext('2d');x.drawImage(source,0,0,80,100);const d=x.getImageData(0,0,80,100).data;let n=0,hash=0;for(let i=3;i<d.length;i+=4){if(d[i]>20)n++;hash=(hash+d[i]*(i%1009))%100000007}s.pixels.push({occupied:n,hash})}},1000);setTimeout(()=>{s.done=true;clearInterval(s.timer)},150000);return true})()'''.replace('150000',str(options.seconds*1000)))
     for i in range(math.ceil(options.seconds/30)):
      await asyncio.sleep(min(30,options.seconds-i*30))
      print(role,await ev('({seconds:Math.round((performance.now()-__idleSample.start)/1000),frames:__idleSample.frames.length,visible:document.visibilityState})'),flush=True)
     return await ev('''(()=>{const s=window.__idleSample,a=s.frames.slice(1).sort((a,b)=>a-b),stats={count:a.length,p50:a[Math.floor(a.length*.5)],p95:a[Math.floor(a.length*.95)],max:a.at(-1)};const result={seconds:(performance.now()-s.start)/1000,done:s.done,frameIntervalMs:stats,states:s.states,visibility:s.visible,pixels:s.pixels,eyes:window.__idleEyes||null};if(window.__idleEyeOriginal){Live2DCubismCore.Model.prototype.update=__idleEyeOriginal;delete window.__idleEyeOriginal;delete window.__idleEyes}s.done=true;clearInterval(s.timer);delete window.__idleSample;return result})()''')
    row=await connect(pet,sample);rows.append(dict(role=role,**row))
    output.write_text(json.dumps(dict(scope='actual built desktop renderer; official role switch; rAF not GPU time',plannedSecondsPerRole=options.seconds,results=rows,restorationPending=True),ensure_ascii=False,indent=2),encoding='utf-8')
  finally:
   await ev(f'(()=>{{const s=document.querySelector(".character-picker select");s.value={json.dumps(original)};s.dispatchEvent(new Event("change",{{bubbles:true}}))}})()');await asyncio.sleep(4)
  data=dict(scope='actual built desktop renderer; official role switch; rAF not GPU time; visual naturalness not inferred',plannedSecondsPerRole=options.seconds,results=rows,restored=original)
  output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
  print('RESTORED',original,flush=True)
 await connect(dev,devWork)
asyncio.run(main())
