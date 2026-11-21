/** Presentation-only IPC. The pet renderer remains the sole owner of replies/actions. */
export type UiKind = 'speech' | 'results' | 'sources'
export interface UiRect { x: number; y: number; width: number; height: number }
export interface ClientPlayback { backend:'netease_client';song_id:string;name:string;artist:string;status:'playing'|'paused';playback_id:string;can_stop:false;liked?:boolean|null }
export interface DetachedState {
  key: string
  outline?: UiRect[]
  anchor: UiRect
  viewport: { width: number; height: number }
  gap?:number
  speech: { text: string; visible: boolean; width: number; alpha: number; offsetX: number; offsetY: number;side?:'left'|'right';anchorY?:number;tailSide?:'left'|'right';headY?:number;tipY?:number;line?:{mouthX:number;mouthY:number;fontSize:number;color:string;stroke:number;rise?:number;bend?:number} }
  results: { title: string; kind: string; items: Record<string, unknown>[]; width: number; alpha: number; side: 'left' | 'right'; offsetX: number; offsetY: number; playback?:ClientPlayback|null;busy?:boolean } | null
  sources?: DetachedState['results']
}
export interface DetachedAction { kind: UiKind; key: string; index?: number; dismiss?: boolean; action?: 'pick'|'open_official'|'client_play'|'client_pause'|'client_resume'|'client_like'|'client_unlike' }
export type DetachedContent = Pick<DetachedState,'key'|'speech'|'results'|'sources'>
export interface DialogueConnector {key:string;path:string;width:number;height:number;color:string;stroke:number}
