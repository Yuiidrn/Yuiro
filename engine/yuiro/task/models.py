"""Task 模型（S08）：跨多轮目标的实体与状态机。

与 Session 的区别：**Session 管一次会话，Task 管一个目标**。
Task 可以跨多轮对话、跨工具调用轮次，甚至跨重启存在。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

# 步骤状态（比 TaskStatus 更细的执行粒度）
STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_DONE = "done"
STEP_SKIPPED = "skipped"
STEP_MARKS: dict[str, str] = {
    STEP_DONE: "[已完成]",
    STEP_RUNNING: "[进行中]",
    STEP_PENDING: "[待执行]",
    STEP_SKIPPED: "[已跳过]",
}


class TaskStatus(str, Enum):
    """任务状态（spec §3.9 的收敛子集）。"""

    CREATED = "created"
    # S29：计划已生成、等待用户批准（spec 的 plan approval / LEVEL 4）。
    # 此状态下**不可推进**——批准前不动手，是"批量操作要审批"的落地方式。
    PENDING_APPROVAL = "pending_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        """终态：不可再推进。"""
        return self in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED)

    @property
    def awaiting_approval(self) -> bool:
        """是否在等用户批准计划（S29）。"""
        return self is TaskStatus.PENDING_APPROVAL


@dataclass
class TaskStep:
    desc: str
    status: str = STEP_PENDING
    note: str = ""
    attempts: int = 0  # S29：本步骤已尝试次数（失败恢复的依据）
    last_error: str = ""  # S29：最近一次失败原因（供重试决策与上下文恢复）

    def to_dict(self) -> dict:
        return {
            "desc": self.desc,
            "status": self.status,
            "note": self.note,
            "attempts": self.attempts,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TaskStep:
        return cls(
            desc=str(d.get("desc", "")),
            status=str(d.get("status", STEP_PENDING)),
            note=str(d.get("note", "")),
            attempts=int(d.get("attempts", 0)),
            last_error=str(d.get("last_error", "")),
        )


@dataclass
class Task:
    id: str
    goal: str
    status: TaskStatus = TaskStatus.CREATED
    steps: list[TaskStep] = field(default_factory=list)
    # 追加式事件记录（Task Journal）：谁在什么时候把任务推进到了哪一步
    journal: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # ---- 查询 ---------------------------------------------------------------
    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps if s.status in (STEP_DONE, STEP_SKIPPED))

    def progress(self) -> str:
        return f"{self.done_count}/{len(self.steps)}" if self.steps else "0/0"

    def current_step(self) -> TaskStep | None:
        """当前应推进的步骤：优先 running，其次首个 pending。"""
        for s in self.steps:
            if s.status == STEP_RUNNING:
                return s
        for s in self.steps:
            if s.status == STEP_PENDING:
                return s
        return None

    def all_done(self) -> bool:
        return bool(self.steps) and all(s.status in (STEP_DONE, STEP_SKIPPED) for s in self.steps)

    # ---- 变更 ---------------------------------------------------------------
    def log(self, event: str, detail: str = "") -> None:
        self.journal.append(
            {
                "ts": time.time(),
                "event": event,
                "detail": detail,
                "status": self.status.value,
                "progress": self.progress(),
            }
        )
        self.updated_at = time.time()

    # ---- 序列化 -------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "journal": self.journal,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        return cls(
            id=str(d.get("id", "")),
            goal=str(d.get("goal", "")),
            status=TaskStatus(str(d.get("status", TaskStatus.CREATED.value))),
            steps=[TaskStep.from_dict(s) for s in d.get("steps", [])],
            journal=list(d.get("journal", [])),
            created_at=float(d.get("created_at", time.time())),
            updated_at=float(d.get("updated_at", time.time())),
        )

    # ---- 上下文摘要 ---------------------------------------------------------
    def summary(self) -> str:
        """供 ContextEngine 注入的【当前目标】文案（含恢复线索）。

        S29（Checkpoint）：把"卡在哪、试过几次、上次为什么失败"一并带上——
        重启或换会话后，LLM 仍能接着做，而不是从头重来或原地打转。
        """
        lines = [f"目标：{self.goal}", f"进度：{self.progress()}"]
        if self.status is TaskStatus.PENDING_APPROVAL:
            lines.append("状态：计划已提交，**等待用户确认后才可执行**（不要提前动手）")
        for s in self.steps:
            mark = STEP_MARKS.get(s.status, s.status)
            note = f"（{s.note}）" if s.note else ""
            lines.append(f"{mark} {s.desc}{note}")
        cur = self.current_step()
        if cur is not None and cur.attempts:
            err = f"（上次失败：{cur.last_error}）" if cur.last_error else ""
            lines.append(
                f"注意：当前步骤已尝试 {cur.attempts} 次{err}，请换思路，不要重复同样的做法"
            )
        return "\n".join(lines)
