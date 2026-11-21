import { app, BrowserWindow, ipcMain, screen } from 'electron'
import { join } from 'node:path'
import type { DetachedAction, DetachedState, UiKind, UiRect } from '../shared/detachedUi'
import { placeDetached } from './detachedLayout'
import { dialogueLine } from '../shared/dialogueLine'

/** Lazy presentation windows; no Engine connection, Agent or playback ownership. */
export function registerDetachedUi(getPet:()=>BrowserWindow|null):void {
  let state:DetachedState|null=null
  const windows:Partial<Record<UiKind,BrowserWindow>>={}
  const sizes:Record<UiKind,{width:number;height:number}>={speech:{width:220,height:120},results:{width:250,height:240},sources:{width:250,height:240}}
  const ready=new Set<UiKind>()
  const delivered:Partial<Record<UiKind,string>>={}
  const measuredKey:Partial<Record<UiKind,string>>={}
  let boundPet:BrowserWindow|null=null
  const kinds:UiKind[]=['speech','results','sources']
  let connector:BrowserWindow|null=null,lineReady=false
  function hide():void {for(const w of Object.values(windows))if(!w.isDestroyed())w.hide();connector?.hide()}
  function drawLine(anchor:UiRect,text:UiRect):UiRect|null {
    const s=state?.speech.line
    if(!state||!s){connector?.hide();return null}
    if(![s.mouthX,s.mouthY,s.fontSize,s.stroke].every(Number.isFinite)||s.mouthX<.5||s.mouthX>.95||s.mouthY<.02||s.mouthY>.4||s.fontSize<10||s.fontSize>36||s.stroke<.5||s.stroke>4||!/^#[0-9a-f]{6}$/i.test(s.color)){connector?.hide();return null}
    if(!Number.isFinite(s.rise??40)||!Number.isFinite(s.bend??.25)||(s.rise??40)<0||(s.rise??40)>240||(s.bend??.25)<0||(s.bend??.25)>.8){connector?.hide();return null}
    const l=dialogueLine(anchor,text,s.mouthX,s.mouthY,s.fontSize,s.bend??.25)
    if(!connector||connector.isDestroyed()){
      connector=new BrowserWindow({parent:getPet()??undefined,show:false,frame:false,transparent:true,alwaysOnTop:true,skipTaskbar:true,hasShadow:false,focusable:false,resizable:false,webPreferences:{preload:join(__dirname,'../preload/index.mjs'),sandbox:false,backgroundThrottling:false}})
      connector.setIgnoreMouseEvents(true,{forward:true});connector.setAlwaysOnTop(true,'screen-saver');connector.setContentProtection(!(process.env['YUIRO_UI_CAPTURE']==='1'&&!app.isPackaged))
      connector.webContents.setWindowOpenHandler(()=>({action:'deny'}));connector.webContents.on('will-navigate',e=>e.preventDefault())
      connector.on('closed',()=>{connector=null;lineReady=false})
      connector.webContents.on('render-process-gone',()=>{connector?.hide();lineReady=false})
      if(process.env['ELECTRON_RENDERER_URL'])void connector.loadURL(`${process.env['ELECTRON_RENDERER_URL']}/detached.html?kind=connector`)
      else void connector.loadFile(join(__dirname,'../renderer/detached.html'),{query:{kind:'connector'}})
    }
    if(!lineReady)return l
    connector.setBounds({x:Math.floor(l.x),y:Math.floor(l.y),width:Math.ceil(l.width),height:Math.ceil(l.height)})
    connector.webContents.send('detached:line',{key:state.key,path:l.path,width:l.width,height:l.height,color:s.color,stroke:s.stroke})
    if(!connector.isVisible())connector.showInactive()
    return l
  }
  function ensure(kind:UiKind):BrowserWindow {
    if(windows[kind]&&!windows[kind]!.isDestroyed())return windows[kind]!
    const w=new BrowserWindow({parent:getPet()??undefined,width:250,height:240,show:false,frame:false,transparent:true,alwaysOnTop:true,skipTaskbar:true,hasShadow:false,roundedCorners:false,focusable:true,resizable:false,
      webPreferences:{preload:join(__dirname,'../preload/index.mjs'),sandbox:false,backgroundThrottling:false}})
    windows[kind]=w
    w.setAlwaysOnTop(true,'screen-saver')
    w.setContentProtection(!(process.env['YUIRO_UI_CAPTURE']==='1'&&!app.isPackaged))
    w.webContents.setWindowOpenHandler(()=>({action:'deny'}))
    w.webContents.on('will-navigate',e=>e.preventDefault())
    w.on('closed',()=>{delete windows[kind];ready.delete(kind);delete delivered[kind]})
    w.webContents.on('render-process-gone',()=>{ready.delete(kind);w.hide();delete delivered[kind]})
    if(process.env['ELECTRON_RENDERER_URL'])void w.loadURL(`${process.env['ELECTRON_RENDERER_URL']}/detached.html?kind=${kind}`)
    else void w.loadFile(join(__dirname,'../renderer/detached.html'),{query:{kind}})
    return w
  }
  function senderKind(id:number):UiKind|undefined {return kinds.find(k=>windows[k]?.webContents.id===id)}
  function layout():void {
    const pet=getPet()
    if(!state||!pet||pet.isDestroyed()||!pet.isVisible()||pet.isMinimized()){hide();return}
    if(boundPet!==pet){
      boundPet=pet
      pet.on('move',layout);pet.on('resize',layout);pet.on('hide',hide);pet.on('minimize',hide);pet.on('show',layout)
      pet.webContents.on('did-start-loading',()=>{state=null;hide()})
      pet.webContents.on('render-process-gone',()=>{state=null;hide()})
      pet.on('closed',()=>{state=null;connector?.destroy();for(const w of Object.values(windows))if(!w.isDestroyed())w.destroy()})
    }
    const b=pet.getBounds(), sx=b.width/state.viewport.width,sy=b.height/state.viewport.height
    const a=state.anchor
    // Only visible model portion is protected; off-window model geometry is not desktop content.
    const x=Math.max(0,a.x),y=Math.max(0,a.y)
    const anchor={x:b.x+x*sx,y:b.y+y*sy,width:Math.max(1,Math.min(state.viewport.width,a.x+a.width)-x)*sx,height:Math.max(1,Math.min(state.viewport.height,a.y+a.height)-y)*sy}
    const validOutline=Array.isArray(state.outline)&&state.outline.length&&state.outline.length<=16&&state.outline.every(r=>[r.x,r.y,r.width,r.height].every(Number.isFinite)&&r.width>0&&r.height>0&&r.x>=-8&&r.y>=-8&&r.x+r.width<=state!.viewport.width+8&&r.y+r.height<=state!.viewport.height+8)
    const outline=validOutline?state.outline!.map(r=>({x:b.x+r.x*sx,y:b.y+r.y*sy,width:r.width*sx,height:r.height*sy})):[]
    const work=screen.getDisplayMatching(b).workArea
    const occupied:UiRect[]=[]
    for(const kind of kinds){
      const content=kind==='speech' ? (state.speech.visible&&state.speech.text.trim()?state.speech:null) : state[kind]
      if(!content){windows[kind]?.hide();if(kind==='speech')connector?.hide();continue}
      const w=ensure(kind)
      if(!ready.has(kind))continue
      const payload={key:state.key,speech:{...state.speech},results:state.results,sources:state.sources}
      if(kind==='speech'){const old=w.getBounds();payload.speech.tipY=Number.isFinite(state.speech.headY)?Math.max(20,Math.min(old.height-16,anchor.y+anchor.height*state.speech.headY!-old.y)):undefined;payload.speech.tailSide=old.x+old.width/2<anchor.x+anchor.width/2?'right':'left'}
      const serialized=JSON.stringify(payload)
      if(delivered[kind]!==serialized){delivered[kind]=serialized;w.webContents.send('detached:state',payload)}
      if(measuredKey[kind]!==state.key){w.hide();if(kind==='speech')connector?.hide();continue}
      const line=state.speech.line
      const extraY=kind==='speech'?(line?anchor.height*(line.mouthY-.14)-(line.rise??40)-line.fontSize*1.25-8:(Number.isFinite(state.speech.headY)?anchor.height*(state.speech.headY!-.14)-Math.min(sizes.speech.height*.8,180):anchor.height*((state.speech.anchorY??.14)-.14))):0
      let placementAnchor=anchor
      const protectedRects=kind==='speech'&&outline.length?outline:[anchor]
      if(kind==='speech'&&outline.length){
        const top=anchor.y+anchor.height*.14+content.offsetY+extraY
        const bands=outline.filter(r=>r.y<top+sizes.speech.height&&r.y+r.height>top)
        if(bands.length){const left=Math.min(...bands.map(r=>r.x)),right=Math.max(...bands.map(r=>r.x+r.width));placementAnchor={...anchor,x:left,width:right-left}}
      }
      const p=placeDetached(placementAnchor,work,sizes[kind],kind==='speech'?(state.speech.side??'right'):state[kind]!.side,content.offsetX,content.offsetY+extraY,occupied,state.gap,protectedRects)
      if(!p){w.hide();if(kind==='speech')connector?.hide();continue}
      occupied.push(p)
      const old=w.getBounds()
      if(old.x!==p.x||old.y!==p.y||old.width!==p.width||old.height!==p.height)w.setBounds(p)
      if(kind==='speech'){
        payload.speech.tipY=Number.isFinite(state.speech.headY)?Math.max(20,Math.min(p.height-16,anchor.y+anchor.height*state.speech.headY!-p.y)):undefined
        payload.speech.tailSide=p.x+p.width/2<anchor.x+anchor.width/2?'right':'left'
        const next=JSON.stringify(payload)
        if(delivered[kind]!==next){delivered[kind]=next;w.webContents.send('detached:state',payload)}
      }
      if(!w.isVisible())w.showInactive()
      if(kind==='speech'){const line=drawLine(anchor,p);if(line)occupied.push(line)}
    }
  }
  ipcMain.on('detached:publish',(e,s:DetachedState)=>{
    if(e.sender!==getPet()?.webContents)return
    if(!s||!s.viewport||![s.viewport.width,s.viewport.height,s.anchor?.x,s.anchor?.y,s.anchor?.width,s.anchor?.height].every(Number.isFinite)||s.viewport.width<=0||s.viewport.height<=0)return
    state=s;layout()
  })
  ipcMain.on('detached:ready',(e)=>{if(e.sender===connector?.webContents){lineReady=true;layout();return}const kind=senderKind(e.sender.id);if(!kind)return;ready.add(kind);delete delivered[kind];layout()})
  ipcMain.on('detached:size',(e,s:{width:number;height:number;key:string})=>{
    const kind=senderKind(e.sender.id);if(!kind||![s?.width,s?.height].every(Number.isFinite))return
    if(s.key!==state?.key)return
    const next={width:Math.max(100,Math.min(1024,Math.ceil(s.width))),height:Math.max(40,Math.min(1000,Math.ceil(s.height)))}
    if(measuredKey[kind]===s.key&&sizes[kind].width===next.width&&sizes[kind].height===next.height)return
    measuredKey[kind]=s.key
    sizes[kind]=next;layout()
  })
  ipcMain.on('detached:action',(e,a:DetachedAction)=>{
    const kind=senderKind(e.sender.id)
    if(!kind||!state||a?.kind!==kind||a.key!==state.key)return
    if(a.action && !['pick','open_official','client_play','client_pause','client_resume','client_like','client_unlike'].includes(a.action))return
    const control=a.action==='client_pause'||a.action==='client_resume'||a.action==='client_like'||a.action==='client_unlike'
    if(control&&(kind!=='results'||!state.results?.playback))return
    if(kind==='sources'&&a.action&&a.action!=='pick')return
    if(!a.dismiss&&!control&&(kind==='speech'||!Number.isInteger(a.index)||a.index!<0||a.index!>=(state[kind]?.items.length??0)))return
    getPet()?.webContents.send('detached:action',a)
  })
  screen.on('display-metrics-changed',layout)
  screen.on('display-added',layout)
  screen.on('display-removed',layout)
}
