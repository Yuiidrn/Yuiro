"""有界串行观测队列：只隔离显式观测者，不改变业务订阅的裁决顺序。"""
from __future__ import annotations

import asyncio
from copy import deepcopy

from yuiro.logger import vlog


class OrderedObservation:
    def __init__(self, capacity=128):
        self.queue = asyncio.Queue(maxsize=capacity)
        self.worker = None
        self.closed = False
        self.failures = 0
        self.peak = 0
        self._admission = asyncio.Lock()

    async def submit(self, event, sink, *, wait=False):
        completed = asyncio.get_running_loop().create_future() if wait else None
        item = (deepcopy(event), sink, completed)
        async with self._admission:
            if self.closed:
                raise RuntimeError('observation queue closed')
            if self.worker is None:
                self.worker = asyncio.create_task(self._run())
            # 冻结payload及目标角色，防止排队期间切角/变更造成串库。
            await self.queue.put(item)
            self.peak = max(self.peak, self.queue.qsize())
        if completed is not None:
            try:
                await asyncio.shield(completed)
            except asyncio.CancelledError:
                await completed
                raise

    async def _run(self):
        while True:
            item = await self.queue.get()
            try:
                if item is None:
                    return
                event, sink, completed = item
                try:
                    await sink(event)
                    if completed is not None:
                        completed.set_result(None)
                except Exception as exc:  # noqa: BLE001 — 保持观测错误隔离
                    self.failures += 1
                    vlog('event', f'观测落盘失败: {type(exc).__name__}')
                    if completed is not None:
                        completed.set_exception(exc)
            finally:
                self.queue.task_done()

    async def flush(self):
        await self.queue.join()

    async def close(self):
        async with self._admission:
            self.closed = True
            if self.worker is not None:
                await self.flush()
                await self.queue.put(None)
                await self.worker
                self.worker = None
