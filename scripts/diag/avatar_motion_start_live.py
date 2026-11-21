"""构建工作台双角色动作/取消回归；不调用云端或开启麦克风。"""
import argparse
import asyncio
import json
from pathlib import Path

from appearance_thumbnails_live import connect, pages


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='docs/plan/avatar-motion-start-ownership-live.json')
    options = parser.parse_args()
    dev = next(p for p in pages() if 'dev.html' in p['url'])

    async def run(call, evaluate):
        assert not await evaluate("document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('devConfig').hasDraftChanges")
        await call('Page.reload')
        await asyncio.sleep(2)
        await evaluate('[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="外观").click()')
        await asyncio.sleep(1)
        await evaluate("""window.__motionStage=()=>{const seen=new Set();function f(v){
          if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
          if(v.component?.type.__name==='Live2DCanvas'&&v.component.props.preview)return v.component.exposed;
          return f(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(f).find(Boolean):null)}
          return f(document.querySelector('#app')._vnode)}""")
        rows = []
        try:
            for model, role, group, index, duration in [(0, 'hiyori', 'Idle', 7, 1600), (1, 'hotaru', 'Motion', 0, 2000)]:
                await evaluate(f'document.querySelectorAll(".model-tile")[{model}].click()')
                for _ in range(100):
                    if await evaluate('!!__motionStage()&&!document.querySelector(".stage-loading")'):
                        break
                    await asyncio.sleep(.2)
                else:
                    raise RuntimeError('Preview model load timeout')
                await evaluate('[...document.querySelectorAll(".studio-tabs button")].find(x=>x.textContent.trim()==="互动节奏").click()')
                for cancel in [False, True]:
                    intent = {'motion': group, 'motion_index': index, 'duration_ms': duration, 'priority': 3}
                    assert await evaluate('__motionStage().preparePreview('+json.dumps(intent)+',()=>true)')
                    await asyncio.sleep(.25)
                    started = await evaluate('__motionStage().getAvatarState()')
                    assert started['motion'] == group and started['motionIndex'] == index, started
                    if cancel:
                        await evaluate('__motionStage().cancelPerformance()')
                    await asyncio.sleep(duration / 1000 + 1)
                    ended = await evaluate('__motionStage().getAvatarState()')
                    assert ended['motion'] == '' and ended['until'] == 0, ended
                    rows.append({'role': role, 'cancelled': cancel, 'started': started, 'ended': ended})
                    print(role, 'cancel' if cancel else 'finish', 'passed', flush=True)
        finally:
            await evaluate("__motionStage()?.cancelPerformance();delete window.__motionStage")
            await evaluate('document.querySelectorAll(".model-tile")[1].click()')
        Path(options.output).write_text(json.dumps({
            'scope': 'Actual built local preview; normal and explicit-cancel state lifecycle. Deterministic delayed SDK completion covered separately by production-function test; no microphone/cloud/visual rating.',
            'rows': rows, 'restoredPreview': 'hotaru'}, ensure_ascii=False, indent=2), encoding='utf-8')

    await connect(dev, run)


if __name__ == '__main__':
    asyncio.run(main())
