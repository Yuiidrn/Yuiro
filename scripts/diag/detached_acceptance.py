"""Native mouse + real Electron windows/roles. Fixtures are explicitly identified.

Does not edit role config or export keys/history. Restores UI prefs/window/role.
"""
import asyncio
import ctypes as c
from ctypes import wintypes as w
import json
import time
from c0_live_acceptance import DEV, PET, ROOT, Page, pages
from c0_live_scenarios import switch
from contour_acceptance import Probe

OUT=ROOT/'docs/plan/detached-ui-artifacts'
KEYS=['yuiro-fade-on-hover-enabled','yuiro-speech-bubble-max-w','yuiro-speech-bubble-alpha','yuiro-speech-bubble-offset-y','yuiro-result-card-side']

async def main():
    c.windll.user32.SetProcessDpiAwarenessContext(c.c_void_p(-4))
    user=c.windll.user32
    user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    user.FindWindowW.restype=w.HWND
    cursor=w.POINT();user.GetCursorPos(c.byref(cursor))
    info=await pages()
    report={'kind':'real Electron/Engine roles + native OS clicks; presentation fixtures identified','roles':[]}
    async with Page(next(p for p in info if p['title']=='Yuiro')) as pet, Page(next(p for p in info if 'dev.html' in p['url'])) as dev:
        original_role=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
        original=await dev.evaluate('Object.fromEntries('+json.dumps(KEYS)+'.map(k=>[k,localStorage.getItem(k)]))')
        def native_bounds(title):
            rect=w.RECT();hwnd=user.FindWindowW(None,title)
            assert hwnd and user.GetWindowRect(hwnd,c.byref(rect)),title
            return {'x':rect.left,'y':rect.top,'width':rect.right-rect.left,'height':rect.bottom-rect.top}
        window=native_bounds('Yuiro')
        layout=await pet.evaluate('window.yuiro.getPetLayout()')
        probe=Probe()
        async def bounds(page):
            return native_bounds(await page.evaluate('document.title'))
        async def native_point(page,title,x,y):
            hwnd=user.FindWindowW(None,title);rect=w.RECT()
            assert hwnd and user.GetWindowRect(hwnd,c.byref(rect)),title
            size=await page.evaluate('({w:innerWidth,h:innerHeight})')
            return round(rect.left+x*(rect.right-rect.left)/size['w']),round(rect.top+y*(rect.bottom-rect.top)/size['h'])
        async def click_at(page,title,x,y):
            px,py=await native_point(page,title,x,y)
            user.SetCursorPos(px,py);await asyncio.sleep(.1)
            user.WindowFromPoint.restype=w.HWND
            top=user.WindowFromPoint(w.POINT(px,py));name=c.create_unicode_buffer(256);user.GetWindowTextW(top,name,256)
            print(json.dumps({'native_click':{'x':px,'y':py,'top':name.value,'target':title}},ensure_ascii=False),flush=True)
            user.mouse_event(2,0,0,0,0);user.mouse_event(4,0,0,0,0);await asyncio.sleep(.2)
        async def ui(kind):
            for _ in range(40):
                available=await pages()
                hit=next((p for p in available if f'kind={kind}' in p['url']),None)
                if hit:return hit
                await asyncio.sleep(.1)
            raise RuntimeError('detached window not created: '+kind)
        async def fixture(card=True):
            # Only presentation fixture. Does not claim real retrieval/synthesis.
            return await pet.evaluate('(()=>{'+PET+"app.closeMenu();app.showSpeech('独立窗口跟随验收：这段回复应该在角色旁边，而不是覆盖模型。',true);"+("app.resultCard={title:'来源展示验收（固定样本）',kind:'source',note:'fixture',items:[{title:'DeepSeek 文档',url:'https://api-docs.deepseek.com/zh-cn/guides/search',snippet:'仅用于独立窗口点击与隔离测试，不是实时检索结果。',published_at:'2026-10-24'}]};" if card else '')+'app.publishDetached();return app.detachedSnapshot().key;})()')
        try:
            await dev.evaluate("localStorage.setItem('yuiro-fade-on-hover-enabled','false')")
            user.SetWindowPos(user.FindWindowW(None,'Yuiro'),0,1000,150,0,0,0x0015)
            for role in ['hiyori','hotaru']:
                await switch(pet,dev,role);await asyncio.sleep(1.5)
                row={'role':role}
                await fixture()
                async with Page(await ui('speech')) as speech,Page(await ui('results')) as results:
                    await asyncio.sleep(.6)
                    row['island_removed']=await pet.evaluate("document.querySelector('.island-handle')===null")
                    row['single_owner']=await results.evaluate("({webgl:!!document.querySelector('canvas'),sockets:performance.getEntriesByType('resource').filter(r=>r.name.includes('8200')).length})")
                    row['initial_bounds']={'pet':await bounds(pet),'speech':await bounds(speech),'results':await bounds(results)}
                    row['visible_content']=await results.evaluate("({title:document.querySelector('.rc-head')?.textContent,date:document.querySelector('time')?.textContent,items:document.querySelectorAll('.rc-item').length})")
                    # Real mouse drag begins on the current opaque model contour.
                    point=await pet.evaluate('(()=>{'+PET+"app.closeMenu();const m=v.contour,r=v.modelRect;let p=null,d=Infinity;for(let j=0;j<m.height;j++)for(let i=0;i<m.width;i++){const x=m.left+(i+.5)*m.cssWidth/m.width,y=m.top+(j+.5)*m.cssHeight/m.height;if(m.alpha[j*m.width+i]>240&&x>20&&y>20&&x<innerWidth-20&&y<innerHeight-20&&!document.elementsFromPoint(x,y).some(e=>e.closest('button,input,.bm-icon,.panel'))){const n=Math.hypot(x-r.left-r.width/2,y-r.top-r.height*.7);if(n<d){d=n;p={x,y}}}}return p;})()")
                    start=await native_point(pet,'Yuiro',point['x'],point['y'])
                    user.SetCursorPos(*start);await asyncio.sleep(.04);user.mouse_event(2,0,0,0,0)
                    for i in range(1,9):user.SetCursorPos(start[0]+i*12,start[1]+i*5);await asyncio.sleep(.04)
                    user.mouse_event(4,0,0,0,0);await asyncio.sleep(.4)
                    row['after_native_drag']={'pet':await bounds(pet),'speech':await bounds(speech),'results':await bounds(results)}
                    assert abs(row['after_native_drag']['pet']['x']-row['initial_bounds']['pet']['x'])>40,'model did not move'
                    # Cross-window localStorage hot-update through the actual dev renderer.
                    await dev.evaluate("localStorage.setItem('yuiro-speech-bubble-max-w','280');localStorage.setItem('yuiro-speech-bubble-alpha','0.65');localStorage.setItem('yuiro-result-card-side','right')")
                    await asyncio.sleep(.5)
                    row['hot_update']=await speech.evaluate("({width:document.querySelector('main').offsetWidth,bg:getComputedStyle(document.querySelector('main')).backgroundColor})")
                    assert row['hot_update']['width']==280,row['hot_update']
                    # Click close with native mouse: no synthetic DOM event.
                    close=await speech.evaluate("(()=>{const r=document.querySelector('.close').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
                    await speech.evaluate("window.__clickLog=[];document.addEventListener('click',e=>__clickLog.push({x:e.clientX,y:e.clientY,target:e.target.className}),true)")
                    await pet.evaluate("window.__actionLog=[];window.__actionOff=window.yuiro.onDetachedAction(a=>__actionLog.push(a))")
                    row['close_geometry']=await speech.evaluate("({viewport:{w:innerWidth,h:innerHeight,dpr:devicePixelRatio},rect:document.querySelector('main').getBoundingClientRect().toJSON()})")
                    await click_at(speech,'Yuiro 回复',close['x'],close['y'])
                    row['native_dismiss']=await pet.evaluate('(()=>{'+PET+'return !app.speechVisible;})()')
                    print(json.dumps({'diagnostic':role,'geometry':row['close_geometry'],'close':close,'dismiss':row['native_dismiss']},ensure_ascii=False),flush=True)
                    if not row['native_dismiss']:
                        print(json.dumps({'clicks':await speech.evaluate('window.__clickLog'),'actions':await pet.evaluate('window.__actionLog'),'owner':await pet.evaluate('(()=>{'+PET+'return {key:app.detachedSnapshot().key,speech:app.speechVisible,bounds:app.detachedSnapshot().anchor};})()'),'ui_key':await speech.evaluate("document.querySelector('main').__vueParentComponent.setupState.state.key"),'native':await bounds(speech)}),flush=True)
                    await pet.evaluate('window.__actionOff()')
                    assert row['native_dismiss'],'native speech close did not reach owner'
                    stale=await results.evaluate("(()=>{const a=document.querySelector('main').__vueParentComponent.setupState;return a.state.key;})()")
                    r=await results.evaluate("(()=>{const r=document.querySelector('.rc-item').getBoundingClientRect();return{x:r.x+20,y:r.y+15}})()")
                    await click_at(results,'Yuiro 结果',r['x'],r['y'])
                    row['native_source_pick']=await pet.evaluate('(()=>{'+PET+"return {cleared:app.resultCard===null,logged:app.logs.some(l=>l.text.includes('[search] 打开来源：https://api-docs.deepseek.com/zh-cn/guides/search'))};})()")
                    assert row['native_source_pick']['cleared'] and row['native_source_pick']['logged']
                    # Stale result click across a real Engine character switch must not play/open anything.
                    target='hotaru' if role=='hiyori' else 'hiyori'
                    await switch(pet,dev,target);await asyncio.sleep(.35)
                    await pet.evaluate('window.__staleReceived=0;window.__staleOff=window.yuiro.onDetachedAction(()=>__staleReceived++)')
                    await results.evaluate('window.yuiro.detachedAction({kind:"results",key:'+json.dumps(stale)+',index:0})')
                    await asyncio.sleep(.1)
                    row['stale_actions_forwarded']=await pet.evaluate('window.__staleReceived')
                    await pet.evaluate('window.__staleOff()')
                    assert row['stale_actions_forwarded']==0
                    row['switch_cleanup']=await pet.evaluate('(()=>{'+PET+'return {role:app.activeCharacter,card:app.resultCard,speech:app.speechVisible};})()')
                    # Native visible flag from Win32, not the hidden renderer DOM.
                    row['native_windows_hidden']=not user.IsWindowVisible(user.FindWindowW(None,'Yuiro 回复')) and not user.IsWindowVisible(user.FindWindowW(None,'Yuiro 结果'))
                    assert row['native_windows_hidden'],row['switch_cleanup']
                report['roles'].append(row)
                OUT.mkdir(parents=True,exist_ok=True);(OUT/'live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(row,ensure_ascii=False),flush=True)
        finally:
            await pet.evaluate('(()=>{'+PET+'app.clearResultCard();app.hideSpeech();return true;})()')
            await switch(pet,dev,original_role)
            await dev.evaluate('(()=>{for(const [k,v] of Object.entries('+json.dumps(original)+')){if(v===null)localStorage.removeItem(k);else localStorage.setItem(k,v)}return true;})()')
            # Never pass physical Win32 dimensions back into Electron's DIP sizing.
            await pet.evaluate('window.yuiro.setPetLayout('+json.dumps(layout)+',false)')
            user.SetWindowPos(user.FindWindowW(None,'Yuiro'),0,window['x'],window['y'],0,0,0x0015)
            user.PostMessageW(probe.hwnd,0x10,0,0);user.SetCursorPos(cursor.x,cursor.y)

if __name__=='__main__':asyncio.run(main())
