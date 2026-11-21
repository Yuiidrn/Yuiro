/** Cubism4：自动眨眼先写基础眼睛值，表情随后合成；不改SDK包或表情曲线。 */
const installed=new WeakMap<object,()=>void>()
export function installExpressionBlinkOrder(internal:any):()=>void {
  if(!internal)return ()=>{}
  const existing=installed.get(internal)
  if(existing)return existing
  const manager=internal.motionManager,blink=internal.eyeBlink
  if(!internal.coreModel||!blink||typeof blink.updateParameters!=='function'||typeof manager?.update!=='function'
    ||typeof internal.update!=='function'||typeof internal.on!=='function'||typeof internal.off!=='function')return ()=>{}
  const update=internal.update,updateMotion=manager.update,updateBlink=blink.updateParameters
  let deltaSeconds=0,motionUpdated=false,closed=false
  const modelUpdate=function(this:any,...args:any[]){
    deltaSeconds=Number(args[0])/1000;motionUpdated=false
    return update.apply(this,args)
  }
  const motionUpdate=function(this:any,...args:any[]){
    const result=updateMotion.apply(this,args);motionUpdated=!!result;return result
  }
  const skipLateBlink=()=>{}
  const beforeExpression=()=>{
    if(!motionUpdated)updateBlink.call(blink,internal.coreModel,deltaSeconds)
  }
  internal.update=modelUpdate;manager.update=motionUpdate;blink.updateParameters=skipLateBlink
  internal.on('afterMotionUpdate',beforeExpression)
  const dispose=()=>{
    if(closed)return
    closed=true;internal.off('afterMotionUpdate',beforeExpression)
    if(internal.update===modelUpdate)internal.update=update
    if(manager.update===motionUpdate)manager.update=updateMotion
    if(blink.updateParameters===skipLateBlink)blink.updateParameters=updateBlink
    installed.delete(internal)
  }
  installed.set(internal,dispose)
  return dispose
}
