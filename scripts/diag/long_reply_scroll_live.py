"""独立回复窗真实滚轮/末行可达检查；临时UI消息，不经LLM/记忆。"""
import asyncio
import base64
import json
from pathlib import Path

exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])


async def main():
    pet=next(p for p in pages() if 'index.html' in p['url'])
    out=Path('docs/plan/long-reply-scroll-artifacts');out.mkdir(exist_ok=True)
    text='### 长回复阅读检查\n\n'+('\n\n'.join(f'第{i}段：女孩后来成为了植物学家。每次野外考察，她都会捡一片特别的叶子带回来，与时光对话。' for i in range(1,31)))+'\n\n【全文结束】'
    async def publish(c,e):
        await c('Page.enable')
        return await e("(()=>{const a=document.querySelector('canvas.live2d-canvas').getBoundingClientRect();window.yuiro.publishDetached({key:'long-scroll-ui-fixture',viewport:{width:innerWidth,height:innerHeight},anchor:{x:a.x+a.width*.35,y:a.y+a.height*.12,width:a.width*.3,height:a.height*.7},gap:12,speech:{visible:true,text:"+json.dumps(text)+",width:240,alpha:.95,offsetX:0,offsetY:0,side:'right'},results:null,sources:null});return true})()")
    try:
        await connect(pet,publish);await asyncio.sleep(1)
        speech=next(p for p in pages() if 'kind=speech' in p['url'])
        async def inspect(c,e):
            await c('Page.enable');await c('Page.reload');await asyncio.sleep(1)
            await connect(pet,publish);await asyncio.sleep(.7)
            await c('Page.bringToFront')
            read="(()=>{const a=document.querySelector('.reply-surface'),f=document.querySelector('.reply-footer');return {client:a.clientHeight,scroll:a.scrollHeight,top:a.scrollTop,rect:a.getBoundingClientRect().toJSON(),footer:f?.getBoundingClientRect().toJSON(),viewport:innerHeight,scrollbar:getComputedStyle(a).scrollbarWidth}})()"
            before=await e(read)
            before['visibility']=await e('document.visibilityState')
            assert before['scroll']>before['client'],before
            shot=await c('Page.captureScreenshot');(out/'top.png').write_bytes(base64.b64decode(shot['data']))
            r=before['rect']
            before['hit']=await e("document.elementFromPoint(110,80)?.outerHTML.slice(0,180)")
            await e("window.__wheelEvents=[];document.querySelector('.reply-surface').addEventListener('wheel',e=>__wheelEvents.push({dy:e.deltaY,target:e.target.className,prevented:e.defaultPrevented}),{capture:true})")
            await c('Input.dispatchMouseEvent',{'type':'mouseMoved','x':r['x']+r['width']/2,'y':r['y']+min(80,r['height']/2)})
            await c('Input.dispatchMouseEvent',{'type':'mouseWheel','x':r['x']+r['width']/2,'y':r['y']+min(80,r['height']/2),'deltaX':0,'deltaY':300})
            await asyncio.sleep(.3)
            wheel=await e(read);wheel['events']=await e('window.__wheelEvents');wheel['visibility']=await e('document.visibilityState');wheel['hit']=before['hit'];assert wheel['top']>0,wheel
            await e("document.querySelector('.reply-surface').scrollTop=document.querySelector('.reply-surface').scrollHeight")
            await asyncio.sleep(.15)
            bottom=await e(read)
            end=await e("(()=>{const a=document.querySelector('.reply-surface'),b=a.lastElementChild,r=a.getBoundingClientRect(),z=b.getBoundingClientRect();return {text:b.textContent,visible:z.bottom<=r.bottom+1&&z.top>=r.top}})()")
            assert end['visible'] and '全文结束' in end['text'],end
            assert bottom['rect']['bottom']<=bottom['viewport']+1,bottom
            if bottom['footer']:assert bottom['rect']['bottom']<=bottom['footer']['top']+1,bottom
            shot=await c('Page.captureScreenshot');(out/'bottom.png').write_bytes(base64.b64decode(shot['data']))
            return {'before':before,'afterWheel':wheel,'bottom':bottom,'lastParagraph':end}
        report=await connect(speech,inspect)
        report['scope']='actual detached renderer, temporary long Markdown UI fixture, CDP wheel, no engine conversation or settings changes'
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    finally:
        async def reset(c,e):
            await c('Page.enable');await c('Page.reload')
        await connect(pet,reset)

asyncio.run(main())
