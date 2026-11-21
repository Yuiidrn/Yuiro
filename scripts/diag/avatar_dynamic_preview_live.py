"""工作台本地舞台动态资源抽查，不应用模型、不发Agent请求或改角色配置。"""
import asyncio
import base64
import json
import sys
from pathlib import Path

from appearance_thumbnails_live import connect, pages


async def main():
    out = Path('docs/plan/avatar-dynamic-preview-after' if '--after' in sys.argv else 'docs/plan/avatar-dynamic-preview')
    out.mkdir(exist_ok=True)
    pet = next(p for p in pages() if 'index.html' in p['url'])
    await connect(pet, lambda c, e: e("window.yuiro.openDev('settings')"))
    await asyncio.sleep(1)
    dev = next(p for p in pages() if 'dev.html' in p['url'])

    async def inspect(call, evaluate):
        await evaluate('[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="外观").click()')
        await asyncio.sleep(1)
        snapshot = """(async()=>{const r=await fetch('http://127.0.0.1:8200/api/config',{
          headers:{'x-yuiro-secret':await window.yuiro.getEngineSecret(),
          'x-yuiro-character':localStorage.getItem('yuiro-active-character')}});
          if(!r.ok)throw Error('Config readback failed');return JSON.stringify(await r.json())})()"""
        before = await evaluate(snapshot)
        await evaluate("""window.__dynamicStage=()=>{const seen=new Set();function find(v){
          if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
          if(v.component?.type.__name==='Live2DCanvas'&&v.component.props.preview)return v.component.exposed;
          return find(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(find).find(Boolean):null)
        }return find(document.querySelector('#app')._vnode)}""")
        rows = []
        try:
            for model, clips in [(0, [('fixed-idle', 'Idle', 0, 4700), ('click-short', 'Idle', 6, 2100)]),
                                  (1, [('tear-effect', 'Motion', 0, 2000), ('cry', 'Motion', 10, 4467),
                                       ('greet', 'Motion', 4, 3533), ('thinking', 'Motion', 40, 2333)])]:
                role = ['hiyori', 'hotaru'][model]
                await evaluate(f'document.querySelectorAll(".model-tile")[{model}].click()')
                for _ in range(120):
                    if await evaluate('!!__dynamicStage()&&!document.querySelector(".stage-loading")'):break
                    await asyncio.sleep(.2)
                else:
                    raise RuntimeError('Preview stage timeout')
                # 取消缩略图后台自动播放，避免它与本次动态取样争抢舞台。
                await evaluate('[...document.querySelectorAll(".studio-tabs button")].find(x=>x.textContent.trim()==="互动节奏").click()')
                await asyncio.sleep(.3)
                for label, group, index, duration in clips:
                    intent = {'motion':group, 'motion_index':index, 'expression':'',
                              'duration_ms':duration, 'priority':4}
                    accepted = await evaluate('__dynamicStage().preparePreview('+json.dumps(intent)+',()=>true)')
                    assert accepted
                    frames = []
                    started = asyncio.get_running_loop().time()
                    targets = [min(.4, duration/1000*.15), duration/2000, duration/1000*.9]
                    for i in range(3):
                        await asyncio.sleep(max(0,targets[i]-(asyncio.get_running_loop().time()-started)))
                        frame = await evaluate('__dynamicStage().capturePreview(true)')
                        file = out / f'{role}-{label}-{i}.png'
                        file.write_bytes(base64.b64decode(frame.split(',')[1]))
                        frames.append(str(file))
                    state = await evaluate('__dynamicStage().getAvatarState()')
                    await asyncio.sleep(max(0,duration/1000+.6-(asyncio.get_running_loop().time()-started)))
                    ended = await evaluate('__dynamicStage().getAvatarState()')
                    rows.append({'role':role, 'label':label, 'group':group, 'index':index,
                                 'durationMs':duration, 'accepted':accepted, 'state':state,
                                 'endingState':ended, 'released':ended.get('until') == 0,
                                 'sampleTargetsSeconds':targets, 'frames':frames})
                    assert ended.get('until') == 0, ended
                    await evaluate('__dynamicStage().cancelPerformance()')
                    print(role, label, 'sampled', flush=True)
        finally:
            await evaluate('__dynamicStage()?.cancelPerformance();delete window.__dynamicStage')
            await evaluate('document.querySelectorAll(".model-tile")[1].click()')
            assert before == await evaluate(snapshot), 'Preview changed active configuration'
        return rows

    rows = await connect(dev, inspect)
    report = {'scope':'actual local AppearanceStudio preview stage, six selected clips and head frames; not all-assets semantic certification',
              'activeConfigUnchanged':True, 'rows':rows}
    (out/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
