"""确定性首句翻译落后fixture；只测本地调度，不调用任何云端。"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path('engine').resolve()))
from yuiro.audio import AudioSegment, VoicePipeline


async def sample():
    started=time.perf_counter();requests=[];played=[]
    class Renderer:
        async def render_speak(self,text):
            await asyncio.sleep(.04 if text=='first' else .001)
            return text
    class TTS:
        async def synthesize_segment(self,text):
            requests.append({'text':text,'ms':round((time.perf_counter()-started)*1000,2)})
            await asyncio.sleep(.01 if text=='first' else .15)
            return AudioSegment(wav=text.encode(),sample_rate=24000,volumes=[])
    async def play(sid,segment):
        played.append({'text':segment.wav.decode(),'ms':round((time.perf_counter()-started)*1000,2)})
    pipe=VoicePipeline(tts=TTS(),renderer=Renderer(),play_callback=play,asr_lock_cool_ms=0)
    await pipe._speak_impl('fixture',sentences=['first','second','third'])
    return {'requests':requests,'played':played}


async def main():
    results=[await sample() for _ in range(5)]
    report={'scope':'deterministic production VoicePipeline scheduling, first translation40ms/later1ms, first synthesis10ms/later150ms; no cloud or renderer','results':results}
    Path(sys.argv[1]).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

asyncio.run(main())
