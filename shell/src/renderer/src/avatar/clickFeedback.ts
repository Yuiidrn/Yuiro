import type { Live2DManifest } from '@shared'
export const motionKey=(m:{group:string;index:number})=>`${m.group}#${m.index}`
export function recommendedClicks(manifest:Live2DManifest|null):string[]{
  return (manifest?.motions??[]).filter(m=>['greet','celebrate','thinking','nod','look'].includes(m.slot)||
    (m.slot==='idle'&&m.durationMs>0&&m.durationMs<=2200)).map(motionKey).slice(0,12)
}
export function validClicks(raw:unknown,manifest:Live2DManifest|null):string[]{
  if(!Array.isArray(raw))return []
  const available=new Set((manifest?.motions??[]).map(motionKey))
  return [...new Set(raw.filter((x):x is string=>typeof x==='string'&&available.has(x)))].slice(0,128)
}
export function isPetClick(dx:number,dy:number,elapsed:number):boolean{
  return Math.hypot(dx,dy)<=5&&elapsed>=0&&elapsed<=600
}
