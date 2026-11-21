/** 仅使用renderer局部坐标，保持滚动/吸顶和非整数DPI下的截图稳定。 */
export function previewCrop(layout:{cx:number;cy:number;w:number;h:number},head:boolean,
  pixelWidth:number,pixelHeight:number,screenWidth:number,screenHeight:number){
  const width=head?layout.w*.65:layout.w,height=head?layout.h*.34:layout.h
  const outputHeight=head?180:240,fit=Math.min(168/width,(outputHeight-12)/height)
  return {sx:(layout.cx-width/2)*pixelWidth/screenWidth,
    sy:(layout.cy-layout.h/2)*pixelHeight/screenHeight,
    sw:width*pixelWidth/screenWidth,sh:height*pixelHeight/screenHeight,
    dx:(180-width*fit)/2,dy:(outputHeight-height*fit)/2,dw:width*fit,dh:height*fit}
}

/** 从低分辨率全身预览的可见轮廓取头像，忽略模型画布透明边距。 */
export function alphaHeadCrop(data:ArrayLike<number>,width:number,height:number){
  let left=width,right=-1,top=height,bottom=-1
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    if(data[(y*width+x)*4+3]>20){
      left=Math.min(left,x);right=Math.max(right,x)
      top=Math.min(top,y);bottom=Math.max(bottom,y)
    }
  }
  if(right<left)return null
  const size=Math.min(width,height,Math.max((right-left+1)*.75,(bottom-top+1)*.30)+8)
  return {sx:Math.max(0,Math.min(width-size,(left+right+1-size)/2)),
    sy:Math.max(0,Math.min(height-size,top-4)),sw:size,sh:size}
}
