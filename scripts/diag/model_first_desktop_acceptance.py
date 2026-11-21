"""原生桌面截图/坐标验收；真实角色+客户端候选，长文为本地展示样本，不播放。"""
import asyncio,ctypes as c,json,sys,time
from ctypes import wintypes as w
from PIL import ImageGrab
from c0_live_acceptance import ROOT,PET,DEV,Page,pages
from c0_live_scenarios import switch
from ui_customization_acceptance import PANEL,KEYS,restore,until
from detached_edges import MI,overlap
OUT=ROOT/'docs/plan/model-first-artifacts'
TEXT='今天也在这里陪着你。\n\n'+('听你慢慢说，我会把每一件小事好好记住。长回复可以滚动，角色仍是画面中心。\n\n'*15)
async def main():
 OUT.mkdir(exist_ok=True);u=c.windll.user32;u.SetThreadDpiAwarenessContext(c.c_void_p(-4));u.FindWindowW.restype=w.HWND;u.MonitorFromWindow.restype=w.HANDLE;u.SetWindowPos.argtypes=[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT]
 def hwnd(t):return u.FindWindowW(None,t)
 def rect(t):
  h=hwnd(t);r=w.RECT();assert h and u.GetWindowRect(h,c.byref(r)),t
  return {'x':r.left,'y':r.top,'width':r.right-r.left,'height':r.bottom-r.top}
 def work():
  m=MI();m.size=c.sizeof(m);assert u.GetMonitorInfoW(u.MonitorFromWindow(hwnd('Yuiro'),2),c.byref(m));r=m.work
  return {'x':r.left,'y':r.top,'width':r.right-r.left,'height':r.bottom-r.top}
 def move(x,y):assert u.SetWindowPos(hwnd('Yuiro'),0,round(x),round(y),0,0,0x15)
 def shot(name,rs):
  a=work();x=max(a['x'],min(r['x'] for r in rs)-12);y=max(a['y'],min(r['y'] for r in rs)-12);right=min(a['x']+a['width'],max(r['x']+r['width'] for r in rs)+12);bottom=min(a['y']+a['height'],max(r['y']+r['height'] for r in rs)+12)
  backdrop_pid=int((ROOT/'.env-local/model-first-backdrop.pid').read_text().strip());windows=[]
  @c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
  def visit(h,_):
   process=w.DWORD();u.GetWindowThreadProcessId(h,c.byref(process))
   if process.value==backdrop_pid and u.IsWindowVisible(h):windows.append(h)
   return True
  u.EnumWindows(visit,0)
  assert len(windows)==1,('controlled backdrop unavailable',windows)
  assert u.SetWindowPos(windows[0],-1,0,0,0,0,0x13)
  try:
   for title in ['Yuiro','Yuiro 回复','Yuiro 结果']:u.SetWindowPos(hwnd(title),-1,0,0,0,0,0x13)
   time.sleep(.3)
   ImageGrab.grab(bbox=(x,y,right,bottom),all_screens=True).save(OUT/name)
  finally:u.SetWindowPos(windows[0],-2,0,0,0,0,0x13)
 async with Page(next(p for p in await pages() if p['title']=='Yuiro')) as pet:
  await pet.evaluate("window.yuiro.openDev('settings')")
  for _ in range(80):
   di=next((p for p in await pages() if 'dev.html' in p['url']),None)
   if di:break
   await asyncio.sleep(.1)
  async with Page(di) as dev:
   await until(dev,'(()=>{'+DEV+'return !!d?.switchTab&&!!s?.character?.active_id;})()',20)
   await dev.evaluate('(()=>{'+DEV+'d.switchTab("ui");return true;})()')
   await until(dev,'(()=>{'+PANEL+'return !!panel?.settings;})()')
   role=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
   backup=await dev.evaluate('Object.fromEntries('+json.dumps(KEYS+['yuiro-fade-on-hover-enabled'])+'.map(k=>[k,localStorage.getItem(k)]))')
   oldlayout=json.loads((OUT/'before-layout.json').read_text(encoding='utf-8'));oldpos=rect('Yuiro')
   report={'capture':'real desktop ImageGrab, temporary development-only content protection opt-out','long_text':'local presentation fixture; songs from real client /搜歌','roles':[],'before_layout':oldlayout};success=False
   async def geometry():
    b=rect('Yuiro');d=await pet.evaluate('(()=>{'+PET+'const r=v.modelRect;return {x:r.left,y:r.top,width:r.width,height:r.height,vw:innerWidth,vh:innerHeight};})()')
    model={'x':b['x']+d['x']*b['width']/d['vw'],'y':b['y']+d['y']*b['height']/d['vh'],'width':d['width']*b['width']/d['vw'],'height':d['height']*b['height']/d['vh']}
    return b,model,d
   async def show():
    await pet.evaluate('(()=>{'+PET+'app.closeMenu();app.showSpeech('+json.dumps(TEXT,ensure_ascii=False)+');app.clearSpeechTimers();return true;})()');await asyncio.sleep(.5)
   try:
    for target in ['hiyori','hotaru']:
     await switch(pet,dev,target)
     await dev.evaluate('localStorage.setItem("yuiro-fade-on-hover-enabled","false")')
     await pet.evaluate('(()=>{'+PET+'app.sendText("/搜歌 Monody");return true;})()')
     await until(pet,'(()=>{'+PET+'return app.resultCard?.items?.some(x=>x.song_id==="36308916");})()',35)
     # Capture previous saved proportions, and its previous non-head-following layout.
     await dev.evaluate('(()=>{'+PANEL+'panel.settings.results.seconds=0;panel.settings.speech.mode="bubble";panel.settings.speech.comic=true;panel.settings.speech.headAnchored=false;return true;})()')
     await pet.evaluate('window.yuiro.setPetLayout('+json.dumps(oldlayout)+',false)')
     a=work();u.SetCursorPos(a['x']+a['width']-5,a['y']+a['height']-5);b=rect('Yuiro');move(a['x']+a['width']*.4-b['width']/2,a['y']+30)
     await show();before,mb,db=await geometry()
     await asyncio.sleep(.4)
     dp=hwnd('Yuiro 开发者调试台');
     if dp:u.ShowWindow(dp,6)
     await asyncio.sleep(.5)
     shot(f'{target}-before.png',[before,rect('Yuiro 回复'),rect('Yuiro 结果')])
     if dp:u.ShowWindow(dp,4)
     await dev.evaluate('(()=>{'+PANEL+'panel.modelFirstPreset();return true;})()')
     await asyncio.sleep(.8);await show()
     row={'role':target,'before_model':mb,'cases':[]};report['roles'].append(row)
     for edge in ['center','right','bottom-right','top-left']:
      a=work();b=rect('Yuiro');x=a['x']+a['width']*.4-b['width']/2;y=a['y']+35
      if edge in ['right','bottom-right']:x=a['x']+a['width']-b['width']-6
      if edge=='bottom-right':y=a['y']+a['height']-b['height']-6
      if edge=='top-left':x=a['x']+6;y=a['y']+6
      move(x,y);await asyncio.sleep(.5)
      b,m,d=await geometry();surfaces=[]
      for title in ['Yuiro 回复','Yuiro 结果']:
       assert u.IsWindowVisible(hwnd(title)),(target,edge,title)
       r=rect(title)
       relative={'x':(r['x']-b['x'])*d['vw']/b['width'],'y':(r['y']-b['y'])*d['vh']/b['height'],'width':r['width']*d['vw']/b['width'],'height':r['height']*d['vh']/b['height']}
       hits=await pet.evaluate('(()=>{'+PET+'const m=v.contour,r='+json.dumps(relative)+';if(!m)return -1;let hits=0;for(let y=0;y<m.height;y++)for(let x=0;x<m.width;x++){const cx=m.left+(x+.5)*m.cssWidth/m.width,cy=m.top+(y+.5)*m.cssHeight/m.height;if(cx>=r.x&&cx<r.x+r.width&&cy>=r.y&&cy<r.y+r.height&&m.alpha[y*m.width+x]>=4)hits++}return hits;})()')
       assert hits==0,(target,edge,title,'visible model pixels covered',hits)
       assert r['x']>=a['x']-2 and r['y']>=a['y']-2 and r['x']+r['width']<=a['x']+a['width']+2 and r['y']+r['height']<=a['y']+a['height']+2
       surfaces.append(r)
      assert not overlap(*surfaces)
      assert d['y']>=-2 and d['x']>=-2 and d['x']+d['width']<=d['vw']+2 and d['y']+d['height']<=d['vh']+2,d
      info=next(p for p in await pages() if p['title']=='Yuiro 回复')
      async with Page(info) as reply:
       detail=await reply.evaluate('(()=>{const r=document.querySelector(".reply-frame"),e=document.querySelector(".reply-surface");return {skin:document.documentElement.dataset.skin,font:getComputedStyle(e).fontSize,scroll:e.scrollHeight>e.clientHeight,path:r.querySelector(".bubble-outline path").getAttribute("d")};})()')
      if dp:u.ShowWindow(dp,6)
      await asyncio.sleep(.5);shot(f'{target}-{edge}.png',[b,*surfaces])
      if dp:u.ShowWindow(dp,4)
      row['cases'].append({'edge':edge,'model':m,'surfaces':surfaces,'skin':detail['skin'],'scroll':detail['scroll'],'model_to_reply_height':round(m['height']/surfaces[0]['height'],2),'no_overlap':True,'model_fully_visible':True})
     # Validate whole-theme identity in all mounted rendering contexts.
     row['theme']=await pet.evaluate('(()=>{'+PET+'return {skin:document.documentElement.dataset.skin,dock:getComputedStyle(document.querySelector(".shell-root")).getPropertyValue("--chat-accent").trim()};})()')
     row['dev_skin']=await dev.evaluate('document.documentElement.dataset.skin')
     info=next(p for p in await pages() if p['title']=='Yuiro 结果')
     async with Page(info) as card:row['card_skin']=await card.evaluate('document.documentElement.dataset.skin')
     expected='lily' if target=='hotaru' else 'cream';assert row['theme']['skin']==row['dev_skin']==row['card_skin']==expected
     (OUT/'desktop.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    await switch(pet,dev,'hiyori' if role=='hotaru' else 'hotaru');await switch(pet,dev,role)
    report['switch_clean']=await pet.evaluate('(()=>{'+PET+'return !app.resultCard&&!app.speechVisible&&!app.officialPlayback;})()');assert report['switch_clean']
    success=True
   finally:
    await switch(pet,dev,role)
    await pet.evaluate('(()=>{'+PET+'app.hideSpeech();app.clearSpeechTimers();app.clearResultCard();return true;})()')
    if not success:
     await restore(dev,{k:v for k,v in backup.items() if k in KEYS});await pet.evaluate('window.yuiro.setPetLayout('+json.dumps(oldlayout)+',true)')
    else:
     await dev.evaluate('(()=>{'+PANEL+'panel.modelFirstPreset();return true;})()')
    fade=backup.get('yuiro-fade-on-hover-enabled');await dev.evaluate('localStorage.'+('removeItem("yuiro-fade-on-hover-enabled")' if fade is None else 'setItem("yuiro-fade-on-hover-enabled",'+json.dumps(fade)+')'))
    a=work();b=rect('Yuiro');move(max(a['x'],min(oldpos['x'],a['x']+a['width']-b['width'])),max(a['y'],min(oldpos['y'],a['y']+a['height']-b['height'])))
    report['completed']=success;report['model_first_kept']=success;(OUT/'desktop.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
