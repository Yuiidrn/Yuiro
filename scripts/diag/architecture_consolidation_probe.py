"""固定替身依赖的共享输出与慢观测对照，不请求网络或修改用户数据。"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine'))


async def speech_case(streaming):
    from yuiro.audio.output import ReplyStream

    start = time.perf_counter()
    marks = {}

    async def speak(source, generation, prepared):
        async for sentence in source:
            await asyncio.sleep(.02)  # 固定合成替身，不是实际TTS耗时。
            marks.setdefault('first_audio_callback_ms', (time.perf_counter() - start) * 1000)

    bridge = ReplyStream(speak, lambda t: None, lambda: 1)
    await asyncio.sleep(.01)
    marks['first_sentence_ms'] = (time.perf_counter() - start) * 1000
    if streaming:
        await bridge.send('这是完整的第一句。')
    await asyncio.sleep(.15)  # 固定后文生成等待。
    marks['generation_done_ms'] = (time.perf_counter() - start) * 1000
    if streaming:
        await bridge.send('这是后文。')
    else:
        await bridge.send('这是完整的第一句。这是后文。')
    await bridge.finish()
    await bridge.task
    return {k: round(v, 2) for k, v in marks.items()}


async def observer_case(buffered):
    from yuiro.runtime.events import AgentEvent, EventBus
    from yuiro.runtime.observation import OrderedObservation

    bus = EventBus()
    observation = OrderedObservation()
    rows = []

    async def slow(event):
        await asyncio.sleep(.05)
        rows.append(event.event_id)

    async def buffered_sink(event):
        await observation.submit(event, slow)

    bus.subscribe_all(buffered_sink if buffered else slow)
    start = time.perf_counter()
    await bus.publish(AgentEvent('probe', 'fixture', 'isolated'))
    publish_ms = (time.perf_counter() - start) * 1000
    await observation.close()
    return {'publish_ms': round(publish_ms, 2), 'writes_completed': len(rows)}


async def disk_case(offload):
    from yuiro.runtime.event_log import EventLog
    from yuiro.runtime.events import AgentEvent

    log = EventLog()
    log.append = lambda event: time.sleep(.05)  # 不写真实磁盘，固定慢写边界。
    start = time.perf_counter()
    tick = asyncio.get_running_loop().create_future()
    asyncio.get_running_loop().call_later(.005, lambda: tick.set_result(
        (time.perf_counter() - start) * 1000))
    if offload:
        await log.sink(AgentEvent('probe', 'fixture', 'isolated'))
    else:
        log.append(None)
    return {'loop_tick_ms': round(await tick, 2)}


async def main():
    report = {'kind': 'controlled_dependency_comparison_NOT_real_TTFA', 'samples': []}
    for _ in range(5):
        report['samples'].append({
            'speech_before': await speech_case(False), 'speech_after': await speech_case(True),
            'observer_before': await observer_case(False), 'observer_after': await observer_case(True),
            'disk_before': await disk_case(False), 'disk_after': await disk_case(True),
        })
    report['actual_disk'] = []
    for _ in range(3):
        report['actual_disk'].append({'before': await actual_disk_case(False),
                                      'after': await actual_disk_case(True)})
    (ROOT / 'docs/plan/architecture-consolidation-probe.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report))


async def actual_disk_case(buffered):
    from yuiro.runtime.event_log import EventLog
    from yuiro.runtime.events import AgentEvent
    from yuiro.runtime.observation import OrderedObservation

    scratch_root = (ROOT / '.env-local').resolve()
    with tempfile.TemporaryDirectory(prefix='observation-probe-', dir=scratch_root) as scratch:
        assert Path(scratch).resolve().is_relative_to(scratch_root)
        log = EventLog(store_dir=scratch)
        observer = OrderedObservation()
        start = time.perf_counter()
        tick = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_soon(lambda: tick.set_result(
            (time.perf_counter()-start)*1000))
        for index in range(100):
            event = AgentEvent('probe', 'isolated', 's', generation=index)
            if buffered:
                await observer.submit(event, log.sink)
            else:
                log.append(event)
        admitted_ms = (time.perf_counter()-start)*1000
        await observer.close()
        total_ms = (time.perf_counter()-start)*1000
        rows = log.load('s')
        return {'admission_ms': round(admitted_ms, 2), 'all_written_ms': round(total_ms, 2),
                'loop_tick_ms': round(await tick, 2),
                'ordered_100': [r['generation'] for r in rows] == list(range(100))}


if __name__ == '__main__':
    asyncio.run(main())
