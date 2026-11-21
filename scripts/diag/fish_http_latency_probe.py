"""有限次数真实Fish采样；不出声、不采麦、不修改角色，不记录凭证/响应正文。"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0,str(Path('engine').resolve()))
from yuiro.characters import CharacterStore
from yuiro.config import load_config
from yuiro.keychain import load_fish_key


async def main():
    path=Path('engine/config.toml')
    cfg=CharacterStore(path).resolve('hotaru',load_config(path,with_character=False))
    assert cfg.tts.provider=='fish'
    key=load_fish_key()
    assert key,'Local Fish key missing'
    rows=[]
    shared=httpx.AsyncClient(timeout=httpx.Timeout(60,connect=10))
    try:
        for i,mode in enumerate(['fresh','shared-cold','fresh','shared-warm','fresh','shared-warm']):
            client=httpx.AsyncClient(timeout=httpx.Timeout(60,connect=10)) if mode=='fresh' else shared
            started=time.perf_counter();row={'mode':mode,'sample':i+1}
            try:
                async with client.stream('POST','https://api.fish.audio/v1/tts',
                    headers={'Authorization':f'Bearer {key}','model':cfg.tts.fish_model},
                    json={'text':'こんにちは。今日はどんな一日でしたか？','reference_id':cfg.tts.fish_reference_id,
                          'format':'wav','sample_rate':44100,'latency':cfg.tts.fish_latency,
                          'prosody':{'speed':cfg.tts.fish_speed}}) as response:
                    row.update(status=response.status_code,headersMs=round((time.perf_counter()-started)*1000,1))
                    total=0;first=None
                    async for chunk in response.aiter_bytes():
                        if first is None:first=round((time.perf_counter()-started)*1000,1)
                        total+=len(chunk)
                    row.update(firstBodyChunkMs=first,completeMs=round((time.perf_counter()-started)*1000,1),bytes=total)
            except httpx.HTTPError as exc:
                row.update(error=type(exc).__name__,elapsedMs=round((time.perf_counter()-started)*1000,1))
            finally:
                if mode=='fresh':await client.aclose()
            rows.append(row);print(json.dumps(row),flush=True)
            if row.get('status') not in (None,200):break
    finally:
        await shared.aclose()
    Path('docs/plan/fish-http-latency-probe.json').write_text(json.dumps({
        'scope':'six maximum paid HTTP requests using current Hotaru voice/model/latency/speed, fixed short Japanese text, no translation/playback/microphone; interleaved fresh vs shared connection, too few samples for latency SLA or causal A/B',
        'model':cfg.tts.fish_model,'latency':cfg.tts.fish_latency,'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')

asyncio.run(main())
