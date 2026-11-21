/** SDK的reset/同表情早退不会撤销加载预约；新指令必须先使旧预约失效。 */
export function installExpressionRequests(manager:any):()=>void {
  if(!manager||typeof manager.setExpression!=='function'||typeof manager.resetExpression!=='function'
    ||typeof manager.reserveExpressionIndex!=='number')return ()=>{}
  const set=manager.setExpression,reset=manager.resetExpression
  const invalidate=()=>{manager.reserveExpressionIndex=-1}
  const setCurrent=function(this:any,...args:any[]){
    invalidate();return set.apply(this,args)
  }
  const resetCurrent=function(this:any,...args:any[]){
    invalidate();return reset.apply(this,args)
  }
  manager.setExpression=setCurrent;manager.resetExpression=resetCurrent
  let disposed=false
  return ()=>{
    if(disposed)return
    disposed=true;invalidate()
    if(manager.setExpression===setCurrent)manager.setExpression=set
    if(manager.resetExpression===resetCurrent)manager.resetExpression=reset
  }
}
