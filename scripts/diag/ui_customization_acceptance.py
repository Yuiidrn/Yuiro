"""受控显示样本：验证真实调试台/独立窗口，不调用聊天、检索、音乐或外链。"""
import asyncio
import json
import time

from c0_live_acceptance import ROOT, PET, DEV, Page, pages
from c0_live_scenarios import switch

KEYS=['yuiro-detached-ui-v1','yuiro-theme','yuiro-speech-bubble-max-w','yuiro-speech-bubble-alpha',
      'yuiro-speech-bubble-offset-x','yuiro-speech-bubble-offset-y','yuiro-result-card-side',
      'yuiro-result-card-max-w','yuiro-result-card-alpha','yuiro-result-card-offset-x','yuiro-result-card-offset-y']
PANEL="const panel=[...document.querySelectorAll('*')].find(e=>e.__vueParentComponent?.type.__file?.includes('DetachedUiSettings.vue'))?.__vueParentComponent.setupState;"


async def until(page, expression, seconds=8):
    started=time.monotonic()
    while time.monotonic()-started<seconds:
        value=await page.evaluate(expression)
        if value:return value
        await asyncio.sleep(.1)
    print('UI timeout snapshot',await page.evaluate("(()=>{const e=document.querySelector('.result-card'),s=e&&getComputedStyle(e);return {title:document.title,width:innerWidth,font:s?.fontSize,maxHeight:s?.maxHeight,lines:document.querySelector('.rc-snippet')&&getComputedStyle(document.querySelector('.rc-snippet')).webkitLineClamp,date:!!document.querySelector('.rc-date'),source:JSON.parse(localStorage.getItem('yuiro-detached-ui-v1'))?.source};})()"),flush=True)
    raise RuntimeError('UI condition timeout: '+expression[-140:])


async def restore(dev, backup):
    # 与实际控件一样通过响应式偏好还原，再还原键是否存在；不能只改同窗口 storage。
    await dev.evaluate('(()=>{'+PANEL+DEV+'const b='+json.dumps(backup)+''';
if(panel){if(b['yuiro-detached-ui-v1'])panel.ui.settings.value=JSON.parse(b['yuiro-detached-ui-v1']);panel.kind='speech';}
d.resetBubble();d.resetCard();
const aliases={bubbleMaxWidth:'yuiro-speech-bubble-max-w',bubbleAlpha:'yuiro-speech-bubble-alpha',bubbleOffsetX:'yuiro-speech-bubble-offset-x',bubbleOffsetY:'yuiro-speech-bubble-offset-y',cardMaxWidth:'yuiro-result-card-max-w',cardAlpha:'yuiro-result-card-alpha',cardOffsetX:'yuiro-result-card-offset-x',cardOffsetY:'yuiro-result-card-offset-y'};
for(const[name,key]of Object.entries(aliases))if(b[key]!==null)d[name]=Number(b[key]);
if(b['yuiro-result-card-side'])d.cardSide=b['yuiro-result-card-side'];
if(['light','dark'].includes(b['yuiro-theme']))d.setPetTheme(b['yuiro-theme']);return true;})()''')
    await asyncio.sleep(.2)
    await dev.evaluate('(()=>{const b='+json.dumps(backup)+';for(const[k,v]of Object.entries(b)){if(v===null)localStorage.removeItem(k);else localStorage.setItem(k,v);}return true;})()')


