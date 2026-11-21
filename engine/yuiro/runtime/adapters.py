"""Runtime 契约适配器（S15）：为**大模块**提供 RuntimeContract 薄包装。

取舍说明（spec 原则"复用现有实现 → 抽抽象 → 适配 → 替换调用路径；禁止删除→重写"）：

- ``audio/__init__.py``（1501 行）与 ``agent/__init__.py``（1151 行）**不修改**，
  用外部 Adapter 提供契约——避免在收敛阶段触碰高风险大文件；
- 小模块（``avatar`` / ``task``）直接在类上实现契约方法（可发现性更好）。

两种方式产出的对象在 ``RuntimeRegistry`` 眼中完全等价。
"""
from __future__ import annotations


class AgentRuntimeAdapter:
    """``AgentLoop`` 的 RuntimeContract 适配（不修改 AgentLoop 本身）。"""

    def __init__(self, loop) -> None:
        self._loop = loop

    def runtime_name(self) -> str:
        return "agent"

    async def cancel(self, session_id: str, reason: str = "") -> None:
        """取消：仅旧路径（无 Session 权威）下自增本地代际。

        新路径由 ``SessionManager.cancel`` 权威负责（S02 语义），此处不重复。
        """
        del reason
        gens = getattr(self._loop, "_generations", None)
        if isinstance(gens, dict):
            gens[session_id] = gens.get(session_id, 0) + 1

    async def on_session_close(self, session_id: str) -> None:
        """保守释放：只清代际计数（不动对话历史与状态摘要，避免行为变化）。"""
        gens = getattr(self._loop, "_generations", None)
        if isinstance(gens, dict):
            gens.pop(session_id, None)

    def state(self) -> dict:
        gens = getattr(self._loop, "_generations", {}) or {}
        history = getattr(self._loop, "_history", {}) or {}
        return {"generations": len(gens), "tracked_sessions": len(history)}


class TaskRuntimeAdapter:
    """``TaskRuntime`` 的 RuntimeContract 适配。

    存在的理由：``TaskRuntime`` 已有业务方法 ``cancel(task_id)``（取消某个任务），
    与契约的 ``cancel(session_id)`` 同名但语义不同 —— 直接在类上实现会**覆盖业务方法**
    （S15 实测踩中，test_task_runtime::test_cancel_and_fail 回归暴露）。
    """

    def __init__(self, runtime) -> None:
        self._rt = runtime

    def runtime_name(self) -> str:
        return "task"

    async def cancel(self, session_id: str, reason: str = "") -> None:
        """统一取消：仅解绑该会话的当前目标（任务本身保留，可后续恢复）。"""
        del reason
        active = getattr(self._rt, "_active", None)
        if isinstance(active, dict):
            active.pop(session_id, None)

    async def on_session_close(self, session_id: str) -> None:
        await self.cancel(session_id)

    def state(self) -> dict:
        fn = getattr(self._rt, "state", None)
        return fn() if callable(fn) else {}


class SpeechRuntimeAdapter:
    """``VoicePipeline`` 的 RuntimeContract 适配（不修改 VoicePipeline 本身）。"""

    def __init__(self, pipeline) -> None:
        self._pipe = pipeline

    def runtime_name(self) -> str:
        return "voice"

    async def cancel(self, session_id: str, reason: str = "") -> None:
        """统一取消 = 既有 interrupt（停 LLM 回合 + TTS 播放 + 前端停播回执）。"""
        del reason
        interrupt = getattr(self._pipe, "interrupt", None)
        if callable(interrupt):
            interrupt(session_id)

    async def on_session_close(self, session_id: str) -> None:
        await self.cancel(session_id)

    def state(self) -> dict:
        return {
            "state": getattr(self._pipe, "_state", "unknown"),
            "stage": getattr(self._pipe, "_loading_stage", ""),
        }
