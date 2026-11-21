"""S15：RuntimeContract / RuntimeRegistry（注册·广播·错误隔离·状态视图·适配器）。

对应 docs/plan/S15-runtime-consolidation.md。
"""
from __future__ import annotations

import os
import tempfile

import pytest

from yuiro.avatar import AvatarRuntime
from yuiro.runtime.adapters import (
    AgentRuntimeAdapter,
    SpeechRuntimeAdapter,
    TaskRuntimeAdapter,
)
from yuiro.runtime.contract import RuntimeContract, RuntimeRegistry
from yuiro.task import TaskRuntime


class _Good:
    def __init__(self) -> None:
        self.cancelled: list[tuple[str, str]] = []
        self.closed: list[str] = []

    def runtime_name(self) -> str:
        return "good"

    async def cancel(self, session_id: str, reason: str = "") -> None:
        self.cancelled.append((session_id, reason))

    async def on_session_close(self, session_id: str) -> None:
        self.closed.append(session_id)

    def state(self) -> dict:
        return {"ok": True}


class _Bad:
    def runtime_name(self) -> str:
        return "bad"

    async def cancel(self, session_id: str, reason: str = "") -> None:
        raise RuntimeError("boom")

    async def on_session_close(self, session_id: str) -> None:
        raise RuntimeError("boom")

    def state(self) -> dict:
        raise RuntimeError("boom")


class _Partial:
    def runtime_name(self) -> str:
        return "partial"


@pytest.mark.asyncio
async def test_registry_broadcast_and_isolation() -> None:
    reg = RuntimeRegistry()
    good, bad, partial = _Good(), _Bad(), _Partial()
    assert reg.register(good) == "good"
    assert reg.register(bad) == "bad"
    assert reg.register(partial) == "partial"
    assert reg.names() == ["bad", "good", "partial"]

    res = await reg.cancel_session("s1", "user")
    assert res["good"] == "ok"
    assert res["bad"].startswith("error")
    assert res["partial"] == "skipped"
    assert good.cancelled == [("s1", "user")]

    res2 = await reg.close_session("s1")
    assert res2["good"] == "ok"
    assert good.closed == ["s1"]


def test_registry_snapshot_isolates_errors() -> None:
    reg = RuntimeRegistry()
    reg.register(_Good())
    reg.register(_Bad())
    reg.register(_Partial())
    snap = reg.snapshot()
    assert snap["good"] == {"ok": True}
    assert "error" in snap["bad"]
    assert snap["partial"] == {"registered": True}


def test_registry_name_fallback() -> None:
    class _Anonymous:
        pass

    reg = RuntimeRegistry()
    assert reg.register(_Anonymous()) == "_Anonymous"


@pytest.mark.asyncio
async def test_avatar_runtime_contract() -> None:
    sent: list[dict] = []

    async def bc(msg: dict) -> None:
        sent.append(msg)

    rt = AvatarRuntime(expression_map={"happy": "expression2"}, broadcast=bc)
    assert isinstance(rt, RuntimeContract)
    assert rt.runtime_name() == "avatar"
    await rt.push_emotion("s1", "happy")
    assert rt.state()["sessions"] == 1
    await rt.cancel("s1")
    assert rt.state()["sessions"] == 0
    await rt.on_session_close("s1")  # 幂等


@pytest.mark.asyncio
async def test_task_runtime_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt = TaskRuntime(store_dir=os.path.join(tmp, "tasks"))
        ad = TaskRuntimeAdapter(rt)
        assert isinstance(ad, RuntimeContract)
        assert ad.runtime_name() == "task"
        await rt.create("目标", ["a"], session_id="s1")
        assert ad.state()["active"] == 1
        await ad.cancel("s1")
        assert ad.state()["active"] == 1  # 任务本身保留（仅解绑会话）
        # 业务方法 cancel(task_id) 不受影响（S15 回归护栏）
        t = await rt.create("要取消的目标", ["a"])
        assert (await rt.cancel(t.id, reason="用户说算了")).status.value == "cancelled"


@pytest.mark.asyncio
async def test_agent_adapter() -> None:
    class _Loop:
        def __init__(self) -> None:
            self._generations = {"s1": 1}
            self._history = {"s1": []}

    loop = _Loop()
    ad = AgentRuntimeAdapter(loop)
    assert isinstance(ad, RuntimeContract)
    assert ad.runtime_name() == "agent"
    assert ad.state() == {"generations": 1, "tracked_sessions": 1}
    await ad.cancel("s1")
    assert loop._generations["s1"] == 2  # 旧路径自增
    await ad.on_session_close("s1")
    assert "s1" not in loop._generations
    assert "s1" in loop._history  # 对话历史未被清理（保守）


@pytest.mark.asyncio
async def test_speech_adapter() -> None:
    class _Pipe:
        _state = "ready"

        def __init__(self) -> None:
            self.interrupted: list[str] = []

        def interrupt(self, session_id: str) -> None:
            self.interrupted.append(session_id)

    pipe = _Pipe()
    ad = SpeechRuntimeAdapter(pipe)
    assert isinstance(ad, RuntimeContract)
    assert ad.runtime_name() == "voice"
    await ad.cancel("s1", "barge-in")
    await ad.on_session_close("s1")
    assert pipe.interrupted == ["s1", "s1"]
    assert ad.state()["state"] == "ready"


def test_adapters_tolerate_missing_attrs() -> None:
    """被包装对象缺属性时适配器不得抛（容错优先）。"""

    class _Empty:
        pass

    assert AgentRuntimeAdapter(_Empty()).state()
    assert SpeechRuntimeAdapter(_Empty()).state()
