"""RuntimeContract（S15）：所有 Runtime 共享的最小契约与注册表。

"Runtime Consolidation"：不新增功能，而是让已经存在的 Runtime-like 模块
（AgentLoop / VoicePipeline / AvatarRuntime / TaskRuntime）共享同一套生命周期
与状态查询原语——避免各自发明 session / generation / cancel / state / event。

设计约束（spec）：
- 所有钩子**错误隔离**：一个 Runtime 失败不得影响其它 Runtime 或主链路；
- 钩子**幂等**：重复关闭 / 重复取消必须安全；
- 未实现某钩子的 Runtime 视为"不支持"，Registry 跳过而不报错。

规范：``docs/spec/runtime-contract.md``、``docs/plan/S15-runtime-consolidation.md``。
"""
from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable


@runtime_checkable
class RuntimeContract(Protocol):
    """Runtime 最小契约（方法全部可选实现；缺省即视为不支持）。"""

    def runtime_name(self) -> str:
        """Runtime 名（状态视图与日志用）。"""
        ...

    async def cancel(self, session_id: str, reason: str = "") -> None:
        """取消该 Runtime 在某会话上进行中的工作（不得抛异常）。"""
        ...

    def state(self) -> dict:
        """当前状态快照（可 JSON 序列化）。"""
        ...

    async def on_session_close(self, session_id: str) -> None:
        """会话关闭时的释放钩子（幂等；不得抛异常）。"""
        ...


class RuntimeRegistry:
    """Runtime 注册表：统一生命周期广播 + 状态汇总（S15）。"""

    def __init__(self) -> None:
        self._runtimes: dict[str, object] = {}

    # ---- 注册 ---------------------------------------------------------------
    def register(self, runtime: object, *, name: str | None = None) -> str:
        """注册一个 Runtime；名缺省取 ``runtime_name()`` 或类名。"""
        key = name
        if key is None:
            fn = getattr(runtime, "runtime_name", None)
            try:
                key = fn() if callable(fn) else type(runtime).__name__
            except Exception:  # noqa: BLE001 — 取名失败退回类名
                key = type(runtime).__name__
        key = str(key)
        self._runtimes[key] = runtime
        return key

    def names(self) -> list[str]:
        return sorted(self._runtimes)

    def get(self, name: str) -> object | None:
        return self._runtimes.get(name)

    # ---- 广播 ---------------------------------------------------------------
    async def _broadcast(self, hook_name: str, *args) -> dict[str, str]:
        results: dict[str, str] = {}
        for name, rt in self._runtimes.items():
            hook = getattr(rt, hook_name, None)
            if hook is None:
                results[name] = "skipped"
                continue
            try:
                await hook(*args)
                results[name] = "ok"
            except Exception as exc:  # noqa: BLE001 — 错误隔离：一个失败不影响其它
                results[name] = f"error: {exc}"
        return results

    async def close_session(self, session_id: str) -> dict[str, str]:
        """会话关闭：广播 ``on_session_close``（错误隔离）。"""
        return await self._broadcast("on_session_close", session_id)

    async def cancel_session(self, session_id: str, reason: str = "") -> dict[str, str]:
        """并发通知取消并等待收敛，慢清理不阻挡其它 Runtime 收到信号。"""
        async def notify(name: str, rt: object) -> tuple[str, str]:
            hook = getattr(rt, "cancel", None)
            if hook is None:
                return name, "skipped"
            try:
                await hook(session_id, reason)
                return name, "ok"
            except Exception as exc:  # noqa: BLE001 — 保持逐 Runtime 错误隔离
                return name, f"error: {exc}"

        # 固定本次接收者；热更新注册不改变已经开始的取消广播。
        tasks = [asyncio.create_task(notify(name, rt))
                 for name, rt in list(self._runtimes.items())]
        try:
            return dict(await asyncio.gather(*tasks))
        finally:
            # 父级取消/子钩子 CancelledError 都必须传播，且不遗留其它通知任务。
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    # ---- 状态视图 -----------------------------------------------------------
    def snapshot(self) -> dict:
        """统一状态视图（供 ``/debug/runtime``；任何 Runtime 异常不影响整体）。"""
        out: dict = {}
        for name, rt in self._runtimes.items():
            fn = getattr(rt, "state", None)
            if not callable(fn):
                out[name] = {"registered": True}
                continue
            try:
                value = fn()
                out[name] = value if isinstance(value, dict) else {"value": value}
            except Exception as exc:  # noqa: BLE001
                out[name] = {"error": str(exc)}
        return out
