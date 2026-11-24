"""同一真实WAV在独立AudioContext回放，区分设备时钟与TTS/排队。"""
import argparse
import asyncio
import base64
import json
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]
JS = r'''(async()=>{
const c=new AudioContext();await c.resume();const bytes=Uint8Array.from(atob(__WAV_BASE64__),x=>x.charCodeAt(0));
const b=await c.decodeAudioData(bytes.buffer);const rows=[];
try{for(let index=0;index<2;index++){
 const s=c.createBufferSource();s.buffer=b;s.connect(c.destination);let ended=0;
 const t=performance.now(),ct=c.currentTime;let last=ct,at=t,maxStall=0;
 s.onended=()=>ended=performance.now()-t;s.start();
 while(!ended&&performance.now()-t<12000){const now=performance.now(),clock=c.currentTime;
  if(clock===last)maxStall=Math.max(maxStall,now-at);else{last=clock;at=now;}
  await new Promise(ok=>setTimeout(ok,25));}
 rows.push({index,duration_ms:b.duration*1000,ended_ms:ended,wall_ms:performance.now()-t,
   clock_ms:(c.currentTime-ct)*1000,max_stall_ms:maxStall,state:c.state});
 try{s.stop()}catch{}s.disconnect();
 if(index===0)await new Promise(ok=>setTimeout(ok,IDLE));
}return {scope:'independent real AudioContext replay, configured generated WAV, no LLM/TTS',rows};}
finally{await c.close();}})()'''


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wav', required=True)
    parser.add_argument('--idle-ms',type=int,default=8000)
    parser.add_argument('--output',default='2026-11-24-device-clock.json')
    args = parser.parse_args()
    raw = (ROOT/args.wav).read_bytes()
    async with httpx.AsyncClient(trust_env=False) as client:
        pages = (await client.get('http://127.0.0.1:9222/json/list')).json()
    page = next(p for p in pages if p['title']=='Yuiro' and p['type']=='page')
    async with websockets.connect(page['webSocketDebuggerUrl'],max_size=20_000_000) as ws:
        code = JS.replace('__WAV_BASE64__',json.dumps(base64.b64encode(raw).decode())).replace('IDLE',str(args.idle_ms))
        await ws.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{
            'expression':code,'awaitPromise':True,'returnByValue':True,'userGesture':True}}))
        while True:
            value = json.loads(await ws.recv())
            if value.get('id')==1:
                if value['result'].get('exceptionDetails'):
                    raise RuntimeError('device probe JS exception')
                report = value['result']['result']['value']
                (ROOT/'docs/plan'/args.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
                print(json.dumps(report))
                break


if __name__ == '__main__':
    asyncio.run(main())
