"""真实双角色、两套皮肤与一体漫画轮廓；仅本地展示，不触发音乐或LLM。"""
import asyncio,json,base64
from c0_live_acceptance import ROOT,PET,DEV,Page,pages
from c0_live_scenarios import switch
from ui_customization_acceptance import PANEL,KEYS,restore,until
from ui_comic_acceptance import SCENE
OUT=ROOT/'docs/plan/manga-skins-artifacts'
async def main():
 OUT.mkdir(exist_ok=True);report={'roles':[]}
 async with Page(next(p for p in await pages() if p['title']=='Yuiro')) as pet:
  await pet.evaluate("window.yuiro.openDev('settings')")
  async with Page(next(p for p in await pages() if 'dev.html' in p['url'])) as dev:
   await dev.evaluate('(()=>{'+DEV+'d.switchTab("ui");return true;})()')
   await until(dev,'(()=>{'+PANEL+'return !!panel?.settings;})()')
   backup=await dev.evaluate('Object.fromEntries('+json.dumps(KEYS)+'.map(k=>[k,localStorage.getItem(k)]))')
   original=await dev.evaluate('(()=>{'+DEV+'return {role:s.character.active_id,theme:d.theme};})()')
   try:
    for role in ['hiyori','hotaru']:
     await switch(pet,dev,role)
     await dev.evaluate('(()=>{'+PANEL+DEV+'panel.comicPreset();panel.settings.skin="auto";panel.settings.theme="light";panel.settings.speech.ornaments=true;d.theme="light";panel.text="今天也在这里陪着你。\\n\\n慢慢说，我在听。";return true;})()')
     skin='lily' if role=='hotaru' else 'cream'
     await until(dev,'document.documentElement.dataset.skin==='+json.dumps(skin))
     await until(pet,'document.documentElement.dataset.skin==='+json.dumps(skin))
     if skin=='lily':await until(pet,'getComputedStyle(document.querySelector(".shell-root")).getPropertyValue("--chat-accent").trim()==="#58776a"')
     header=await dev.evaluate('(()=>{const r=document.querySelector(".topbar").getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()')
     shot=await dev.call('Page.captureScreenshot',{"format":"png","clip":header});(OUT/f'{role}-header.png').write_bytes(base64.b64decode(shot['data']))
     await pet.evaluate('(()=>{'+PET+'app.showSpeech("今天也在这里陪着你。\\n\\n慢慢说，我在听。");app.clearSpeechTimers();return true;})()')
     info=None
     for _ in range(80):
      info=next((p for p in await pages() if p['title']=='Yuiro 回复'),None)
      if info:break
      await asyncio.sleep(.1)
     async with Page(info) as reply:
      await until(reply,'!!document.querySelector(".bubble-outline path")')
      for brush in ['soft','ink']:
       await dev.evaluate('(()=>{'+PANEL+'panel.settings.speech.bubbleStyle='+json.dumps(brush)+';return true;})()')
       await asyncio.sleep(.3)
       details=await reply.evaluate('(()=>{const e=document.querySelector(".reply-frame"),p=e.querySelector(".bubble-outline path:last-of-type"),r=e.getBoundingClientRect();return {skin:document.documentElement.dataset.skin,width:r.width,height:r.height,path:e.querySelector(".bubble-outline path").getAttribute("d"),textColor:getComputedStyle(e.querySelector(".reply-surface")).color,decorative:e.querySelectorAll(".character-motif").length};})()')
       assert details['skin']==skin and 'Z' in details['path'] and 'NaN' not in details['path']
       image=await reply.call('Page.captureScreenshot',{'format':'png'})
       (OUT/f'{role}-{brush}.png').write_bytes(base64.b64decode(image['data']))
       report['roles'].append({'role':role,'brush':brush,**details})
      await pet.evaluate('(()=>{'+PET+'app.showSpeech('+json.dumps('长回复排版与滚动检查。\n\n'*65,ensure_ascii=False)+');app.clearSpeechTimers();return true;})()')
      await until(reply,'(()=>{const e=document.querySelector(".reply-surface");return e.scrollHeight>e.clientHeight+20;})()')
      await dev.evaluate('(()=>{'+PANEL+'panel.settings.speech.ornaments=false;return true;})()')
      await until(reply,'!document.querySelector(".character-motif")')
     # Capture safe model-layout preview, no account/config provider fields.
     await dev.evaluate('(()=>{'+SCENE+'scene.enabled=true;scene.island=false;return true;})()')
     await until(dev,'(()=>{'+SCENE+'return !!scene.canvas?.getModelRect?.();})()',30)
     await asyncio.sleep(.5)
     clip=await dev.evaluate('(()=>{const e=document.querySelector(".ui-scene");e.scrollIntoView({block:"center"});const r=e.getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()')
     shot=await dev.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':clip});(OUT/f'{role}-scene.png').write_bytes(base64.b64decode(shot['data']))
     await dev.evaluate('(()=>{'+DEV+'d.theme="dark";return true;})()')
     if skin=='lily':await until(dev,'getComputedStyle(document.documentElement).getPropertyValue("--bg").trim()==="#1b2229"')
     await dev.evaluate('(()=>{'+PANEL+'panel.settings.skin="cream";return true;})()')
     await until(pet,'document.documentElement.dataset.skin==="cream"')
     await dev.evaluate('(()=>{'+PANEL+DEV+SCENE+'panel.settings.skin="auto";d.theme="light";scene.enabled=false;return true;})()')
     await pet.evaluate('(()=>{'+PET+'app.hideSpeech();return true;})()')
    report['manual_override_and_auto']=True;report['long_reply_and_decor_toggle']=True
   finally:
    await switch(pet,dev,'hotaru' if original['role']=='hiyori' else 'hiyori');await switch(pet,dev,original['role'])
    await pet.evaluate('(()=>{'+PET+'app.hideSpeech();app.clearSpeechTimers();app.clearResultCard();return true;})()')
    await dev.evaluate('(()=>{'+DEV+SCENE+'d.theme='+json.dumps(original['theme'])+';scene.enabled=false;return true;})()')
    await restore(dev,backup)
    report['restored']=True;(OUT/'ui-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
