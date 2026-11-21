"""真实桌宠App控制消息回放；静音音频，无LLM/TTS/麦克风。"""
import asyncio
import base64
import io
import json
import wave
from pathlib import Path

from appearance_thumbnails_live import connect, pages

STATE = """(()=>{const seen=new Set();function find(v){
 if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
 if(v.component?.type.__name==='Live2DCanvas'&&!v.component.props.preview)return v.component;
 return find(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(find).find(Boolean):null)}
 const c=find(document.querySelector('#app')?._vnode);return {
 role:localStorage.getItem('yuiro-active-character'),model:c?.exposed.getModelPath(),
 mouth:c?.props.mouthOpen,state:JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}'),
 mic:!!document.querySelector('.mic-btn.recording')}})()"""


async def main():
    ps = pages()
    pet = next(p for p in ps if 'index.html' in p['url'])
    dev = next(p for p in ps if 'dev.html' in p['url'])
    raw = io.BytesIO()
    with wave.open(raw, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b'\0\0' * 24000)
    wav = base64.b64encode(raw.getvalue()).decode()
    rows = []
    out = Path('docs/plan/avatar-tts-waiting-integrated-live.json')

    async def select(role):
        async def run(call, evaluate):
            for _ in range(120):
                if await evaluate("!!document.querySelector('.character-picker select')&&!document.querySelector('.character-picker select').disabled"):
                    break
                await asyncio.sleep(.25)
            else:
                raise RuntimeError('Existing role switch still pending')
            await evaluate("(()=>{const s=document.querySelector('.character-picker select');s.value="
                           + json.dumps(role) + ";s.dispatchEvent(new Event('change',{bubbles:true}))})()")
            for _ in range(120):
                if await evaluate("(()=>{const s=document.querySelector('.character-picker select');return !s.disabled&&s.value==="+json.dumps(role)+"})()"):
                    break
                await asyncio.sleep(.25)
            else:
                raise RuntimeError('Role selection did not complete')
        await connect(dev, run)

    async def run(call, evaluate):
        before = await evaluate(STATE)
        assert before['role'] in ('hotaru', 'hiyori') and not before['mic'] and before['state']['presence'] == 'idle'
        await call('Page.enable')
        hook = await call('Page.addScriptToEvaluateOnNewDocument', {'source': """
          window.__waitingAudit={sockets:[],sentTypes:[]};const Native=window.WebSocket;
          window.WebSocket=new Proxy(Native,{construct(target,args){const s=Reflect.construct(target,args);
            if(String(args[0]).includes('/ws/control')){
              __waitingAudit.sockets.push(s);
              s.addEventListener('message',e=>{try{const m=JSON.parse(e.data);
                if(m.type==='session:ready')s.__ready=m;
                if(Number.isInteger(m.generation))s.__generation=Math.max(s.__generation||0,m.generation)
              }catch{}});
              const send=s.send;s.send=function(data){try{__waitingAudit.sentTypes.push(JSON.parse(data).type)}catch{}return send.call(this,data)}
            }return s}});
          window.__waitingSend=payload=>{const s=__waitingAudit.sockets.findLast(s=>s.readyState===1&&s.__ready);
            if(!s)throw Error('No current control session');
            s.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({session_id:s.__ready.session_id,
              generation:s.__generation||0,character_id:localStorage.getItem('yuiro-active-character'),...payload})}))};
        """})
        try:
            await call('Page.reload')
            for role in ['hiyori', 'hotaru', 'hiyori']:
                await select(role)
                for _ in range(120):
                    current = await evaluate(STATE)
                    ready = await evaluate("!!window.__waitingAudit?.sockets.some(s=>s.readyState===1&&s.__ready)")
                    model_ok = ('/hiyori/' in str(current.get('model'))) if role == 'hiyori' else ('/Hotaru Shiomi/' in str(current.get('model')))
                    if current['role'] == role and model_ok and ready:
                        break
                    await asyncio.sleep(.25)
                else:
                    raise RuntimeError('Role/model/session readiness timeout')
                assert not current['mic']
                for empty in [False, True]:
                    await evaluate("__waitingSend({type:'chat:assistant',text:'本地表现状态验证，不请求云端。'})")
                    await asyncio.sleep(.25)
                    waiting = await evaluate(STATE)
                    assert waiting['state']['presence'] == 'thinking', waiting
                    stale_rejected = None
                    if await evaluate('!!__waitingAudit.previousIdentity'):
                        distinct = await evaluate("__waitingAudit.previousIdentity.session_id!==__waitingAudit.sockets.findLast(s=>s.readyState===1&&s.__ready).__ready.session_id")
                        assert distinct, 'Role switch must establish distinct session for this scenario'
                        await evaluate("__waitingSend({type:'tts:reply_end',...__waitingAudit.previousIdentity})")
                        await evaluate('__waitingSend({...'+json.dumps({'type': 'tts:reply_audio', 'wav': wav,
                            'sample_rate': 24000, 'slice_ms': 20, 'volumes': [.35] * 50})
                            + ',...__waitingAudit.previousIdentity})')
                        await asyncio.sleep(.15)
                        after_stale = await evaluate(STATE)
                        stale_rejected = after_stale['state']['presence'] == 'thinking' and after_stale['mouth'] == 0
                        assert stale_rejected, after_stale
                    if not empty:
                        await evaluate('__waitingSend('+json.dumps({'type': 'tts:reply_audio', 'wav': wav,
                            'sample_rate': 24000, 'slice_ms': 20, 'volumes': [.35] * 50})+')')
                        for _ in range(80):
                            playing = await evaluate(STATE)
                            if playing['state']['presence'] == 'speaking' and playing['mouth'] > 0:
                                break
                            await asyncio.sleep(.025)
                        else:
                            raise RuntimeError('Actual App playback/mouth did not start')
                    else:
                        playing = None
                    await evaluate("__waitingSend({type:'tts:reply_end'})")
                    for _ in range(120):
                        ended = await evaluate(STATE)
                        if ended['state']['presence'] == 'idle' and ended['mouth'] == 0:
                            break
                        await asyncio.sleep(.025)
                    else:
                        raise RuntimeError('App playback did not settle')
                    rows.append({'role': role, 'empty': empty, 'stalePreviousRoleRejected': stale_rejected,
                                 'waiting': waiting, 'playing': playing, 'ended': ended})
                    print(role, 'empty' if empty else 'audio', 'App/Avatar passed', flush=True)
                await evaluate("(()=>{const s=__waitingAudit.sockets.findLast(s=>s.readyState===1&&s.__ready);__waitingAudit.previousIdentity={session_id:s.__ready.session_id,generation:s.__generation||0}})()")
            sent = await evaluate('__waitingAudit.sentTypes')
            assert 'chat:user' not in sent and 'audio:start' not in sent, sent
        finally:
            await select('hotaru')
            for _ in range(120):
                restored = await evaluate(STATE)
                if restored['role'] == 'hotaru' and '/Hotaru Shiomi/' in str(restored.get('model')):
                    break
                await asyncio.sleep(.25)
            await call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': hook['identifier']})
            await call('Page.reload')
            await asyncio.sleep(5)
            final = await evaluate(STATE)
            clean = await evaluate('!window.__waitingAudit&&!window.__waitingSend')
            out.write_text(json.dumps({'scope': 'Actual App control handler + Avatar presence/props + WebAudio via synthetic incoming control events; formal role service switches, silent WAV and synthetic volume envelope. No supplier/ASR/microphone or acoustic proof.',
                'rows': rows, 'final': final, 'hookRemoved': clean}, ensure_ascii=False, indent=2), encoding='utf-8')
        assert clean and final['role'] == 'hotaru' and not final['mic'] and final['state']['presence'] == 'idle'

    await connect(pet, run)


if __name__ == '__main__':
    asyncio.run(main())
