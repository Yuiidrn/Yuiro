"""Task 工具（S08）：让 Agent 自主登记/推进跨多轮目标。

- 免审批（不触碰系统资源，只管理目标状态）；
- 未注入 TaskRuntime 时返回 pending 说明（与 system_tool 的同款降级策略）；
- ``run(args, task_id)`` 的 ``task_id`` 实参由 AgentLoop 传入 **session_id**
  （见 agent/__init__.py 的 tools.execute 调用），因此可直接用于任务绑定。
"""
from __future__ import annotations

import json

from yuiro.tools import BaseTool


class TaskCreateTool(BaseTool):
    name = "task_create"
    approval_required = False
    description = (
        "为一个需要多步完成的目标创建任务（跨多轮跟踪进度）。"
        "当用户提出需要好几步才能做完的事（如\"帮我整理下载文件夹\"、"
        "\"研究一下这个问题然后写个报告\"、\"帮我把这批文件按日期归档\"），"
        "调用本工具登记目标与步骤清单；之后每完成一步调用 task_advance 推进。"
        "简单的一步操作（打开软件、播放音乐、闲聊）不要创建任务。"
    )

    def __init__(self, runtime=None) -> None:
        self._runtime = runtime

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "目标（一句话，如 '整理下载文件夹'）",
                        },
                        "steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "步骤清单（2-6 步，按执行顺序）",
                        },
                    },
                    "required": ["goal"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        if self._runtime is None:
            return json.dumps(
                {"status": "pending", "note": "TaskRuntime 未注入"}, ensure_ascii=False
            )
        goal = str(args.get("goal", "")).strip()
        if not goal:
            return json.dumps({"status": "error", "note": "goal 不能为空"}, ensure_ascii=False)
        steps = [str(s) for s in (args.get("steps") or [])]
        try:
            task = await self._runtime.create(goal, steps, session_id=task_id)
        except Exception as exc:  # noqa: BLE001 — 创建失败透出而不抛
            return json.dumps({"status": "error", "note": str(exc)}, ensure_ascii=False)
        cur = task.current_step()
        return json.dumps(
            {
                "status": "ok",
                "task_id": task.id,
                "goal": task.goal,
                "progress": task.progress(),
                "current_step": cur.desc if cur is not None else "",
                "note": "任务已登记；每完成一步调用 task_advance(task_id=...) 推进",
            },
            ensure_ascii=False,
        )


class TaskAdvanceTool(BaseTool):
    name = "task_advance"
    approval_required = False
    description = (
        "推进当前任务：把正在进行的步骤标记完成，并自动把下一步转为进行中。"
        "每真正完成一步就调用一次；传入 task_id（来自 task_create 或 task_list）。"
        "若任务的全部步骤都已完成，任务会自动标记为完成。"
    )

    def __init__(self, runtime=None) -> None:
        self._runtime = runtime

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "任务 id（task_xxx）"},
                        "note": {
                            "type": "string",
                            "description": "这一步做了什么/结果如何（简短）",
                        },
                    },
                    "required": ["task_id"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        if self._runtime is None:
            return json.dumps(
                {"status": "pending", "note": "TaskRuntime 未注入"}, ensure_ascii=False
            )
        tid = str(args.get("task_id", "")).strip() or (
            self._runtime.active_for(task_id).id
            if self._runtime.active_for(task_id) is not None
            else ""
        )
        if not tid:
            return json.dumps(
                {"status": "error", "note": "未指定 task_id 且当前无活跃任务"},
                ensure_ascii=False,
            )
        try:
            task = await self._runtime.advance(tid, note=str(args.get("note", "")))
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"status": "error", "note": str(exc)}, ensure_ascii=False)
        cur = task.current_step()
        return json.dumps(
            {
                "status": "ok",
                "task_id": task.id,
                "task_status": task.status.value,
                "progress": task.progress(),
                "current_step": cur.desc if cur is not None else "",
            },
            ensure_ascii=False,
        )


class TaskCompleteTool(BaseTool):
    name = "task_complete"
    approval_required = False
    description = (
        "把任务标记为完成（中止剩余步骤）。当目标已达成或用户说\"不用做了/算了\"时调用；"
        "用户明确要求放弃时改用 task_list 确认后再结束。"
    )

    def __init__(self, runtime=None) -> None:
        self._runtime = runtime

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "任务 id（task_xxx）"},
                        "summary": {"type": "string", "description": "结果小结（可选）"},
                    },
                    "required": ["task_id"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        if self._runtime is None:
            return json.dumps(
                {"status": "pending", "note": "TaskRuntime 未注入"}, ensure_ascii=False
            )
        tid = str(args.get("task_id", "")).strip()
        if not tid:
            return json.dumps({"status": "error", "note": "task_id 不能为空"}, ensure_ascii=False)
        try:
            task = await self._runtime.complete(tid, summary=str(args.get("summary", "")))
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"status": "error", "note": str(exc)}, ensure_ascii=False)
        return json.dumps(
            {"status": "ok", "task_id": task.id, "task_status": task.status.value},
            ensure_ascii=False,
        )


