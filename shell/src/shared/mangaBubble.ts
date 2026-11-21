/** 一条闭合轮廓将圆润框体和弯曲尖尾合并；坐标为实际DIP，避免SVG非等比拉伸描边。 */
export function mangaBubble(width:number,height:number,tail:number,radius:number,tipY?:number){
 const w=Math.max(80,width),h=Math.max(60,height),t=Math.max(0,Math.min(tail,w*.3)),x=6+t,y=6,right=w-6,bottom=h-8
 const r=Math.max(12,Math.min(radius||28,(right-x)/2,(bottom-y)*(t?.28:.5))),low=Math.min(bottom-r-2,y+(bottom-y)*.77),high=Math.min(low-12,Math.max(y+r+2,y+(bottom-y)*.53))
 const tip=typeof tipY==='number'&&Number.isFinite(tipY)?Math.max(y+r+5,Math.min(bottom-r-5,tipY)):bottom+3
 const lo=tipY===undefined?low:Math.min(bottom-r-2,tip+18),hi=tipY===undefined?high:Math.max(y+r+2,lo-30)
 const left=t?`L ${x} ${lo} C ${x-3} ${lo+10} 12 ${tip+4} 5 ${tip} C 19 ${tip-2} ${x+5} ${hi+13} ${x} ${hi}`:''
 return `M ${x+r} ${y} H ${right-r} Q ${right} ${y} ${right} ${y+r} V ${bottom-r} Q ${right} ${bottom} ${right-r} ${bottom} H ${x+r} Q ${x} ${bottom} ${x} ${bottom-r} ${left} V ${y+r} Q ${x} ${y} ${x+r} ${y} Z`
}
