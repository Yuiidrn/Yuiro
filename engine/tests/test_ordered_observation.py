import asyncio

import pytest

from yuiro.runtime.events import AgentEvent
from yuiro.runtime.observation import OrderedObservation


@pytest.mark.asyncio
async def test_slow_observation_order_backpressure_and_frozen_role_payload():
    entered, release = asyncio.Event(), asyncio.Event()
    rows = []
    observer = OrderedObservation(capacity=1)

    async def old_role(event):
        entered.set()
        await release.wait()
        rows.append(('old', event.payload['value']))

    async def new_role(event):
        rows.append(('new', event.payload['value']))

    event = AgentEvent('test', 'fixture', 's', payload={'value': 1})
    await observer.submit(event, old_role)
    await entered.wait()
    event.payload['value'] = 2
    await observer.submit(event, new_role)
    third = asyncio.create_task(observer.submit(event, new_role))
    await asyncio.sleep(0)
    assert not third.done() and observer.queue.qsize() == 1
    release.set()
    await third
    await observer.close()
    assert rows == [('old', 1), ('new', 2), ('new', 2)]
    assert observer.worker is None


@pytest.mark.asyncio
async def test_observer_failure_is_counted_and_later_events_continue():
    observer = OrderedObservation()

    async def bad(event):
        raise RuntimeError('fixture')

    await observer.submit(AgentEvent('test', 'fixture', 's'), bad)
    await observer.close()
    assert observer.failures == 1
    await observer.close()
    with pytest.raises(RuntimeError, match='closed'):
        await observer.submit(AgentEvent('test', 'fixture', 's'), bad)


@pytest.mark.asyncio
async def test_close_waits_for_already_admitted_blocked_submission():
    observer = OrderedObservation(capacity=1)
    entered, release = asyncio.Event(), asyncio.Event()
    rows = []

    async def sink(event):
        entered.set()
        await release.wait()
        rows.append(event.type)

    await observer.submit(AgentEvent('one', 'fixture', 's'), sink)
    await entered.wait()
    await observer.submit(AgentEvent('two', 'fixture', 's'), sink)
    third = asyncio.create_task(observer.submit(AgentEvent('three', 'fixture', 's'), sink))
    await asyncio.sleep(0)
    closing = asyncio.create_task(observer.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await asyncio.wait_for(asyncio.gather(third, closing), 1)
    assert rows == ['one', 'two', 'three']


@pytest.mark.asyncio
async def test_real_event_log_roundtrip_and_failure_visible(tmp_path, monkeypatch):
    from yuiro.runtime.event_log import EventLog

    log = EventLog(store_dir=tmp_path)
    observer = OrderedObservation()
    await observer.submit(AgentEvent('one', 'fixture', 's'), log.sink)
    await observer.flush()
    assert log.load('s')[0]['type'] == 'one'
    monkeypatch.setattr(log, 'append', lambda event: False)
    await observer.submit(AgentEvent('failed', 'fixture', 's'), log.sink)
    await observer.close()
    assert observer.failures == 1


@pytest.mark.asyncio
async def test_durable_notification_waits_for_its_write_and_parent_cancel_joins():
    observer = OrderedObservation()
    entered, release = asyncio.Event(), asyncio.Event()
    written = []

    async def sink(event):
        entered.set()
        await release.wait()
        written.append(event.type)

    task = asyncio.create_task(observer.submit(AgentEvent('turn.step', 'fixture', 's'),
                                               sink, wait=True))
    await entered.wait()
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await observer.close()
    assert written == ['turn.step']
