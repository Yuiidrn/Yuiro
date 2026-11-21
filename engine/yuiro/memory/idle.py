"""MemoryIdleScheduler（S51）：**会话间隙 / 会话结束时**触发一轮记忆整理。

为什么需要它（与既有 6 小时维护循环的分工）：

- ``_memory_maintenance_loop`` 是"不管有没有人都按时跑"，价值是**兜底**；
  但它**不知道用户刚聊完**。而"刚聊完"恰恰是整理的最佳时机 —— 这一场的线索还热、
  L2 刚写进新条目、正好可以把新条目与旧的比对一遍。
- **会话结束（连接断开）**是另一条自然边界："这一场聊完了"。

三条设计约束（与 consolidation 同源）：

1. **不占回复时间**：:meth:`note_activity` 只重置一个计时器（同步、O(1)），
   真正的整理跑在**独立任务**里 —— 聊天链路从头到尾不 await 它；
2. **单飞 + 最小间隔**：同一时刻只有一轮；且两次整理之间至少间隔 ``min_interval_s``，
   否则"用户连发几条消息"会触发好几轮无用扫描；
3. **失败静默**：整理出错绝不影响对话（只写日志）。
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable

from yuiro.logger import vlog


class MemoryIdleScheduler:
    """按"空闲"与"会话结束"两种信号安排记忆整理。"""

    def __init__(
        self,
        tidy: Callable[[], Awaitable[dict]],
        *,
        idle_s: float = 120.0,
        end_delay_s: float = 20.0,
        min_interval_s: float = 300.0,
    ) -> None:
        """
        :param tidy: 整理动作（通常是 ``MemorySystem.tidy``）
        :param idle_s: 最后一轮对话结束后，静默这么久算"会话间隙"
        :param end_delay_s: 会话结束（连接断开）后延迟多久整理（等尾音落定）
        :param min_interval_s: 两轮整理之间的最小间隔（防连发触发）
        """
        self._tidy = tidy
        self._idle_s = idle_s
        self._end_delay_s = end_delay_s
        self._min_interval_s = min_interval_s
        self._timer: asyncio.Task | None = None
        self._running: asyncio.Task | None = None
        self._last_run = 0.0
        # 观测：跑了几轮、上一轮做了什么（调试台/日志可查）
        self.runs = 0
        self.last_result: dict | None = None

    # ---- 信号（由主链路调用）-------------------------------------------------
    def note_activity(self) -> None:
        """每轮回复结束后调用。

        **必须同步且 O(1)** —— 它站在回复路径的末尾，绝不能 await 任何东西。
        它只做一件事：把"空闲计时"重新开始；整理自己在独立 task 里跑。
        """
        self._cancel_timer()
        self._timer = asyncio.create_task(self._after(self._idle_s))

    def note_session_end(self) -> None:
        """会话（连接）结束时调用：安排一次较短的延迟整理。"""
        self._cancel_timer()
        self._timer = asyncio.create_task(self._after(self._end_delay_s))

    async def stop(self) -> None:
        """关闭：取消待命计时与正在跑的整理（幂等）。"""
        self._cancel_timer()
        task = self._running
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def snapshot(self) -> dict:
        """给调试台/日志的只读状态。"""
        return {
            "runs": self.runs,
            "last_result": self.last_result,
            "idle_s": self._idle_s,
            "min_interval_s": self._min_interval_s,
            "pending": bool(self._timer is not None and not self._timer.done()),
            "running": bool(self._running is not None and not self._running.done()),
        }

    # ---- 内部 ---------------------------------------------------------------
    def _cancel_timer(self) -> None:
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
        self._timer = None

    async def _after(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return  # 期间又说话了 → 这次作废，重新计时（这正是"间隙"语义）
        self._kick()

    def _kick(self) -> None:
        now = time.monotonic()
        if now - self._last_run < self._min_interval_s:
            return  # 距上次整理太近 → 跳过（防连发触发）
        if self._running is not None and not self._running.done():
            return  # 单飞：上一轮还没跑完
        self._running = asyncio.create_task(self._run())

    async def _run(self) -> None:
        self._last_run = time.monotonic()
        try:
            result = await self._tidy()
            self.runs += 1
            self.last_result = result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — 整理失败绝不影响对话
            vlog("memory", f"[整理] 空闲整理失败（不影响对话）：{type(exc).__name__}: {exc}")
