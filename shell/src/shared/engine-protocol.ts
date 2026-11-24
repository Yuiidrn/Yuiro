/** 新增客户端搜索消息的单一类型来源；旧 WS 事件暂沿用既有实现。 */
export interface ClientSearchRequest {
  type:'media:search';backend:'netease_client';keyword:string;request_id:number;daily?:boolean;
  character_id:string;character_revision:number;session_id:string
}
export interface ClientSearchReply {
  type:'media:search-result';request_id:number;character_id:string;character_revision:number;session_id:string;
  status:'ok'|'error';keyword:string;items:Record<string,unknown>[];note:string
}

/** 原文直存复用独立日记会话，不进入Agent/工具循环。 */
export interface DiarySaveRawRequest {title?:string;attachment_ids?:string[];type:'diary:save_raw';privacy:'local_only'|'shared'|'discard'}

/** 日记陪伴轨道：只生成短句，不保存正文、不调用工具。 */
export type DiaryQuipRequest = {type:'diary:quip';text:string;idle_s:number;request_id:number} | {type:'diary:quip_cancel'}

export interface DiaryInteractionRequest {type:"diary:interact";request_id:number;kind:"short"|"paragraph";text:string;segment_id:string|null;tts:boolean}

/** 已认证控制连接上的渲染回执；引擎按意图ID和会话验证。 */
export interface AvatarPlaybackReceipt {
  type:'avatar:receipt';intent_id:string;session_id:string;
  phase:'started'|'finished'|'cancelled';duration_ms?:number
}

/** 文字回复朗读帧绑定权威会话与generation，旧回合不能重新入队。 */
export interface ReplySpeechIdentity { session_id:string;generation:number;reply_request_id?:string;character_id?:string }
export interface ControlInterrupt { type:'interrupt' }
export interface ChatUserRequest {
  type:'chat:user';text:string;web_search?:boolean;stream_reply?:boolean;reply_request_id?:string;
  bilingual_order?:BilingualOrder|'baseline'
}
export interface ControlInterruptComplete extends ReplySpeechIdentity {
  type:'interrupt:complete';settle_ms:number
}
export interface ChatBusy { type:'chat:busy';message:string }
/** 仅显式开启服务端实验后允许，普通输入始终走既有 AgentLoop。 */
export type BilingualOrder='ja_first'|'zh_first'
export interface BilingualSentence extends ReplySpeechIdentity {
  type:'chat:sentence';text:string;reply_request_id:string
}
export interface OutputExperimentMetrics {
  type:'experiment:metrics'|'experiment:audio_metrics';session_id:string;generation:number;
  reply_request_id:string;metrics?:Record<string,unknown>;stages_ms?:Record<string,number>
}
/** 回合中间状态也会影响口型/气泡/表现，必须与音频共享身份护栏。 */
export interface SpeechStateIdentity extends ReplySpeechIdentity { character_id:string }
/** Agent的自动反应由真实工具阶段驱动，携带角色/回合身份。 */
export interface AgentActivityFrame extends SpeechStateIdentity {
  type:'agent:activity';character_revision:number;activity_id:string;
  stage:'tool'|'tool_result';outcome:'running'|'success'|'waiting'|'error'|'unknown';
  tool:string;text:string;progress:string;motion_slot?:string;motion_group?:string;motion_index?:number|null
}
/** 实际播放占用按片段释放；不能以tts:end替代播放结束。 */
export interface SpeechPlaybackIdentity extends ReplySpeechIdentity {
  character_id:string;playback_id:string
}
export interface SpeechAudioFrame extends SpeechPlaybackIdentity {
  type:'tts:audio';wav:string;sample_rate:number;slice_ms:number;volumes:number[];streaming?:boolean;stream_id?:string
}
export type SpeechPlaybackReceipt = SpeechPlaybackIdentity & {
  type:'audio:playback_started'|'audio:playback_finished'
}
export type ReplySpeechEvent = ReplySpeechIdentity & (
  {type:'tts:reply_audio';wav:string;sample_rate:number;slice_ms:number;volumes:number[];streaming?:boolean;stream_id?:string} |
  {type:'tts:reply_start';session_id:string;generation:number} |
  {type:'tts:reply_end';reason?:string}
)
