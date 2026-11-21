import type { AgentActivityFrame } from '../../../shared/engine-protocol'
/** 本地反应只消费事实；每个工具批次结果最多一次，不追加模型请求。 */
export class AgentReactions {
  private seen=new Set<string>()
  private lastStart=-Infinity
  private lastResult=-Infinity
  reset(){this.seen.clear();this.lastStart=-Infinity;this.lastResult=-Infinity}
  plan(frame:AgentActivityFrame,now:number,cooldown:number){
    if(!frame.activity_id||frame.tool==='avatar_perform'||frame.outcome==='unknown')return null
    if(frame.stage==='tool'?frame.outcome!=='running':frame.stage!=='tool_result'||!['success','waiting','error'].includes(frame.outcome))return null
    const key=`${frame.activity_id}:${frame.stage}`
    if(this.seen.has(key))return null
    this.seen.add(key)
    if(this.seen.size>128)this.seen.delete(this.seen.values().next().value!)
    const result=frame.stage==='tool_result'
    if(now-(result?this.lastResult:this.lastStart)<cooldown)return null
    if(result)this.lastResult=now;else this.lastStart=now
    return {expression_slot:frame.outcome==='success'?'happy':frame.outcome==='error'?'neutral':'thinking',
      motion:frame.outcome==='waiting'||frame.outcome==='error'?null:frame.motion_group||null,motion_index:frame.motion_index??null,
      motion_slot:frame.outcome==='error'||frame.outcome==='waiting'?null:frame.motion_slot||'thinking',
      duration_ms:1100,priority:2,source:'activity'}
  }
}
