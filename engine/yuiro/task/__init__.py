"""Task 包（S08 起）：跨多轮目标的实体与运行时。

- ``TaskStatus`` / ``TaskStep`` / ``Task``：目标状态机与步骤（含 Journal）；
- ``TaskRuntime``：create / advance / complete / cancel / fail + 落盘 + 重启恢复。

规范：``docs/spec/architecture-goal.md`` §3.5、``docs/plan/S08-task-runtime.md``。
"""
from yuiro.task.models import Task, TaskStatus, TaskStep
from yuiro.task.runtime import TaskRuntime

__all__ = ["Task", "TaskRuntime", "TaskStatus", "TaskStep"]
