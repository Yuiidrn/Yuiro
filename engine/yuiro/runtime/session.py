"""AgentSession + SessionManager（S02：统一 Session / Generation）。

- ``AgentSession``：一次交互的完整轨迹（**不是聊天记录**）；
- ``SessionManager``：会话注册表 + control/audio 传输绑定 + 进程内 resume；
- **generation 权威**：新用户回合（``next_generation``）或显式失效（``invalidate``）
  时自增；旧代际的一切异步结果一律作废（由 AgentLoop 等消费方检查并丢弃）。

范围（S02）：统一身份与代际 + 显式失效；Cancellation 的跨 Runtime 传播属 S03。
见 docs/plan/S02-session-generation-unify.md 与 docs/spec/target-file-preview.md §3.1。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from yuiro.logger import vlog


class SessionState(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"  # 通道断开但保留在内存中，可进程内 resume
    CLOSED = "closed"


@dataclass
class AgentSession:
    """Agent 从开始到结束的一条完整执行轨迹。"""

    session_id: str
    generation: int = 0
    state: SessionState = SessionState.ACTIVE
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    active_tasks: dict[str, str] = field(default_factory=dict)  # task_id -> owner
    # 传输绑定（不参与业务逻辑；只用于寻址与生命周期判断）
    control_ws: object | None = None
    audio_ws: object | None = None

    def next_generation(self) -> int:
        """新用户回合：generation++（旧代际的异步结果从此作废）。"""
        self.generation += 1
        self.last_active_at = time.time()
        return self.generation

    def invalidate(self, reason: str = "") -> int:
        """显式失效（barge-in / stop / reset）：开新代际但不启动新回合。"""
        del reason  # 语义参数，S03 的取消事件会用到
        self.generation += 1
        self.last_active_at = time.time()
        return self.generation


class SessionManager:
    """会话注册表：control/audio 归属同一 AgentSession；支持进程内 resume。"""

    #: 挂起会话的内存保留时长（秒）—— 超过则回收（**事件日志仍留盘，可 revive**）。
    #: 这是「内存不涨」与「会话不丢」的平衡点：太短会频繁复活，太长白占内存。
    SUSPEND_TTL_S = 1800.0

    def __init__(self, *, events=None, event_log=None, suspend_ttl_s=None) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._events = events  # EventBus | None（S02 可选注入）
        # S43：事件日志（落盘）—— 用于「复活」被回收的会话，以及列出历史会话。
        self._event_log = event_log
        self._ttl = float(
            suspend_ttl_s if suspend_ttl_s is not None else self.SUSPEND_TTL_S
        )

    # ---- 查询 / 创建 ---------------------------------------------------------
    def get(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    def create(self) -> AgentSession:
        session = AgentSession(session_id=uuid4().hex)
        self._sessions[session.session_id] = session
        return session

    def get_or_create(self, session_id: str | None) -> AgentSession:
        """按优先级解析会话：**内存命中 → 磁盘复活 → 新建**。

        S43 加了中间那一档。此前只有「内存命中 / 新建」两种结果，于是：
        引擎重启、或会话被 sweep 回收之后，前端带着旧 session_id 连上来会被
        **静默新建**一个空会话 —— 用户侧表现为"上下文全丢了"，而且**没有任何提示**。
        现在只要事件日志还在磁盘上，就能把身份、创建时间、最近活跃时间还原回来。
        """
        if session_id:
            existing = self._sessions.get(session_id)
            if existing is not None and existing.state is not SessionState.CLOSED:
                return existing
            revived = self.revive(session_id)
            if revived is not None:
                return revived
        return self.create()

    # ---- 回收 / 复活 / 一览（S43） -------------------------------------------
    def sweep(self, *, now: float | None = None) -> list[str]:
        """回收超时的挂起会话，返回被回收的 id 列表。

        **为什么必须有**：原来只有 ``_maybe_suspend``（改状态为 SUSPENDED），
        而 ``close`` 全项目**零调用** —— 会话只增不减。实测开发态热重载一天就攒下
        好几个，每个都带着自己的上下文常驻内存。

        回收原则（两条都必须满足，宁可不收）：
        1. **两条通道都断开**（有连接的会话绝不能动，哪怕它很久没说话）；
        2. 已挂起且静默超过 TTL。

        事件日志不动，所以随时可 :meth:`revive`。
        """
        t = now if now is not None else time.time()
        dropped: list[str] = []
        for sid, s in list(self._sessions.items()):
            if s.control_ws is not None or s.audio_ws is not None:
                continue
            if s.state is not SessionState.SUSPENDED:
                continue
            if t - s.last_active_at < self._ttl:
                continue
            self._sessions.pop(sid, None)
            dropped.append(sid)
        if dropped:
            vlog(
                "session",
                f"回收 {len(dropped)} 个挂起会话（超过 {self._ttl:.0f}s 静默；"
                f"事件日志保留，可复活）：{', '.join(x[:8] for x in dropped)}",
            )
        return dropped

    def revive(self, session_id: str) -> AgentSession | None:
        """从磁盘事件日志复活一个已回收/已重启丢失的会话；无法复活返回 None。"""
        if not session_id or self._event_log is None:
            return None
        events = self._event_log.load(session_id, limit=200)
        if not events:
            return None
        stamps = [float(e.get("ts") or 0.0) for e in events]
        now = time.time()
        session = AgentSession(
            session_id=session_id,
            # 复活后先挂起：等 attach_control/attach_audio 真正接上再转 ACTIVE，
            # 否则会留下一个"看起来有连接"的幽灵会话，sweep 永远收不掉它。
            state=SessionState.SUSPENDED,
            created_at=min(stamps) if stamps else now,
            last_active_at=max(stamps) if stamps else now,
        )
        self._sessions[session_id] = session
        vlog(
            "session",
            f"从事件日志复活会话 {session_id[:8]}（{len(events)} 条事件，"
            f"最后活跃 {time.strftime('%m-%d %H:%M', time.localtime(session.last_active_at))}）",
        )
        return session

    def archive(self, session_id: str) -> bool:
        """归档会话：从内存移除（事件日志保留，仍可复活）。

        与 :meth:`sweep` 的区别：sweep 是超时自动回收，archive 是**用户主动结束**。
        """
        s = self._sessions.pop(session_id, None)
        if s is None:
            return False
        s.state = SessionState.CLOSED
        s.control_ws = None
        s.audio_ws = None
        vlog("session", f"归档会话 {session_id[:8]}（事件日志保留，可复活）")
        return True

    def list_sessions(self, *, limit: int = 50) -> list[dict]:
        """会话一览：内存中的（活跃/挂起）+ 磁盘上有日志的历史会话。

        前端此前只握着自己那一个 session_id，**看不到"还有哪些会话"** ——
        既无法切换，也对历史毫无感知（这就是"没有选择加载页"的数据层原因）。
        这里把两个来源合并成一个可直接渲染的列表。
        """
        items: dict[str, dict] = {}
        for sid, s in self._sessions.items():
            items[sid] = {
                "session_id": sid,
                "state": str(s.state.value if hasattr(s.state, "value") else s.state),
                "live": s.control_ws is not None or s.audio_ws is not None,
                "created_at": s.created_at,
                "last_active_at": s.last_active_at,
                "generation": s.generation,
                "has_log": False,
            }
        if self._event_log is not None:
            for sid in self._event_log.sessions():
                if sid in items:
                    items[sid]["has_log"] = True
                    continue
                events = self._event_log.load(sid, limit=1)
                ts = float(events[-1].get("ts") or 0.0) if events else 0.0
                items[sid] = {
                    "session_id": sid,
                    "state": "archived",
                    "live": False,
                    "created_at": ts,
                    "last_active_at": ts,
                    "generation": 0,
                    "has_log": True,
                }
        return sorted(
            items.values(), key=lambda x: -float(x["last_active_at"])
        )[:limit]

    # ---- 传输绑定 -----------------------------------------------------------
    def attach_control(self, ws, *, session_id: str | None = None) -> AgentSession:
        """control 建连：带 session_id 则 resume，否则新建。"""
        session = self.get_or_create(session_id)
        session.control_ws = ws
        session.state = SessionState.ACTIVE
        session.last_active_at = time.time()
        return session

    def attach_audio(self, ws, *, session_id: str | None = None) -> AgentSession:
        """audio 建连：带 ?session= 绑定同一会话；不带则独立会话。"""
        session = self.get_or_create(session_id)
        session.audio_ws = ws
        session.last_active_at = time.time()
        return session

    # ---- 取消（S03：统一取消入口） -------------------------------------------
    def cancel(self, session_id: str, reason: str = "") -> int:
        """统一取消入口：代际作废（旧代际的一切异步结果从此丢弃）。

        返回新 generation；会话不存在时返回 0。
        本方法保持**同步**（取消不应阻塞）；跨 Runtime 的编排（停语音 / 停播 /
        事件发布）由调用方 ``main._cancel_turn`` 负责。
        """
        session = self._sessions.get(session_id)
        if session is None:
            return 0
        return session.invalidate(reason)

    # ---- 生命周期 -----------------------------------------------------------
    def detach_control(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.control_ws = None
        self._maybe_suspend(session)

    def detach_audio(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.audio_ws = None
        self._maybe_suspend(session)

    def _maybe_suspend(self, session: AgentSession) -> None:
        """两条通道都断开 → 挂起（保留内存，允许进程内 resume）。"""
        if session.control_ws is None and session.audio_ws is None:
            session.state = SessionState.SUSPENDED

    def close(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            session.state = SessionState.CLOSED
