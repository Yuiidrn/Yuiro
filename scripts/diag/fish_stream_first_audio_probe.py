"""有限真实Fish HTTP流式首片采样：不播放、不采麦、不改配置。"""
import asyncio
import argparse
import io
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0,str(Path('engine').resolve()))
from yuiro.audio.fish import build_fish_provider
from yuiro.characters import CharacterStore
from yuiro.config import load_config


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--samples',type=int,default=3)
    parser.add_argument('--output',default='docs/plan/fish-stream-first-audio-probe.json')
    options=parser.parse_args()
    if not 1<=options.samples<=6:raise ValueError('Use 1 to 6 bounded requests')
    path=Path('engine/config.toml')
    cfg=CharacterStore(path).resolve('hotaru',load_config(path,with_character=False))
    assert cfg.tts.provider=='fish' and cfg.tts.segment_streaming
    rows=[]
    for i in range(options.samples):
        provider=build_fish_provider(cfg.tts)
        started=time.perf_counter();chunks=[]
        try:
            async with asyncio.timeout(65):
                async for segment in provider.synthesize_stream('こんにちは。今日はどんな一日でしたか？'):
                    with wave.open(io.BytesIO(segment.wav)) as audio:
                        frames=audio.getnframes();rate=audio.getframerate()
                        assert audio.getsampwidth()==2 and audio.getnchannels()==1
                    chunks.append({'ms':round((time.perf_counter()-started)*1000,1),
                                   'frames':frames,'sampleRate':rate,'rmsSlices':len(segment.volumes)})
            complete=round((time.perf_counter()-started)*1000,1)
            assert chunks and chunks[0]['ms']<complete
            row={'sample':i+1,'firstPlayableChunkMs':chunks[0]['ms'],'completeMs':complete,
                 'durationMs':round(sum(c['frames']/c['sampleRate']*1000 for c in chunks),1),'chunks':chunks}
        except (RuntimeError,TimeoutError) as exc:
            row={'sample':i+1,'errorType':type(exc).__name__,
                 'elapsedMs':round((time.perf_counter()-started)*1000,1),'chunksBeforeError':chunks}
        rows.append(row);print(json.dumps(row),flush=True)
        Path(options.output).write_text(json.dumps({
            'scope':'bounded actual production FishAudioProvider HTTP streaming requests using unchanged Hotaru voice/model/latency/speed, fixed short Japanese text; independently decodeable WAV chunks with RMS; no translation, playback or microphone; not controlled A/B or latency SLA',
            'maximumRequests':options.samples,'rows':rows},indent=2),encoding='utf-8')
        if 'errorType' in row:break  # 记录失败，不以自动重试制造成功样本。

asyncio.run(main())
