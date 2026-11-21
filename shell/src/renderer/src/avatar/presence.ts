/** 本地表现状态只响应现有链路事件，不产生网络请求。 */
export type Presence = 'idle' | 'listening' | 'thinking' | 'speaking'
export function presenceAfter(current: Presence, type: string, state?: string): Presence {
  // 控制连接与音频播放独立；文字请求断线要退思考，已有音频仍按真实播放收尾。
  if(type==='mic:stop')return current==='speaking'||current==='thinking'?current:'idle'
  if(type==='control:closed')return current==='speaking'?current:'idle'
  if (['tts:interrupted','tts:playback_cancelled','ws:closed','asr:error','llm:error','tts:error','asr:dropped','tts:playback_end','tts:playback_empty','avatar:reset'].includes(type)) return 'idle'
  if (type === 'vad:state' && state === 'active') return 'listening'
  if (['asr:start','llm:start','chat:sent'].includes(type)) return 'thinking'
  if (type === 'tts:playback_start') return 'speaking'
  if (['tts:playback_waiting','tts:start','tts:synthesize'].includes(type)) return current === 'speaking' ? current : 'thinking'
  if (type === 'tts:playback_buffering') return current === 'speaking' ? 'thinking' : current
  if (type === 'chat:assistant' || type === 'llm:text') return current === 'speaking' ? current : 'idle'
  return current
}
