"""运行中 Engine/renderer 的有界真实文字出声验证，不采麦、不批准工具。"""
import argparse
import asyncio
import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import websockets
from g0_browser_samples import INSTALL

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/plan/runtime-renderer-live.json'
SAMPLE = r'''(async()=>{
const g=window.__g0;
const r={sample:INDEX,t0:performance.now(),starts:0,ended:0,received_segments:0,
pending:0,events:[],sent_all:false};g.active=r;
r.budget_before=g.app.playbackBudgetState?.();r.peak_queued_bytes=0;r.peak_decode_ahead_seconds=0;
let lastTick=performance.now();r.renderer_max_tick_gap_ms=0;
let lastGraph=-1,lastGraphAt=0,graphStart=-1,graphAt=0;r.max_graph_stall_ms=0;
g.app.sendText('请只回复“你好呀。”，不要调用工具。');
while(performance.now()-r.t0<60000){
 const tick=performance.now();r.renderer_max_tick_gap_ms=Math.max(r.renderer_max_tick_gap_ms,tick-lastTick);lastTick=tick;
 const ctx=window.__runtimeAudioContext;if(ctx&&r.starts){const t=ctx.currentTime;
  if(r.first_graph_progress_ms===undefined&&r.source_starts?.length&&t>r.source_starts[0].scheduled_s+.005)r.first_graph_progress_ms=tick-r.t0;
  if(graphStart<0){graphStart=t;graphAt=tick;}r.audio_context_drift_ms=tick-graphAt-(t-graphStart)*1000;
  if(t===lastGraph)r.max_graph_stall_ms=Math.max(r.max_graph_stall_ms,tick-lastGraphAt);else {lastGraph=t;lastGraphAt=tick;}
  r.audio_context={state:ctx.state,base_latency:ctx.baseLatency,output_latency:ctx.outputLatency,sample_rate:ctx.sampleRate};}
 const b=g.app.playbackBudgetState?.();if(b){r.peak_queued_bytes=Math.max(r.peak_queued_bytes,b.queued_bytes);r.peak_decode_ahead_seconds=Math.max(r.peak_decode_ahead_seconds,b.decode_ahead_seconds);}
 if(r.error)break;
 if(CANCEL&&(BEFORE?r.events.some(e=>e.type==='tts:reply_start'):r.first_graph_progress_ms!==undefined)&&!r.stop_ms){
  r.stop_ms=performance.now()-r.t0;r.starts_at_stop=r.starts;
  if(g.app.socket?.readyState===WebSocket.OPEN)g.app.socket.send(JSON.stringify({type:'interrupt'}));
  else g.app.sendInterrupt();g.app.stopPlayback();
 }
 if(r.stop_ms&&performance.now()-r.t0-r.stop_ms>1500)break;
 if(!CANCEL&&r.sent_all&&r.starts>0&&r.pending===0&&
    (!b||(b.pending===0&&b.queued_bytes===0&&b.scheduled===0&&b.decode_waiters===0))){r.completed=true;break;}
 await new Promise(ok=>setTimeout(ok,25));
}
if(!r.first_start_ms&&!r.stop_ms&&!r.error)r.error='no_audio_started_within_budget';
if(!CANCEL&&!r.completed&&!r.error)r.error='playback_not_drained_within_budget';
r.total_ms=performance.now()-r.t0;
r.budget_after=g.app.playbackBudgetState?.();
if(r.stop_ms)r.late_starts=r.starts-r.starts_at_stop;
delete r.t0;g.active=null;return r;
})()'''


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--cancel-last', action='store_true')
    parser.add_argument('--cancel-all', action='store_true')
    parser.add_argument('--cancel-before-audio', action='store_true')
    parser.add_argument('--replay-after-stop', action='store_true')
    parser.add_argument('--prompt', default='请只回复“你好呀。”，不要调用工具。')
    parser.add_argument('--output', default='runtime-renderer-live.json')
    parser.add_argument('--bilingual-order', choices=['ja_first', 'zh_first', 'baseline'])
    parser.add_argument('--expected-role', choices=['hotaru', 'hiyori'])
    parser.add_argument('--audio-output', help='可选：保存本次实际收到的完整合成WAV用于人工听感')
    args = parser.parse_args()
    output = ROOT / 'docs/plan' / args.output
    async with httpx.AsyncClient(trust_env=False) as client:
        pages = (await client.get('http://127.0.0.1:9222/json/list')).json()
    page = next(p for p in pages if p['title'] == 'Yuiro' and p['type'] == 'page')
    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=20_000_000) as ws:
        seq = 0

        async def call(method, params):
            nonlocal seq
            seq += 1
            await ws.send(json.dumps({'id': seq, 'method': method, 'params': params}))
            while True:
                result = json.loads(await ws.recv())
                if result.get('id') == seq:
                    return result['result']

        async def evaluate(code):
            result = await call('Runtime.evaluate', {'expression': code, 'awaitPromise': True,
                                'returnByValue': True, 'userGesture': True})
            if result.get('exceptionDetails'):
                raise RuntimeError(result['exceptionDetails'])
            return result.get('result', {}).get('value')

        for _ in range(40):
            ready = await evaluate('(()=>{const e=[...document.querySelectorAll("*")].find('
                'e=>e.__vueParentComponent?.setupState.sendText);const a=e?.__vueParentComponent.setupState;'
                'return !!(a?.socket?.readyState===WebSocket.OPEN&&a.sessionId&&a.modelReady&&a.controlReady===true)'
                + (f'&&String(a.modelPath).toLowerCase().includes({json.dumps("hotaru" if args.expected_role == "hotaru" else "hiyori")})' if args.expected_role else '')
                + '})()')
            if ready:
                break
            await asyncio.sleep(.25)
        else:
            raise RuntimeError('renderer control/session/model not ready within 10s')
        await evaluate('window.__runtimeOriginal={decode:BaseAudioContext.prototype.decodeAudioData,'
                       'start:AudioBufferSourceNode.prototype.start};void 0')
        install = INSTALL.replace("r.events.push({type:m.type,ms:performance.now()-r.t0});",
            "r.events.push({type:m.type,ms:performance.now()-r.t0});"
            "if(m.trace_id)r.trace_id=m.trace_id;if(m.stages_ms)r.stages_ms=m.stages_ms;"
            "if(m.tts_timing?.raw_first_audio_ms!==undefined)r.tts_timing=m.tts_timing;"
            "if(m.server_sent_unix_ms&&!r.wire_delivery_ms)r.wire_delivery_ms=Date.now()-m.server_sent_unix_ms;"
            "if(m.character_id)r.observed_character=m.character_id;"
            "if(m.type==='experiment:metrics')r.experiment=m;"
            "if(m.type==='experiment:audio_metrics')r.audio_experiment=m.metrics;"
            "if(m.type==='tts:reply_audio')window.__lastReplyFrame=m;"
            "if(m.type==='tts:reply_audio'&&window.__runtimeAudio){"
            "if(window.__runtimeAudioBytes+m.wav.length<=16000000){__runtimeAudio.push(m.wav);__runtimeAudioBytes+=m.wav.length;}"
            "else r.audio_capture_overflow=true;}"
            "if(m.type==='interrupt:complete'){r.cancel_ack_ms=performance.now()-r.t0;"
            "r.cancel_server_settle_ms=m.settle_ms;}")
        install = install.replace("r.starts++;r.pending++;",
            "r.first_graph_start_ms ??=performance.now()-r.t0+Math.max(0,(args[0]||0)-this.context.currentTime)*1000;"
            "r.starts++;r.pending++;")
        install = install.replace('return p.then(b=>{',
            'return p.then(b=>{if(r)(r.decoded_buffers??=[]).push({ms:performance.now()-r.t0,duration_s:b.duration,sample_rate:b.sampleRate,frames:b.length});')
        install = install.replace('const answer=oldStart.apply(this,args);',
            'window.__runtimeAudioContext=this.context;'
            'if(r)(r.source_starts??=[]).push({ms:performance.now()-r.t0,context_s:this.context.currentTime,scheduled_s:args[0]??this.context.currentTime,duration_s:this.buffer?.duration,rate:this.playbackRate?.value});'
            'const answer=oldStart.apply(this,args);')
        install = install.replace("r.pending--;r.ended++;",
            "(r.source_ends??=[]).push({ms:performance.now()-r.t0,context_s:this.context.currentTime});r.pending--;r.ended++;")
        install = install.replace("const attach=()=>app.socket.addEventListener('message',ev=>{",
                                  "const observedSocket=app.socket;const handler=ev=>{")
        install = install.replace("});\nattach();return",
            "};observedSocket.addEventListener('message',handler);"
            "window.__runtimeMessageCleanup=()=>observedSocket.removeEventListener('message',handler);return")
        report = {'captured_at_utc': datetime.now(UTC).isoformat(),
                  'scope': 'Real text UI to configured Engine/LLM/TTS/renderer AudioContext; '
                           'no VAD/ASR or acoustic measurement',
                  'prompt': args.prompt, 'state': await evaluate(install), 'samples': []}
        try:
            if args.audio_output:
                await evaluate('window.__runtimeAudio=[];window.__runtimeAudioBytes=0;void 0')
            for index in range(args.samples):
                ping_rows = []
                ping_stop = asyncio.Event()
                async def ping(ping_stop=ping_stop, ping_rows=ping_rows):
                    import time
                    async with httpx.AsyncClient(timeout=10, trust_env=False) as health_client:
                        while not ping_stop.is_set():
                            t0 = time.perf_counter()
                            try:
                                status = (await health_client.get('http://127.0.0.1:8200/health')).status_code
                                ping_rows.append({'ms':round((time.perf_counter()-t0)*1000, 2), 'status':status})
                            except httpx.HTTPError:
                                ping_rows.append({'error':'health_timeout'})
                            try:
                                await asyncio.wait_for(ping_stop.wait(), .5)
                            except TimeoutError:
                                pass
                ping_task = asyncio.create_task(ping())
                heap_before = await call('Runtime.getHeapUsage', {})
                code = SAMPLE.replace('INDEX', str(index+1)).replace(
                    'CANCEL', 'true' if args.cancel_all or (
                        args.cancel_last and index == args.samples-1) else 'false')
                code = code.replace('BEFORE', 'true' if args.cancel_before_audio else 'false')
                code = code.replace("'请只回复“你好呀。”，不要调用工具。'", json.dumps(args.prompt))
                if args.bilingual_order:
                    code = code.replace('g.app.sendText('+json.dumps(args.prompt)+');',
                        'g.app.sendText('+json.dumps(args.prompt)+','+json.dumps(args.bilingual_order)+');')
                try:
                    row = await evaluate(code)
                finally:
                    ping_stop.set()
                    await ping_task
                row['engine_health_pings'] = ping_rows
                row['heap_before'] = heap_before
                row['heap_after'] = await call('Runtime.getHeapUsage', {})
                if args.expected_role and row.get('observed_character', args.expected_role) != args.expected_role:
                    row['error'] = 'role_identity_mismatch'
                report['samples'].append(row)
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(row, ensure_ascii=False), flush=True)
            if args.audio_output:
                import io
                import wave
                frames = await evaluate('window.__runtimeAudio')
                if not frames:
                    raise RuntimeError('no audio frames to save')
                output_audio = ROOT / args.audio_output
                output_audio.parent.mkdir(exist_ok=True, parents=True)
                frame_dir = output_audio.with_suffix('.frames')
                frame_dir.mkdir(exist_ok=True)
                capture = []
                for number, encoded in enumerate(frames):
                    raw = base64.b64decode(encoded)
                    (frame_dir/f'{number:04d}.wav').write_bytes(raw)
                    with wave.open(io.BytesIO(raw)) as source:
                        capture.append({'bytes':len(raw), 'declared_frames':source.getnframes(),
                                        'sample_rate':source.getframerate()})
                with wave.open(io.BytesIO(base64.b64decode(frames[0]))) as first:
                    params = first.getparams()
                with wave.open(str(output_audio), 'wb') as destination:
                    destination.setparams(params)
                    for encoded in frames:
                        with wave.open(io.BytesIO(base64.b64decode(encoded))) as source:
                            if (source.getnchannels(),source.getsampwidth(),source.getframerate()) != (params.nchannels,params.sampwidth,params.framerate):
                                raise RuntimeError('mixed audio formats cannot be concatenated')
                            destination.writeframes(source.readframes(source.getnframes()))
                report['audio_capture'] = capture
                output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            if args.replay_after_stop:
                report['controlled_replay'] = await evaluate('''(async()=>{
const a=__g0.app,frame=window.__lastReplyFrame;if(!frame)return {error:'no_fixture'};
a.stopPlayback();let starts=0;const original=AudioBufferSourceNode.prototype.start;
AudioBufferSourceNode.prototype.start=function(...args){starts++;return original.apply(this,args)};
try{a.enqueueReplyAudio(frame);await new Promise(ok=>setTimeout(ok,500));
return {kind:'real_renderer_old_frame_replay_after_stop',late_starts:starts};}
finally{AudioBufferSourceNode.prototype.start=original;delete window.__lastReplyFrame;}
})()''')
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(report['controlled_replay']), flush=True)
            screenshot = await call('Page.captureScreenshot', {'format': 'png'})
            output.with_suffix('.png').write_bytes(
                base64.b64decode(screenshot['data']))
        finally:
            await evaluate('BaseAudioContext.prototype.decodeAudioData=__runtimeOriginal.decode;'
                           'AudioBufferSourceNode.prototype.start=__runtimeOriginal.start;'
                           '__runtimeMessageCleanup();__g0.active=null;delete window.__runtimeAudio;'
                           'delete window.__runtimeAudioBytes;delete window.__runtimeAudioContext;void 0')


if __name__ == '__main__':
    asyncio.run(main())
