"""真实构建预览的重叠意图/取消/换模型回归，不开启麦克风。"""
import asyncio
import json
from pathlib import Path

from appearance_thumbnails_live import connect, pages


async def main():
    async def run(call, evaluate):
        assert not await evaluate("document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('devConfig').hasDraftChanges")
        await call('Page.reload')
        await asyncio.sleep(2)
        await evaluate('[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="外观").click()')
        await asyncio.sleep(1)
        await evaluate("""window.__overlapStage=()=>{const seen=new Set();function f(v){
          if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
          if(v.component?.type.__name==='Live2DCanvas'&&v.component.props.preview)return v.component.exposed;
          return f(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(f).find(Boolean):null)}
          return f(document.querySelector('#app')._vnode)}""")
        rows = []

        async def model(index):
            await evaluate(f'document.querySelectorAll(".model-tile")[{index}].click()')
            for _ in range(100):
                if await evaluate('!!__overlapStage()&&!document.querySelector(".stage-loading")'):
                    break
                await asyncio.sleep(.2)
            else:
                raise RuntimeError('Model preview timeout')
            await evaluate('[...document.querySelectorAll(".studio-tabs button")].find(x=>x.textContent.trim()==="互动节奏").click()')

        async def apply(intent):
            await evaluate('__overlapStage().applyAvatarIntent('+json.dumps(intent)+')')

        async def state():
            return await evaluate('__overlapStage().getAvatarState()')

        try:
            for index, role, smile in [(0, 'hiyori', 'happy'), (1, 'hotaru', 'exp_bsmile01')]:
                await model(index)
                expressions = await evaluate('__overlapStage().listExpressions()')
                assert smile in expressions
                base = next(e for e in expressions if e != smile)
                await apply({'expression': '', 'priority': 5})
                await apply({'expression': smile, 'duration_ms': 1200, 'priority': 4})
                await asyncio.sleep(.1)
                held = await state()
                await apply({'expression': base, 'priority': 1})
                deferred = await state()
                assert deferred['expression'] == smile and deferred['until'] == held['until']
                await asyncio.sleep(1.4)
                released = await state()
                assert released['expression'] == base and released['until'] == 0
                await apply({'expression': smile, 'duration_ms': 1200, 'priority': 4})
                await evaluate('__overlapStage().cancelPerformance()')
                cancelled = await state()
                assert cancelled['expression'] == base and cancelled['until'] == 0
                await asyncio.sleep(1.4)
                assert await state() == cancelled, 'Cancelled timer modified settled state'
                rows.append({'role': role, 'scope': 'temporary high priority / deferred base / cancel',
                             'held': held, 'deferred': deferred, 'released': released, 'cancelled': cancelled})
                print(role, 'overlap/cancel passed', flush=True)
            # 旧模型尚未结束的表情计时器，不能重置新模型正在进行的表情。
            await apply({'expression': 'exp_bsmile01', 'duration_ms': 1600, 'priority': 4})
            await model(0)
            await apply({'expression': 'happy', 'duration_ms': 5000, 'priority': 4})
            current = await state()
            await asyncio.sleep(2)
            after = await state()
            assert after == current and after['expression'] == 'happy'
            rows.append({'scope': 'old model release timer cannot reset new model', 'before': current, 'after': after})
            print('cross-model old timer isolation passed', flush=True)
        finally:
            await evaluate("__overlapStage()?.cancelPerformance();__overlapStage()?.applyAvatarIntent({expression:'',priority:5})")
            await model(1)
            await evaluate('delete window.__overlapStage')
        Path('docs/plan/avatar-overlap-live.json').write_text(json.dumps({
            'scope': 'Actual built SDK local preview; state lifecycle and timer isolation. No microphone/cloud, not human naturalness or formal character-service switching.',
            'rows': rows, 'restoredPreview': 'hotaru'}, ensure_ascii=False, indent=2), encoding='utf-8')

    await connect(next(p for p in pages() if 'dev.html' in p['url']), run)


if __name__ == '__main__':
    asyncio.run(main())
