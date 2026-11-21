"""S16：Agent Harness Extraction（抽离出的 tool_dispatch / tool_events 独立可测）。

对应 docs/plan/S16-agent-harness-extraction.md。
"""
from __future__ import annotations

import json

import pytest

from yuiro.agent.tool_dispatch import ToolDispatcher
from yuiro.agent.tool_events import StateNotes, describe_tool_event, describe_tool_state
from yuiro.capability import Policy


class _Reg:
    def __init__(self) -> None:
        self.executed: list[tuple[str, bool]] = []

    async def execute(self, name, args, task_id, approval_callback=None):  # noqa: ARG002
        self.executed.append((name, approval_callback is not None))
        return '{"status": "ok"}'


class _TC:
    def __init__(self, name: str, args: dict | None = None) -> None:
        self.tool_name = name
        self.tool_args = args or {}


# ---- ToolDispatcher ---------------------------------------------------------
@pytest.mark.asyncio
async def test_execute_one_allows_low_risk() -> None:
    reg = _Reg()
    d = ToolDispatcher(reg, policy=Policy(profile="normal"))
    out = await d.execute_one("file_read", {"path": "x"}, "s1")
    assert json.loads(out)["status"] == "ok"
    assert reg.executed == [("file_read", False)]  # 低风险 → 不挂审批门


@pytest.mark.asyncio
async def test_execute_one_denies_hard() -> None:
    reg = _Reg()
    d = ToolDispatcher(reg, policy=Policy(profile="read_only"))
    out = json.loads(await d.execute_one("file_write", {"path": "x"}, "s1"))
    assert out["status"] == "denied"
    assert reg.executed == []  # 硬边界：未执行、未走审批


@pytest.mark.asyncio
async def test_execute_one_ask_attaches_approval() -> None:
    reg = _Reg()

    async def gate(tool, args, task_id):  # noqa: ARG001
        return True

    d = ToolDispatcher(reg, policy=Policy(profile="normal"), approval_gate=gate)
    await d.execute_one("file_write", {"path": "x"}, "s1")
    assert reg.executed == [("file_write", True)]  # 中风险 → 挂审批门


@pytest.mark.asyncio
async def test_execute_one_error_normalized() -> None:
    class _Boom:
        async def execute(self, *a, **kw):  # noqa: ANN002, ANN003
            raise RuntimeError("boom")

    d = ToolDispatcher(_Boom())
    out = json.loads(await d.execute_one("x", {}, "s"))
    assert "error" in out


@pytest.mark.asyncio
async def test_run_batch_order_and_execution() -> None:
    reg = _Reg()
    d = ToolDispatcher(reg)
    pending = [(0, _TC("a"), "a:", {}), (1, _TC("b"), "b:", {})]
    out = await d.run_batch(pending, "s1")
    assert [i for i, _ in out] == [0, 1]
    assert [n for n, _ in reg.executed] == ["a", "b"]


def test_normalize_json_and_text() -> None:
    assert ToolDispatcher.normalize('{"status":"ok"}') == '{"status":"ok"}'
    out = json.loads(ToolDispatcher.normalize("[todo] 无待办"))
    assert out["status"] == "text"
    assert out["output"] == "[todo] 无待办"


def test_denied_result_shape() -> None:
    out = json.loads(ToolDispatcher.denied_result("file_write", "超权"))
    assert out == {"status": "denied", "tool": "file_write", "note": "超权"}


# ---- tool_events ------------------------------------------------------------
def test_describe_tool_state() -> None:
    assert "记事本" in (describe_tool_state("app_open", {"name": "记事本"}) or "")
    assert describe_tool_state("app_focus", {"name": "微信"}) == "已聚焦应用：微信"
    assert describe_tool_state("unknown_tool", {}) is None


def test_describe_tool_event_ok_and_fail() -> None:
    assert (
        describe_tool_event("app_open", {"name": "网易云音乐"}, "ok")
        == "我帮用户打开了网易云音乐"
    )
    assert (
        describe_tool_event("app_open", {"name": "网易云音乐"}, "error")
        == "我尝试打开网易云音乐，但没成功"
    )
    # 未知工具不再返回 None（否则该轮在多轮历史/记忆里"消失"，跨轮接不上话），
    # 而是产出通用可读事件。
    assert describe_tool_event("unknown", {}, "ok") == "我调用了 unknown，已完成"
    # need_choice / pending 三态：交互式流程（点歌选版本/扫码登录）的关键措辞
    ev = describe_tool_event("netease_play", {"keyword": "晴天"}, "need_choice")
    assert "等用户确认" in (ev or ""), f"need_choice 应产出等待措辞，实际：{ev!r}"


def test_state_notes_record_replaces_same_prefix() -> None:
    sn = StateNotes()
    sn.record("s", "app_open", {"name": "记事本"})
    sn.record("s", "app_open", {"name": "微信"})
    notes = sn.get("s")
    assert len(notes) == 1  # 同前缀覆盖而非追加
    assert "微信" in notes[0]
    sn.set("s", ["自定义"])
    assert sn.get("s") == ["自定义"]
    sn.clear("s")
    assert sn.get("s") == []
    assert sn.snapshot() == {}
