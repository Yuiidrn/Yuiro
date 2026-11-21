"""两方向真实文字朗读中正式换角色；观测原页面音频节点停止，不用刷新掩盖清理。"""
import asyncio
import json
import sys
from pathlib import Path

from appearance_thumbnails_live import connect, pages


def pet_page():
    return next(p for p in pages() if 'index.html' in p['url'])


async def pet_eval(code):
    return await connect(pet_page(), lambda c,e:e(code))


STATE = """(()=>{const seen=new Set();function find(v){
 if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
 if(v.component?.type.__name==='Live2DCanvas'&&!v.component.props.preview)return v.component;
 return find(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(find).find(Boolean):null)}
 const c=find(document.querySelector('#app')._vnode);
 return {role:localStorage.getItem('yuiro-active-character'),model:c?.exposed.getModelPath(),
 mouth:c?.props.mouthOpen,presence:JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}').presence,
 avatar:c?.exposed.getAvatarState(),mic:!!document.querySelector('.mic-btn.recording')}})()"""


async def select_role(role):
    dev = next(p for p in pages() if 'dev.html' in p['url'])
    async def select(call,evaluate):
        await evaluate("(()=>{const s=document.querySelector('.character-picker select');s.value="+
                       json.dumps(role)+";s.dispatchEvent(new Event('change',{bubbles:true}))})()")
    await connect(dev, select)
    needle = '/hiyori/' if role == 'hiyori' else '/Hotaru Shiomi/'
    for _ in range(120):
        state = await pet_eval(STATE)
        if state['role'] == role and needle in str(state.get('model')):
            return state
        await asyncio.sleep(.25)
    raise RuntimeError('Formal switch timeout')


async def snapshot():
    return await pet_eval("""(async()=>{const r=await fetch('http://127.0.0.1:8200/api/config',{
      headers:{'x-yuiro-secret':await window.yuiro.getEngineSecret(),
      'x-yuiro-character':localStorage.getItem('yuiro-active-character')}});
      if(!r.ok)throw Error('Config readback');return JSON.stringify((await r.json()).sections)})()""")


async def sample(source, target):
    initial = await pet_eval(STATE)
    assert initial['role'] == source and not initial['mic'], initial
    await pet_eval("""(()=>{const p=AudioBufferSourceNode.prototype;
      window.__midplayAudit={oldStart:p.start,oldStop:p.stop,ids:new WeakMap(),entries:[]};
      p.start=function(...args){const r=Reflect.apply(__midplayAudit.oldStart,this,args),ctx=this.context;
        const start=args[0]??ctx.currentTime,e={id:__midplayAudit.entries.length,start,
        end:start+(this.buffer?.duration??0),ctx,stops:[]};
        __midplayAudit.ids.set(this,e);__midplayAudit.entries.push(e);return r};
      p.stop=function(...args){const r=Reflect.apply(__midplayAudit.oldStop,this,args),e=__midplayAudit.ids.get(this);
        if(e)e.stops.push({clock:this.context.currentTime,wall:performance.now()});return r};return true})()""")
    try:
        await pet_eval("window.yuiro.relayChat('请只用一句约六十字的话，温柔地描述雨后花园。')")
        active = None
        for _ in range(360):
            active = await pet_eval("""(()=>{const rows=__midplayAudit.entries;
              return rows.some(e=>e.ctx.currentTime>=e.start+.1&&e.ctx.currentTime<e.end)?
              {at:performance.now(),rows:rows.map(e=>({id:e.id,start:e.start,end:e.end,clock:e.ctx.currentTime}))}:null})()""")
            if active:break
            await asyncio.sleep(.25)
        if active is None:raise RuntimeError('No active audio observed before timeout')
        before = await pet_eval(STATE)
        assert before['presence'] == 'speaking' and before['role'] == source, before
        await select_role(target)
        await asyncio.sleep(1)
        final = await pet_eval(STATE)
        audio = await pet_eval("""(()=>{const a=__midplayAudit;return a?{
          sameDocument:true,rows:a.entries.map(e=>({id:e.id,start:e.start,end:e.end,
          clock:e.ctx.currentTime,stops:e.stops}))}:{sameDocument:false,rows:[]}})()""")
        checks = {'sameDocument':audio['sameDocument'],
                  'oldNodeStopped':any(e['stops'] for e in audio['rows']),
                  'oldNodesQuiescent':all(e['stops'] or e['clock']>=e['end']-.005 for e in audio['rows']),
                  'targetModel':final['role']==target and ('/hiyori/' if target=='hiyori' else '/Hotaru Shiomi/') in str(final['model']),
                  'mouthZero':final.get('mouth')==0, 'idle':final['presence']=='idle',
                  'performanceReleased':final.get('avatar',{}).get('until')==0,
                  'micClosed':not final['mic']}
        return {'source':source,'target':target,'before':before,'activeAudioBeforeSwitch':active,
                'audioAfterSwitch':audio,'final':final,'checks':checks,'passed':all(checks.values())}
    finally:
        await pet_eval("(()=>{if(window.__midplayAudit){const a=__midplayAudit,p=AudioBufferSourceNode.prototype;p.start=a.oldStart;p.stop=a.oldStop;delete window.__midplayAudit}})()")


async def main():
    reverse_only = '--reverse-only' in sys.argv
    output = Path('docs/plan/avatar-midplay-current-reverse-live.json' if reverse_only else 'docs/plan/avatar-midplay-current-live.json')
    report = {'scope':'real current text Agent/TTS and formal character switching while actual WebAudio active; no page reload or microphone; source.stop calls are not acoustic stop latency', 'rows':[]}
    original = await pet_eval(STATE)
    assert original['role']=='hotaru' and not original['mic'], original
    hotaru_config = await snapshot()
    try:
        await select_role('hiyori')
        hiyori_config = await snapshot()
        if reverse_only:
            await select_role('hotaru')
        else:
            report['rows'].append(await sample('hiyori','hotaru'))
            report['hotaruConfigUnchanged'] = hotaru_config == await snapshot()
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print('hiyori to hotaru',report['rows'][-1]['checks'],flush=True)
        report['rows'].append(await sample('hotaru','hiyori'))
        report['hiyoriConfigUnchanged'] = hiyori_config == await snapshot()
        print('hotaru to hiyori',report['rows'][-1]['checks'],flush=True)
    except Exception as exc:
        report['errorType'] = type(exc).__name__
        raise
    finally:
        report['restored'] = await select_role('hotaru')
        report['hotaruFinalConfigUnchanged'] = hotaru_config == await snapshot()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
