import asyncio,json,base64,time
from pathlib import Path
import soundfile as sf,numpy as np
from scipy.signal import resample_poly
exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])
async def main():
 path=Path('assets/voices/Model/Neuro/参考音频.wav');audio,rate=sf.read(path,dtype='float32');audio=audio.mean(axis=1) if audio.ndim>1 else audio
 import math
 g=math.gcd(rate,16000);audio=resample_poly(audio,16000//g,rate//g);pcm=(np.clip(audio,-1,1)*32767).astype('<i2').tobytes();encoded=base64.b64encode(pcm).decode()
 async def test(c,e):
  start=time.perf_counter()
  result=await e("(async()=>{const raw=Uint8Array.from(atob("+json.dumps(encoded)+"),x=>x.charCodeAt(0));const r=await fetch('http://127.0.0.1:8200/api/diary/transcribe',{method:'POST',headers:{'Content-Type':'application/octet-stream','x-yuiro-secret':await window.yuiro.getEngineSecret(),'x-yuiro-character':localStorage.getItem('yuiro-active-character')||'hotaru'},body:raw});const d=await r.json();return {status:r.status,ok:d.ok,textLength:String(d.text||'').length,durationMs:d.duration_ms,note:d.note||''}})()")
  result.update(scope='existing 6.42s reference audio through running ASR-only endpoint; not microphone/VAD/LLM/Avatar',fixture=str(path),wallMs=round((time.perf_counter()-start)*1000))
  Path('docs/plan/avatar-asr-fixture-live.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(result)
 await connect(next(p for p in pages() if 'index.html' in p['url']),test)
asyncio.run(main())
