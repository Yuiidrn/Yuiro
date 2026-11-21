"""插话的延迟上限、主动取消、过期草稿与流资源回收。"""
import asyncio
from types import SimpleNamespace

import pytest

from yuiro.agent import LLMChunk
from yuiro.diary.quip import QuipGate, QuipService
from yuiro.diary.session import DiarySession


@pytest.mark.asyncio
async def test_first_sentence_closes_stream_without_waiting_for_tail():
    closed = asyncio.Event()

    class Provider:
        async def stream_text(self, messages, **kwargs):
            assert kwargs['max_tokens'] == 64
            assert messages[0]['role'] == 'system'
            try:
                yield LLMChunk(kind='token', content='这段很有画面。后面的解释不要了')
                await asyncio.sleep(60)
            finally:
                closed.set()

    service = QuipService(llm=Provider())
    assert await asyncio.wait_for(service.maybe_quip('今天在公园遇到了小猫', idle_s=2), .2) == '这段很有画面。'
    assert closed.is_set()


@pytest.mark.asyncio
async def test_timeout_is_silent_and_cancellation_propagates():
    entered, closed = asyncio.Event(), asyncio.Event()

    class Provider:
        async def stream_text(self, messages, **kwargs):
            try:
                entered.set()
                await asyncio.sleep(60)
                yield LLMChunk(kind='done')
            finally:
                closed.set()

    service = QuipService(llm=Provider(), timeout_s=.02)
    assert await service.maybe_quip('今天在公园遇到了小猫', idle_s=2) is None
    assert closed.is_set() and not service._inflight
    service.timeout_s = 60
    entered.clear(); closed.clear()
    task = asyncio.create_task(service.maybe_quip('今天在公园遇到了小猫', idle_s=2))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and not service._inflight


@pytest.mark.asyncio
async def test_uncommitted_text_is_not_appended_and_changed_draft_drops_reply():
    entered, finish = asyncio.Event(), asyncio.Event()

    async def reply(text, **kwargs):
        assert text == '还在编辑但没有保存的内容'
        entered.set()
        await finish.wait()
        return '听起来不错。'

    session = DiarySession(quip=SimpleNamespace(maybe_quip=reply, gate=QuipGate()))
    session.start()
    task = asyncio.create_task(session.maybe_quip(2, text='还在编辑但没有保存的内容'))
    await entered.wait()
    assert not session.segments
    session.append('新段落')
    finish.set()
    assert await task is None


@pytest.mark.asyncio
async def test_overlapping_requests_do_not_call_provider_twice():
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []

    class Provider:
        async def stream_text(self, messages, **kwargs):
            calls.append(messages)
            entered.set()
            await finish.wait()
            yield LLMChunk(kind='token', content='记下这一刻。')

    service = QuipService(llm=Provider())
    first = asyncio.create_task(service.maybe_quip('今天在公园遇到了小猫', idle_s=2))
    await entered.wait()
    assert await service.maybe_quip('又看见一只可爱的小狗', idle_s=2) is None
    finish.set()
    assert await first == '记下这一刻。'
    assert len(calls) == 1


def test_gate_rejects_nonfinite_idle():
    assert not QuipGate().should_quip(text='今天在公园遇到了小猫', idle_s=float('nan'))


@pytest.mark.asyncio
async def test_control_channel_cancel_keeps_save_responsive(monkeypatch):
    """运行真实 WS 分发循环：挂起的插话不能占住保存/撤销队列。"""
    import yuiro.main as main
    from starlette.websockets import WebSocketDisconnect
    from unittest.mock import AsyncMock

    entered, cancelled, saved = asyncio.Event(), asyncio.Event(), asyncio.Event()
    incoming = asyncio.Queue()

    class Socket:
        query_params = {}
        accept = AsyncMock()

        async def receive_json(self):
            item = await incoming.get()
            if item is None:
                raise WebSocketDisconnect()
            return item

    async def handle(ws, session_id, item):
        if item['type'] == 'diary:quip':
            entered.set()
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()
        elif item['type'] == 'diary:save_raw':
            saved.set()

    monkeypatch.setattr(main, '_authorized', lambda _: True)
    monkeypatch.setattr(main.app.state, 'characters', None, raising=False)
    monkeypatch.setattr(main.app.state, 'sessions', SimpleNamespace(
        attach_control=lambda *a, **k: SimpleNamespace(session_id='quip-test', generation=0),
        detach_control=lambda _: None), raising=False)
    monkeypatch.setattr(main, '_send_session_ready', AsyncMock())
    monkeypatch.setattr(main, '_handle_diary_message', handle)
    monkeypatch.setattr(main, '_note_memory_session_end', lambda: None)
    task = asyncio.create_task(main.control_channel(Socket()))
    try:
        await incoming.put({'type': 'diary:quip'})
        await asyncio.wait_for(entered.wait(), .5)
        await incoming.put({'type': 'diary:save_raw'})
        await asyncio.wait_for(saved.wait(), .5)
        assert cancelled.is_set()
    finally:
        await incoming.put(None)
        await asyncio.wait_for(task, .5)
