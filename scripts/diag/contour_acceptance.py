"""真实模型 Alpha 与 Windows 下层点击探针；不注入网页点击冒充 OS 穿透。"""
import asyncio
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
import threading

from c0_live_acceptance import DEV, PET, ROOT, Page, pages
from c0_live_scenarios import switch

OUT = ROOT / "docs/plan/contour-artifacts"


class Probe:
    def __init__(self):
        self.clicks = 0
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError("underlay probe not ready")

    def run(self):
        user = c.windll.user32
        user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
        c.windll.kernel32.GetModuleHandleW.restype = w.HMODULE
        user.DefWindowProcW.restype = c.c_ssize_t
        user.DefWindowProcW.argtypes = [w.HWND,w.UINT,w.WPARAM,w.LPARAM]
        user.CreateWindowExW.restype = w.HWND
        user.CreateWindowExW.argtypes = [w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,c.c_void_p]
        callback = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        @callback
        def procedure(hwnd, message, wp, lp):
            if message == 0x201:
                self.clicks += 1
            return user.DefWindowProcW(hwnd, message, wp, lp)
        class WC(c.Structure):
            _fields_ = [("style",w.UINT),("proc",callback),("cls",c.c_int),("win",c.c_int),
                        ("instance",w.HINSTANCE),("icon",w.HICON),("cursor",w.HANDLE),
                        ("brush",w.HBRUSH),("menu",w.LPCWSTR),("name",w.LPCWSTR)]
        instance = c.windll.kernel32.GetModuleHandleW(None)
        wc = WC(0, procedure, 0, 0, instance, None, None, c.c_void_p(6), None, "YuiroContourProbe")
        user.RegisterClassW(c.byref(wc))
        self.hwnd = user.CreateWindowExW(0x08000000, wc.name, "Yuiro 点击穿透验收探针", 0x90000000,
                                          0,0,100,100,None,None,instance,None)
        self.ready.set()
        message = w.MSG()
        while user.GetMessageW(c.byref(message), None, 0, 0) > 0:
            user.TranslateMessage(c.byref(message)); user.DispatchMessageW(c.byref(message))

    def place(self, bounds):
        c.windll.user32.SetWindowPos(self.hwnd, 0, bounds["left"], bounds["top"], bounds["width"], bounds["height"], 0x0010)


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',default=str(OUT))
    output=__import__('pathlib').Path(parser.parse_args().out)
    c.windll.user32.SetProcessDpiAwarenessContext(c.c_void_p(-4))
    user = c.windll.user32
    user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    old = w.POINT(); user.GetCursorPos(c.byref(old))
    available = await pages()
    report = {"models": [], "native_probe": "WM_LBUTTONDOWN on own underlay window"}
    async with Page(next(p for p in available if p["title"] == "Yuiro")) as pet:
        async with Page(next(p for p in available if "dev.html" in p.get("url", ""))) as dev:
            pref_keys = ['yuiro-contour-debug','yuiro-contour-threshold','yuiro-contour-tolerance','yuiro-fade-on-hover-enabled']
            original = await dev.evaluate("Object.fromEntries("+json.dumps(pref_keys)+".map(k=>[k,localStorage.getItem(k)]))")
            original_role = await dev.evaluate("(()=>{"+DEV+"return s.character.active_id;})()")
            probe = Probe()
            click_trace=[]
            async def move(point, delay=.12):
                user.FindWindowW.restype = w.HWND
                hwnd = user.FindWindowW(None, 'Yuiro')
                rect = w.RECT()
                if not hwnd or not user.GetWindowRect(hwnd,c.byref(rect)):
                    raise RuntimeError('pet native window not found')
                bounds = {"left":rect.left,"top":rect.top,"width":rect.right-rect.left,"height":rect.bottom-rect.top}
                size = await pet.evaluate('({w:innerWidth,h:innerHeight})')
                probe.place(bounds)
                tx=round(bounds["left"]+point["x"]*bounds['width']/size['w']);ty=round(bounds["top"]+point["y"]*bounds['height']/size['h'])
                if not user.SetCursorPos(tx,ty):
                    raise RuntimeError('SetCursorPos rejected by current Windows input desktop')
                await asyncio.sleep(delay)
            async def click(point):
                before = probe.clicks
                await move(point, .08)
                user.WindowFromPoint.restype=w.HWND
                pos=w.POINT();user.GetCursorPos(c.byref(pos));target=user.WindowFromPoint(pos)
                title=c.create_unicode_buffer(256);user.GetWindowTextW(target,title,256)
                click_trace.append({'requested':point,'screen':{'x':pos.x,'y':pos.y},'top':title.value,'input':await pet.evaluate('window.__yuiroContourInput')})
                user.mouse_event(2,0,0,0,0); user.mouse_event(4,0,0,0,0)
                await asyncio.sleep(.12)
                return probe.clicks-before
            try:
                ratio = await pet.evaluate("devicePixelRatio")
                report['devicePixelRatio'] = ratio
                for role in ('hiyori','hotaru'):
                    click_trace.clear()
                    await dev.evaluate("(()=>{localStorage.setItem('yuiro-fade-on-hover-enabled','false');localStorage.setItem('yuiro-contour-threshold','24');localStorage.setItem('yuiro-contour-tolerance','2');return true;})()")
                    await switch(pet,dev,role)
                    await asyncio.sleep(2)
                    points = await pet.evaluate("(()=>{"+PET+"""
const m=v.contour,r=v.modelRect;if(!m)throw Error('mask missing');let opaque=null,transparent=null,best=Infinity;
for(let j=0;j<m.height;j++)for(let i=0;i<m.width;i++){
 const x=m.left+(i+.5)*m.cssWidth/m.width,y=m.top+(j+.5)*m.cssHeight/m.height;
 const inside=x>r.left+10&&x<r.left+r.width-10&&y>r.top+10&&y<r.top+r.height-10;
 if(!inside)continue;
 const distance=Math.hypot(x-r.left-r.width/2,y-r.top-r.height/2);
 if(m.alpha[j*m.width+i]>240&&distance<best){opaque={x,y};best=distance;}
 if(!transparent&&!v.hitContour(x,y,10))transparent={x,y};
}
return {opaque,transparent,occupied:m.alpha.filter(a=>a>=24).length,w:m.width,h:m.height,path:v.currentModelPath};})()""")
                    row = {"role":role,"mask":points}
                    row["transparent_clicks_reaching_underlay"] = sum([await click(points["transparent"]) for _ in range(5)])
                    row["transparent_attempts"] = 5
                    row["transparent_input"] = await pet.evaluate('window.__yuiroContourInput')
                    row["opaque_clicks_reaching_underlay"] = sum([await click(points["opaque"]) for _ in range(3)])
                    row["opaque_attempts"] = 3
                    await dev.evaluate("localStorage.setItem('yuiro-fade-on-hover-enabled','true')")
                    await pet.evaluate("(()=>{"+PET+"app.closeMenu();return true;})()")
                    await move(points["opaque"], .65)
                    row["fades_on_body"] = await pet.evaluate("(()=>{"+PET+"return app.shouldFade;})()")
                    row["mask_while_faded"] = await pet.evaluate("(()=>{"+PET+"return v.contour.alpha.filter(a=>a>=24).length;})()")
                    row['permanent_island_removed']=await pet.evaluate("document.querySelector('.island-handle')===null")
                    row['faded_clicks_reaching_underlay']=await click(points['opaque'])
                    row['click_trace']=list(click_trace)
                    stats_before = await pet.evaluate("(()=>{"+PET+"return {...v.contourStats};})()")
                    await asyncio.sleep(3)
                    row["performance"] = await pet.evaluate("(()=>{"+PET+"return {...v.contourStats};})()")
                    row["sample_window_ms"] = 3000
                    row["window_samples"] = row["performance"]["samples"]-stats_before["samples"]
                    row["window_avg_ms"] = (row["performance"]["totalMs"]-stats_before["totalMs"])/max(1,row["window_samples"])
                    await dev.evaluate("(()=>{localStorage.setItem('yuiro-contour-debug','true');localStorage.setItem('yuiro-contour-threshold','180');localStorage.setItem('yuiro-contour-tolerance','7');return true;})()")
                    await asyncio.sleep(.3)
                    row["hot_update"] = await pet.evaluate("(()=>{"+PET+"return {threshold:v.contourPref.threshold.value,tolerance:v.contourPref.tolerance.value,debug:v.contourPref.debug.value,overlay_visible:getComputedStyle(document.querySelector('.contour-preview')).display!=='none'};})()")
                    row['frame_benchmark'] = await pet.evaluate("(async()=>{"+PET+"""
async function measure(){const values=[];let last=performance.now(),start=last;while(performance.now()-start<1500){await new Promise(requestAnimationFrame);const now=performance.now();values.push(now-last);last=now;}values.sort((a,b)=>a-b);return {frames:values.length,p95_ms:values[Math.floor(values.length*.95)],max_ms:values.at(-1)};}
v.app.ticker.remove(v.sampleContour);
let baseline;try{baseline=await measure();}finally{v.app.ticker.add(v.sampleContour,undefined,-50);}
return {sampling_paused:baseline,sampling_enabled:await measure()};})()""")
                    assert row['transparent_clicks_reaching_underlay']==5,row
                    assert row['opaque_clicks_reaching_underlay']==0,row
                    assert row['fades_on_body'] and row['faded_clicks_reaching_underlay']==1,row
                    report["models"].append(row)
                    output.mkdir(parents=True,exist_ok=True)
                    (output/'live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                    print(json.dumps({k:v for k,v in row.items() if k!='click_trace'},ensure_ascii=False),flush=True)
            finally:
                user.PostMessageW(probe.hwnd,0x0010,0,0)
                user.SetCursorPos(old.x,old.y)
                await dev.evaluate("(()=>{const original="+json.dumps(original)+";for(const [k,v] of Object.entries(original)){if(v===null)localStorage.removeItem(k);else localStorage.setItem(k,v)}return true;})()")
                await switch(pet,dev,original_role)


if __name__ == '__main__':
    asyncio.run(main())
