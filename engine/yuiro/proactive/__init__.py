"""Yuiro engine — proactive interaction package (M5).

借鉴 OpenDesktop-Pet 的主动互动模型：定时观察（截图/摄像头）→ LLM 决策
是否打招呼（注意力模型，避免打扰专注用户）→ 问候经 proactive:greet 事件
推送到壳层。

框架版：观察层支持 SystemDaemon 截图（未接线时降级为无观察数据）；
决策层 LLM 未就绪时用启发式（低打扰概率）；调度层 asyncio 定时循环。
"""
from __future__ import annotations

import asyncio
import random
import time

from yuiro.logger import vlog


class AttentionObserver:
    """周期观察：截图（SystemDaemon）+ 可选摄像头，封装采集策略。"""

    def __init__(self, min_interval_s: int = 300, max_interval_s: int = 1200,
                 system_daemon=None) -> None:
        self.min_interval_s = min_interval_s
        self.max_interval_s = max_interval_s
        self._daemon = system_daemon  # SystemDaemonClient（window_screenshot）
        self._last_capture = 0.0

    async def next_capture(self) -> dict:
        """等待随机间隔后返回观察数据 {screenshot?, camera?, timestamp}。

        screenshot 经 SystemDaemon（未接线时返回 None——框架版不阻塞）。
        """
        delay = random.uniform(self.min_interval_s, self.max_interval_s)
        await asyncio.sleep(delay)
        screenshot = None
        if self._daemon is not None:
            try:
                result = await self._daemon.call(
                    "window_screenshot", {}, dry_run=True
                )
                if result.status == "ok":
                    screenshot = result.artifacts[0] if result.artifacts else None
            except Exception:  # noqa: BLE001 — 截图失败降级无视觉观察
                pass
        self._last_capture = time.monotonic()
        return {"screenshot": screenshot, "camera": None, "timestamp": self._last_capture}


class ProactiveDecider:
    """决策是否主动打招呼；LLM 未就绪时启发式（低打扰）。"""

    def __init__(self, llm=None) -> None:
        self._llm = llm  # LLMProvider（可选；None = 启发式）

    async def should_greet(self, observation: dict) -> dict:
        """返回 {greet: bool, reason: str, message?: str}。"""
        del observation  # 框架版观察数据未用于决策（截图语义分析后续）
        if self._llm is not None:
            # 框架版：LLM 决策占位（调优阶段用视觉观察 + prompt 决策）
            return {"greet": False, "reason": "llm-decider-not-wired"}
        # 启发式：低概率 + 长时间无互动才打招呼（避免打扰）
        should = random.random() < 0.15
        return (
            {"greet": True, "reason": "heuristic", "message": "在忙吗？需要我陪你聊聊天吗？"}
            if should
            else {"greet": False, "reason": "heuristic-skip"}
        )


class ProactiveScheduler:
    """observe → decide → greet 定时循环；greet 时经回调推送。"""

    def __init__(self, observer: AttentionObserver, decider: ProactiveDecider,
                 on_greet=None) -> None:
        self._observer = observer
        self._decider = decider
        self._on_greet = on_greet  # async (message) -> None，推送壳层
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())
        vlog("proactive", "主动互动调度已启动（定时观察→决策→打招呼）")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            vlog("proactive", "主动互动调度已停止")

    async def _run(self) -> None:
        while True:
            try:
                observation = await self._observer.next_capture()
                decision = await self._decider.should_greet(observation)
                if decision.get("greet") and self._on_greet is not None:
                    message = decision.get("message", "在忙吗？")
                    vlog("proactive", f"主动打招呼: {message}")
                    await self._on_greet(message)
                else:
                    vlog("proactive", f"本轮不打招呼（{decision.get('reason')}）")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 单轮异常不终止循环
                vlog("proactive", f"调度异常: {exc}")
