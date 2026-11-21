import type { AlphaMask } from './alphaHit'
import type { UiRect } from '../../../shared/detachedUi'
let previous:AlphaMask|null=null,cached:UiRect[]=[]
/** 复用已有低分辨率遮罩，16段保守包络；不新增GPU读回。 */
export function contourBands(mask:AlphaMask|null):UiRect[]{
 if(!mask)return []
 if(mask===previous)return cached
 previous=mask;cached=[]
 const {width:w,height:h,alpha,cssWidth,cssHeight,left,top}=mask
 for(let row=0;row<h;row+=Math.ceil(h/16)){
  const end=Math.min(h,row+Math.ceil(h/16));let lo=w,hi=-1
  for(let y=row;y<end;y++)for(let x=0;x<w;x++)if(alpha[y*w+x]>=4){lo=Math.min(lo,x);hi=Math.max(hi,x)}
  if(hi>=lo)cached.push({x:left+lo*cssWidth/w-4,y:top+row*cssHeight/h-4,width:(hi-lo+1)*cssWidth/w+8,height:(end-row)*cssHeight/h+8})
 }
 return cached
}