class TaskListTool(BaseTool):
    name = "task_list"
    approval_required = False
    description = (
        "列出当前未完成的任务（目标 + 进度 + 当前步骤）。"
        "当用户问\"我们刚才做到哪了\"、\"还有什么没做\"时调用。"
    )

    def __init__(self, runtime=None) -> None:
        self._runtime = runtime

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del args
        if self._runtime is None:
            return json.dumps(
                {"status": "pending", "note": "TaskRuntime 未注入"}, ensure_ascii=False
            )
        tasks = self._runtime.list_active()
        return json.dumps(
            {
                "status": "ok",
                "count": len(tasks),
                "tasks": [
                    {
                        "task_id": t.id,
                        "goal": t.goal,
                        "progress": t.progress(),
                        "current_step": (t.current_step().desc if t.current_step() else ""),
                    }
                    for t in tasks
                ],
            },
            ensure_ascii=False,
        )


class TaskPlanTool(BaseTool):
    name = "task_plan"
    approval_required = False
    description = (
        "提交一份**多步计划**给用户先确认，再开始执行。"
        "当你判断这件事需要好几步、且**会影响大量文件或难以回退**时"
        "（如\"整理整个下载文件夹\"\"批量重命名\"\"按规则归档\"），用本工具提交计划；"
        "用户确认后你才会被要求继续执行（可能按原计划，也可能被改过）。"
        "简单一步的事（打开软件、播放音乐、建一个文件）不要用本工具。"
        "注意：提交计划后**不要**立刻动手执行，先等用户确认结果。"
    )

    def __init__(self, runtime=None) -> None:
        self._runtime = runtime

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "目标（一句话，如 '整理下载文件夹'）",
                        },
                        "steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "计划步骤（2-6 步，按执行顺序；用户可能修改）",
                        },
                    },
                    "required": ["goal"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        if self._runtime is None:
            return json.dumps(
                {"status": "pending", "note": "TaskRuntime 未注入"}, ensure_ascii=False
            )
        goal = str(args.get("goal", "")).strip()
        if not goal:
            return json.dumps({"status": "error", "note": "goal 不能为空"}, ensure_ascii=False)
        steps = [str(s) for s in (args.get("steps") or [])]
        try:
            task = await self._runtime.plan(goal, steps, session_id=task_id)
        except Exception as exc:  # noqa: BLE001 — 提交失败透出而不抛
            return json.dumps({"status": "error", "note": str(exc)}, ensure_ascii=False)
        return json.dumps(
            {
                "status": "pending_approval",
                "task_id": task.id,
                "goal": task.goal,
                "steps": [s.desc for s in task.steps],
                "note": "计划已提交，正在等待用户确认；确认前不要开始执行",
            },
            ensure_ascii=False,
        )


class TaskRetryTool(BaseTool):
    name = "task_retry"
    approval_required = False
    description = (
        "当某一步执行**失败**、你想换一种方法再试时调用（记录一次失败并重试）。"
        "调用前请先想清楚失败原因并换思路——用同样的做法重复重试没有意义。"
        "系统会在多次失败后自动判定任务失败，届时如实告知用户即可。"
    )

    def __init__(self, runtime=None) -> None:
        self._runtime = runtime

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "任务 id"},
                        "reason": {
                            "type": "string",
                            "description": "这次失败的原因（一句话）",
                        },
                    },
                    "required": ["task_id"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        if self._runtime is None:
            return json.dumps(
                {"status": "pending", "note": "TaskRuntime 未注入"}, ensure_ascii=False
            )
        # task_id 参数优先（跨会话时可显式指定）；缺省用当前会话绑定的任务
        target = str(args.get("task_id", "")).strip() or task_id
        reason = str(args.get("reason", ""))
        try:
            task = await self._runtime.retry(target, reason)
        except (KeyError, ValueError) as exc:
            return json.dumps({"status": "error", "note": str(exc)}, ensure_ascii=False)
        if task.status.terminal:
            return json.dumps(
                {
                    "status": "failed",
                    "task_id": task.id,
                    "note": "已达到重试上限，任务判定为失败；请如实告知用户并说明卡在哪一步",
                    "summary": task.summary(),
                },
                ensure_ascii=False,
            )
        cur = task.current_step()
        return json.dumps(
            {
                "status": "retrying",
                "task_id": task.id,
                "attempts": cur.attempts if cur is not None else 0,
                "current_step": cur.desc if cur is not None else "",
                "note": "已记录失败，请换一种方法继续（不要重复同样的做法）",
            },
            ensure_ascii=False,
        )


TASK_TOOLS = [
    TaskCreateTool,
    TaskAdvanceTool,
    TaskCompleteTool,
    TaskListTool,
    TaskPlanTool,
    TaskRetryTool,
]
