/** 有界的显示偏好；旧宽度/透明度/位置键继续由原 composable 管理。 */
export const UI_APPEARANCE_DEFAULTS = {
  skin:'auto' as 'auto'|'cream'|'lily',theme:'light' as 'light'|'dark'|'auto', gap:12, speechSide:'right' as 'left'|'right',
  speech:{fontSize:15,lineHeight:1.55,maxHeight:400,radius:16,padding:14,comic:false,bubbleStyle:'soft' as 'soft'|'ink',ornaments:true,ornamentAlpha:.6,tail:48,headAnchored:true,anchorY:.14,border:0,
    mode:'bubble' as 'bubble'|'line',font:'system' as 'system'|'serif'|'hand'|'mono',weight:400,tracking:0,align:'left' as 'left'|'center'|'right',paragraphGap:.55,customInk:false,ink:'#ffffff',shadowColor:'#000000',shadowSize:1.5,lineColor:'#ffffff',lineWidth:1.2,lineRise:40,lineBend:.25,calibratedMouth:true,mouthX:.7,mouthY:.16},
  island:{size:44,gap:60,distance:50,alpha:.66,radius:50,offsetY:0,duration:280},
  results:{fontSize:12,lineHeight:1.5,maxHeight:420,radius:16,padding:12,compact:false,
    stackPlayers:false,showAvailableNote:true,showOfficialPage:true,seconds:20},
  source:{independent:false,width:280,fontSize:12,maxHeight:380,summaryLines:3,showDate:true,seconds:40},
}
export type UiAppearance=typeof UI_APPEARANCE_DEFAULTS
export type PanelKind='speech'|'music'|'source'
const obj=(v:unknown):Record<string,unknown>=>v&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:{}
const n=(v:unknown,def:number,lo:number,hi:number)=>typeof v==='number'&&Number.isFinite(v)?Math.max(lo,Math.min(hi,v)):def
const b=(v:unknown,def:boolean)=>typeof v==='boolean'?v:def
const color=(v:unknown,def:string)=>typeof v==='string'&&/^#[0-9a-f]{6}$/i.test(v)?v:def
export function normalizeUiAppearance(value:unknown):UiAppearance {
  const p=obj(value),s=obj(p.speech),r=obj(p.results),q=obj(p.source),i=obj(p.island),d=UI_APPEARANCE_DEFAULTS
  return {
    skin:p.skin==='cream'||p.skin==='lily'?p.skin:'auto',theme:p.theme==='auto'||p.theme==='dark'?p.theme:'light',gap:n(p.gap,d.gap,4,48),speechSide:p.speechSide==='left'?'left':'right',
    speech:{fontSize:n(s.fontSize,15,10,36),lineHeight:n(s.lineHeight,1.55,1,2.5),maxHeight:n(s.maxHeight,400,80,900),radius:n(s.radius,16,0,100),padding:n(s.padding,14,4,48),comic:b(s.comic,false),bubbleStyle:s.bubbleStyle==='ink'?'ink':'soft',ornaments:b(s.ornaments,true),ornamentAlpha:n(s.ornamentAlpha,.6,0,1),tail:n(s.tail,48,0,120),headAnchored:b(s.headAnchored,true),anchorY:n(s.anchorY,.14,-.8,1.2),border:n(s.border,0,0,4),
      mode:s.mode==='line'?'line':'bubble',font:s.font==='serif'||s.font==='hand'||s.font==='mono'?s.font:'system',weight:n(s.weight,400,300,800),tracking:n(s.tracking,0,-.5,6),align:s.align==='center'||s.align==='right'?s.align:'left',paragraphGap:n(s.paragraphGap,.55,.1,2),customInk:b(s.customInk,false),ink:color(s.ink,'#ffffff'),shadowColor:color(s.shadowColor,'#000000'),shadowSize:n(s.shadowSize,1.5,0,5),lineColor:color(s.lineColor,'#ffffff'),lineWidth:n(s.lineWidth,1.2,.5,4),lineRise:n(s.lineRise,40,0,240),lineBend:n(s.lineBend,.25,0,.8),calibratedMouth:b(s.calibratedMouth,true),mouthX:n(s.mouthX,.7,.5,.95),mouthY:n(s.mouthY,.16,.02,.4)},
    island:{size:n(i.size,44,28,80),gap:n(i.gap,60,32,120),distance:n(i.distance,50,12,180),alpha:n(i.alpha,.66,.05,1),radius:n(i.radius,50,0,50),offsetY:n(i.offsetY,0,-200,200),duration:n(i.duration,280,0,600)},
    results:{fontSize:n(r.fontSize,12,11,20),lineHeight:n(r.lineHeight,1.5,1.2,2),maxHeight:n(r.maxHeight,420,160,440),radius:n(r.radius,16,0,32),padding:n(r.padding,12,8,24),compact:b(r.compact,false),stackPlayers:b(r.stackPlayers,false),showAvailableNote:b(r.showAvailableNote,true),showOfficialPage:b(r.showOfficialPage,true),seconds:n(r.seconds,20,0,120)},
    source:{independent:b(q.independent,false),width:n(q.width,280,160,420),fontSize:n(q.fontSize,12,11,20),maxHeight:n(q.maxHeight,380,160,440),summaryLines:Math.round(n(q.summaryLines,3,1,8)),showDate:b(q.showDate,true),seconds:n(q.seconds,40,0,120)},
  }
}
export function panelAppearance(p:UiAppearance,kind:PanelKind,petTheme:string,skin:'cream'|'lily'='cream'):Record<string,string> {
  const dark=p.theme==='dark'||(p.theme==='auto'&&petTheme==='dark')
  const base=kind==='speech'?p.speech:p.results
  const font=kind==='source'&&p.source.independent?p.source.fontSize:base.fontSize
  const height=kind==='source'&&p.source.independent?p.source.maxHeight:base.maxHeight
  const lily=skin==='lily'
  return {'--panel-rgb':dark?(lily?'29, 35, 43':'36, 32, 29'):'255, 255, 255','--panel-text':dark?'#f2e7d6':lily?'#35434c':'#29221c',
    '--panel-accent':lily?(dark?'#b8cdc4':'#506e62'):dark?'#edc48b':'#8a5a12','--panel-border':lily?(dark?'#73888c':'#a9bbba'):dark?'#79644b':'#cbb78e',
    '--panel-font':`${font}px`,'--panel-line':String(base.lineHeight),'--panel-height':`${height}px`,
    '--panel-radius':`${base.radius}px`,'--panel-padding':`${base.padding}px`,
    '--panel-row':p.results.compact?'2px':'6px','--source-lines':String(p.source.summaryLines)}
}

export function resolveSkin(choice:UiAppearance['skin'],role:string):'cream'|'lily'{return choice==='auto'?(role==='hotaru'?'lily':'cream'):choice}
