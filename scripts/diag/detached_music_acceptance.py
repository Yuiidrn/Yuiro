"""Real preflight; native song selection. Expired login => explicitly isolated fixture.

Fixture media:play is intercepted before network send, never played on the account.
An available login exercises actual Agent retrieval/playback instead.
"""
import asyncio
import ctypes as c
from ctypes import wintypes as w
import json
import sys
import time
from c0_live_acceptance import PET, DEV, ROOT, Page, pages
from c0_live_scenarios import switch

OUT=ROOT/'docs/plan/detached-ui-artifacts'
sys.path.insert(0,str(ROOT/'engine'))

async def main():
    from yuiro.tools.netease_tool import NeteaseSearchTool
    preflight=json.loads(await asyncio.wait_for(NeteaseSearchTool().run({'keyword':'LIFE','limit':1},'detached-preflight'),25))
    fixture=preflight.get('status')!='ok'
    c.windll.user32.SetProcessDpiAwarenessContext(c.c_void_p(-4))
    user=c.windll.user32
    user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    user.FindWindowW.restype=w.HWND
    cursor=w.POINT();user.GetCursorPos(c.byref(cursor))
    info=await pages()
    report={'kind':'native song selection; fixture status is NOT real playback acceptance','preflight':{'status':preflight.get('status'),'message':preflight.get('message') if fixture else None},'roles':[]}
    async with Page(next(p for p in info if p['title']=='Yuiro')) as pet,Page(next(p for p in info if 'dev.html' in p['url'])) as dev:
        role=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
        fade=await dev.evaluate("localStorage.getItem('yuiro-fade-on-hover-enabled')")
        try:
            await dev.evaluate("localStorage.setItem('yuiro-fade-on-hover-enabled','false')")
            for target in ['hiyori','hotaru']:
                await switch(pet,dev,target)
                await pet.evaluate('(()=>{'+PET+"app.clearResultCard();window.__mediaSent=[];const ws=app.socket,original=ws.send;window.__mediaRestore=()=>{ws.send=original};ws.send=function(data){const m=JSON.parse(data);if(m.type==='media:play'){__mediaSent.push(m);"+('return;' if fixture else '')+"}return original.call(this,data)};return true;})()")
                if fixture:
                    await pet.evaluate('(()=>{'+PET+"app.resultCard={kind:'song',title:'选歌 UI 验收（固定样本，不实际播放）',note:'fixture',items:[{name:'UI 路由验收曲目',artist:'测试样本',song_id:'fixture-song-001',encrypted_id:'fixture-encrypted-001'}]};app.publishDetached();return true;})()")
                else:
                    await pet.evaluate('(()=>{'+PET+"app.sendText('请搜索歌曲 LIFE，列出候选让我点击选择，暂时不要播放。');return true;})()")
                started=time.monotonic();card=None
                while time.monotonic()-started<60:
                    card=await pet.evaluate('(()=>{'+PET+"return app.resultCard&&app.resultCard.kind!=='source'?JSON.parse(JSON.stringify({kind:app.resultCard.kind,count:app.resultCard.items.length,first:app.resultCard.items[0]})):null;})()")
                    if card:break
                    await asyncio.sleep(.2)
                row={'role':target,'fixture':fixture,'real_playback_accepted':False,'card':card}
                if not card:
                    row['status']='blocked: no selectable real Agent result'
                else:
                    await asyncio.sleep(.6)
                    result=next(p for p in await pages() if 'kind=results' in p['url'])
                    async with Page(result) as ui:
                        point=await ui.evaluate("(()=>{const r=document.querySelector('.rc-item').getBoundingClientRect();return{x:r.x+25,y:r.y+r.height/2,w:innerWidth,h:innerHeight}})()")
                        rect=w.RECT();hwnd=user.FindWindowW(None,'Yuiro 结果')
                        assert hwnd and user.IsWindowVisible(hwnd)
                        user.GetWindowRect(hwnd,c.byref(rect))
                        user.SetCursorPos(round(rect.left+point['x']*(rect.right-rect.left)/point['w']),round(rect.top+point['y']*(rect.bottom-rect.top)/point['h']))
                        await asyncio.sleep(.1);user.mouse_event(2,0,0,0,0);user.mouse_event(4,0,0,0,0);await asyncio.sleep(.4)
                        row['sent']=await pet.evaluate('window.__mediaSent')
                        row['card_cleared']=await pet.evaluate('(()=>{'+PET+'return app.resultCard===null;})()')
                        assert row['sent'] and row['card_cleared'],row
                        chosen=card['first'];sent=row['sent'][0]
                        print(json.dumps({'selected':chosen,'sent':sent},ensure_ascii=False),flush=True)
                        assert str(sent.get('song_id'))==str(chosen.get('song_id')) and sent.get('encrypted_id')==chosen.get('encrypted_id')
                        row['status']='native click and exact IDs passed'+('; fixture intercepted before network' if fixture else '; real playback feedback needs human hearing confirmation')
                        if not fixture:
                            await asyncio.sleep(3)
                            await pet.evaluate('(()=>{'+PET+"app.sendText('停止播放音乐');return true;})()")
                await pet.evaluate('window.__mediaRestore?.()')
                report['roles'].append(row)
                OUT.mkdir(parents=True,exist_ok=True)
                (OUT/'music.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(row,ensure_ascii=False),flush=True)
        finally:
            await pet.evaluate('(()=>{'+PET+'window.__mediaRestore?.();app.clearResultCard();app.hideSpeech();return true;})()')
            await switch(pet,dev,role)
            await dev.evaluate('localStorage.'+('removeItem("yuiro-fade-on-hover-enabled")' if fade is None else 'setItem("yuiro-fade-on-hover-enabled",'+json.dumps(fade)+')'))
            user.SetCursorPos(cursor.x,cursor.y)

if __name__=='__main__':asyncio.run(main())
