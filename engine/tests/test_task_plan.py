"""S29 测试：Plan 审批（plan approval）+ 失败恢复（retry）。

覆盖 spec 的 LEVEL 4（"批量操作 → plan approval"）与 Era 4 的失败恢复：
- `plan()` 提交待批准计划，**批准前不可推进**；
- 批准时可**改写步骤**（用户改计划）；
- `retry()` 记录失败并在超限后判定任务失败（不再无限重试）；
- 摘要携带恢复线索（卡在哪 / 试过几次 / 上次为什么失败）。
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from yuiro.task import TaskRuntime
from yuiro.task.models import STEP_RUNNING, TaskStatus


class _Bus:
    """最小 EventBus（只记录事件类型，验证事件确实发出）。"""

    def __init__(self) -> None:
        self.types: list[str] = []

    async def publish(self, event) -> None:
        self.types.append(event.type)


def _rt(tmp: str, **kw) -> tuple[TaskRuntime, _Bus]:
    bus = _Bus()
    return TaskRuntime(store_dir=os.path.join(tmp, "tasks"), events=bus, **kw), bus


# ── Plan 提交与审批 ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_plan_creates_pending_approval() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, bus = _rt(tmp)
        task = await rt.plan("整理下载文件夹", ["列清单", "按类型归档"], session_id="s1")
        assert task.status is TaskStatus.PENDING_APPROVAL
        assert task.status.awaiting_approval is True
        assert all(s.status != STEP_RUNNING for s in task.steps)  # 未开始
        assert "task.planned" in bus.types
        assert "task.created" not in bus.types  # 批准前不算开始


@pytest.mark.asyncio
async def test_advance_blocked_before_approval() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, _ = _rt(tmp)
        task = await rt.plan("整理", ["a"])
        with pytest.raises(ValueError, match="批准"):
            await rt.advance(task.id)


@pytest.mark.asyncio
async def test_retry_blocked_before_approval() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, _ = _rt(tmp)
        task = await rt.plan("整理", ["a"])
        with pytest.raises(ValueError, match="批准"):
            await rt.retry(task.id, "炸了")


@pytest.mark.asyncio
async def test_approve_starts_task() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, bus = _rt(tmp)
        task = await rt.plan("整理", ["a", "b"])
        approved = await rt.approve(task.id)
        assert approved.status is TaskStatus.RUNNING
        assert approved.steps[0].status == STEP_RUNNING
        assert "task.created" in bus.types  # 批准后才算开始
        # 批准后可以正常推进
        await rt.advance(task.id)
        assert approved.progress() == "1/2"


@pytest.mark.asyncio
async def test_approve_can_rewrite_steps() -> None:
    """用户改计划：批准时传入新步骤清单。"""
    with tempfile.TemporaryDirectory() as tmp:
        rt, _ = _rt(tmp)
        task = await rt.plan("整理", ["旧步骤 1", "旧步骤 2"])
        approved = await rt.approve(task.id, steps=["新步骤 A", "新步骤 B", "新步骤 C"])
        assert [s.desc for s in approved.steps] == ["新步骤 A", "新步骤 B", "新步骤 C"]
        assert approved.steps[0].status == STEP_RUNNING


@pytest.mark.asyncio
async def test_reject_cancels_task() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, bus = _rt(tmp)
        task = await rt.plan("整理", ["a"])
        rejected = await rt.approve(task.id, approved=False, note="不放心")
        assert rejected.status is TaskStatus.CANCELLED
        assert "task.rejected" in bus.types
        # 终态不可推进
        with pytest.raises(ValueError):
            await rt.advance(task.id)


@pytest.mark.asyncio
async def test_approve_requires_pending_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, _ = _rt(tmp)
        task = await rt.create("直接开始", ["a"])
        with pytest.raises(ValueError, match="待批准"):
            await rt.approve(task.id)


@pytest.mark.asyncio
async def test_plan_persists_across_restart() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, _ = _rt(tmp)
        task = await rt.plan("整理", ["a", "b"])
        rt2, _ = _rt(tmp)  # 重启
        reloaded = rt2.get(task.id)
        assert reloaded is not None
        assert reloaded.status is TaskStatus.PENDING_APPROVAL
        # 重启后仍可批准
        assert (await rt2.approve(task.id)).status is TaskStatus.RUNNING


# ── 失败恢复 ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_retry_increments_attempts_and_keeps_running() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, bus = _rt(tmp)
        task = await rt.create("整理", ["a", "b"])
        retried = await rt.retry(task.id, "文件被占用")
        assert retried.status is TaskStatus.RUNNING
        assert retried.current_step().attempts == 1
        assert retried.current_step().last_error == "文件被占用"
        assert "task.retrying" in bus.types


@pytest.mark.asyncio
async def test_retry_exhausts_to_failed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, bus = _rt(tmp, max_attempts=3)
        task = await rt.create("整理", ["a"])
        await rt.retry(task.id, "失败 1")
        await rt.retry(task.id, "失败 2")
        assert task.status is TaskStatus.RUNNING
        await rt.retry(task.id, "失败 3")
        assert task.status is TaskStatus.FAILED
        assert "task.failed" in bus.types
        assert task.current_step().attempts == 3


@pytest.mark.asyncio
async def test_retry_after_success_moves_on() -> None:
    """换思路成功后：下一步骤的 attempts 从 0 开始（不继承上一步的失败计数）。"""
    with tempfile.TemporaryDirectory() as tmp:
        rt, _ = _rt(tmp)
        task = await rt.create("整理", ["a", "b"])
        await rt.retry(task.id, "第一次失败")
        await rt.advance(task.id, note="换方法成功了")
        assert task.current_step().desc == "b"
        assert task.current_step().attempts == 0


# ── 摘要（恢复线索）───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_summary_shows_pending_approval() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, _ = _rt(tmp)
        task = await rt.plan("整理下载文件夹", ["列清单"])
        text = task.summary()
        assert "等待用户确认" in text
        assert "整理下载文件夹" in text


@pytest.mark.asyncio
async def test_summary_includes_failure_hint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt, _ = _rt(tmp)
        task = await rt.create("整理", ["a"])
        await rt.retry(task.id, "权限不足")
        text = task.summary()
        assert "已尝试 1 次" in text
        assert "权限不足" in text
        assert "换思路" in text


# ── 工具 ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_task_plan_tool() -> None:
    from yuiro.tools.task_tool import TASK_TOOLS, TaskPlanTool

    assert TaskPlanTool in TASK_TOOLS
    with tempfile.TemporaryDirectory() as tmp:
        rt, _ = _rt(tmp)
        tool = TaskPlanTool(runtime=rt)
        assert tool.approval_required is False
        out = json.loads(
            await tool.run({"goal": "批量归档", "steps": ["列清单", "移动文件"]}, "sess-1")
        )
        assert out["status"] == "pending_approval"
        assert out["steps"] == ["列清单", "移动文件"]
        assert "等待用户确认" in out["note"]
        # 缺 goal → error
        bad = json.loads(await tool.run({}, "sess-1"))
        assert bad["status"] == "error"


@pytest.mark.asyncio
async def test_task_retry_tool_retrying_and_failed() -> None:
    from yuiro.tools.task_tool import TaskRetryTool

    with tempfile.TemporaryDirectory() as tmp:
        rt, _ = _rt(tmp, max_attempts=2)
        tool = TaskRetryTool(runtime=rt)
        task = await rt.create("整理", ["a"])
        first = json.loads(await tool.run({"reason": "占用"}, task.id))
        assert first["status"] == "retrying"
        assert first["attempts"] == 1
        second = json.loads(await tool.run({"reason": "还是占用"}, task.id))
        assert second["status"] == "failed"
        assert "如实告知用户" in second["note"]


@pytest.mark.asyncio
async def test_task_tools_without_runtime_degrade() -> None:
    from yuiro.tools.task_tool import TaskPlanTool, TaskRetryTool

    assert json.loads(await TaskPlanTool().run({"goal": "x"}, "s"))["status"] == "pending"
    assert json.loads(await TaskRetryTool().run({}, "s"))["status"] == "pending"


# ── 完整流程 ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_full_plan_flow() -> None:
    """plan → 批准 → 逐步推进 → 完成。"""
    with tempfile.TemporaryDirectory() as tmp:
        rt, bus = _rt(tmp)
        task = await rt.plan("整理下载文件夹", ["列清单", "按类型归档", "生成报告"])
        assert task.status is TaskStatus.PENDING_APPROVAL
        await rt.approve(task.id)
        await rt.advance(task.id, note="42 个文件")
        await rt.advance(task.id, note="已归档")
        await rt.advance(task.id, note="报告已生成")
        assert task.status is TaskStatus.COMPLETED
        assert task.progress() == "3/3"
        assert "task.completed" in bus.types
