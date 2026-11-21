"""前端音频占用：下发结束不代表设备队列播放结束。"""
from __future__ import annotations

import time
import uuid


class PlaybackLeases:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._pending: dict[str, dict[str, tuple[dict, float]]] = {}

    def offer(self, session_id: str, character_id: str, generation: int, duration: float) -> dict:
        self.busy(session_id)  # 顺便裁剪失联或过期的占用。
        pending = self._pending.setdefault(session_id, {})
        now = self._clock()
        tail = max((deadline - 10 for _, deadline in pending.values()), default=now)
        identity = {'session_id': session_id, 'character_id': character_id,
                    'generation': generation, 'playback_id': uuid.uuid4().hex}
        pending[identity['playback_id']] = (identity, max(now, tail) + duration + 10)
        return identity

    def receipt(self, session_id: str, message: dict) -> bool:
        self.busy(session_id)
        pending = self._pending.get(session_id, {})
        if (not isinstance(message.get('playback_id'), str)
            or type(message.get('generation')) is not int
            or message.get('type') not in ('audio:playback_started', 'audio:playback_finished')):
            return False
        item = pending.get(message.get('playback_id'))
        if item is None or any(message.get(k) != v for k, v in item[0].items()):
            return False
        if message.get('type') == 'audio:playback_finished':
            pending.pop(message['playback_id'])
            if not pending:
                self._pending.pop(session_id, None)
        return True

    def busy(self, session_id: str) -> bool:
        pending = self._pending.get(session_id, {})
        now = self._clock()
        for key, (_, deadline) in list(pending.items()):
            if deadline <= now:
                pending.pop(key)
        if not pending:
            self._pending.pop(session_id, None)
        return bool(pending)

    def clear(self, session_id: str) -> None:
        self._pending.pop(session_id, None)