async def main():
    report={'kind':'controlled display data; live Vue/Electron and real role switching; no chat/search/music operations','checks':[]}
    pet_info=None
    for _ in range(100):
        try:
            pet_info=next((p for p in await pages() if p['title']=='Yuiro'),None)
        except Exception:
            pass
        if pet_info:break
        await asyncio.sleep(.1)
    assert pet_info,'Electron desktop page not ready'
    async with Page(pet_info) as pet:
        await until(pet,'(()=>{'+PET+'return app?.modelReady&&app.socket?.readyState===1&&!app.officialPlayback&&!app.officialPending;})()')
        await pet.evaluate("window.yuiro.openDev('settings')")
        for _ in range(100):
            dev_info=next((p for p in await pages() if 'dev.html' in p['url']),None)
            if dev_info:break
            await asyncio.sleep(.1)
        async with Page(dev_info) as dev:
            await until(dev,'(()=>{'+DEV+'return !!s?.character?.active_id&&!s.loading;})()')
            initial=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
            await dev.evaluate('(()=>{'+DEV+"d.switchTab('ui');return true;})()")
            await until(dev,'(()=>{'+PANEL+'return !!panel?.settings;})()')
            backup=await dev.evaluate('Object.fromEntries('+json.dumps(KEYS)+'.map(k=>[k,localStorage.getItem(k)]))')
            await restore(dev,backup)
            await pet.evaluate('(()=>{'+PET+'app.hideSpeech();app.clearResultCard();window.__uiSocket=app.socket;window.__uiSend=app.socket.send;window.__uiSends=[];app.socket.send=function(x){__uiSends.push(JSON.parse(x).type);return __uiSend.call(this,x)};return true;})()')
            try:
                # 此用例验证标准圆角；漫画轮廓另由 ui_comic_acceptance 验证。
                await dev.evaluate('(()=>{'+PANEL+"panel.settings.speech.comic=false;panel.settings.speech.mode='bubble';panel.settings.speech.customInk=false;return true;})()")
                await pet.evaluate('(()=>{'+PET+"app.showSpeech('这是独立回复排版验证。'.repeat(35));app.clearSpeechTimers();return true;})()")
                for _ in range(100):
                    speech_info=next((p for p in await pages() if p['title']=='Yuiro 回复'),None)
                    if speech_info:break
                    await asyncio.sleep(.1)
                async with Page(speech_info) as speech:
                    await until(speech,"!!document.querySelector('.reply-surface')")
                    # 通过实际数值输入框触发设置，不直接改桌宠样式。
                    start=time.monotonic()
                    await dev.evaluate("(()=>{const e=document.querySelector('input[aria-label=\"回复字号数值\"]');e.value='22';e.dispatchEvent(new Event('change',{bubbles:true}));return true;})()")
                    await until(speech,"getComputedStyle(document.querySelector('.reply-surface')).fontSize==='22px'")
                    report['reply_hot_update_ms']=round((time.monotonic()-start)*1000)
                    await dev.evaluate('(()=>{'+PANEL+"panel.settings.speech.maxHeight=120;panel.settings.speech.radius=4;panel.settings.theme='dark';return true;})()")
                    await until(speech,"(()=>{const s=getComputedStyle(document.querySelector('.reply-surface'));return s.maxHeight==='120px'&&s.borderRadius==='4px'&&s.color==='rgb(242, 231, 214)';})()")
                    report['checks'].append('reply font/height/radius/theme hot update')
                    await speech.call('Page.reload')
                    await until(speech,"!!document.querySelector('.reply-surface')&&getComputedStyle(document.querySelector('.reply-surface')).fontSize==='22px'")
                    report['checks'].append('fresh detached renderer reads persisted preferences')
                await dev.evaluate('(()=>{'+PANEL+"panel.kind='music';panel.settings.results.fontSize=17;panel.settings.results.stackPlayers=true;panel.settings.results.showOfficialPage=false;panel.settings.results.seconds=0;return true;})()")
                await until(dev,"!!document.querySelector('.preview-board .rc-client')")
                await dev.evaluate("document.querySelector('.preview-board .rc-client').click()")
                assert await dev.evaluate("document.querySelector('.detached-settings [role=status]').textContent.includes('未执行真实操作')")
                assert await dev.evaluate("getComputedStyle(document.querySelector('.preview-board .rc-players')).flexDirection==='column'")
                # 无效 ID 与不可播标志使桌面显示样本也无法误触真实播放。
                music={'title':'UI 排版验证（显示样本）','kind':'song','items':[{'name':'仅用于外观验证','song_id':'ui-preview-only','availability':'api_unavailable'}],'note':''}
                await pet.evaluate('(()=>{'+PET+'app.resultCard='+json.dumps(music,ensure_ascii=False)+';return true;})()')
                for _ in range(100):
                    card_info=next((p for p in await pages() if p['title']=='Yuiro 结果'),None)
                    if card_info:break
                    await asyncio.sleep(.1)
                async with Page(card_info) as card:
                    await until(card,"!!document.querySelector('.rc-players')&&getComputedStyle(document.querySelector('.rc-players')).flexDirection==='column'")
                    assert await card.evaluate("[...document.querySelectorAll('.rc-official')].every(e=>!e.textContent.includes('打开官方'))")
                    report['checks'].append('music live density/buttons; offline preview emits demo only')
                    source={'title':'来源排版验证（显示样本）','kind':'source','items':[{'title':'来源样本','url':'','snippet':'这段文字仅用于验证摘要排版。'*30,'published_at':'2026-10-24T08:00:00+08:00'}],'note':''}
                    await dev.evaluate('(()=>{'+PANEL+"panel.kind='source';panel.settings.source.independent=true;panel.settings.source.width=340;panel.settings.source.fontSize=19;panel.settings.source.maxHeight=180;panel.settings.source.summaryLines=2;panel.settings.source.showDate=false;panel.settings.source.seconds=0;return true;})()")
                    await dev.evaluate("document.querySelector('.preview-board .rc-item').click()")
                    assert await dev.evaluate("document.querySelector('.detached-settings [role=status]').textContent.includes('未执行真实操作')")
                    await pet.evaluate('(()=>{'+PET+'app.resultCard='+json.dumps(source,ensure_ascii=False)+';return true;})()')
                    # Windows 混合 DPI 的 native DIP 向上取整允许 1px，不能把 340→341 当未热更新。
                    await until(card,"(()=>{const e=document.querySelector('.result-card');return e&&getComputedStyle(e).fontSize==='19px'&&getComputedStyle(e).maxHeight==='180px'&&document.querySelector('.rc-snippet')&&getComputedStyle(document.querySelector('.rc-snippet')).webkitLineClamp==='2'&&!document.querySelector('.rc-date')&&Math.abs(innerWidth-340)<=1;})()")
                    report['checks'].append('source independent size/font/summary/date live update')
                    # 关闭独立样式后即时继承通用结果卡的 17px。
                    await dev.evaluate('(()=>{'+PANEL+'panel.settings.source.independent=false;return true;})()')
                    await until(card,"getComputedStyle(document.querySelector('.result-card')).fontSize==='17px'")
                    report['checks'].append('source style inheritance')
                # 主题跟随在同一个调试台窗口中也需即时更新。
                await dev.evaluate('(()=>{'+PANEL+DEV+"panel.settings.theme='auto';d.setPetTheme('dark');return true;})()")
                await until(dev,"getComputedStyle(document.querySelector('.preview-board .result-card')).color==='rgb(242, 231, 214)'")
                await dev.evaluate('(()=>{'+DEV+"d.setPetTheme('light');return true;})()")
                await until(dev,"getComputedStyle(document.querySelector('.preview-board .result-card')).color==='rgb(41, 34, 28)'")
                report['checks'].append('same-window and cross-window theme following')
                await dev.evaluate('(()=>{'+PANEL+'panel.settings.source.seconds=1;return true;})()')
                await until(pet,'(()=>{'+PET+'return app.resultCard===null;})()',4)
                report['checks'].append('changed auto-hide duration applies to current card')
                await dev.evaluate('(()=>{'+PANEL+'panel.resetGroup();return true;})()')
                assert await dev.evaluate('(()=>{'+PANEL+'return !panel.settings.source.independent&&panel.settings.source.summaryLines===3&&panel.settings.results.fontSize===17;})()')
                report['checks'].append('group reset preserves other groups')
                await dev.evaluate('(()=>{'+DEV+"d.switchTab('overview');return true;})()")
                await pet.evaluate('(()=>{'+PET+'app.uiAppearance.settings.value.results.fontSize=18;return true;})()')
                await dev.evaluate('(()=>{'+DEV+"d.switchTab('ui');return true;})()")
                await until(dev,'(()=>{'+PANEL+'return panel?.settings.results.fontSize===18;})()')
                report['checks'].append('preferences continue syncing while settings component is unmounted')
                expected=await dev.evaluate("localStorage.getItem('yuiro-detached-ui-v1')")
                await switch(pet,dev,'hotaru' if initial=='hiyori' else 'hiyori')
                await switch(pet,dev,initial)
                assert await dev.evaluate("localStorage.getItem('yuiro-detached-ui-v1')")==expected
                assert await pet.evaluate('(()=>{'+PET+'return !app.resultCard&&!app.speechVisible;})()')
                report['checks'].append('Hiyori/Hotaru share display preferences and clear old content')
                sends=await pet.evaluate('window.__uiSends')
                assert not any(x.startswith('media:') or x=='chat:user' for x in sends),sends
                report['no_chat_or_media_requests']=True
            finally:
                await restore(dev,backup)
                await pet.evaluate('(()=>{'+PET+'if(window.__uiSocket&&window.__uiSend)__uiSocket.send=__uiSend;app.hideSpeech();app.clearResultCard();return true;})()')
                await switch(pet,dev,initial)
            await asyncio.sleep(.3)
            restored=await dev.evaluate('Object.fromEntries('+json.dumps(KEYS)+'.map(k=>[k,localStorage.getItem(k)]))')
            assert restored==backup,'Display preferences must be restored after acceptance'
            report['original_preferences_restored']=True
    path=ROOT/'docs/plan/ui-customization-artifacts/live.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':asyncio.run(main())
