"""两模型真实绘制前眼睛参数/头像采样；本地工作台，不开麦、不调用云端。"""
import asyncio
import argparse
import base64
import json
from pathlib import Path

from appearance_thumbnails_live import connect, pages


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--combo', action='store_true')
    parser.add_argument('--output')
    options = parser.parse_args()
    combo = options.combo
    out = Path(options.output or ('docs/plan/avatar-expression-eye-combo' if combo else 'docs/plan/avatar-expression-eye-after'))
    out.mkdir(exist_ok=True)
    dev = next(p for p in pages() if 'dev.html' in p['url'])
    async def inspect(call,evaluate):
        assert not await evaluate("document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('devConfig').hasDraftChanges")
        await call('Page.reload');await asyncio.sleep(2)
        await evaluate('[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="外观").click()')
        await asyncio.sleep(1)
        await evaluate("""window.__eyeStage=()=>{const seen=new Set();function f(v){
          if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
          if(v.component?.type.__name==='Live2DCanvas'&&v.component.props.preview){window.__eyePreviewComponent=v.component;return v.component.exposed;}
          return f(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(f).find(Boolean):null)}
          return f(document.querySelector('#app')._vnode)};
          window.__coreEyes={original:Live2DCubismCore.Model.prototype.update,rows:[]};
          Live2DCubismCore.Model.prototype.update=function(...args){
            const r=Reflect.apply(__coreEyes.original,this,args),p=this.parameters;
            if(p){const l=p.ids.indexOf('ParamEyeLOpen'),rr=p.ids.indexOf('ParamEyeROpen');
              __coreEyes.rows.push({left:p.values[l],right:p.values[rr],mouth:p.values[p.ids.indexOf('ParamMouthOpenY')]})}return r}""")
        rows = []
        try:
            for model,role,expression in [(0,'hiyori','happy'),(1,'hotaru','exp_bsmile01')]:
                await evaluate(f'document.querySelectorAll(".model-tile")[{model}].click()')
                for _ in range(100):
                    if await evaluate('!!__eyeStage()&&!document.querySelector(".stage-loading")'):break
                    await asyncio.sleep(.2)
                else:raise RuntimeError('Stage timeout')
                await evaluate('[...document.querySelectorAll(".studio-tabs button")].find(x=>x.textContent.trim()==="互动节奏").click()')
                await asyncio.sleep(.2)
                phases = [('combined',expression,.7),('released','',.7)] if combo else [('neutral','',8.2),('expression',expression,1.2),('reset','',8.2)]
                for label,name,duration in phases:
                    intent = {'expression':name}
                    if label == 'combined':
                        intent.update(motion='Idle' if model==0 else 'Motion',motion_index=6 if model==0 else 4,duration_ms=2100 if model==0 else 3533)
                    assert await evaluate('__eyeStage().preparePreview('+json.dumps(intent)+',()=>true)')
                    await evaluate('__eyePreviewComponent.props.mouthOpen='+('.7' if label=='combined' else '0'))
                    await asyncio.sleep(.35 if combo else 1.2)
                    await evaluate('__coreEyes.rows=[]')
                    await asyncio.sleep(duration)
                    values = await evaluate('__coreEyes.rows')
                    assert values
                    left = [v['left'] for v in values]
                    right = [v['right'] for v in values]
                    frame = await evaluate('__eyeStage().capturePreview(true)')
                    file = out/f'{role}-{label}.png'
                    file.write_bytes(base64.b64decode(frame.split(',')[1]))
                    closed = max(left+right) <= (.56 if role=='hiyori' else .01)
                    blinking = min(left+right)<.25 and max(left+right)>.8
                    mouth = [v['mouth'] for v in values]
                    passed = (closed and min(mouth)>.69 and max(mouth)<.71) if label=='combined' else (max(mouth)<.01 if combo else (closed if label=='expression' else blinking))
                    row = {'role':role,'phase':label,'expression':name,'frames':len(values),
                           'sampleSeconds':duration,'leftRange':[min(left),max(left)],
                           'rightRange':[min(right),max(right)],'frame':str(file),
                           'mouthRange':[min(mouth),max(mouth)],'passed':passed}
                    rows.append(row)
                    print(row,flush=True)
                    assert row['passed'],row
        finally:
            await evaluate("Live2DCubismCore.Model.prototype.update=__coreEyes.original;delete window.__coreEyes;__eyeStage()?.cancelPerformance();__eyeStage()?.applyAvatarIntent({expression:''});if(window.__eyePreviewComponent)__eyePreviewComponent.props.mouthOpen=0;delete window.__eyePreviewComponent;delete window.__eyeStage")
            await evaluate('document.querySelectorAll(".model-tile")[1].click()')
            (out/'result.json').write_text(json.dumps({'scope':'actual native Cubism Model.update boundary parameter values, local preview only, no microphone or service calls; combo uses synthetic mouth prop, not real speech', 'combo':combo,'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
        return rows
    await connect(dev,inspect)


if __name__ == '__main__':
    asyncio.run(main())
