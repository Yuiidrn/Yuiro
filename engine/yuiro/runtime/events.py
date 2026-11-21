"""AgentEvent + EventBus：agent-native 事件总线（S02 最小版）。

定位（见 docs/spec/target-file-preview.md §3.2、docs/plan/S02-session-generation-unify.md）：

- 内部事件用**点分名**（``session.started`` / ``agent.stale_discarded``），
  对外 WS 事件用**冒号名**（保持前端零破坏）；映射只允许存在于本模块；
- S02 只做"内存总线 + 事实广播"；EventLog 落盘 / Replay 留待 S03+；
- **Event / Hook / Intent 三者分离**（spec 红线）：本模块只承载 Event（已发生的事实）。
"""
from __future__ import annotations

import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import uuid4

from yuiro.logger import vlog

# 内部点分名 → 对外冒号名（唯一转换点；无映射时原样透传）
_WIRE_TYPE_MAP: dict[str, str] = {
    "session.started": "session:ready",
    "session.cancelled": "session:cancelled",
    "agent.stale_discarded": "agent:stale_discarded",
}

Handler = Callable[["AgentEvent"], Awaitable[None]]


@dataclass
class AgentEvent:
    """一次"已发生的事实"（不是 Intent，也不是 Hook 扩展点）。"""

    type: str  # 内部点分名
    source: str  # 产生事件的 Runtime / 模块名
    session_id: str
    generation: int = 0
    trace_id: str = ""
    event_id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)


class EventBus:
    """进程内 typed 事件总线（asyncio + dataclass；不引入 broker）。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._all_handlers: list[Handler] = []  # S12：全局订阅（EventLog 等横切关注点）

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """订阅指定事件类型（S02 用精确匹配；前缀订阅待有真实用例再加）。"""
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        """订阅所有事件（S12：EventLog 落盘走此通道）。"""
        self._all_handlers.append(handler)

    async def publish(self, event: AgentEvent) -> None:
        """发布事件：先打日志（可观测），再分发订阅者；任何异常不影响主流程。"""
        with contextlib.suppress(Exception):  # 观测失败不阻断业务
            extra = f" {event.payload}" if event.payload else ""
            vlog(
                "event",
                f"[{event.session_id[:8]}] {event.type} "
                f"(gen={event.generation}, src={event.source}){extra}",
            )
        for handler in self._handlers.get(event.type, []):
            try:
                await handler(event)
            except Exception as exc:  # noqa: BLE001 — 订阅者异常不阻断发布
                vlog("event", f"订阅者处理 {event.type} 失败: {exc}")
        # S12：全局订阅者（EventLog 等横切关注点；同样不得阻断发布）
        for handler in self._all_handlers:
            try:
                await handler(event)
            except Exception as exc:  # noqa: BLE001
                vlog("event", f"全局订阅者处理 {event.type} 失败: {exc}")

    @staticmethod
    def to_wire(event: AgentEvent) -> dict:
        """内部事件 → 前端 JSON（唯一转换点，供 WS 下发复用）。"""
        msg: dict = {
            "type": _WIRE_TYPE_MAP.get(event.type, event.type),
            "session_id": event.session_id,
            "generation": event.generation,
        }
        if event.trace_id:
            msg["trace_id"] = event.trace_id
        if event.payload:
            msg.update(event.payload)
        return msg
