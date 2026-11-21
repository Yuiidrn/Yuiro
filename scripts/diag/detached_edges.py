"""Native edge placement and fade + detached reply collaboration, both real models."""
import asyncio,ctypes as c,json
from ctypes import wintypes as w
from c0_live_acceptance import PET,DEV,ROOT,Page,pages
from c0_live_scenarios import switch

class MI(c.Structure):
    _fields_=[('size',w.DWORD),('monitor',w.RECT),('work',w.RECT),('flags',w.DWORD)]
def overlap(a,b):return a['x']<b['x']+b['width'] and a['x']+a['width']>b['x'] and a['y']<b['y']+b['height'] and a['y']+a['height']>b['y']

async def main():
    user=c.windll.user32;user.SetProcessDpiAwarenessContext(c.c_void_p(-4));user.FindWindowW.restype=w.HWND;user.MonitorFromWindow.restype=w.HANDLE
    user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    def rect(title):
        hwnd=user.FindWindowW(None,title);r=w.RECT();assert hwnd and user.GetWindowRect(hwnd,c.byref(r))
        return {'x':r.left,'y':r.top,'width':r.right-r.left,'height':r.bottom-r.top}
    def work(title):
        mi=MI();mi.size=c.sizeof(mi);assert user.GetMonitorInfoW(user.MonitorFromWindow(user.FindWindowW(None,title),2),c.byref(mi))
        r=mi.work;return {'x':r.left,'y':r.top,'width':r.right-r.left,'height':r.bottom-r.top}
    info=await pages();report={'kind':'Win32 physical geometry, real models; presentation fixtures','roles':[]}
    async with Page(next(p for p in info if p['title']=='Yuiro')) as pet,Page(next(p for p in info if 'dev.html' in p['url'])) as dev:
        role=await dev.evaluate('(()=>{'+DEV+'return s.character.active_id;})()')
        fade=await dev.evaluate("localStorage.getItem('yuiro-fade-on-hover-enabled')")
        layout=await pet.evaluate('window.yuiro.getPetLayout()');original=rect('Yuiro');cursor=w.POINT();user.GetCursorPos(c.byref(cursor))
        try:
            for target in ['hiyori','hotaru']:
                await switch(pet,dev,target);await dev.evaluate("localStorage.setItem('yuiro-fade-on-hover-enabled','false')")
                await pet.evaluate('(()=>{'+PET+"app.showSpeech('边缘避让验证：回复不压模型，长文本可以在外置窗口中滚动。',true);app.resultCard={title:'独立候选卡（固定样本）',kind:'song',items:[{name:'布局样本，不播放',song_id:'fixture-only'}],note:'fixture'};app.publishDetached();return true;})()")
                await asyncio.sleep(.5)
                area=work('Yuiro');size=rect('Yuiro');row={'role':target,'edges':[]}
                for side in ['left','right']:
                    x=area['x']+12 if side=='left' else area['x']+area['width']-size['width']-12
                    user.SetWindowPos(user.FindWindowW(None,'Yuiro'),0,x,area['y']+30,0,0,0x15)
                    await asyncio.sleep(.5)
                    b=rect('Yuiro')
                    model=await pet.evaluate('(()=>{'+PET+'const r=v.modelRect;return {x:r.left,y:r.top,width:r.width,height:r.height,vw:innerWidth,vh:innerHeight};})()')
                    sx=b['width']/model['vw'];sy=b['height']/model['vh']
                    a={'x':b['x']+max(0,model['x'])*sx,'y':b['y']+max(0,model['y'])*sy,'width':(min(model['vw'],model['x']+model['width'])-max(0,model['x']))*sx,'height':(min(model['vh'],model['y']+model['height'])-max(0,model['y']))*sy}
                    overlays=[]
                    for title in ['Yuiro 回复','Yuiro 结果']:
                        visible=bool(user.IsWindowVisible(user.FindWindowW(None,title)))
                        r=rect(title);wa=work(title)
                        assert visible,(target,side,title,'unexpectedly hidden')
                        assert not overlap(r,a),(target,side,title,r,a)
                        assert r['x']>=wa['x']-2 and r['y']>=wa['y']-2 and r['x']+r['width']<=wa['x']+wa['width']+2 and r['y']+r['height']<=wa['y']+wa['height']+2
                        overlays.append(r)
                    assert not overlap(*overlays)
                    row['edges'].append({'edge':side,'pet':b,'model':a,'overlays':overlays,'within_work_area':True,'no_overlap':True})
                # Reset to center before fading: near-window-border intentionally suppresses fade.
                user.SetWindowPos(user.FindWindowW(None,'Yuiro'),0,area['x']+area['width']//3,area['y']+60,0,0,0x15)
                await asyncio.sleep(.3)
                await dev.evaluate("localStorage.setItem('yuiro-fade-on-hover-enabled','true')")
                point=await pet.evaluate('(()=>{'+PET+'app.closeMenu();const r=v.modelRect;return {x:r.left+r.width/2,y:r.top+r.height*.55,vw:innerWidth,vh:innerHeight};})()')
                b=rect('Yuiro');user.SetCursorPos(round(b['x']+point['x']*b['width']/point['vw']),round(b['y']+point['y']*b['height']/point['vh']))
                await asyncio.sleep(.8)
                row['fade']=await pet.evaluate('(()=>{'+PET+'return {model_fades:app.shouldFade,speech_lifecycle_visible:app.speechVisible};})()')
                row['fade']['detached_reply_visible']=bool(user.IsWindowVisible(user.FindWindowW(None,'Yuiro 回复')))
                assert row['fade']['model_fades'] and row['fade']['detached_reply_visible'],row['fade']
                report['roles'].append(row)
                out=ROOT/'docs/plan/detached-ui-artifacts';out.mkdir(parents=True,exist_ok=True);(out/'edges.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(row,ensure_ascii=False),flush=True)
        finally:
            await pet.evaluate('(()=>{'+PET+'app.hideSpeech();app.clearResultCard();return true;})()')
            await switch(pet,dev,role)
            await dev.evaluate('localStorage.'+('removeItem("yuiro-fade-on-hover-enabled")' if fade is None else 'setItem("yuiro-fade-on-hover-enabled",'+json.dumps(fade)+')'))
            await pet.evaluate('window.yuiro.setPetLayout('+json.dumps(layout)+',false)')
            user.SetWindowPos(user.FindWindowW(None,'Yuiro'),0,original['x'],original['y'],0,0,0x15);user.SetCursorPos(cursor.x,cursor.y)

if __name__=='__main__':asyncio.run(main())
