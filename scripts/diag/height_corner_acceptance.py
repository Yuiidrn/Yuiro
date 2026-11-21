"""真实窗口高度/聊天坞和角花回归；仅本地UI，不播放或请求LLM。"""
import asyncio,json,sys,ctypes as c,base64
from ctypes import wintypes as w
from c0_live_acceptance import ROOT,PET,DEV,Page,pages
from ui_customization_acceptance import PANEL,until
from detached_edges import MI
OUT=ROOT/'docs/plan/height-and-corner-artifacts'
async def main():
 OUT.mkdir(exist_ok=True);u=c.windll.user32;u.SetThreadDpiAwarenessContext(c.c_void_p(-4));u.FindWindowW.restype=w.HWND;u.MonitorFromWindow.restype=w.HANDLE
 async with Page(next(p for p in await pages() if p['title']=='Yuiro')) as pet,Page(next(p for p in await pages() if 'dev.html' in p['url'])) as dev:
  await dev.evaluate('(()=>{'+DEV+'d.switchTab("ui");return true;})()')
  await until(dev,'!!document.querySelector("#dock-h")')
  original=await pet.evaluate('window.yuiro.getPetLayout()')
  state=await dev.evaluate('(()=>{'+PANEL+DEV+'return {skin:panel.settings.skin,ornaments:panel.settings.speech.ornaments,opacity:panel.settings.speech.ornamentAlpha,mode:panel.settings.speech.mode,lock:d.lockRatio,dock:d.dockHeight};})()')
  chat=await pet.evaluate('(()=>{'+PET+'return app.activePanel;})()')
  rect=w.RECT();h=u.FindWindowW(None,'Yuiro');u.GetWindowRect(h,c.byref(rect));mi=MI();mi.size=c.sizeof(mi);u.GetMonitorInfoW(u.MonitorFromWindow(h,2),c.byref(mi))
  ratio=(rect.bottom-rect.top)/(await pet.evaluate('innerHeight'));maximum=int((mi.work.bottom-mi.work.top)/ratio)-16
  target=max(260,min(2000,maximum)//10*10);low=max(220,target-160)
  report={'original':original,'height_cases':[],'motifs':[]}
  try:
   await dev.evaluate('(()=>{'+DEV+'d.lockRatio=false;return true;})()')
   for value in [low,target]:
    await dev.evaluate('(()=>{const e=document.querySelector("#win-h");e.value='+str(value)+';e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));return true;})()')
    await asyncio.sleep(.5);actual=await pet.evaluate('window.yuiro.getPetLayout()');assert abs(actual['height']-value)<=2,(actual,value)
    model=await pet.evaluate('(()=>{'+PET+'return v.modelRect.height;})()')
    report['height_cases'].append({'requested':value,'actual':actual['height'],'model_height':model})
   await pet.evaluate('window.yuiro.fitWindowToModel({width:300,height:400})');await asyncio.sleep(.3)
   assert abs((await pet.evaluate('window.yuiro.getPetLayout()'))['height']-target)<=2
   report['automatic_fit_did_not_overwrite']=True
   await pet.evaluate('(()=>{'+PET+'app.activePanel="chat";return true;})()')
   report['dock_heights']=[]
   for value in [36,80]:
    await dev.evaluate('(()=>{const e=document.querySelector("#dock-h");e.value='+str(value)+';e.dispatchEvent(new Event("input",{bubbles:true}));return true;})()')
    await until(pet,'!!document.querySelector(".composer")&&Math.abs(document.querySelector(".composer").getBoundingClientRect().height-'+str(value)+')<1')
    report['dock_heights'].append(await pet.evaluate('document.querySelector(".composer").getBoundingClientRect().height'))
   await dev.evaluate('(()=>{'+PANEL+'panel.settings.speech.mode="bubble";panel.settings.speech.ornaments=true;panel.settings.speech.ornamentAlpha=.6;return true;})()')
   await pet.evaluate('(()=>{'+PET+'app.showSpeech('+json.dumps('长文滚动与角落装饰检查。\n\n'*30,ensure_ascii=False)+');app.clearSpeechTimers();return true;})()')
   for _ in range(80):
    ri=next((p for p in await pages() if p['title']=='Yuiro 回复'),None)
    if ri:break
    await asyncio.sleep(.1)
   async with Page(ri) as reply:
    for skin in ['cream','lily']:
     await dev.evaluate('(()=>{'+PANEL+'panel.settings.skin='+json.dumps(skin)+';return true;})()')
     await until(reply,'document.documentElement.dataset.skin==='+json.dumps(skin)+'&&!!document.querySelector(".reply-footer .character-motif")')
     detail=await reply.evaluate('(()=>{const e=document.querySelector(".reply-surface"),f=document.querySelector(".reply-footer"),m=f.querySelector("svg"),a=e.getBoundingClientRect(),b=f.getBoundingClientRect();e.scrollTop=e.scrollHeight;return {color:getComputedStyle(m).color,alpha:getComputedStyle(m).opacity,footerBelowContent:b.y>=a.bottom-1,footerHeight:b.height,scroll:e.scrollHeight>e.clientHeight};})()')
     assert detail['footerBelowContent'] and detail['scroll'] and float(detail['alpha'])==.6,detail
     image=await reply.call('Page.captureScreenshot',{'format':'png'});(OUT/f'{skin}-corner.png').write_bytes(base64.b64decode(image['data']));report['motifs'].append({'skin':skin,**detail})
    await dev.evaluate('(()=>{'+PANEL+'panel.settings.speech.ornaments=false;return true;})()');await until(reply,'!document.querySelector(".reply-footer")');report['toggle_off']=True
  finally:
   await pet.evaluate('(()=>{'+PET+'app.hideSpeech();app.clearSpeechTimers();app.activePanel='+json.dumps(chat)+';return true;})()')
   await dev.evaluate('(()=>{'+PANEL+DEV+'panel.settings.skin='+json.dumps(state['skin'])+';panel.settings.speech.mode='+json.dumps(state['mode'])+';panel.settings.speech.ornaments='+json.dumps(state['ornaments'])+';panel.settings.speech.ornamentAlpha='+str(state['opacity'])+';d.lockRatio='+json.dumps(state['lock'])+';d.dockHeight='+str(state['dock'])+';return true;})()')
   report['final_layout']=await pet.evaluate('window.yuiro.getPetLayout()');(OUT/'live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report))
if __name__=='__main__':asyncio.run(main())
