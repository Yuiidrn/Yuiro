"""真实Electron/WebAudio中验证断供缓冲、尾块释放和取消；静音fixture、不采麦。"""
import asyncio
import base64
import io
import json
import subprocess
import wave
from pathlib import Path

from appearance_thumbnails_live import connect, pages


async def main():
    code = (await asyncio.to_thread(subprocess.run, [
        'node', '-e',
        ("const fs=require('fs'),ts=require('./shell/node_modules/typescript');"
        "process.stdout.write(ts.transpileModule(fs.readFileSync("
        "'shell/src/renderer/src/composables/useVoiceInput.ts','utf8'),"
        "{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)"),
    ], capture_output=True, text=True, check=True)).stdout
    raw = io.BytesIO()
    with wave.open(raw, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b'\0\0' * 11520)
    wav = base64.b64encode(raw.getvalue()).decode()
    page = next(p for p in pages() if 'index.html' in p['url'])
    rows = []
    for role in ['hiyori', 'hotaru']:
        for mode in ['threshold', 'tail', 'cancel']:
            async def run(call, evaluate, role=role, mode=mode):
                return await evaluate("""(async()=>{
                  const contexts=[],sources=[],events=[],Native=window.AudioContext;
                  const Ctx=function(){const c=new Native();contexts.push(c);
                    const create=c.createBufferSource.bind(c);
                    c.createBufferSource=()=>{const s=create(),start=s.start.bind(s);
                      s.start=t=>{sources.push({start:t,duration:s.buffer.duration});start(t)};return s};return c};
                  const exports={},require=n=>n==='vue'?{ref:value=>({value})}:
                    n.includes('useAudioDevices')?{useAudioDevices:()=>({}),describeMicError:String}:{inputLevel:()=>0};
                  new Function('exports','require','localStorage','AudioContext',CODE)
                    (exports,require,{getItem:()=>ROLE},Ctx);
                  const v=exports.useVoiceInput((type,payload)=>events.push({type,...payload}));
                  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
                  const send=()=>v.enqueueReplyAudio({wav:WAV,sample_rate:24000,slice_ms:20,
                    volumes:Array(24).fill(.2),streaming:true});
                  try{
                    v.beginReplyPlayback();send();await sleep(850);
                    const mouthDuringGap=v.mouthOpen.value;
                    send();await sleep(100);
                    const held=sources.length===1;
                    if(MODE==='threshold'){send();await sleep(150);v.endReplyAudio();await sleep(1200)}
                    if(MODE==='tail'){v.endReplyAudio();await sleep(800)}
                    if(MODE==='cancel'){v.stopPlayback();await sleep(1700)}
                    await v.dispose();
                    return {mode:MODE,held,mouthDuringGap,finalMouth:v.mouthOpen.value,sources,events,contextsClosed:contexts.every(c=>c.state==='closed')};
                  }finally{await v.dispose();for(const c of contexts)if(c.state!=='closed')await c.close()}
                })()""".replace('CODE', json.dumps(code)).replace('ROLE', json.dumps(role))
                    .replace('WAV', json.dumps(wav)).replace('MODE', json.dumps(mode)))
            result = await connect(page, run)
            assert result['held'] and result['mouthDuringGap'] == 0, result
            assert result['finalMouth'] == 0 and result['contextsClosed'], result
            if mode == 'threshold':
                assert len(result['sources']) == 3, result
                assert abs(result['sources'][2]['start'] - result['sources'][1]['start'] - .48) < .001
            elif mode == 'tail':
                assert len(result['sources']) == 2, result
            else:
                assert len(result['sources']) == 1, result
            if mode != 'cancel':
                assert any(e['type'] == 'tts:playback_end' for e in result['events']), result
            rows.append({'roleFixture': role, **result, 'passed': True})
            print(role, mode, 'passed', flush=True)
    Path('docs/plan/avatar-stream-rebuffer-browser-live.json').write_text(json.dumps({
        'scope': 'production composable in actual Electron/WebAudio, silent 480ms WAV with synthetic mouth envelope; isolated role fixtures, no microphone/cloud, no formal character switching or acoustic proof',
        'rows': rows,
    }, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
