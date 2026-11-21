import type { UiRect } from '../shared/detachedUi'
export function overlaps(a: UiRect, b: UiRect): boolean {
  return a.x < b.x+b.width && a.x+a.width > b.x && a.y < b.y+b.height && a.y+a.height > b.y
}
/** All coordinates are Electron screen DIP, including negative-origin displays. */
export function placeDetached(anchor: UiRect, work: UiRect, size: {width:number;height:number}, side: 'left'|'right', ox=0, oy=0, occupied: UiRect[]=[], requestedGap=12,protectedRects:UiRect[]=[anchor]): UiRect | null {
  const gap=Number.isFinite(requestedGap)?Math.max(4,Math.min(48,requestedGap)):12, edge=8
  const width=Math.min(size.width,work.width-edge*2), height=Math.min(size.height,work.height-edge*2)
  const clampX=(x:number)=>Math.round(Math.max(work.x+edge,Math.min(x,work.x+work.width-width-edge)))
  const clampY=(y:number)=>Math.round(Math.max(work.y+edge,Math.min(y,work.y+work.height-height-edge)))
  const left=anchor.x-width-gap, right=anchor.x+anchor.width+gap
  const top=anchor.y-height-gap, bottom=anchor.y+anchor.height+gap
  const y=anchor.y+anchor.height*.14+oy
  const candidates = side==='left' ? [[left+ox,y],[right+ox,y]] : [[right+ox,y],[left+ox,y]]
  candidates.push([anchor.x+ox,top+oy],[anchor.x+ox,bottom+oy])
  // If both windows need the same side, stack without covering the character.
  for(const r of occupied) candidates.push([r.x,r.y+r.height+gap],[r.x,r.y-height-gap])
  // Three panels can exhaust the preferred sides. Search obstacle boundaries
  // before hiding: a free corner may still exist on the same work area.
  const xs=[left+ox,right+ox,work.x+edge,work.x+work.width-width-edge]
  const ys=[y,top+oy,bottom+oy,work.y+edge,work.y+work.height-height-edge]
  for(const r of occupied){xs.push(r.x-width-gap,r.x+r.width+gap);ys.push(r.y-height-gap,r.y+r.height+gap)}
  const extra:number[][]=[]
  for(const x of xs)for(const cy of ys)extra.push([x,cy])
  const distance=([x,y]:number[])=>Math.hypot(clampX(x)+width/2-anchor.x-anchor.width/2,clampY(y)+height/2-anchor.y-anchor.height/2)
  extra.sort((a,b)=>distance(a)-distance(b))
  candidates.push(...extra)
  for(const [x,y] of candidates){
    const r={x:clampX(x),y:clampY(y),width:Math.round(width),height:Math.round(height)}
    if(!protectedRects.some(o=>overlaps(r,o)) && !occupied.some(o=>overlaps(r,o)))return r
  }
  // Never fall back to covering the model on unusually small displays.
  return null
}
