"""本机真实模型/窗口的受控 UI 验收；不播放音乐、不修改角色配置或账户。"""
import asyncio
import base64
import ctypes as c
from ctypes import wintypes as w
import json

from c0_live_acceptance import ROOT, PET, DEV, Page, pages
from c0_live_scenarios import switch
from ui_customization_acceptance import PANEL,KEYS,restore,until
from detached_edges import overlap

SCENE="const scene=[...document.querySelectorAll('*')].find(e=>e.__vueParentComponent?.type.__file?.includes('UiScenePreview.vue'))?.__vueParentComponent.setupState;"
OUT=ROOT/'docs/plan/ui-comic-artifacts'
TEXT='# 排版验收\n\n**粗体**与*斜体*，以及 `inline code`。\n\n1. 第一项\n2. 第二项\n\n[官方文档](https://www.electronjs.org/)\n\n<script>window.__unsafeMarkdown=true</script><img src="https://example.com/no-fetch" onerror="alert(1)"><a href="javascript:alert(1)">危险链接</a>\n\n'+('长回复滚动检查：仅本地显示，不发送给模型或语音。\n\n'*12)

async def main():
    u=c.windll.user32;u.SetThreadDpiAwarenessContext(c.c_void_p(-4));u.FindWindowW.restype=w.HWND
    def bounds(title):
        r=w.RECT();h=u.FindWindowW(None,title);assert h and u.GetWindowRect(h,c.byref(r))
        return {'x':r.left,'y':r.top,'width':r.right-r.left,'height':r.bottom-r.top}
    ps=await pages()
    async with Page(next(p for p in ps if p['title']=='Yuiro')) as pet,Page(next(p for p in ps if 'dev.html' in p['url'])) as dev:
        await pet.evaluate("window.yuiro.openDev('settings')")
        role=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
        await dev.evaluate('(()=>{'+DEV+"d.switchTab('appearance');return true;})()")
        await until(dev,"[...document.querySelectorAll('.mp-model-name')].some(e=>e.textContent.includes('Hiyori'))")
        names=await dev.evaluate("[...document.querySelectorAll('.mp-model-name')].map(e=>e.textContent)")
        assert not any('Mao' in n or '肥牛' in n for n in names),names
        await dev.evaluate('(()=>{'+DEV+"d.switchTab('ui');return true;})()")
        await until(dev,'(()=>{'+PANEL+'return !!panel?.settings;})()')
        backup=await dev.evaluate('Object.fromEntries('+json.dumps(KEYS)+'.map(k=>[k,localStorage.getItem(k)]))')
        report={'kind':'controlled display content; real dual Live2D models/native windows; no chat/music/account actions','models':names,'roles':[]}
        OUT.mkdir(parents=True,exist_ok=True)
        try:
            for target in ['hiyori','hotaru']:
                await switch(pet,dev,target)
                await dev.evaluate('(()=>{'+SCENE+'scene.enabled=false;return true;})()')
                before=bounds('Yuiro')
                await dev.evaluate("[...document.querySelectorAll('button')].find(e=>e.textContent==='试用漫画曲线预设').click()")
                await dev.evaluate('(()=>{'+SCENE+'scene.enabled=true;return true;})()')
                await until(dev,'(()=>{'+SCENE+'return !!scene?.canvas?.getModelRect?.();})()',30)
                await until(dev,'(()=>{'+SCENE+DEV+'return scene.canvas.getModelPath()===s.sections.persona.model_path;})()',30)
                await until(dev,'(()=>{'+SCENE+'return !!scene.placement;})()')
                await asyncio.sleep(.7)
                after=bounds('Yuiro')
                assert max(abs(before[k]-after[k]) for k in before)<=3,('preview resized real pet',before,after)
                await dev.evaluate('(()=>{'+PANEL+'panel.settings.island.size=62;panel.settings.island.radius=20;panel.settings.island.alpha=.35;const e=document.querySelectorAll(".scene-controls input")[1];if(!e.checked)e.click();return true;})()')
                await until(dev,"!!document.querySelector('.ui-scene .bm-icon')&&Math.abs(parseFloat(getComputedStyle(document.querySelector('.ui-scene .bm-icon')).width)-62)<.1")
                await dev.evaluate('document.querySelector(".ui-scene").scrollIntoView({block:"center"})')
                await asyncio.sleep(.3)
                shot=await dev.evaluate('(()=>{const r=document.querySelector(".ui-scene").getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()')
                image=await dev.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':shot})
                (OUT/f'preview-{target}.png').write_bytes(base64.b64decode(image['data']))
                await pet.evaluate('(()=>{'+PET+'app.showSpeech('+json.dumps(TEXT,ensure_ascii=False)+');app.clearSpeechTimers();return true;})()')
                await asyncio.sleep(.5)
                info=next(p for p in await pages() if p['title']=='Yuiro 回复')
                async with Page(info) as reply:
                    await until(reply,"document.querySelector('.reply-surface strong')?.textContent==='粗体'")
                    safety=await reply.evaluate('(()=>{const e=document.querySelector(".reply-surface");return {strong:e.querySelectorAll("strong").length,lists:e.querySelectorAll("ol li").length,unsafeTags:e.querySelectorAll("script,img,iframe,svg,input").length,unsafeLinks:[...e.querySelectorAll("a")].some(a=>/^(javascript|file|data):/i.test(a.getAttribute("href")||"")),executed:!!window.__unsafeMarkdown,tail:!!document.querySelector(".reply-tail"),scrollbar:getComputedStyle(e).scrollbarWidth};})()')
                    assert safety['strong'] and safety['lists']==2 and not safety['unsafeTags'] and not safety['unsafeLinks'] and not safety['executed'] and safety['tail']
                    await dev.evaluate('(()=>{'+PANEL+'panel.bubble.maxWidth.value=640;panel.settings.speech.fontSize=32;return true;})()')
                    await until(reply,"getComputedStyle(document.querySelector('.reply-surface')).fontSize==='32px'")
                    native=bounds('Yuiro 回复');b=bounds('Yuiro')
                    m=await pet.evaluate('(()=>{'+PET+'const r=v.modelRect;return {x:r.left,y:r.top,width:r.width,height:r.height,vw:innerWidth,vh:innerHeight};})()')
                    model={'x':b['x']+max(0,m['x'])*b['width']/m['vw'],'y':b['y']+max(0,m['y'])*b['height']/m['vh'],'width':m['width']*b['width']/m['vw'],'height':m['height']*b['height']/m['vh']}
                    assert not overlap(native,model),(native,model)
                # Inspect actual card component without requesting playback.
                await dev.evaluate('(()=>{'+PANEL+"panel.kind='music';return true;})()")
                assert await dev.evaluate("![...document.querySelectorAll('.preview-board button')].some(e=>e.textContent.includes('桌宠播放器'))&&!!document.querySelector('.preview-board .rc-client')")
                await dev.evaluate('(()=>{'+PANEL+'panel.song.push({name:"随机样本（仅预览）",song_id:"123456"});return true;})()')
                await until(dev,"!!document.querySelector('.preview-board .rc-random')")
                await dev.evaluate("document.querySelector('.preview-board .rc-random').click()")
                assert await dev.evaluate("document.querySelector('.detached-settings [role=status]').textContent.includes('未执行真实操作')")
                await dev.evaluate('(()=>{'+PANEL+'panel.song.pop();return true;})()')
                report['roles'].append({'role':target,'markdown':safety,'preview_did_not_resize_pet':True,'island_hot_update':True,'wide_reply_no_model_overlap':True,'client_only_card':True,'random_candidate_preview':True})
                await dev.evaluate('(()=>{'+PANEL+SCENE+"panel.kind='speech';scene.enabled=false;return true;})()")
        finally:
            await dev.evaluate('(()=>{'+SCENE+'scene.enabled=false;return true;})()')
            await pet.evaluate('(()=>{'+PET+'app.hideSpeech();app.clearResultCard();return true;})()')
            await switch(pet,dev,role)
            await restore(dev,backup)
            report['preferences_restored']=await dev.evaluate('Object.fromEntries('+json.dumps(KEYS)+'.map(k=>[k,localStorage.getItem(k)]))')==backup
            (OUT/'live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
