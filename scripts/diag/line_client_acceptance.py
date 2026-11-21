"""单曲线真实模型 UI + Agent 客户端搜索/选歌/暂停。无检索/播放 mock。"""
import asyncio
import argparse
import base64
import ctypes as c
from ctypes import wintypes as w
import json
import sys
import time
from c0_live_acceptance import ROOT,PET,DEV,Page,pages
from c0_live_scenarios import switch
from ui_customization_acceptance import PANEL,KEYS,restore,until
from ui_comic_acceptance import SCENE

sys.path.insert(0,str(ROOT/'engine'))
from yuiro.netease import official_client as client

OUT=ROOT/'docs/plan/line-client-artifacts'

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--direct',action='store_true');parser.add_argument('--ui-only',action='store_true');parser.add_argument('--role',choices=['hiyori','hotaru']);parser.add_argument('--search-only',action='store_true');args=parser.parse_args()
    baseline=await client._read()
    assert baseline.get('status')=='paused','当前网易云正在播放：不替换用户音乐'
    report={'kind':'real Live2D/native connector + real Agent -> client UI search -> card -> official playback/pause','baseline_paused':True,'roles':[]}
    if args.direct:report['kind']='real Live2D/native connector + explicit /搜歌 UI -> client UI search -> card -> official playback/pause; LLM not used'
    if args.ui_only:report['kind']='real dual-model line UI only; no music or LLM calls'
    receipt='ui-line.json' if args.ui_only else 'live.json'
    if args.role and not args.direct and not args.ui_only:receipt=f'agent-{args.role}.json'
    OUT.mkdir(parents=True,exist_ok=True)
    u=c.windll.user32;u.FindWindowW.restype=w.HWND
    ps=await pages()
    async with Page(next(p for p in ps if p['title']=='Yuiro')) as pet:
        await pet.evaluate("window.yuiro.openDev('settings')")
        info=next(p for p in await pages() if 'dev.html' in p['url'])
        async with Page(info) as dev:
            await until(dev,'(()=>{'+DEV+'return !!s?.character?.active_id&&!s.loading;})()')
            await dev.evaluate('(async()=>{'+DEV+'await s.load();d.switchTab("ui");return true;})()')
            await until(dev,'(()=>{'+PANEL+'return !!panel?.settings;})()')
            role=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
            backup=await dev.evaluate('Object.fromEntries('+json.dumps(KEYS)+'.map(k=>[k,localStorage.getItem(k)]))')
            try:
                for target in ([args.role] if args.role else ['hiyori','hotaru']):
                    await switch(pet,dev,'hotaru' if target=='hiyori' else 'hiyori')
                    await switch(pet,dev,target)
                    await dev.evaluate('(()=>{'+PANEL+'panel.linePreset(false);panel.settings.results.seconds=0;return true;})()')
                    await pet.evaluate('(()=>{'+PET+'app.showSpeech("单曲线对白验收。\\n只有文字和一条柔和的曲线。");app.clearSpeechTimers();return true;})()')
                    await until(pet,'(()=>{'+PET+'return app.speechVisible;})()')
                    await asyncio.sleep(.6)
                    for _ in range(100):
                        ps=await pages()
                        if any(p['title']=='Yuiro 对白曲线' for p in ps) and any(p['title']=='Yuiro 回复' for p in ps):break
                        await asyncio.sleep(.1)
                    async with Page(next(p for p in ps if p['title']=='Yuiro 回复')) as reply,Page(next(p for p in ps if p['title']=='Yuiro 对白曲线')) as line:
                        await until(line,'!!document.querySelector("svg path")')
                        check=await reply.evaluate('(()=>{const e=document.querySelector(".reply-surface"),s=getComputedStyle(e);return {background:s.backgroundColor,border:s.borderTopWidth,closedTail:!!document.querySelector(".reply-tail")};})()')
                        path=await line.evaluate('(()=>{const p=document.querySelector("path");return {count:document.querySelectorAll("path").length,fill:p.getAttribute("fill"),d:p.getAttribute("d")};})()')
                        assert check['background']=='rgba(0, 0, 0, 0)' and check['border']=='0px' and not check['closedTail']
                        assert path['count']==1 and path['fill']=='none' and 'Z' not in path['d'].upper()
                        hwnd=u.FindWindowW(None,'Yuiro 对白曲线');ex=u.GetWindowLongW(hwnd,-20)
                        assert ex&0x20,'connector must always pass clicks through'
                        await dev.evaluate('(()=>{'+PANEL+'panel.settings.speech.ink="#123456";panel.settings.speech.lineColor="#abcdef";panel.settings.speech.lineWidth=2.3;panel.settings.speech.font="hand";panel.settings.speech.weight=700;panel.settings.speech.tracking=1.5;return true;})()')
                        await until(reply,'getComputedStyle(document.querySelector(".reply-surface")).color==="rgb(18, 52, 86)"')
                        await until(line,'document.querySelector("path").getAttribute("stroke")==="#abcdef"')
                        compact=await line.evaluate('document.querySelector("path").getTotalLength()')
                        await dev.evaluate('(()=>{'+PANEL+'panel.settings.speech.lineRise=180;panel.settings.speech.lineBend=.7;return true;})()')
                        await until(line,'document.querySelector("path").getTotalLength()>'+str(compact+20))
                        extended=await line.evaluate('document.querySelector("path").getTotalLength()')
                        await dev.evaluate('(()=>{'+PANEL+'panel.settings.speech.lineRise=40;panel.settings.speech.lineBend=.25;return true;})()')
                        await dev.evaluate('(()=>{'+PANEL+'panel.settings.speech.mode="bubble";return true;})()')
                        await asyncio.sleep(.2);assert not u.IsWindowVisible(hwnd)
                        await dev.evaluate('(()=>{'+PANEL+'panel.linePreset(false);return true;})()')
                        await asyncio.sleep(.3);assert u.IsWindowVisible(hwnd)
                    await dev.evaluate('(()=>{'+SCENE+'scene.enabled=true;scene.island=false;return true;})()')
                    await dev.evaluate('(()=>{'+PANEL+'panel.text="今天也在这里陪着你。\\n\\n让文字轻轻落在留白里，\\n一条曲线，连起你的视线与我的回应。";panel.settings.speech.weight=400;panel.settings.speech.tracking=0;return true;})()')
                    await until(dev,'(()=>{'+SCENE+'return scene.canvas?.getModelRect?.()&&scene.placement&&scene.curve;})()',30)
                    await dev.evaluate('document.querySelector(".ui-scene").scrollIntoView({block:"center"})')
                    await asyncio.sleep(.3)
                    clip=await dev.evaluate('(()=>{const r=document.querySelector(".ui-scene").getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()')
                    shot=await dev.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':clip})
                    (OUT/f'line-{target}.png').write_bytes(base64.b64decode(shot['data']))
                    await dev.evaluate('(()=>{'+SCENE+'scene.enabled=false;return true;})()')
                    row={'role':target,'line_no_background':True,'one_open_curve':True,'curve_click_through':True,'typography_hot_update':True,'mode_switch':True,'curve_compact_length':round(compact,1),'curve_extended_length':round(extended,1),'distance_curvature_hot_update':True}
                    report['roles'].append(row)
                    if args.ui_only:continue
                    query='/搜歌 Monody' if args.direct else '请调用 netease_search 在网易云官方客户端内搜索 Monody，只显示候选供我点击，不要播放，不调用其他音乐工具。'
                    await pet.evaluate('(()=>{'+PET+'window.__clientCase={events:[],sent:[]};const ws=app.socket,send=ws.send;const listener=e=>{const m=JSON.parse(e.data);if(m.type==="agent:result"||m.type==="media:state"||m.type==="media:search-result")__clientCase.events.push(m)};ws.addEventListener("message",listener);ws.send=function(x){const m=JSON.parse(x);if(m.type.startsWith("media:"))__clientCase.sent.push({type:m.type,backend:m.backend,song_id:m.song_id});return send.call(this,x)};window.__clientOff=()=>{ws.send=send;ws.removeEventListener("message",listener)};app.clearResultCard();app.sendText('+json.dumps(query,ensure_ascii=False)+');return true;})()')
                    start=time.monotonic()
                    await until(pet,'(()=>{'+PET+'return app.resultCard?.items?.some(i=>String(i.song_id)==="36308916")&&app.resultCard.items.every(i=>i.source==="netease_client_ui");})()',100)
                    row['search_seconds' if args.direct else 'agent_search_seconds']=round(time.monotonic()-start,2)
                    row['candidates']=await pet.evaluate('(()=>{'+PET+'return JSON.parse(JSON.stringify(app.resultCard.items));})()')
                    if args.search_only:
                        row['real_agent_search']=not args.direct
                        await pet.evaluate('window.__clientOff?.()')
                        continue
                    info=None
                    for _ in range(80):
                        info=next((p for p in await pages() if p['title']=='Yuiro 结果'),None)
                        if info:break
                        await asyncio.sleep(.1)
                    assert info,'result renderer did not become ready'
                    async with Page(info) as card:
                        await until(card,'!!document.querySelector(".rc-client")')
                        # Original ID only, never choose the first approximate/Remix row.
                        index=next(i for i,it in enumerate(row['candidates']) if str(it['song_id'])=='36308916')
                        await card.evaluate('(()=>{const e=document.querySelectorAll(".rc-item")['+str(index)+'];e.scrollIntoView({block:"nearest"});e.querySelector(".rc-client").click();return true;})()')
                        await until(pet,'(()=>{'+PET+'return app.officialPlayback?.song_id==="36308916"&&app.officialPlayback.status==="playing";})()',45)
                        row['playing_original']=True
                        await card.evaluate('document.querySelector(".rc-control").click()')
                        await until(pet,'(()=>{'+PET+'return app.officialPlayback?.status==="paused";})()',15)
                        row['paused']=True
                    sent=await pet.evaluate('__clientCase.sent')
                    assert any(s.get('backend')=='netease_client' and s.get('song_id')=='36308916' for s in sent),sent
                    assert not any(s.get('backend')=='builtin' for s in sent)
                    row['no_builtin_playback']=True
                    await pet.evaluate('window.__clientOff?.()')
                    (OUT/receipt).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                await switch(pet,dev,'hotaru' if role=='hiyori' else 'hiyori')
                await switch(pet,dev,role)
                await asyncio.sleep(.3)
                assert not u.IsWindowVisible(u.FindWindowW(None,'Yuiro 对白曲线'))
                assert await pet.evaluate('(()=>{'+PET+'return !app.resultCard&&!app.speechVisible;})()')
                report['role_cleanup']=True
            finally:
                await switch(pet,dev,'hotaru' if role=='hiyori' else 'hiyori')
                await switch(pet,dev,role)
                await pet.evaluate('(()=>{'+PET+'window.__clientOff?.();app.hideSpeech();app.clearResultCard();return true;})()')
                await dev.evaluate('(()=>{'+SCENE+'scene.enabled=false;return true;})()')
                await restore(dev,backup)
                report['preferences_restored']=await dev.evaluate('Object.fromEntries('+json.dumps(KEYS)+'.map(k=>[k,localStorage.getItem(k)]))')==backup
                (OUT/receipt).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
