"""生产语音组件+真实WebAudio/WS+生产下发/VAD路径，无麦克风、无云端请求。"""
import ast
import asyncio
import base64
import io
import json
import subprocess
import sys
import time
import wave
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path('engine').resolve()))
from yuiro import approval
from yuiro.audio import AudioSegment, VADEvent, VoicePipeline
from websockets.asyncio.server import serve

exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])


async def main():
    code = subprocess.run(['node', '-e', "const fs=require('fs'),ts=require('./shell/node_modules/typescript');let s=fs.readFileSync('shell/src/renderer/src/composables/useVoiceInput.ts','utf8').replace(/\\r\\n/g,'\\n');s=s.replace('  return {\\n    inputLevel,','  return {\\n    testReceive:handleServerMessage,testBind:(socket:any)=>{ws=socket;voiceSessionId=\"s\"},\\n    inputLevel,');process.stdout.write(ts.transpileModule(s,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)"], capture_output=True, text=True, check=True).stdout
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * 16000)
    streaming='--streaming' in sys.argv
    segment = AudioSegment(wav=buf.getvalue(), sample_rate=16000, slice_ms=20,
                           volumes=[.2]*50, streaming=streaming)
    node = next(n for n in ast.parse(Path('engine/yuiro/main.py').read_text(encoding='utf-8')).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == '_play_audio')
    page = next(p for p in pages() if 'index.html' in p['url'])
    rows = []
    original_conn = approval.get_audio_conn
    try:
        for role in ['hiyori', 'hotaru']:
            for interrupt in [False, True]:
                received = []
                done = asyncio.Event()
                class VAD:
                    def feed(self, chunk):
                        return VADEvent.SpeechStart
                pipe = VoicePipeline(vad=VAD(), barge_in_enabled=True)
                pipe._set_state(pipe.STATE_READY, 'ready', 1)
                row = {'role':role, 'interrupt':interrupt}
                async def handler(socket):
                    class Adapter:
                        async def send_json(self, frame):
                            await socket.send(json.dumps(frame))
                    adapter = Adapter()
                    approval.get_audio_conn = lambda sid: adapter
                    async def emit(sid, kind, payload):
                        await socket.send(json.dumps({'type':kind, **payload,
                            'session_id':sid, 'character_id':role, 'generation':7}))
                    pipe._event_callback = emit
                    pipe._barge_in_callback = lambda sid: pipe.interrupt(sid)
                    namespace = {'AudioSegment':AudioSegment, 'base64':base64, 'vlog':lambda *args:None,
                                 'app':SimpleNamespace(state=SimpleNamespace(
                                     sessions=SimpleNamespace(get=lambda sid:SimpleNamespace(generation=7)),
                                     app_config=SimpleNamespace(_character_id=role), voice_pipeline=pipe))}
                    exec(compile(ast.Module(body=[node],type_ignores=[]),'production _play_audio','exec'),namespace)
                    await namespace['_play_audio']('s',segment)
                    pipe._speaking['s']=False
                    await socket.send(json.dumps({'type':'tts:end', 'session_id':'s',
                        'character_id':role, 'generation':7}))
                    row['busyAfterSentAll']=pipe.playback.busy('s')
                    async for raw in socket:
                        message=json.loads(raw)
                        accepted=pipe.playback.receipt('s',message)
                        received.append({'type':message['type'],'accepted':accepted,
                                         'keys':sorted(message),'at':time.monotonic()})
                        if message['type']=='audio:playback_started' and interrupt:
                            await asyncio.sleep(.15)
                            row['busyBeforeVad']=pipe.playback.busy('s')
                            row['vadAt']=time.monotonic()
                            await pipe.on_audio(b'\0\0'*512,'s')
                        if message['type']=='audio:playback_finished':
                            row['busyAfterFinished']=pipe.playback.busy('s')
                            await socket.close()
                            done.set()
                            break
                async with serve(handler,'127.0.0.1',0) as server:
                    port=server.sockets[0].getsockname()[1]
                    async def browser(call,evaluate):
                        return await evaluate("(async()=>{const contexts=[],Native=window.AudioContext;const exports={};const Ctx=function(){const c=new Native();contexts.push(c);return c};const require=n=>n==='vue'?{ref:value=>({value})}:n.includes('useAudioDevices')?{useAudioDevices:()=>({}),describeMicError:String}:{inputLevel:()=>0};new Function('exports','require','localStorage','AudioContext',"+json.dumps(code)+")(exports,require,{getItem:()=>"+json.dumps(role)+"},Ctx);const events=[];const v=exports.useVoiceInput(t=>events.push(t));const socket=new WebSocket('ws://127.0.0.1:"+str(port)+"');v.testBind(socket);let mouthAfterInterrupt=null;try{await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture timeout')),10000);socket.onmessage=e=>{const m=JSON.parse(e.data);v.testReceive(m);if(m.type==='tts:interrupted')mouthAfterInterrupt=v.mouthOpen.value};socket.onclose=()=>{clearTimeout(timer);resolve()};socket.onerror=reject});return {events,mouthAfterInterrupt,finalMouth:v.mouthOpen.value}}finally{await v.dispose();socket.close();for(const c of contexts)if(c.state!=='closed')await c.close()}})()")
                    row['browser']=await connect(page,browser)
                    await asyncio.wait_for(done.wait(),2)
                row['receipts']=received
                assert row['busyAfterSentAll'] and not row['busyAfterFinished'],row
                if interrupt:
                    assert row['busyBeforeVad'] and 'tts:interrupted' in row['browser']['events'],row
                    assert row['browser']['mouthAfterInterrupt']==0,row
                    row['vadToFinishReceiptMs']=round((received[-1]['at']-row['vadAt'])*1000,2)
                else:
                    assert all(x['accepted'] for x in received),row
                assert row['browser']['finalMouth']==0,row
                rows.append(row)
                print(role,'interrupt' if interrupt else 'natural','passed',flush=True)
    finally:
        approval.get_audio_conn=original_conn
    output='docs/plan/avatar-http-stream-browser-live.json' if streaming else 'docs/plan/avatar-playback-ownership-browser-live.json'
    Path(output).write_text(json.dumps({
        'streamingScheduling':streaming,
        'scope':'production composable transpiled in existing Electron page, real WebAudio and localhost WS, production _play_audio and VoicePipeline; isolated role fixtures, silent WAV with synthetic nonzero mouth envelope; no microphone/cloud/model-switch or acoustic proof',
        'results':rows},ensure_ascii=False,indent=2),encoding='utf-8')

asyncio.run(main())
