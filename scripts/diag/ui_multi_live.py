"""Real Agent responses/searches, native model drag, three detached windows.

No fake results or playback. Long reply is redisplayed after TTS for geometry
measurement. Restores display preferences, role, model layout and mouse.
"""
import asyncio
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
import time

from c0_live_acceptance import ROOT, PET, DEV, Page, pages
from c0_live_scenarios import switch
from ui_customization_acceptance import PANEL, KEYS, restore, until
from detached_edges import MI, overlap

OUT=ROOT/'docs/plan/ui-multi-artifacts/live.json'

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--role',choices=['hiyori','hotaru'])
    parser.add_argument('--stress-long',action='store_true',help='Explicit, labeled typography sample if the real answer is short')
    args=parser.parse_args()
    global OUT
    if args.role:OUT=ROOT/f'docs/plan/ui-multi-artifacts/{args.role}-stress.json'
    user=c.windll.user32
    user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    user.FindWindowW.restype=w.HWND
    user.MonitorFromWindow.restype=w.HANDLE
    titles=['Yuiro 回复','Yuiro 结果','Yuiro 来源']
    def rect(title):
        h=user.FindWindowW(None,title);r=w.RECT()
        assert h and user.GetWindowRect(h,c.byref(r)),title
        return dict(x=r.left,y=r.top,width=r.right-r.left,height=r.bottom-r.top)
    def move(x,y):
        assert user.SetWindowPos(user.FindWindowW(None,'Yuiro'),0,round(x),round(y),0,0,0x15)
    def save():
        OUT.parent.mkdir(parents=True,exist_ok=True)
        OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    info=await pages()
    async with Page(next(p for p in info if p['title']=='Yuiro')) as pet,Page(next(p for p in info if 'dev.html' in p['url'])) as dev:
        await dev.evaluate('(()=>{'+DEV+"d.switchTab('ui');return true;})()")
        await until(dev,'(()=>{'+PANEL+'return !!panel?.settings;})()')
        original_role=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
        web_on=await pet.evaluate('(()=>{'+PET+'return app.webSearchOn;})()')
        backup=await dev.evaluate('Object.fromEntries('+json.dumps(KEYS+['yuiro-fade-on-hover-enabled'])+'.map(k=>[k,localStorage.getItem(k)]))')
        layout=await pet.evaluate('window.yuiro.getPetLayout()')
        original=rect('Yuiro');cursor=w.POINT();user.GetCursorPos(c.byref(cursor))
        mi=MI();mi.size=c.sizeof(mi)
        assert user.GetMonitorInfoW(user.MonitorFromWindow(user.FindWindowW(None,'Yuiro'),2),c.byref(mi))
        area=dict(x=mi.work.left,y=mi.work.top,width=mi.work.right-mi.work.left,height=mi.work.bottom-mi.work.top)
        report={'kind':'real Agent LLM + netease_search + web search; native geometry/drag; no music playback','work_area_physical':area,'roles':[]}
        async def geometry(label):
            await asyncio.sleep(.6)
            b=rect('Yuiro')
            m=await pet.evaluate('(()=>{'+PET+'const r=v.modelRect;return {x:r.left,y:r.top,width:r.width,height:r.height,vw:innerWidth,vh:innerHeight};})()')
            sx=b['width']/m['vw'];sy=b['height']/m['vh']
            anchor=dict(x=b['x']+max(0,m['x'])*sx,y=b['y']+max(0,m['y'])*sy,width=(min(m['vw'],m['x']+m['width'])-max(0,m['x']))*sx,height=(min(m['vh'],m['y']+m['height'])-max(0,m['y']))*sy)
            panels=[]
            for title in titles:
                assert user.IsWindowVisible(user.FindWindowW(None,title)),(label,title,'hidden')
                r=rect(title)
                assert not overlap(r,anchor),(label,title,'covers model',r,anchor)
                assert all(not overlap(r,o) for o in panels),(label,'panels overlap')
                assert r['x']>=area['x']-1 and r['y']>=area['y']-1 and r['x']+r['width']<=area['x']+area['width']+1 and r['y']+r['height']<=area['y']+area['height']+1,(label,'off screen',r)
                panels.append(r)
            return dict(case=label,pet=b,model=anchor,panels=panels,no_overlap=True)
        try:
            await dev.evaluate('(()=>{'+PANEL+"panel.settings.results.seconds=0;panel.settings.source.seconds=0;return true;})()")
            await dev.evaluate("localStorage.setItem('yuiro-fade-on-hover-enabled','false')")
            for role in ([args.role] if args.role else ['hiyori','hotaru']):
                # New isolated session even if the requested role was already active.
                await switch(pet,dev,'hotaru' if role=='hiyori' else 'hiyori')
                await switch(pet,dev,role)
                assert await pet.evaluate('(()=>{'+PET+'return !app.resultCard&&!app.sourceCard&&!app.speechVisible;})()'),'old role content'
                row={'role':role,'geometry':[]};report['roles'].append(row);save()
                await pet.evaluate('(()=>{'+PET+"window.__multi={types:[],tools:[],reply:''};const ws=app.socket;const fn=e=>{const m=JSON.parse(e.data);__multi.types.push(m.type);if(m.type==='tool:call'||m.type==='tool:start')__multi.tools.push(m.name??m.tool);if(m.type==='chat:assistant')__multi.reply=String(m.text??'')};ws.addEventListener('message',fn);window.__multiOff=()=>ws.removeEventListener('message',fn);return true;})()")
                query='这是一次桌面界面验收。请在这一轮实际调用 netease_search 搜索 TheFatRat Monody，返回可点击选歌候选（只搜索，不播放）；再调用联网检索查找 Electron 官方 BrowserWindow 文档，展示可点击来源卡。两个检索都要执行。最后写至少700字中文，分段说明这两个检索分别得到什么、桌宠如何同时展示长回复、歌曲选项与来源，避免工具结果中的网址进入朗读正文。'
                await pet.evaluate('(()=>{'+PET+'app.webSearchOn=true;app.sendText('+json.dumps(query,ensure_ascii=False)+');return true;})()')
                start=time.monotonic()
                await until(pet,'(()=>{'+PET+'return !!app.resultCard&&!!app.sourceCard&&window.__multi.reply.length>0;})()',90)
                row['original_reply_chars']=await pet.evaluate('__multi.reply.length')
                if args.stress_long and row['original_reply_chars']<600:
                    await pet.evaluate('(()=>{'+PET+'const paragraph=__multi.reply+"\\n"+app.sourceCard.items.map(i=>i.title+"："+(i.snippet??"")).join("\\n");__multi.reply="【排版压力样本：本角色实际回复与检索内容重复展开，不是新生成的回答】\\n"+Array(8).fill(paragraph).join("\\n\\n");return true;})()')
                    row['long_reply_mode']='explicit typography stress sample from same-role real search/reply'
                elif row['original_reply_chars']<600:
                    # Persona may answer briefly. Keep the real source result from
                    # this same role/session for a separate genuine long response.
                    await pet.evaluate('(()=>{'+PET+'const saved=JSON.parse(JSON.stringify(app.sourceCard));const ws=app.socket;const fn=e=>{const m=JSON.parse(e.data);if(m.type==="chat:assistant"){app.sourceCard=saved;ws.removeEventListener("message",fn)}};ws.addEventListener("message",fn);__multi.reply="";app.sendText("请写一篇至少800字的中文文章，详细讨论桌面角色的自然陪伴、长文字排版、音乐选择与资料核验四个方面。分成八段，每段至少100字；这轮不用再次检索，不播放音乐。这是长回复滚动验收，请输出完整正文，不要只说开始。");return true;})()')
                    await until(pet,'(()=>{'+PET+'return !!app.sourceCard&&__multi.reply.length>600;})()',90)
                    row['source_retained_for_followup']=True
                else:row['long_reply_mode']='real LLM response'
                row['real_response_seconds']=round(time.monotonic()-start,2)
                data=await pet.evaluate('(()=>{'+PET+'return {reply_chars:__multi.reply.length,song_count:app.resultCard.items.length,source_count:app.sourceCard.items.length,types:[...new Set(__multi.types)],song_ids:app.resultCard.items.map(i=>String(i.song_id??""))};})()')
                row.update(data);save()
                # Hold the actual received response for reproducible long-content layout checks.
                await pet.evaluate('(()=>{'+PET+'app.showSpeech(__multi.reply);app.clearSpeechTimers();return true;})()')
                size=rect('Yuiro')
                move(area['x']+(area['width']-size['width'])/2,area['y']+(area['height']-size['height'])/2)
                row['geometry'].append(await geometry('center'))
                for corner in ['left-top','right-top','left-bottom','right-bottom']:
                    move(area['x']+8 if corner.startswith('left') else area['x']+area['width']-size['width']-8,area['y']+8 if corner.endswith('top') else area['y']+area['height']-size['height']-8)
                    row['geometry'].append(await geometry(corner))
                move(area['x']+(area['width']-size['width'])/2,area['y']+(area['height']-size['height'])/2)
                before=await geometry('before-drag')
                point=await pet.evaluate('(()=>{'+PET+'app.closeMenu();const m=v.contour,r=v.modelRect;let p=null,best=Infinity;for(let j=0;j<m.height;j++)for(let i=0;i<m.width;i++){const x=m.left+(i+.5)*m.cssWidth/m.width,y=m.top+(j+.5)*m.cssHeight/m.height;if(m.alpha[j*m.width+i]>240&&x>20&&y>20&&x<innerWidth-20&&y<innerHeight-20&&!document.elementsFromPoint(x,y).some(e=>e.closest("button,input,.bm-icon,.panel"))){const d=Math.hypot(x-r.left-r.width/2,y-r.top-r.height*.7);if(d<best){best=d;p={x,y,vw:innerWidth,vh:innerHeight}}}}return p;})()')
                assert point
                b=rect('Yuiro');x=round(b['x']+point['x']*b['width']/point['vw']);y=round(b['y']+point['y']*b['height']/point['vh'])
                assert user.SetCursorPos(x,y),'input desktop unavailable'
                await asyncio.sleep(.15)
                user.mouse_event(2,0,0,0,0)
                try:
                    for i in range(1,9):
                        user.SetCursorPos(x+i*9,y+i*3);await asyncio.sleep(.05)
                finally:user.mouse_event(4,0,0,0,0)
                after=await geometry('after-drag');dx=after['pet']['x']-before['pet']['x'];dy=after['pet']['y']-before['pet']['y']
                assert abs(dx)>30,('native drag failed',dx)
                row['native_drag_delta']=[dx,dy]
                row['panel_drag_deltas']=[[b['x']-a['x'],b['y']-a['y']] for a,b in zip(before['panels'],after['panels'])]
                row['geometry'].extend([before,after])
                # Read actual renderers, scroll long panels, then hot-update through real controls.
                infos=await pages()
                async with Page(next(p for p in infos if p['title']=='Yuiro 回复')) as reply,Page(next(p for p in infos if p['title']=='Yuiro 来源')) as source:
                    row['long_reply_scroll']=await reply.evaluate('(()=>{const e=document.querySelector(".reply-surface");e.scrollTop=e.scrollHeight;return {scrollHeight:e.scrollHeight,clientHeight:e.clientHeight,scrollTop:e.scrollTop};})()')
                    assert row['long_reply_scroll']['scrollTop']>0
                    start=time.monotonic()
                    await dev.evaluate('(()=>{'+PANEL+"panel.kind='speech';return true;})()")
                    await dev.evaluate("(()=>{const e=document.querySelector('input[aria-label=\"回复字号数值\"]');e.value='20';e.dispatchEvent(new Event('change',{bubbles:true}));return true;})()")
                    await until(reply,"getComputedStyle(document.querySelector('.reply-surface')).fontSize==='20px'")
                    row['hot_update_ms']=round((time.monotonic()-start)*1000)
                    await dev.evaluate('(()=>{'+PANEL+'panel.settings.source.independent=true;panel.settings.source.width=280;panel.settings.source.fontSize=16;panel.settings.source.summaryLines=2;panel.settings.source.maxHeight=240;panel.settings.speech.maxHeight=320;panel.settings.results.maxHeight=320;return true;})()')
                    await until(source,"getComputedStyle(document.querySelector('.result-card')).fontSize==='16px'")
                    row['geometry'].append(await geometry('after-hot-update'))
                # Real native close click only dismisses sources, keeps reply and song selection.
                info=next(p for p in await pages() if p['title']=='Yuiro 来源')
                async with Page(info) as source:
                    p=await source.evaluate('(()=>{const r=document.querySelector(".close").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,vw:innerWidth,vh:innerHeight};})()')
                b=rect('Yuiro 来源');assert user.SetCursorPos(round(b['x']+p['x']*b['width']/p['vw']),round(b['y']+p['y']*b['height']/p['vh']))
                await asyncio.sleep(.1);user.mouse_event(2,0,0,0,0);user.mouse_event(4,0,0,0,0)
                await until(pet,'(()=>{'+PET+'return !app.sourceCard&&!!app.resultCard&&app.speechVisible;})()')
                row['independent_native_dismiss']=True
                await pet.evaluate('window.__multiOff?.()');save()
            await switch(pet,dev,original_role)
            await pet.evaluate('(()=>{'+PET+'app.webSearchOn='+json.dumps(web_on)+';return true;})()')
            assert await pet.evaluate('(()=>{'+PET+'return !app.sourceCard&&!app.resultCard&&!app.speechVisible;})()')
            report['role_switch_cleanup']=True
        finally:
            await pet.evaluate('(()=>{'+PET+'window.__multiOff?.();app.hideSpeech();app.clearResultCard();app.stopPlayback();return true;})()')
            await switch(pet,dev,original_role)
            await pet.evaluate('(()=>{'+PET+'app.webSearchOn='+json.dumps(web_on)+';return true;})()')
            await restore(dev,backup)
            await pet.evaluate('window.yuiro.setPetLayout('+json.dumps(layout)+',false)')
            move(original['x'],original['y']);user.SetCursorPos(cursor.x,cursor.y)
            report['preferences_restored']=await dev.evaluate('Object.fromEntries('+json.dumps(list(backup))+'.map(k=>[k,localStorage.getItem(k)]))')==backup
            save()
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':asyncio.run(main())
