import type { Presence } from './presence'

/** 只在真实语音从聆听进入识别时回应，不把普通思考或播放缓冲当作听完。 */
export function shouldAcknowledgeListening(previous:Presence|undefined,current:Presence|undefined,
  enabled:boolean,busy:boolean,gazeOwns:boolean,now:number,last:number,cooldown:number):boolean {
  return enabled && !busy && !gazeOwns && previous==='listening' && current==='thinking'
    && now-last>=cooldown
}
