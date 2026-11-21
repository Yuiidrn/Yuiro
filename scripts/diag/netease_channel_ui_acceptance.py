"""真实 API 数据 + 受控卡片投影；DOM 点击验证，不冒充真实 Agent/鼠标/音频验收。"""
import asyncio
import json
import sys

from c0_live_acceptance import ROOT, Page, PET, DEV, pages
from c0_live_scenarios import switch

sys.path.insert(0, str(ROOT / 'engine'))
from yuiro.tools.netease_tool import NeteaseSearchTool


async def main():
    result = json.loads(await NeteaseSearchTool().run({'keyword': 'Monody TheFatRat', 'limit': 8}, 'channel-ui-audit'))
    original = next(x for x in result['items'] if str(x.get('song_id')) == '36308916')
    assert original['availability'] == 'api_unavailable'
    report = {'mode': 'real API; controlled card projection; DOM click; media sends intercepted', 'roles': []}
    async with Page(next(p for p in await pages() if p['title'] == 'Yuiro')) as pet:
        await pet.evaluate("window.yuiro.openDev('settings')")
        for _ in range(50):
            info = await pages()
            if any('dev.html' in p['url'] for p in info):
                break
            await asyncio.sleep(.1)
        async with Page(next(p for p in info if 'dev.html' in p['url'])) as dev:
            for _ in range(100):
                if await dev.evaluate('(()=>{'+DEV+'return !!s?.character?.active_id&&!s.loading;})()'):
                    break
                await asyncio.sleep(.1)
            initial = await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
            try:
                old_key = None
                for role in ('hiyori', 'hotaru', 'hiyori'):
                    await switch(pet, dev, role)
                    assert await pet.evaluate('(()=>{'+PET+'return app.resultCard===null;})()')
                    await pet.evaluate('(()=>{'+PET+"window.__musicSends=[];window.__musicSocket=app.socket;window.__musicSend=app.socket.send;app.socket.send=function(s){window.__musicSends.push(JSON.parse(s).type)};app.resultCard="+json.dumps({'title':'Monody 通道验证','kind':'song','items':[original]}, ensure_ascii=False)+';return true;})()')
                    for _ in range(70):
                        card_info = next((p for p in await pages() if p['title'] == 'Yuiro 结果'), None)
                        if card_info:
                            break
                        await asyncio.sleep(.1)
                    assert card_info, '结果窗口未就绪'
                    async with Page(card_info) as card:
                        if old_key:
                            await card.evaluate('window.yuiro.detachedAction('+json.dumps({'kind':'results','key':old_key,'index':0,'action':'open_official'})+')')
                        for _ in range(60):
                            state = await card.evaluate("(()=>{const q=[...document.querySelectorAll('*')].find(e=>e.__vueParentComponent?.setupState.state)?.__vueParentComponent.setupState;return {key:q?.state?.key,note:document.querySelector('.rc-rights')?.textContent,official:document.querySelector('.rc-official')?.textContent};})()")
                            if state.get('official'):
                                break
                            await asyncio.sleep(.1)
                        # 点击真实歌曲行；不可播时不得发送 media:play，也不得清掉卡片。
                        await card.evaluate("document.querySelector('.rc-item').click()")
                        await asyncio.sleep(.2)
                        check = await pet.evaluate('(()=>{'+PET+'return {card:!!app.resultCard,sends:window.__musicSends};})()')
                        assert check['card'] and check['sends'] == [], check
                        assert state['official'] == '打开官方歌曲页'
                        report['roles'].append({'role':role,'unavailable_click_no_play':True,'card_retained':True,'official_button':True,'stale_action_tested':bool(old_key)})
                        old_key = state['key']
                    # 保留卡片进入下一次角色切换，实测切换负责清理，不能由脚本提前清卡。
                    await pet.evaluate('(()=>{'+PET+'window.__musicSocket.send=window.__musicSend;app.hideSpeech();return true;})()')
            finally:
                await pet.evaluate('(()=>{'+PET+'if(window.__musicSocket&&window.__musicSend)window.__musicSocket.send=window.__musicSend;app.clearResultCard();app.hideSpeech();return true;})()')
                await switch(pet, dev, initial)
    (ROOT/'docs/plan/netease-client-artifacts/frontend-channel.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
