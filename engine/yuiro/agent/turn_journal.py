"""回合日志（S47 / B4）：把"这一轮做到哪"写成**追加式事件**，供崩溃后查询。

**为什么需要它** —— 现在持久化的粒度是：

- **任务级**：``TaskRuntime`` + Journal ✓
- **会话级**：``SessionManager.revive``（身份/创建时间/活跃时间可还原）✓
- **事件级**：``EventLog``（追加落盘 + 回放 + 自动轮转）✓

**缺的是"这一轮"** —— 已经调过哪些工具、各自结果是什么。引擎崩溃或重启后，
进行中的回合**全部丢失**，只能从头重来；而工具可能有副作用（写文件、放歌、
发消息），重来就可能**重复执行**。前沿做法（durable execution）的核心正是：

> 在声明成功之前持久化每一步，并按确定性的边界重放。

本模块做的是**第一步：记录 + 可查询**。真正的"自动续跑"还要处理幂等副作用
（哪些步骤可以安全重放、哪些必须跳过），属于后续工作 —— 但**没有记录就无从谈起**；
而且有了它，用户至少能看到"上次那句话做到哪了"，而不是一片空白。

**为什么是"薄层"而不是又一套存储**：``EventLog`` 已经是追加式、可回放、
按会话分文件、自动轮转的事件流，正是 durable execution 需要的东西。再写一套
持久化只会多出一个会漂移的真相源 —— 本项目已经在"多套并存"上吃过三次亏
（提示词三份、上下文注入两条、工具轮绕过预算）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from yuiro.logger import vlog

#: 一轮对话的生命周期事件类型（落进 EventLog 的 type 字段）
TURN_STARTED = "turn.started"
TURN_STEP = "turn.step"
TURN_COMPLETED = "turn.completed"


@dataclass
class TurnRecord:
    """一轮对话的快照（**由事件流重建**，不单独存储）。"""

    session_id: str = ""
    generation: int = 0
    started_at: float = 0.0
    text: str = ""
    steps: list[dict] = field(default_factory=list)
    finished: bool = False
    reply_preview: str = ""

    def describe(self) -> str:
        """一行人类可读的进度 —— 用于日志，或告诉用户"上次做到哪了"。"""
        if not self.steps:
            return f"「{self.text[:30]}」刚开口，还没动手"
        done = "；".join(
            f"{s.get('tool')}({s.get('status') or '?'})" for s in self.steps[-5:]
        )
        tail = "已完成" if self.finished else "尚未完成"
        return f"「{self.text[:30]}」已执行：{done} —— {tail}"


def _step_effect(step: dict) -> str:
    """取步骤的副作用等级：事件里记了就用它，否则**按工具名重新推断**。

    为什么要有"否则"这一支：S48 之前写入的事件没有 ``effect`` 字段。重放历史
    数据时既不能让它们一律落进"危险"堆（会把老记录全吓一遍），也不能一律当
    安全（那等于没有防护）—— 按名字保守推断是唯一合理的折中。
    """
    from yuiro.tools import EFFECT_ALL, infer_effect

    declared = str(step.get("effect") or "").strip().lower()
    if declared in EFFECT_ALL:
        return declared
    return infer_effect(str(step.get("tool") or ""))


@dataclass
class ResumePlan:
    """崩溃恢复建议（S48 / 方案 D）：**按步骤副作用分级**决定怎么续。

    为什么不是三个"一律"：
    - **一律重放** → 放歌、发消息会**重复**（外部副作用不幂等）；
    - **一律跳过** → 读文件这类安全步骤也白丢了，用户还得从头说一遍；
    - **一律问用户** → 唠叨到没人看，**等于没有防护**。

    所以按 ``effect`` 分成两堆：``read`` / ``local`` 可安全重放，
    ``external`` 必须问用户。这样"要不要确认"取决于**这一轮究竟做了什么**，
    而不是取决于我们怕不怕。
    """

    record: TurnRecord
    #: 可安全重放的步骤（只读 / 本地写）
    replayable: list[dict] = field(default_factory=list)
    #: 对外产生影响的步骤 —— 重做可能重复，必须由用户确认
    risky: list[dict] = field(default_factory=list)

    @property
    def auto_safe(self) -> bool:
        """是否可以**不问用户**直接续（这一轮没有任何外部副作用步骤）。"""
        return not self.risky

    def question(self) -> str:
        """给用户的询问（无危险步骤时返回空串）。

        刻意只给**工具名清单**、不在这里编自然语言 —— 由上层（LLM 或 UI）按
        人设转述，与项目一贯的"机器产事实、模型说话"分工一致。
        """
        if not self.risky:
            return ""
        tools = "、".join(
            list(dict.fromkeys(str(s.get("tool")) for s in self.risky))[:4]
        )
        return (
            f"上次「{self.record.text[:20]}」做到一半，其中 {tools} 会对外产生影响，"
            f"重做可能重复。要继续吗？"
        )

    def describe(self) -> str:
        """一行摘要（日志 / 调试面板用）。"""
        return (
            f"未完成的回合：{self.record.describe()}｜"
            f"可安全重放 {len(self.replayable)} 步 / 需确认 {len(self.risky)} 步"
        )


def replay_unfinished(
    events: list[dict], *, session_id: str = ""
) -> TurnRecord | None:
    """从事件流重放，找"开始过但没结束"的回合；无则 ``None``。

    ⚠ 这就是 durable execution 里的 **replay boundary** —— "可以安全重放的起点"：
    之前的步骤都已落盘（副作用已发生），之后的工作尚未开始。

    **刻意写成纯函数、不碰 IO**：判据能从生成器/IO 里搬出来才能被单测覆盖，
    这正是 P0-A（TurnState）与本次都坚持的做法。
    """
    current: TurnRecord | None = None
    for e in events or []:
        etype = e.get("type")
        payload = e.get("payload") or {}
        if etype == TURN_STARTED:
            # 新回合开始 → 上一个没结束的被取代（同一会话同一时刻只有一个进行中）
            current = TurnRecord(
                session_id=str(e.get("session_id") or session_id),
                generation=int(e.get("generation") or 0),
                started_at=float(e.get("ts") or 0.0),
                text=str(payload.get("text") or ""),
            )
        elif etype == TURN_STEP and current is not None:
            current.steps.append(dict(payload))
        elif etype == TURN_COMPLETED and current is not None:
            current.finished = True
            current.reply_preview = str(payload.get("reply") or "")
    if current is None or current.finished:
        return None
    return current


class TurnJournal:
    """回合级 Journal：写入靠 ``EventBus``，查询靠 ``EventLog``。

    两个依赖都可选（缺哪个就退化）：
    - 只有 ``events``：只能写（正常运行时够用）；
    - 加上 ``event_log``：还能查"未完成的回合"（复活/诊断场景需要）。
    """

    def __init__(self, *, events=None, event_log=None) -> None:
        self._events = events
        self._log = event_log

    async def _emit(
        self, session_id: str, generation: int, etype: str, payload: dict
    ) -> None:
        """发一条回合事件（失败静默 —— 持久化绝不能反过来打断对话）。"""
        if self._events is None:
            return
        try:
            from yuiro.runtime.events import AgentEvent

            await self._events.publish(
                AgentEvent(
                    type=etype,
                    source="TurnJournal",
                    session_id=session_id,
                    generation=generation,
                    payload=payload,
                )
            )
        except Exception as exc:  # noqa: BLE001
            vlog("agent", f"[回合日志] {etype} 写入失败（忽略）：{exc}")

    # ---- 写入 ---------------------------------------------------------------
    async def started(self, session_id: str, generation: int, text: str) -> None:
        """标记一轮开始 —— 这是 replay boundary 的**上界**。"""
        await self._emit(
            session_id, generation, TURN_STARTED, {"text": (text or "")[:200]}
        )

    async def step(
        self,
        session_id: str,
        generation: int,
        *,
        tool: str,
        status: str = "",
        preview: str = "",
        effect: str = "",
    ) -> None:
        """记录一次工具步骤。**只记已完成的** —— 它才代表"已经发生的副作用"。

        ``effect``：副作用等级（S48）。记录它，恢复时才能**按步骤分级**决定
        是"直接重放"还是"必须问用户" —— 而不是一律重放（会重复放歌）或
        一律跳过（读文件也白做了）。
        """
        await self._emit(
            session_id,
            generation,
            TURN_STEP,
            {
                "tool": str(tool),
                "status": str(status),
                "preview": (preview or "")[:200],
                "effect": str(effect or ""),
            },
        )

    async def completed(
        self,
        session_id: str,
        generation: int,
        *,
        reply: str = "",
        stop_reason: str = "",
    ) -> None:
        """标记一轮结束。**正常结束与预算耗尽都算结束** —— 结束就是结束。"""
        await self._emit(
            session_id,
            generation,
            TURN_COMPLETED,
            {"reply": (reply or "")[:200], "stop_reason": str(stop_reason)},
        )

    # ---- 查询（重建）--------------------------------------------------------
    def unfinished(self, session_id: str, *, limit: int = 500) -> TurnRecord | None:
        """最近一个**开始过但没结束**的回合；无则 ``None``。"""
        if self._log is None or not session_id:
            return None
        try:
            events = self._log.load(session_id, limit=limit)
        except Exception as exc:  # noqa: BLE001
            vlog("agent", f"[回合日志] 读取失败（忽略）：{exc}")
            return None
        return replay_unfinished(events, session_id=session_id)

    def resume_plan(self, session_id: str) -> ResumePlan | None:
        """给出这一轮的**恢复建议**（S48 / 方案 D）；无未完成回合时返回 None。

        分级依据是每一步的副作用等级 —— 这是"按工具自描述决定能不能重放"，
        而不是让恢复逻辑去猜工具语义。
        """
        from yuiro.tools import EFFECT_EXTERNAL

        record = self.unfinished(session_id)
        if record is None:
            return None
        replayable: list[dict] = []
        risky: list[dict] = []
        for step in record.steps:
            (risky if _step_effect(step) == EFFECT_EXTERNAL else replayable).append(step)
        return ResumePlan(record=record, replayable=replayable, risky=risky)

    def recent_turns(self, session_id: str, *, limit: int = 200) -> list[TurnRecord]:
        """最近的若干回合（含已完成的），供诊断面板展示。"""
        if self._log is None:
            return []
        try:
            events = self._log.load(session_id, limit=limit)
        except Exception:  # noqa: BLE001
            return []
        out: list[TurnRecord] = []
        current: TurnRecord | None = None
        for e in events or []:
            etype = e.get("type")
            payload = e.get("payload") or {}
            if etype == TURN_STARTED:
                if current is not None:
                    out.append(current)
                current = TurnRecord(
                    session_id=session_id,
                    generation=int(e.get("generation") or 0),
                    started_at=float(e.get("ts") or 0.0),
                    text=str(payload.get("text") or ""),
                )
            elif etype == TURN_STEP and current is not None:
                current.steps.append(dict(payload))
            elif etype == TURN_COMPLETED and current is not None:
                current.finished = True
                current.reply_preview = str(payload.get("reply") or "")
        if current is not None:
            out.append(current)
        return out
