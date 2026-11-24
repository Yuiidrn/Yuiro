export function acceptsReplyRequest(value: {reply_request_id?: unknown}, active: string): boolean {
  return !value.reply_request_id || value.reply_request_id === active
}

/** 停播后拒收同一会话旧代际的新音频；epoch另管已在解码/排期的旧回调。 */
export class PlaybackAdmission {
  private current?: { session: string; generation: number }
  private cancelled?: { session: string; generation: number }

  accept(value?: { session_id?: unknown; generation?: unknown }): boolean {
    // 无身份的本地试听保留兼容；引擎帧由上层先验证会话/角色归属。
    if (value?.session_id === undefined && value?.generation === undefined) return true
    if (typeof value?.session_id !== 'string' || !Number.isSafeInteger(value.generation)) return false
    const generation = Number(value.generation)
    if (generation < 0) return false
    const session = value.session_id
    if (this.cancelled?.session === session && generation <= this.cancelled.generation) return false
    if (this.current?.session === session && generation < this.current.generation) return false
    this.current = { session, generation }
    return true
  }

  cancel(): void {
    if (this.current) this.cancelled = { ...this.current }
  }

  reset(): void {
    this.current = undefined
    this.cancelled = undefined
  }
}
