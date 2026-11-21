import asyncio,json,ctypes,time,urllib.request,argparse
from ctypes import wintypes as W
from pathlib import Path
exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])
class Mouse(ctypes.Structure):_fields_=[('dx',W.LONG),('dy',W.LONG),('mouseData',W.DWORD),('flags',W.DWORD),('time',W.DWORD),('extra',ctypes.c_size_t)]
class Payload(ctypes.Union):_fields_=[('mouse',Mouse)]
class Input(ctypes.Structure):_fields_=[('type',W.DWORD),('payload',Payload)]
async def main():
 parser=argparse.ArgumentParser();parser.add_argument('--role',choices=['hiyori','hotaru'],default='hiyori');parser.add_argument('--gaze-only',action='store_true');options=parser.parse_args();role=options.role
 model='/live2d/hiyori/Hiyori.model3.json' if role=='hiyori' else '/live2d/Hotaru Shiomi/016_casual_spring_01/016_casual_spring_01.model3.json'
 group,index=('Idle',6) if role=='hiyori' else ('Motion',4)
 idle_group,idle_index=('Idle',0) if role=='hiyori' else ('Motion',19)
 version=json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
 async with websockets.connect(version['webSocketDebuggerUrl']) as browser:
  await browser.send(json.dumps({'id':1,'method':'SystemInfo.getProcessInfo'}))
  while True:
   response=json.loads(await browser.recv())
   if response.get('id')==1:break
  owner_pid=int(next(p['id'] for p in response['result']['processInfo'] if p['type']=='browser'))
 user=ctypes.WinDLL('user32',use_last_error=True)
 try:user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
 except Exception:pass
 user.IsWindowVisible.argtypes=[W.HWND]
 user.GetCursorPos.argtypes=[ctypes.POINTER(W.POINT)]
 user.SetCursorPos.argtypes=[ctypes.c_int,ctypes.c_int]
 user.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
 user.GetClientRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)];user.ClientToScreen.argtypes=[W.HWND,ctypes.POINTER(W.POINT)]
 user.WindowFromPoint.argtypes=[W.POINT];user.WindowFromPoint.restype=W.HWND
 user.GetAncestor.argtypes=[W.HWND,W.UINT];user.GetAncestor.restype=W.HWND
 user.SendInput.argtypes=[W.UINT,ctypes.POINTER(Input),ctypes.c_int]
 cursor=W.POINT();assert user.GetCursorPos(ctypes.byref(cursor))
 dev=next(p for p in pages() if 'dev.html' in p['url']);pet=next(p for p in pages() if 'index.html' in p['url'])
 async def setup(c,e):
  original=await e('document.querySelector(".character-picker select").value')
  pool=await e("localStorage.getItem('yuiro-avatar-click-pools-v1')")
  await e('(()=>{const s=document.querySelector(".character-picker select");s.value='+json.dumps(role)+';s.dispatchEvent(new Event("change",{bubbles:true}))})()');await asyncio.sleep(4)
  if not options.gaze_only:await e('(()=>{const k="yuiro-avatar-click-pools-v1",pool=JSON.parse(localStorage.getItem(k)||"{}");pool['+json.dumps(role+':'+model)+']={enabled:true,motions:['+json.dumps(f'{group}#{index}')+']};localStorage.setItem(k,JSON.stringify(pool))})()')
  return original,pool
 original,pool=await connect(dev,setup)
 report={'role':role,'scope':'native Windows cursor and SendInput click, verified owned window and renderer contour','started':False,'returnedToIdle':False}
 try:
  async def click(c,e):
   await c('Page.bringToFront');await asyncio.sleep(.3)
   info=await e("(()=>{const seen=new Set();function find(v){if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);if(v.component?.type.__name==='Live2DCanvas')return v.component;return find(v.component?.subTree)||(Array.isArray(v.children)?v.children.map(find).find(Boolean):null)}const component=find(document.querySelector('#app')._vnode),api=component.exposed,r=api.getModelRect();window.__nativeAvatar=api;for(const fy of [.5,.6,.7,.4])for(const fx of [.5,.45,.55]){const x=r.left+r.width*fx,y=r.top+r.height*fy;if(api.hitContour(x,y))return {x,y,w:innerWidth,h:innerHeight,dpr:devicePixelRatio}}throw Error('No safe opaque target')})()")
   windows=[]
   @ctypes.WINFUNCTYPE(ctypes.c_bool,W.HWND,W.LPARAM)
   def visit(hwnd,_):
    pid=W.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));rect=W.RECT();user.GetClientRect(hwnd,ctypes.byref(rect))
    if pid.value==owner_pid and user.IsWindowVisible(hwnd):windows.append((hwnd,rect.right,rect.bottom))
    return True
   user.EnumWindows(visit,0)
   candidates=[v for v in windows if abs(v[1]-info['w']*info['dpr'])<4 and abs(v[2]-info['h']*info['dpr'])<4]
   assert len(candidates)==1,{'matches':len(candidates)}
   hwnd,cw,ch=candidates[0];origin=W.POINT();assert user.ClientToScreen(hwnd,ctypes.byref(origin))
   x=origin.x+round(info['x']*cw/info['w']);y=origin.y+round(info['y']*ch/info['h'])
   assert user.SetCursorPos(x,y),'Native positioning rejected'
   await asyncio.sleep(.35)
   current_cursor=W.POINT();assert user.GetCursorPos(ctypes.byref(current_cursor))
   assert (current_cursor.x,current_cursor.y)==(x,y),'Cursor moved during probe; no click sent'
   hit=user.WindowFromPoint(W.POINT(x,y));assert user.GetAncestor(hit,2)==hwnd,'Target window not owned pet; no click sent'
   if options.gaze_only:
    report['scope']='native Windows pointer movement and hold expiry with current preferences; no click or microphone'
    for dx in [0,4,8,12,8,4]:
     assert user.SetCursorPos(x+dx,y),'Native cursor movement rejected'
     await asyncio.sleep(.09)
    active=await e('__nativeAvatar.getGazeState()')
    hold=await e('Number(localStorage.getItem('+json.dumps('yuiro-avatar-gaze-hold-ms'+(':hotaru' if role=='hotaru' else ''))+')||'+str(2800 if role=='hotaru' else 2200)+')')
    await asyncio.sleep(min(10000,max(500,hold))/1000+.7)
    quiet=await e('({gaze:__nativeAvatar.getGazeState(),state:__nativeAvatar.getAvatarState()})')
    report.update(active=active,quiet=quiet,holdMs=hold)
    report['started']=active['owns']
    report['returnedToIdle']=not quiet['gaze']['owns'] and quiet['gaze']['weight']<.05 and quiet['state']['motion']==idle_group and quiet['state']['motionIndex']==idle_index
    return
   sequence=(Input*2)(Input(type=0,payload=Payload(mouse=Mouse(flags=2))),Input(type=0,payload=Payload(mouse=Mouse(flags=4))))
   sent=user.SendInput(2,sequence,ctypes.sizeof(Input))
   if sent==1:
    release=Input(type=0,payload=Payload(mouse=Mouse(flags=4)))
    user.SendInput(1,ctypes.byref(release),ctypes.sizeof(Input))
   assert sent==2,'Native click rejected'
   t=time.perf_counter();samples=[]
   for _ in range(100):
    state=await e("JSON.parse(localStorage.getItem('yuiro-avatar-status')||'{}')");samples.append(dict(ms=round((time.perf_counter()-t)*1000),**state))
    report['started']|=state.get('motion')==group and state.get('motionIndex')==index and state.get('until',0)>0
    if report['started'] and state.get('motion')==idle_group and state.get('motionIndex')==idle_index and state.get('until')==0:report['returnedToIdle']=True;break
    await asyncio.sleep(.2)
   report['samples']=samples
  await connect(pet,click)
  assert report['started'] and report['returnedToIdle'],{k:v for k,v in report.items() if k!='samples'}
 except Exception as ex:
  report['error']=str(ex)
 finally:
  report['cursorRestored']=bool(user.SetCursorPos(cursor.x,cursor.y))
  async def restore(c,e):
   if not options.gaze_only:await e(('localStorage.removeItem("yuiro-avatar-click-pools-v1")' if pool is None else 'localStorage.setItem("yuiro-avatar-click-pools-v1",'+json.dumps(pool)+')'))
   await e('(()=>{const s=document.querySelector(".character-picker select");s.value='+json.dumps(original)+';s.dispatchEvent(new Event("change",{bubbles:true}))})()');await asyncio.sleep(3)
  await connect(dev,restore);report['restoredRole']=original
  async def clear_probe(c,e):return await e('delete window.__nativeAvatar')
  await connect(pet,clear_probe)
  async def verify(c,e):return await e("localStorage.getItem('yuiro-avatar-click-pools-v1')")
  report['clickPoolRestored']=await connect(dev,verify)==pool
  Path(f'docs/plan/avatar-native-{"gaze" if options.gaze_only else "click"}-{role}-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print({k:v for k,v in report.items() if k!='samples'})
 if report.get('error'):raise RuntimeError(report['error'])
asyncio.run(main())
