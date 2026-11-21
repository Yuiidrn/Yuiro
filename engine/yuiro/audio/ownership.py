"""继承现有VoicePipeline取消epoch，避免旧任务交付时重取当前身份。"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps


@dataclass(frozen=True)
class SpeechOwner:
    pipeline: object
    session_id: str
    epoch: int


_owner: ContextVar[SpeechOwner | None] = ContextVar('yuiro_speech_owner', default=None)


def capture_owner(pipeline, session_id: str) -> SpeechOwner:
    return SpeechOwner(pipeline, session_id, pipeline._turn_gen.get(session_id, 0))


def check_owner(pipeline, session_id: str) -> None:
    owner = _owner.get()
    if (owner is not None and owner.pipeline is pipeline and owner.session_id == session_id
            and owner.epoch != pipeline._turn_gen.get(session_id, 0)):
        raise asyncio.CancelledError('speech owner invalidated')


def owned_speech(function):
    @wraps(function)
    async def run(pipeline, session_id, *args, **kwargs):
        inherited = _owner.get()
        # 子任务必须继承原owner；不能在旧任务的子入口重新捕获新epoch。
        token = None
        if inherited is None or inherited.pipeline is not pipeline or inherited.session_id != session_id:
            token = _owner.set(capture_owner(pipeline, session_id))
        try:
            check_owner(pipeline, session_id)
            return await function(pipeline, session_id, *args, **kwargs)
        finally:
            if token is not None:
                _owner.reset(token)
    return run


async def emit_owned(pipeline, owner: SpeechOwner, event_type: str, payload: dict) -> None:
    token = _owner.set(owner)
    try:
        await pipeline._emit(owner.session_id, event_type, payload)
    finally:
        _owner.reset(token)
