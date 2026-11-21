import type { UiRect } from './detachedUi'
import type { UiAppearance } from './uiAppearance'
/** 当前两份完整身体资源的静态标定，非脸部/嘴部自动追踪。 */
export function dialogueAnchor(s:UiAppearance['speech'],path:string){
  if(s.calibratedMouth){
    if(path.toLowerCase().includes('hiyori'))return {mouthX:.7,mouthY:.22}
    if(path.toLowerCase().includes('hotaru'))return {mouthX:.7,mouthY:.28}
  }
  return {mouthX:s.mouthX,mouthY:s.mouthY}
}
/** 局部嘴部侧点向外出发，端点水平切线；不绘制箭头或闭合轮廓。 */
export function dialogueLine(model:UiRect,text:UiRect,mouthX:number,mouthY:number,fontSize:number,curvature=.25){
  const right=text.x+text.width/2>=model.x+model.width/2,dir=right?1:-1
  const sx=model.x+model.width*(right?mouthX:1-mouthX),sy=model.y+model.height*mouthY
  const ex=right?text.x-4:text.x+text.width+4,ey=text.y+Math.min(text.height-4,fontSize*1.25+8)
  const bend=Math.max(0,Math.min(70,Math.abs(ex-sx)*curvature)),pad=4
  const x=Math.min(sx,ex,sx+dir*bend,ex-dir*bend)-pad,y=Math.min(sy,ey)-pad
  const width=Math.max(sx,ex,sx+dir*bend,ex-dir*bend)-x+pad,height=Math.abs(ey-sy)+pad*2
  return {x,y,width,height,path:`M ${sx-x} ${sy-y} C ${sx+dir*bend-x} ${sy-y} ${ex-dir*bend-x} ${ey-y} ${ex-x} ${ey-y}`}
}

/** 单曲线文字以嘴部为基准抬高；气泡继续使用原 anchorY。 */
export function dialogueOffset(s:UiAppearance['speech'],path:string,height:number,panelHeight=140){
  return s.mode==='line'?height*(dialogueAnchor(s,path).mouthY-.14)-s.lineRise-s.fontSize*1.25-8:s.headAnchored?height*(dialogueAnchor(s,path).mouthY-.14)-Math.min(panelHeight*.8,180):height*(s.anchorY-.14)
}
