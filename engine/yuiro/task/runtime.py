"""TaskRuntime（S08）：跨多轮目标的唯一管理入口。

职责：
- create / advance / complete / cancel / fail（状态机 + 终态保护）；
- Task Journal 落盘（``<store_dir>/<task_id>.json``）→ 重启可恢复；
- 事件发布（可选 EventBus）：task.created / task.updated / task.completed；
- ``summary_for_context``：给 ContextEngine 的【当前目标】文案。

原则：任何失败都不得影响主链路（IO/事件异常静默）。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from yuiro.logger import vlog
from yuiro.task.models import (
    STEP_DONE,
    STEP_PENDING,
    STEP_RUNNING,
    Task,
    TaskStatus,
    TaskStep,
)


class TaskRuntime:
    def __init__(
        self,
        *,
        store_dir: str | Path = "data/tasks",
        events=None,
        load_limit: int = 50,
        max_attempts: int = 3,
    ) -> None:
        self._dir = Path(store_dir)
        self._events = events
        self._load_limit = load_limit
        # S29：单步最大尝试次数（达到即判任务失败，避免无限重试）
        self._max_attempts = max(1, int(max_attempts))
        self._tasks: dict[str, Task] = {}
        self._active: dict[str, str] = {}  # session_id -> task_id（该会话当前目标）
        self._load()

    # ---- 持久化 -------------------------------------------------------------
    def _path(self, task_id: str) -> Path:
        return self._dir / f"{task_id}.json"

    def _load(self) -> None:
        """启动时从磁盘恢复（只载入最近 load_limit 个文件）。"""
        try:
            if not self._dir.exists():
                return
            files = sorted(
                self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )[: self._load_limit]
            for f in files:
                try:
                    task = Task.from_dict(json.loads(f.read_text(encoding="utf-8")))
                    if task.id:
                        self._tasks[task.id] = task
                except Exception:  # noqa: BLE001, S112 — 单个损坏文件不影响其余
                    continue
            if self._tasks:
                active = len(self.list_active())
                vlog("task", f"[任务恢复] 已载入 {len(self._tasks)} 个任务（活跃 {active} 个）")
        except Exception as exc:  # noqa: BLE001 — 恢复失败不阻断启动
            vlog("task", f"[任务恢复] 失败（忽略）：{exc}")

    def _persist(self, task: Task) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path(task.id).write_text(
                json.dumps(task.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 — 落盘失败不阻断任务推进
            vlog("task", f"[任务落盘] 失败（忽略）：{exc}")

    async def _emit(self, event_type: str, task: Task, extra: dict | None = None) -> None:
        if self._events is None:
            return
        try:
            from yuiro.runtime.events import AgentEvent

            # S18 修复：AgentEvent.session_id 为必填，此前漏传导致事件被 except 静默吞掉
            # （任务事件从未真正发布过）。此处由 _active 反查该任务的会话。
            session_id = ""
            for sid, tid in self._active.items():
                if tid == task.id:
                    session_id = sid
                    break
            payload = {"task_id": task.id, "goal": task.goal, "status": task.status.value}
            if extra:
                payload.update(extra)
            await self._events.publish(
                AgentEvent(
                    type=event_type,
                    source="TaskRuntime",
                    session_id=session_id,
                    payload=payload,
                )
            )
        except Exception:  # noqa: BLE001, S110 — 事件失败不影响任务
            pass

    # ---- 查询 ---------------------------------------------------------------
    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def active_for(self, session_id: str = "") -> Task | None:
        """该会话当前目标；无绑定则退回最近更新的活跃任务。"""
        tid = self._active.get(session_id or "")
        if tid is not None:
            task = self._tasks.get(tid)
            if task is not None and not task.status.terminal:
                return task
        return self.list_active()[0] if self.list_active() else None

    def list_active(self) -> list[Task]:
        """未结束的任务，按更新时间倒序。"""
        items = [t for t in self._tasks.values() if not t.status.terminal]
        items.sort(key=lambda t: t.updated_at, reverse=True)
        return items

    def list_all(self) -> list[Task]:
        """全部任务（含终态），按更新时间倒序——供调试台/管理视图（S29）。"""
        items = list(self._tasks.values())
        items.sort(key=lambda t: t.updated_at, reverse=True)
        return items

    def bind(self, session_id: str, task_id: str) -> None:
        """把任务绑定为某会话的当前目标。"""
        if task_id in self._tasks:
            self._active[session_id] = task_id

    def summary_for_context(self, session_id: str = "") -> str:
        """给 ContextEngine 的【当前目标】文案（无活跃任务返回空）。"""
        task = self.active_for(session_id)
        return task.summary() if task is not None else ""

    # ---- 变更 ---------------------------------------------------------------
    def _require(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"任务不存在: {task_id}")
        return task

    async def _create_task(
        self, goal: str, steps: list[str] | None, session_id: str, *, status: TaskStatus
    ) -> Task:
        """创建任务实体（S29：create / plan 共用的落盘逻辑）。"""
        goal = (goal or "").strip()
        if not goal:
            raise ValueError("任务目标不能为空")
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        cleaned = [s.strip() for s in (steps or []) if str(s).strip()]
        task = Task(
            id=task_id,
            goal=goal[:200],
            status=status,
            steps=[TaskStep(desc=s[:120]) for s in cleaned],
        )
        # 只有"直接开始"的任务才把首步置为进行中（待批准的先不动手）
        if status is TaskStatus.RUNNING and task.steps:
            task.steps[0].status = STEP_RUNNING
        task.log(
            "created" if status is TaskStatus.RUNNING else "planned",
            f"共 {len(task.steps)} 步",
        )
        self._tasks[task_id] = task
        if session_id:
            self._active[session_id] = task_id
        self._persist(task)
        return task

    async def create(
        self, goal: str, steps: list[str] | None = None, session_id: str = ""
    ) -> Task:
        """创建任务并立即开始：目标 + 步骤清单；首个步骤置为进行中。"""
        task = await self._create_task(goal, steps, session_id, status=TaskStatus.RUNNING)
        vlog("task", f"[任务创建] {task.id} {task.goal}（{len(task.steps)} 步）")
        await self._emit("task.created", task)
        return task

    async def plan(
        self, goal: str, steps: list[str] | None = None, session_id: str = ""
    ) -> Task:
        """S29：提交一份**待批准**的计划（spec 的 plan approval / LEVEL 4）。

        与 ``create`` 的区别：**不立刻开始执行** —— 状态为 ``PENDING_APPROVAL``，
        必须经 ``approve`` 才转 RUNNING；批准前 ``advance`` / ``retry`` 都会被拒绝。
        适用于"会影响大量文件 / 难以回退"的多步操作。
        """
        task = await self._create_task(
            goal, steps, session_id, status=TaskStatus.PENDING_APPROVAL
        )
        vlog(
            "task",
            f"[计划提交] {task.id} {task.goal}（{len(task.steps)} 步，待用户确认）",
        )
        await self._emit("task.planned", task, {"steps": [s.desc for s in task.steps]})
        return task

    async def approve(
        self,
        task_id: str,
        *,
        approved: bool = True,
        steps: list[str] | None = None,
        note: str = "",
    ) -> Task:
        """批准 / 拒绝待批准的计划（S29）。

        批准时可用 ``steps`` **改写计划**（用户"改一下再执行"是常见需求）。
        """
        task = self._require(task_id)
        if not task.status.awaiting_approval:
            raise ValueError(f"任务不在待批准状态（{task.status.value}）")
        if not approved:
            task.status = TaskStatus.CANCELLED
            task.log("rejected", note or "用户拒绝了计划")
            self._persist(task)
            vlog("task", f"[计划被拒] {task.id} {task.goal}")
            await self._emit("task.rejected", task)
            return task
        if steps:
            cleaned = [str(s).strip() for s in steps if str(s).strip()]
            if cleaned:
                task.steps = [TaskStep(desc=s[:120]) for s in cleaned]
        task.status = TaskStatus.RUNNING
        if task.steps:
            task.steps[0].status = STEP_RUNNING
        task.log("approved", note or "用户批准计划")
        self._persist(task)
        vlog(
            "task",
            f"[计划批准] {task.id} {task.goal}（{len(task.steps)} 步，开始执行）",
        )
        await self._emit("task.created", task)  # 批准后才算真正开始
        return task

    async def advance(
        self, task_id: str, note: str = "", step_index: int | None = None
    ) -> Task:
        """推进任务：把指定/当前步骤标记完成，下一个待执行步骤转为进行中。"""
        task = self._require(task_id)
        if task.status.terminal:
            raise ValueError(f"任务已结束（{task.status.value}），无法推进")
        if task.status.awaiting_approval:
            raise ValueError("计划尚未获用户批准，不能推进（先等用户确认）")
        target: TaskStep | None = None
        if step_index is not None and 0 <= step_index < len(task.steps):
            target = task.steps[step_index]
        else:
            target = task.current_step()
        if target is not None:
            target.status = STEP_DONE
            if note:
                target.note = note[:120]
        nxt = task.current_step()
        if nxt is not None and nxt.status == STEP_PENDING:
            nxt.status = STEP_RUNNING
        if task.all_done():
            task.status = TaskStatus.COMPLETED
            task.log("completed", "全部步骤完成")
            self._persist(task)
            vlog("task", f"[任务完成] {task.id} {task.goal}（{task.progress()}）")
            await self._emit("task.completed", task)
            return task
        task.status = TaskStatus.RUNNING
        task.log("advance", note or (target.desc if target is not None else ""))
        self._persist(task)
        vlog(
            "task",
            f"[任务推进] {task.id} {task.progress()} "
            f"{'→ ' + nxt.desc if nxt is not None else ''}",
        )
        await self._emit("task.updated", task, {"progress": task.progress()})
        return task

    async def complete(self, task_id: str, summary: str = "") -> Task:
        task = self._require(task_id)
        for s in task.steps:
            if s.status in (STEP_PENDING, STEP_RUNNING):
                s.status = STEP_DONE
        task.status = TaskStatus.COMPLETED
        task.log("completed", summary or "手动标记完成")
        self._persist(task)
        vlog("task", f"[任务完成] {task.id} {task.goal}")
        await self._emit("task.completed", task)
        return task

    async def cancel(self, task_id: str, reason: str = "") -> Task:
        task = self._require(task_id)
        task.status = TaskStatus.CANCELLED
        task.log("cancelled", reason or "用户取消")
        self._persist(task)
        vlog("task", f"[任务取消] {task.id} {task.goal}（{reason or '未说明'}）")
        await self._emit("task.cancelled", task)
        return task

    async def retry(self, task_id: str, reason: str = "", note: str = "") -> Task:
        """S29：记录一次失败并决定"再试"还是"放弃"（失败恢复）。

        - 当前步骤 ``attempts += 1`` 并记录 ``last_error``；未达 ``max_attempts``
          → 保持 RUNNING（LLM 应**换思路**再试，摘要里会带失败原因）；
        - 达到上限 → 任务转 ``FAILED``（不再无限重试）。

        返回值：任务对象（调用方用 ``status`` 判断是重试还是已失败）。
        """
        del note
        task = self._require(task_id)
        if task.status.terminal:
            raise ValueError(f"任务已结束（{task.status.value}），无法重试")
        if task.status.awaiting_approval:
            raise ValueError("计划尚未获用户批准，不能重试")

        target = task.current_step()
        detail = (reason or "").strip()[:200]
        if target is not None:
            target.attempts += 1
            target.status = STEP_RUNNING
            if detail:
                target.last_error = detail
        attempts = target.attempts if target is not None else 0

        if target is not None and attempts >= self._max_attempts:
            task.log("retry_exhausted", f"{target.desc}：{detail or '多次失败'}")
            return await self.fail(
                task_id, detail or f"步骤「{target.desc}」重试 {attempts} 次仍未成功"
            )

        task.status = TaskStatus.RUNNING
        task.log("retry", f"{target.desc if target else ''}：{detail or '换思路重试'}")
        self._persist(task)
        vlog(
            "task",
            f"[任务重试] {task.id} {task.progress()} 第 {attempts}/{self._max_attempts} 次",
        )
        await self._emit(
            "task.retrying", task, {"attempts": attempts, "reason": detail}
        )
        return task

    async def fail(self, task_id: str, reason: str = "") -> Task:
        task = self._require(task_id)
        task.status = TaskStatus.FAILED
        task.log("failed", reason or "执行失败")
        self._persist(task)
        vlog("task", f"[任务失败] {task.id} {task.goal}（{reason or '未说明'}）")
        await self._emit("task.failed", task)
        return task

    # ---- 维护 ---------------------------------------------------------------
    def prune(self, keep_days: float = 7.0) -> int:
        """清理长期结束的任务文件（返回删除数）。"""
        cutoff = time.time() - keep_days * 86400
        removed = 0
        for task_id, task in list(self._tasks.items()):
            if task.status.terminal and task.updated_at < cutoff:
                self._tasks.pop(task_id, None)
                try:
                    self._path(task_id).unlink(missing_ok=True)
                except Exception:  # noqa: BLE001, S112
                    continue
                removed += 1
        return removed

    # ---- RuntimeContract（S15）----------------------------------------------
    # 注意：本类已有业务方法 ``cancel(task_id)``（取消某个任务），与契约的
    # ``cancel(session_id)`` 同名但语义不同 —— 因此契约的 cancel 由
    # ``TaskRuntimeAdapter`` 提供（见 runtime/adapters.py），此处**不得覆盖**。
    def runtime_name(self) -> str:
        return "task"

    async def on_session_close(self, session_id: str) -> None:
        """会话关闭：解绑该会话的当前目标（任务本身保留，可后续恢复）。"""
        self._active.pop(session_id, None)

    def state(self) -> dict:
        return {"active": len(self.list_active()), "total": len(self._tasks)}
