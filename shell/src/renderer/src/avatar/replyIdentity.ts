import type { ReplySpeechIdentity } from '../../../shared/engine-protocol'
/** 缺身份、其他会话或旧代际帧均不能改变当前播放队列及结束状态。 */
export function acceptsReplySpeech(frame:Partial<ReplySpeechIdentity>,sessionId:string,generation:number):boolean{
  return !!sessionId&&frame.session_id===sessionId&&Number.isInteger(frame.generation)&&Number(frame.generation)>=generation
}
