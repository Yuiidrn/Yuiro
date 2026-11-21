import asyncio,json,re,time
from pathlib import Path
exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])
async def main():
 async def send(c,e):print('relay',await e("window.yuiro.relayChat('你好，请用一句简短的话向我打招呼。')"))
 await connect(next(p for p in pages() if 'index.html' in p['url']),send)
 for _ in range(160):
  lines=[l for l in Path('.env-local/engine_start.out.log').read_text(encoding='utf-8').splitlines() if '[trace]' in l and 'memory_retrieve_start=' in l]
  if lines:break
  await asyncio.sleep(.25)
 else:raise RuntimeError('No completed trace yet; engine remains live')
 marks={k:float(v) for k,v in re.findall(r'\b([a-z_][a-z_0-9]*)=([0-9.]+)',lines[-1])}
 report={'scope':'one live chat after restart with empty-KB fast path; same prompt as before, not controlled percentile comparison','marks':marks,'memoryMs':marks['memory_retrieve']-marks['memory_retrieve_start'],'providerFirstTokenMs':marks['llm_provider_first_token']-marks['llm_request_start']}
 Path('docs/plan/avatar-memory-empty-kb-after.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(report)
asyncio.run(main())
