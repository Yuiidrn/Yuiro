"""真实 API 候选投影 + Windows 原生点选 + Engine + 官方客户端；不冒充 LLM 搜索。"""
import asyncio
import ctypes as c
from ctypes import wintypes as w
import json
import sys
import time

from c0_live_acceptance import ROOT, PET, DEV, Page, pages
from c0_live_scenarios import switch
sys.path.insert(0, str(ROOT/'engine'))
from yuiro.native.backend import NativeBackend
from yuiro.tools.netease_tool import NeteaseSearchTool, NeteaseControlTool


async def main():
    result = json.loads(await NeteaseSearchTool().run({'keyword':'Monody TheFatRat','limit':8},'exact-client-acceptance'))
    song = next(x for x in result['items'] if str(x.get('song_id'))=='36308916')
    user = c.windll.user32
    user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    user.FindWindowW.restype=w.HWND
    user.WindowFromPoint.restype=w.HWND
    user.GetAncestor.restype=w.HWND
    report={'candidate_source':'real API; controlled projection, no LLM claim','input':'native Windows mouse', 'roles':[]}
    target=ROOT/'docs/plan/netease-client-artifacts'/('exact-client-cold-roles.json' if '--cold' in sys.argv else 'exact-client-roles.json')
    if '--cold' in sys.argv:
        preflight=await NativeBackend(txn_enabled=False).call('media_control',{'action':'client_state','target':'cloudmusic.exe'})
        assert preflight.status=='ok' and json.loads(preflight.stdout).get('source')=='client_closed'
        report['initial_client_closed']=True
    def save(): target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    async def native_state():
        b=NativeBackend(txn_enabled=False)
        track=await b.call('media_control',{'action':'client_state','target':'cloudmusic.exe'})
        state=await b.call('media_control',{'action':'now_playing','target':'cloudmusic.exe'})
        assert track.status==state.status=='ok',(track.stdout,state.stdout)
        return {**json.loads(track.stdout),'status':json.loads(state.stdout)['status']}
    async def wait_playback(pet, status):
        start=time.monotonic()
        for _ in range(400):
            p=await pet.evaluate('(()=>{'+PET+'return JSON.parse(JSON.stringify({p:app.officialPlayback,busy:app.officialPending}));})()')
            if (p.get('p') or {}).get('status')==status and not p['busy']:
                return p['p'],round((time.monotonic()-start)*1000)
            await asyncio.sleep(.1)
        failure=await pet.evaluate('(()=>{'+PET+'return {playback:app.officialPlayback,pending:app.officialPending,note:app.speechText,events:window.__exactEvents};})()')
        report['failure']=failure;save()
        raise RuntimeError('官方播放状态超时：'+json.dumps(failure,ensure_ascii=False))
    async def click(card, selector):
        for _ in range(60):
            point=await card.evaluate('(()=>{const e=document.querySelector('+json.dumps(selector)+');if(!e||e.disabled)return null;e.scrollIntoView({block:"nearest"});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:innerWidth,h:innerHeight};})()')
            if point:break
            await asyncio.sleep(.1)
        assert point, selector
        hwnd=user.FindWindowW(None,'Yuiro 结果');rect=w.RECT()
        assert hwnd and user.GetWindowRect(hwnd,c.byref(rect))
        x=round(rect.left+point['x']*(rect.right-rect.left)/point['w'])
        y=round(rect.top+point['y']*(rect.bottom-rect.top)/point['h'])
        assert user.SetCursorPos(x,y),'输入桌面不可用'
        await asyncio.sleep(.08)
        hit=user.GetAncestor(user.WindowFromPoint(w.POINT(x,y)),2)
        assert hit==hwnd,'目标位置不属于独立结果卡，未点击'
        user.mouse_event(2,0,0,0,0);user.mouse_event(4,0,0,0,0)
    async with Page(next(p for p in await pages() if p['title']=='Yuiro')) as pet:
        await pet.evaluate("window.yuiro.openDev('settings')")
        for _ in range(100):
            dev_info=next((p for p in await pages() if 'dev.html' in p['url']),None)
            if dev_info:break
            await asyncio.sleep(.1)
        async with Page(dev_info) as dev:
            for _ in range(200):
                if await dev.evaluate('(()=>{'+DEV+'return !!s?.character?.active_id&&!s.loading;})()'):break
                await asyncio.sleep(.1)
            initial=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
            await switch(pet,dev,'hotaru' if initial=='hiyori' else 'hiyori')
            await switch(pet,dev,initial)
            old_key=None
            try:
                for role, following in [('hiyori','hotaru'),('hotaru','hiyori')]:
                    await switch(pet,dev,role)
                    assert await pet.evaluate('(()=>{'+PET+'return !app.resultCard&&!app.officialPlayback;})()')
                    await pet.evaluate('(()=>{'+PET+'window.__exactEvents=[];app.socket.addEventListener("message",e=>{const m=JSON.parse(e.data);if(m.type==="media:state")window.__exactEvents.push(m)});app.resultCard='+json.dumps({'title':'Monody 原版播放器选择','kind':'song','items':[song],'note':''},ensure_ascii=False)+';return true;})()')
                    for _ in range(80):
                        card_info=next((p for p in await pages() if p['title']=='Yuiro 结果'),None)
                        if card_info:break
                        await asyncio.sleep(.1)
                    async with Page(card_info) as card:
                        if old_key:
                            await card.evaluate('window.yuiro.detachedAction('+json.dumps({'kind':'results','key':old_key,'action':'client_resume'})+')')
                            await asyncio.sleep(.2)
                            assert (await native_state())['status']=='Paused'
                        started=time.monotonic()
                        await click(card,'.rc-client')
                        playback,_=await wait_playback(pet,'playing')
                        elapsed=round((time.monotonic()-started)*1000)
                        real=await native_state()
                        assert real['song_id']=='36308916' and real['status']=='Playing' and not real['preview']
                        # 自管 Stop 不得控制已显式归属官方客户端的音乐。
                        await NeteaseControlTool().run({'action':'stop'},'exact-client-builtin-stop-check')
                        assert (await native_state())['status']=='Playing'
                        assert await card.evaluate("document.querySelector('.rc-control').textContent.trim()==='暂停'")
                        await click(card,'.rc-control');await wait_playback(pet,'paused')
                        assert (await native_state())['status']=='Paused'
                        await click(card,'.rc-control');await wait_playback(pet,'playing')
                        assert (await native_state())['status']=='Playing'
                        old_key=await card.evaluate("[...document.querySelectorAll('*')].find(e=>e.__vueParentComponent?.setupState.state)?.__vueParentComponent.setupState.state.key")
                        old_identity=await pet.evaluate('(()=>{'+PET+'return {character_id:app.activeCharacter,character_revision:app.characterRevision,session_id:app.sessionId};})()')
                        started=time.monotonic();await switch(pet,dev,following)
                        switch_ms=round((time.monotonic()-started)*1000)
                        assert (await native_state())['status']=='Paused'
                        assert await pet.evaluate('(()=>{'+PET+'return !app.resultCard&&!app.officialPlayback;})()')
                        stale={**old_identity,'type':'media:control','backend':'netease_client','action':'resume','playback_id':playback['playback_id'],'request_id':-100}
                        await pet.evaluate('(()=>{'+PET+'app.socket.send('+json.dumps(json.dumps(stale))+');return true;})()')
                        await asyncio.sleep(.5)
                        assert (await native_state())['status']=='Paused'
                        report['roles'].append({'role':role,'song_id':real['song_id'],'native_pick_ms':elapsed,'play_pause_resume':True,'builtin_stop_did_not_control_client':True,'switch_to':following,'switch_ms':switch_ms,'switch_paused_owned_song':True,'switch_cleared_card_and_owner':True,'stale_ws_control_refused':True,'old_detached_key_tested':bool(len(report['roles']))})
                        save()
                        print(json.dumps(report['roles'][-1],ensure_ascii=False),flush=True)
            finally:
                await switch(pet,dev,'hotaru' if initial=='hiyori' else 'hiyori')
                await switch(pet,dev,initial)
    save()


if __name__=='__main__':asyncio.run(main())
