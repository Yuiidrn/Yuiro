"""S08：TaskRuntime（状态机 / Journal 落盘 / 重启恢复 / Context 注入 / 工具）。

对应 docs/plan/S08-task-runtime.md。

注：不使用 pytest 的 ``tmp_path`` fixture —— 本机 ``C:\\Windows\\Temp\\pytest-of-*``
目录无访问权限（WinError 5），与项目其余测试一致改用 ``tempfile.TemporaryDirectory``。
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from yuiro.context import ContextBudget, ContextEngine
from yuiro.task import TaskRuntime, TaskStatus
from yuiro.tools.task_tool import (
    TASK_TOOLS,
    TaskAdvanceTool,
    TaskCompleteTool,
    TaskCreateTool,
    TaskListTool,
)


@pytest.fixture()
def taskdir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


def _rt(tmp: str) -> TaskRuntime:
    return TaskRuntime(store_dir=os.path.join(tmp, "tasks"))


# ---- 状态机 -----------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_and_progress(taskdir) -> None:
    rt = _rt(taskdir)
    task = await rt.create("整理下载文件夹", ["列清单", "分类归档", "生成报告"], session_id="s1")
    assert task.status == TaskStatus.RUNNING
    assert task.progress() == "0/3"
    assert task.current_step() is not None
    assert task.current_step().desc == "列清单"
    assert task.steps[0].status == "running"


@pytest.mark.asyncio
async def test_create_requires_goal(taskdir) -> None:
    rt = _rt(taskdir)
    with pytest.raises(ValueError):
        await rt.create("   ", ["a"])


@pytest.mark.asyncio
async def test_advance_flow_and_auto_complete(taskdir) -> None:
    rt = _rt(taskdir)
    task = await rt.create("目标", ["a", "b"], session_id="s1")
    t = await rt.advance(task.id, note="a 完成")
    assert t.progress() == "1/2"
    assert t.current_step().desc == "b"
    t = await rt.advance(task.id, note="b 完成")
    assert t.status == TaskStatus.COMPLETED
    assert t.progress() == "2/2"


@pytest.mark.asyncio
async def test_advance_by_step_index(taskdir) -> None:
    rt = _rt(taskdir)
    task = await rt.create("目标", ["a", "b", "c"])
    t = await rt.advance(task.id, step_index=2, note="先做 c")
    assert t.steps[2].status == "done"
    assert t.progress() == "1/3"


@pytest.mark.asyncio
async def test_terminal_guard(taskdir) -> None:
    rt = _rt(taskdir)
    task = await rt.create("目标", ["a"])
    await rt.complete(task.id, summary="搞定")
    assert task.status == TaskStatus.COMPLETED
    with pytest.raises(ValueError):
        await rt.advance(task.id)


@pytest.mark.asyncio
async def test_cancel_and_fail(taskdir) -> None:
    rt = _rt(taskdir)
    t1 = await rt.create("要取消的目标", ["a"])
    assert (await rt.cancel(t1.id, reason="用户说算了")).status == TaskStatus.CANCELLED
    t2 = await rt.create("会失败的目标", ["a"])
    assert (await rt.fail(t2.id, reason="工具报错")).status == TaskStatus.FAILED


# ---- 持久化 / 恢复 ----------------------------------------------------------
@pytest.mark.asyncio
async def test_journal_persist_and_restore(taskdir) -> None:
    rt = _rt(taskdir)
    task = await rt.create("跨重启目标", ["a", "b"], session_id="s1")
    await rt.advance(task.id, note="完成了 a")
    # 模拟重启：同目录新建实例
    rt2 = _rt(taskdir)
    restored = rt2.get(task.id)
    assert restored is not None
    assert restored.progress() == "1/2"
    assert any(j["event"] == "advance" for j in restored.journal)
    assert rt2.summary_for_context("") != ""


@pytest.mark.asyncio
async def test_terminal_task_not_in_active(taskdir) -> None:
    rt = _rt(taskdir)
    task = await rt.create("目标", ["a"])
    assert len(rt.list_active()) == 1
    await rt.complete(task.id)
    assert rt.list_active() == []
    assert rt.active_for("s1") is None


@pytest.mark.asyncio
async def test_active_for_falls_back_to_latest(taskdir) -> None:
    """会话未绑定 → 退回最近更新的活跃任务（单窗口桌宠的实际使用方式）。"""
    rt = _rt(taskdir)
    await rt.create("目标A", ["a"], session_id="s1")
    assert rt.active_for("unknown-session") is not None


# ---- 上下文摘要 -------------------------------------------------------------
@pytest.mark.asyncio
async def test_summary_for_context(taskdir) -> None:
    rt = _rt(taskdir)
    task = await rt.create("整理下载文件夹", ["列清单", "归档"], session_id="s1")
    await rt.advance(task.id)
    s = rt.summary_for_context("s1")
    assert "整理下载文件夹" in s
    assert "1/2" in s
    assert "[进行中]" in s or "[待执行]" in s


def test_summary_empty_without_tasks(taskdir) -> None:
    rt = _rt(taskdir)
    assert rt.summary_for_context("s") == ""


# ---- ContextEngine 分段 -----------------------------------------------------
@pytest.mark.asyncio
async def test_context_task_segment() -> None:
    engine = ContextEngine(
        system_prompt="SYS", persona_prompt="PERS", budget=ContextBudget(total=6000)
    )
    msgs = await engine.build(
        session_id="s",
        user_text="hi",
        task_summary="目标：整理下载文件夹\n进度：1/2\n[已完成] 列清单\n[进行中] 归档",
    )
    joined = "\n".join(str(m.get("content", "")) for m in msgs if m["role"] == "system")
    assert "【当前目标】" in joined
    assert "整理下载文件夹" in joined


@pytest.mark.asyncio
async def test_context_no_task_segment_by_default() -> None:
    engine = ContextEngine(system_prompt="SYS", persona_prompt="PERS")
    msgs = await engine.build(session_id="s", user_text="hi")
    assert all("【当前目标】" not in str(m.get("content", "")) for m in msgs)


def test_priority_ordering() -> None:
    from yuiro.context import engine as eng

    assert eng.P_PERSONA > eng.P_TASK > eng.P_EXPLICIT > eng.P_FACT


# ---- 工具 -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tools_roundtrip(taskdir) -> None:
    rt = _rt(taskdir)
    out = json.loads(
        await TaskCreateTool(runtime=rt).run(
            {"goal": "整理下载文件夹", "steps": ["列清单", "归档"]}, "s1"
        )
    )
    assert out["status"] == "ok"
    assert out["progress"] == "0/2"
    tid = out["task_id"]

    out2 = json.loads(await TaskAdvanceTool(runtime=rt).run({"task_id": tid, "note": "列完"}, "s1"))
    assert out2["progress"] == "1/2"
    assert out2["task_status"] == "running"

    out3 = json.loads(await TaskListTool(runtime=rt).run({}, "s1"))
    assert out3["count"] == 1
    assert out3["tasks"][0]["goal"] == "整理下载文件夹"

    out4 = json.loads(await TaskCompleteTool(runtime=rt).run({"task_id": tid}, "s1"))
    assert out4["task_status"] == "completed"


@pytest.mark.asyncio
async def test_advance_tool_falls_back_to_active_task(taskdir) -> None:
    """未传 task_id 时推进当前会话的活跃任务。"""
    rt = _rt(taskdir)
    await rt.create("目标", ["a", "b"], session_id="s1")
    out = json.loads(await TaskAdvanceTool(runtime=rt).run({}, "s1"))
    assert out["status"] == "ok"
    assert out["progress"] == "1/2"


@pytest.mark.asyncio
async def test_tools_degrade_without_runtime() -> None:
    out = json.loads(await TaskCreateTool().run({"goal": "x"}, "s"))
    assert out["status"] == "pending"


def test_tool_schemas() -> None:
    for cls in TASK_TOOLS:
        s = cls().schema()
        assert s["type"] == "function"
        assert s["function"]["name"] == cls.name
        assert s["function"]["description"]


def test_build_agent_loop_registers_task_tools(taskdir) -> None:
    from yuiro.agent import build_agent_loop
    from yuiro.config import MemoryConfig, PersonaConfig

    rt = _rt(taskdir)
    loop = build_agent_loop(
        base_url="http://127.0.0.1:1/v1",
        model="m",
        api_key="k",
        persona=PersonaConfig(),
        memory_config=MemoryConfig(),
        task_runtime=rt,
    )
    names = [s["function"]["name"] for s in loop._tools.schemas()]
    assert {"task_create", "task_advance", "task_complete", "task_list"} <= set(names)
    assert loop._tasks is rt
