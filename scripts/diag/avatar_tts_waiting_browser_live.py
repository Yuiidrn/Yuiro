"""真实WebAudio内回放首段等待/空结果，不调用云端或采麦。"""
import asyncio
import base64
import io
import json
import subprocess
import wave
from pathlib import Path

from appearance_thumbnails_live import connect, pages


async def main():
    modules = {}
    for name, file in [('voice', 'composables/useVoiceInput'), ('presence', 'avatar/presence')]:
        modules[name] = (await asyncio.to_thread(subprocess.run, ['node', '-e',
            "const fs=require('fs'),ts=require('./shell/node_modules/typescript');"
            "process.stdout.write(ts.transpileModule(fs.readFileSync("
            + json.dumps('shell/src/renderer/src/' + file + '.ts')
            + ",'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)"
        ], capture_output=True, text=True, check=True)).stdout
    data = io.BytesIO()
    with wave.open(data, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b'\0\0' * 11520)
    audio = base64.b64encode(data.getvalue()).decode()
    rows = []
    page = next(p for p in pages() if 'index.html' in p['url'])
    for role in ['hiyori', 'hotaru']:
        for empty in [False, True]:
            async def run(call, evaluate, role=role, empty=empty):
                return await evaluate("""(async()=>{
                  const p={},v={},contexts=[],events=[],Native=window.AudioContext;
                  const require=n=>n==='vue'?{ref:value=>({value})}:
                    n.includes('useAudioDevices')?{useAudioDevices:()=>({}),describeMicError:String}:{inputLevel:()=>0};
                  new Function('exports',PRESENCE)(p);
                  const Ctx=function(){const c=new Native();contexts.push(c);return c};
                  new Function('exports','require','localStorage','AudioContext',VOICE)
                    (v,require,{getItem:()=>ROLE},Ctx);
                  let state='idle';const voice=v.useVoiceInput(type=>{
                    state=p.presenceAfter(state,type);events.push({type,state})});
                  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
                  try{
                    voice.beginReplyPlayback();await sleep(150);const waiting=state;
                    if(!EMPTY)voice.enqueueReplyAudio({wav:WAV,sample_rate:24000,slice_ms:20,volumes:Array(24).fill(.2)});
                    if(!EMPTY){const until=performance.now()+3000;
                      while(state!=='speaking'&&performance.now()<until)await sleep(10)}
                    const beforeEnd=state;voice.endReplyAudio();
                    const until=performance.now()+3000;
                    while(state!=='idle'&&performance.now()<until)await sleep(10);
                    const ended=state;
                    await voice.dispose();
                    return {role:ROLE,empty:EMPTY,waiting,beforeEnd,ended,events,
                      mouth:voice.mouthOpen.value,contextsClosed:contexts.every(c=>c.state==='closed')};
                  }finally{await voice.dispose();for(const c of contexts)if(c.state!=='closed')await c.close()}
                })()""".replace('PRESENCE', json.dumps(modules['presence']))
                    .replace('VOICE', json.dumps(modules['voice']))
                    .replace('ROLE', json.dumps(role)).replace('EMPTY', json.dumps(empty))
                    .replace('WAV', json.dumps(audio)))
            row = await connect(page, run)
            Path('docs/plan/avatar-tts-waiting-browser-last-attempt.json').write_text(
                json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
            assert row['waiting'] == 'thinking' and row['ended'] == 'idle'
            assert row['mouth'] == 0 and row['contextsClosed']
            types = [e['type'] for e in row['events']]
            if empty:
                assert row['beforeEnd'] == 'thinking' and 'tts:playback_empty' in types
                assert 'tts:playback_start' not in types and 'tts:playback_end' not in types
            else:
                assert row['beforeEnd'] == 'speaking' and 'tts:playback_end' in types
                assert 'tts:playback_empty' not in types
            rows.append(row)
            print(role, 'empty' if empty else 'audio', 'passed', flush=True)
    Path('docs/plan/avatar-tts-waiting-browser-live.json').write_text(json.dumps({
        'scope': 'Actual Electron WebAudio with current production composable and presence reducer; silent fixtures in isolated instances, no microphone/cloud, not integrated avatar rendering or supplier TTFA.',
        'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
