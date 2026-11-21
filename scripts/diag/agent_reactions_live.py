"""真实App的Agent互动回放：静音、不调用工具/LLM/TTS、不打开麦克风。"""
import asyncio
import json
from pathlib import Path

from appearance_thumbnails_live import connect, pages
from avatar_tts_waiting_integrated_live import STATE


async def main():
    ps = pages()
    dev = next(p for p in ps if 'dev.html' in p['url'])
    pet = next(p for p in ps if 'index.html' in p['url'])
    rows = []

    async def select(role):
        async def choose(call, evaluate):
            for _ in range(120):
                if await evaluate("!document.querySelector('.character-picker select').disabled"):
                    break
                await asyncio.sleep(.25)
            await evaluate("(()=>{const s=document.querySelector('.character-picker select');s.value="
                           + json.dumps(role) + ";s.dispatchEvent(new Event('change',{bubbles:true}))})()")
            for _ in range(120):
                if await evaluate("(()=>{const s=document.querySelector('.character-picker select');return !s.disabled&&s.value==="+json.dumps(role)+"})()"):
                    return
                await asyncio.sleep(.25)
            raise RuntimeError('Role switch timeout')
        await connect(dev, choose)

    async def run(call, evaluate):
        await call('Page.enable')
        hook = await call('Page.addScriptToEvaluateOnNewDocument', {'source': """
          window.__agentAudit={sockets:[]};const Native=WebSocket;
          window.WebSocket=new Proxy(Native,{construct(T,args){const s=Reflect.construct(T,args);
            if(String(args[0]).includes('/ws/control')){__agentAudit.sockets.push(s);
              s.addEventListener('message',e=>{try{const d=JSON.parse(e.data);
                if(d.type==='session:ready')s.__ready=d;
                if(Number.isInteger(d.generation))s.__gen=Math.max(s.__gen||0,d.generation)}catch{}})}return s}});
          window.__agentCanvas=()=>{const seen=new Set();function f(v){
            if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
            if(v.component?.type.__name==='Live2DCanvas'&&!v.component.props.preview)return v.component.exposed;
            return f(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(f).find(Boolean):null)}
            return f(document.querySelector('#app')?._vnode)};
          window.__agentSend=p=>{const s=__agentAudit.sockets.findLast(s=>s.readyState===1&&s.__ready);
            s.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'agent:activity',
              session_id:s.__ready.session_id,generation:s.__gen||0,character_id:localStorage.getItem('yuiro-active-character'),
              character_revision:__agentAudit.revision,text:'本地互动回放',progress:'',tool:'web_search',...p})}))};
        """})
        try:
            await call('Page.reload')
            await asyncio.sleep(4)
            for role, group, index in [('hiyori', 'Idle', 6), ('hotaru', 'Motion', 4)]:
                await select(role)
                for _ in range(120):
                    state = await evaluate(STATE)
                    ready = await evaluate("!!window.__agentAudit?.sockets.some(s=>s.readyState===1&&s.__ready)")
                    needle = '/hiyori/' if role == 'hiyori' else '/Hotaru Shiomi/'
                    if state['role'] == role and needle in str(state.get('model')) and ready:
                        break
                    await asyncio.sleep(.25)
                assert not state['mic']
                await evaluate("(async()=>{const r=await fetch('http://127.0.0.1:8200/api/config',{headers:{'x-yuiro-secret':await window.yuiro.getEngineSecret()}});if(!r.ok)throw Error('Config read');__agentAudit.revision=(await r.json()).character.revision})()")
                await evaluate("__agentSend({activity_id:'fixture-a',stage:'tool',outcome:'running',motion_slot:'thinking'})")
                await asyncio.sleep(.2)
                started = await evaluate(STATE)
                assert started['state']['until'] > 0 and started['state']['expression'], started
                await evaluate('__agentSend('+json.dumps({'activity_id': 'fixture-a', 'stage': 'tool_result',
                    'outcome': 'success', 'motion_group': group, 'motion_index': index, 'motion_slot': 'greet'})+')')
                await asyncio.sleep(.3)
                success = await evaluate(STATE)
                assert success['state']['motion'] == group and success['state']['motionIndex'] == index, success
                assert success['state']['expression'] != started['state']['expression'], success
                await evaluate('__agentSend('+json.dumps({'activity_id': 'fixture-a', 'stage': 'tool_result',
                    'outcome': 'success', 'motion_group': group, 'motion_index': index, 'motion_slot': 'greet'})+')')
                duplicate = await evaluate(STATE)
                assert duplicate['state'] == success['state'], 'Duplicate restarted reaction'
                await evaluate("__agentSend({activity_id:'foreign',stage:'tool_result',outcome:'error',character_id:'other',motion_slot:'thinking'})")
                stale = await evaluate(STATE)
                assert stale['state'] == success['state'], 'Foreign character changed reaction'
                await evaluate("__agentCanvas().applyAvatarIntent({expression_slot:'thinking',duration_ms:1800,priority:4})")
                user = await evaluate(STATE)
                await evaluate("__agentCanvas().playAgentReaction({expression_slot:'happy',duration_ms:1100,priority:2})")
                protected = await evaluate(STATE)
                assert protected['state'] == user['state'], 'Auto reaction overrode user performance'
                await evaluate('__agentCanvas().cancelPerformance()')
                rows.append({'role': role, 'started': started, 'success': success,
                             'duplicateRejected': True, 'foreignRoleRejected': True, 'userPriorityPreserved': True})
                print(role, 'Agent reaction integration passed', flush=True)
        finally:
            await select('hotaru')
            await call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': hook['identifier']})
            await call('Page.reload')
            await asyncio.sleep(5)
            final = await evaluate(STATE)
            clean = await evaluate('!window.__agentAudit&&!window.__agentSend&&!window.__agentCanvas')
            Path('docs/plan/agent-reactions-live.json').write_text(json.dumps({
                'scope': 'Actual built App/SDK via local synthetic activity events; formal role switches, no real tools/cloud/microphone; backend actual result production tests separate',
                'rows': rows, 'final': final, 'hooksRemoved': clean}, ensure_ascii=False, indent=2), encoding='utf-8')
        assert len(rows) == 2 and clean and final['role'] == 'hotaru' and not final['mic']

    await connect(pet, run)


if __name__ == '__main__':
    asyncio.run(main())
