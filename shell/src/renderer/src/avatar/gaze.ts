/** 窗口CSS坐标→轻量注视目标，远离模型时回正，不追踪整块桌面。 */
export function gazeTarget(x:number,y:number,rect:{left:number;top:number;width:number;height:number},strength:number):[number,number]{
  if(![x,y,rect.left,rect.top,rect.width,rect.height,strength].every(Number.isFinite)||rect.width<=0||rect.height<=0)return [0,0]
  const dx=(x-rect.left-rect.width/2)/rect.width
  const dy=(y-rect.top-rect.height*.2)/rect.height
  if(Math.abs(dx)>1.5||Math.abs(dy)>1.5)return [0,0]
  const amount=Math.max(0,Math.min(.4,strength))
  return [Math.max(-1,Math.min(1,dx))*amount,-Math.max(-1,Math.min(1,dy*2.4))*amount]
}

/** 只有附近真实移动才续租注视；静止超过holdMs后归还待机所有权。 */
export class GazeActivity {
  private x=NaN
  private y=NaN
  private until=0
  step(x:number,y:number,near:boolean,now:number,holdMs:number):boolean{
    if(!Number.isFinite(x)||!Number.isFinite(y)){this.reset();return false}
    if(!Number.isFinite(this.x)){this.x=x;this.y=y;return false}
    const moved=Math.hypot(x-this.x,y-this.y)>1
    if(moved||!near){this.x=x;this.y=y}
    if(!near){this.until=0;return false}
    if(moved)this.until=now+Math.max(500,Math.min(10000,holdMs))
    return now<this.until
  }
  reset():void{this.x=NaN;this.y=NaN;this.until=0}
}

export function applyGaze(core:{getParameterValueById:(id:string)=>number;setParameterValueById:(id:string,v:number)=>void},ids:Set<string>,x:number,y:number,weight:number):void{
  const values:Record<string,number>={ParamAngleX:x*30,ParamAngleY:y*30,ParamEyeBallX:Math.max(-.8,Math.min(.8,x*2)),ParamEyeBallY:Math.max(-.8,Math.min(.8,y*2))}
  for(const [id,target] of Object.entries(values))if(ids.has(id)){
    const current=core.getParameterValueById(id)
    core.setParameterValueById(id,current+(target-current)*Math.max(0,Math.min(1,weight)))
  }
}

/** 从上一帧显示姿态追随实时目标，避免目标移动或待机接管时产生跳变。 */
export function followPose(current:number,target:number,dtMs:number,eye:boolean):number{
  const dt=Math.max(0,Math.min(50,Number.isFinite(dtMs)?dtMs:0))/1000
  const tau=eye?.22:.38
  const maxSpeed=eye?2:45
  const delta=(target-current)*(1-Math.exp(-dt/tau))
  return current+Math.max(-maxSpeed*dt,Math.min(maxSpeed*dt,delta))
}
