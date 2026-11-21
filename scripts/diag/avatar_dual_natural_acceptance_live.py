"""正式角色切换与真实Agent/TTS招呼；不打开麦克风、不输出正文或音频。"""
import asyncio
import json
import time
from pathlib import Path

import websockets
from appearance_thumbnails_live import connect, pages


async def select_role(role):
    dev = next(p for p in pages() if 'dev.html' in p['url'])
    async def switch(call, evaluate):
        return await evaluate("(()=>{const s=document.querySelector('.character-picker select');"
                              "if(!s)throw Error('Missing character selector');s.value="+json.dumps(role)+
                              ";s.dispatchEvent(new Event('change',{bubbles:true}));return true})()")
    await connect(dev, switch)
    pet = next(p for p in pages() if 'index.html' in p['url'])
    async def wait(call, evaluate):
        for _ in range(120):
            if await evaluate("localStorage.getItem('yuiro-active-character')==="+json.dumps(role)):
                await call('Page.reload')
                await asyncio.sleep(3)
                return
            await asyncio.sleep(.25)
        raise RuntimeError('Character switch timeout')
    await connect(pet, wait)


async def sample(role):
    page = next(p for p in pages() if 'index.html' in p['url'])
    frames, samples = [], []
    sequence = 0
    started = time.monotonic()
    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=30000000) as socket:
        async def call(method, params=None):
            nonlocal sequence
            sequence += 1
            await socket.send(json.dumps({'id':sequence,'method':method,'params':params or {}}))
            while True:
                message = json.loads(await socket.recv())
                kind = message.get('method')
                if kind in ('Network.webSocketFrameReceived', 'Network.webSocketFrameSent'):
                    try:
                        data = json.loads(message['params']['response']['payloadData'])
                        if data.get('type') in ('avatar:intent','avatar:receipt','chat:assistant',
                                                'tts:reply_audio','tts:reply_end'):
                            row = {k:data.get(k) for k in ('type','source','performance','session_id',
                                   'generation','intent_id','phase','streaming')}
                            row['chars'] = len(str(data.get('text','')))
                            row['observedMs'] = round((time.monotonic()-started)*1000,1)
                            frames.append(row)
                    except (ValueError, KeyError, AttributeError):
                        pass
                if message.get('id') == sequence:
                    if 'error' in message:raise RuntimeError(message['error']['message'])
                    return message['result']

        async def evaluate(code):
            result = await call('Runtime.evaluate', {'expression':code,'awaitPromise':True,'returnByValue':True})
            if 'exceptionDetails' in result:raise RuntimeError('Browser evaluation failed')
            return result.get('result',{}).get('value')

        snapshot = """(async()=>{const r=await fetch('http://127.0.0.1:8200/api/config',{
          headers:{'x-yuiro-secret':await window.yuiro.getEngineSecret(),
          'x-yuiro-character':localStorage.getItem('yuiro-active-character')}});
          if(!r.ok)throw Error('Config readback');return JSON.stringify(await r.json())})()"""
        before = await evaluate(snapshot)
        sid = await evaluate("localStorage.getItem('yuiro.session_id')")
        assert not await evaluate("!!document.querySelector('.mic-btn.recording')")
        await evaluate("""window.__naturalCanvas=()=>{const seen=new Set();function find(v){
          if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
          if(v.component?.type.__name==='Live2DCanvas'&&!v.component.props.preview)return v.component;
          return find(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(find).find(Boolean):null)
        }return find(document.querySelector('#app')._vnode)}""")
        try:
            await call('Network.enable')
            started = time.monotonic()
            await evaluate("window.yuiro.relayChat('请向我打个招呼，配合一个合适的小动作，只回复一句话。')")
            for _ in range(360):
                state = await evaluate("(()=>{const c=__naturalCanvas();return {presence:JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}').presence,mouth:c?.props.mouthOpen,model:c?.exposed.getModelPath(),avatar:c?.exposed.getAvatarState(),visibility:document.visibilityState}})()")
                samples.append(state)
                has_end = any(f['type']=='tts:reply_end' for f in frames)
                if has_end and state.get('presence')=='idle' and any(s.get('presence')=='speaking' for s in samples):break
                await asyncio.sleep(.25)
            same = before == await evaluate(snapshot)
        finally:
            await evaluate('delete window.__naturalCanvas')
        intents = [f for f in frames if f['type']=='avatar:intent' and f['source']=='agent']
        ids = {f['intent_id'] for f in intents}
        audio = [f for f in frames if f['type']=='tts:reply_audio']
        checks = {'agentIntent':bool(intents),
                  'startedReceipt':any(f['type']=='avatar:receipt' and f['phase']=='started' and f['intent_id'] in ids for f in frames),
                  'audioIdentity':bool(audio) and all(f['session_id']==sid and isinstance(f['generation'],int) for f in audio),
                  'speakingAndMouth':any(s.get('presence')=='speaking' and (s.get('mouth') or 0)>0 for s in samples),
                  'finalIdle':samples[-1].get('presence')=='idle',
                  'finalMouthZero':samples[-1].get('mouth') == 0,
                  'modelMatchesRole':all(('/hiyori/' if role=='hiyori' else '/Hotaru Shiomi/') in str(s.get('model')) for s in samples),
                  'configUnchanged':same}
        return {'role':role,'checks':checks,'passed':all(checks.values()),'frames':frames,'samples':samples}


async def main():
    output = Path('docs/plan/avatar-dual-natural-current-live.json')
    rows = []
    report = {'scope':'real formal role switching and natural text through current Agent/TTS/Avatar; no microphone/ASR or subjective acoustic acceptance; observer times are not physical latency', 'rows':rows}
    try:
        for role in ['hiyori','hotaru']:
            await select_role(role)
            row = await sample(role)
            rows.append(row)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(role, row['checks'], flush=True)
    finally:
        await select_role('hotaru')
        report['restoredRole'] = 'hotaru'
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
