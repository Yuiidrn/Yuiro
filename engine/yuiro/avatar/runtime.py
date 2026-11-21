"""AvatarRuntime：表情/动作意图的唯一出口（意图工厂 + 仲裁 + 广播）。

职责：

- 情绪变化 → ``AvatarIntent(EMOTION)``；
- LLM 等待期 → ``thinking`` 表情，出结果后回落当前主情绪；
- S18：**命名表演**（``perform``）→ Performance Resolver 解析出 expression + motion，
  以 ACTION 优先级发送，``duration_ms`` 到期后自动不再压制情绪回落；
- 仲裁：低优先级不覆盖当前更高优先级的意图（ACTION/USER 为一次性，带时效）；
- 广播：经 ``broadcast`` 回调（复用现有 control 连接广播）发给前端 Live2D adapter。

任何失败都不得影响主链路（广播异常静默）。

规范：``docs/spec/roadmap.md`` Era 1 Perform；``docs/plan/S18-performance.md``。
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from yuiro.avatar.intent import AvatarIntent, AvatarPriority
from yuiro.avatar.performance import (
    DEFAULT_PERFORMANCE_MS,
    EMOTION_EXPRESSION_SLOT,
    PerformanceResolver,
)
from yuiro.logger import vlog

Broadcast = Callable[[dict], Awaitable[None]]


class AvatarRuntime:
    def __init__(
        self,
        *,
        expression_map: dict[str, str] | None = None,
        motion_map: dict[str, str] | None = None,
        performance_map: dict[str, str] | None = None,
        motion_slots: dict[str, str] | None = None,
        broadcast: Broadcast | None = None,
        generation_getter: Callable[[str], int | None] | None = None,
    ) -> None:
        self._expression_map = dict(expression_map or {})
        self._broadcast = broadcast
        self._generation_getter = generation_getter
        self._current: dict[str, AvatarIntent] = {}
        # S18：意图生效时刻（配合 duration_ms 判断一次性表演是否到期）
        self._current_at: dict[str, float] = {}
        self._resolver = PerformanceResolver(
            expression_map=self._expression_map,
            motion_map=motion_map,
            performance_map=performance_map,
            motion_slots=motion_slots,
        )
        self._perf_count = 0

    # ---- 配置 ---------------------------------------------------------------
    def update_expression_map(self, mapping: dict[str, str]) -> None:
        """人设热重载：替换表情映射（S05）。"""
        self._expression_map = dict(mapping or {})
        self._resolver.update(expression_map=self._expression_map)

    def update_motion_map(self, mapping: dict[str, str]) -> None:
        """人设热重载：替换动作映射（S18）。"""
        self._resolver.update(motion_map=dict(mapping or {}))

    def update_performance_map(self, mapping: dict[str, str]) -> None:
        """人设热重载：替换自由搭配表（S48）——表演名 → 表情 + 动作。"""
        self._resolver.update(performance_map=dict(mapping or {}))

    def update_motion_slots(self, mapping: dict[str, str]) -> None:
        """人设热重载：替换语义动作槽位（S53）——槽位 → "组#索引"。

        给动作文件名无语义的模型（Hiyori / 肥牛）用；Hotaru 这类可从文件名
        推断的模型无需配置。
        """
        self._resolver.update(motion_slots=dict(mapping or {}))

    # ---- 查询 ---------------------------------------------------------------
    def expression_for(self, emotion: str) -> str:
        """emotion → 模型表情名；未映射返回空串（前端 reset）。"""
        return self._expression_map.get(emotion, "")

    def resolve_motion_slot(self, slot: str) -> tuple[str, int | None]:
        """语义动作槽位 → 当前模型的具体动作（供工具活动联动 / 调试）。"""
        return self._resolver.slot_motion(slot)

    def current(self, session_id: str) -> AvatarIntent | None:
        """最近一次生效的意图（调试 / 事件日志用）。"""
        return self._current.get(session_id)

    def performances(self) -> list[dict]:
        """表演库清单（S18 Performance Gallery：调试台 / 前端展示用）。"""
        return [p.to_dict() for p in self._resolver.library()]

    # ---- 意图入口 -----------------------------------------------------------
    async def push_emotion(self, session_id: str, emotion: str | None) -> bool:
        """情绪（``None`` → 回落默认）→ 表情意图。

        返回是否实际发送（被更高优先级拦截时为 False）。
        """
        key = emotion or "neutral"
        expr = self.expression_for(key)
        slot = EMOTION_EXPRESSION_SLOT.get(key, "")
        intent = AvatarIntent(
            source="emotion",
            emotion=key,
            # 有具体名才发；否则交给槽位（不能发 ""，那会被壳层当成"回落默认"）
            expression=expr if expr else (None if slot else ""),
            expression_slot=slot or None,
            priority=AvatarPriority.EMOTION,
            session_id=session_id,
        )
        return await self._apply(intent)

    async def push_action(self, session_id: str, motion: str,
                          motion_index: int | None = None) -> bool:
        """动作意图（如 "TapBody" 随机 / 指定索引；优先级 ACTION，一次性）。

        返回是否实际发送（被更高优先级拦截时为 False）。
        """
        intent = AvatarIntent(
            source="agent",
            motion=motion,
            motion_index=motion_index,
            priority=AvatarPriority.ACTION,
            session_id=session_id,
            duration_ms=DEFAULT_PERFORMANCE_MS,
        )
        return await self._apply(intent)

    async def perform(self, session_id: str, name: str, *, source: str = "agent") -> bool:
        """S18：按名字表演一次（expression + motion 组合，ACTION 优先级）。

        ``name`` 来自表演库（celebrate / comfort / greet / surprise / happy ...）；
        未登记的名字按情绪解析（宽松，不抛错）。到期后自动允许情绪回落。
        """
        perf = self._resolver.resolve(name)
        # 具体名不存在时**不发空串**：空串会被壳层当作"回落默认"，
        # 而这里要表达的是"按语义槽位解析"。
        expr_value = perf.expression or (None if perf.expression_slot else "")
        intent = AvatarIntent(
            source=source,
            emotion=perf.emotion,
            expression=expr_value,
            expression_slot=perf.expression_slot or None,
            motion=perf.motion or None,
            motion_index=perf.motion_index,
            motion_slot=perf.motion_slot or None,
            performance=perf.name,
            priority=AvatarPriority.ACTION,
            session_id=session_id,
            duration_ms=perf.duration_ms,
        )
        ok = await self._apply(intent)
        if ok:
            self._perf_count += 1
            idx = "" if perf.motion_index is None else f"#{perf.motion_index}"
            vlog(
                "avatar",
                f"[表演] {perf.name} → 表情 {perf.expression or perf.expression_slot or '(默认)'} / "
                f"动作 {perf.motion or perf.motion_slot or '(无)'}{idx}（{perf.duration_ms}ms）",
            )
        return ok

    # ---- 内部 ---------------------------------------------------------------
    def _expired(self, session_id: str, now: float) -> bool:
        """一次性意图（带 duration_ms）是否已到期。"""
        intent = self._current.get(session_id)
        if intent is None or intent.duration_ms is None:
            return intent is None
        return (now - self._current_at.get(session_id, 0.0)) >= intent.duration_ms / 1000.0

    async def _apply(self, intent: AvatarIntent) -> bool:
        now = time.monotonic()
        sid = intent.session_id
        if sid and self._generation_getter is not None:
            current_generation = self._generation_getter(sid)
            if current_generation is None:
                return False
            if intent.generation and intent.generation != current_generation:
                return False
            intent.generation = current_generation
        # S18：一次性表演到期后不再压制后续情绪（否则 ACTION 会永久拦截 EMOTION）
        if self._expired(sid, now):
            self._current.pop(sid, None)
            self._current_at.pop(sid, None)
        cur = self._current.get(sid)
        if cur is not None and sid and cur.generation != intent.generation:
            self._current.pop(sid, None)
            self._current_at.pop(sid, None)
            cur = None
        if (cur is not None and intent.source == "agent" and intent.performance
                and cur.performance == intent.performance
                and (cur.expression, cur.motion, cur.motion_index, cur.expression_slot, cur.motion_slot)
                == (intent.expression, intent.motion, intent.motion_index, intent.expression_slot, intent.motion_slot)):
            return False  # 同一表演未结束时合并，避免工具重试造成反复起播。
        if cur is not None and intent.priority < cur.priority:
            return False  # 低优先级不覆盖
        self._current[sid] = intent
        self._current_at[sid] = now
        if self._broadcast is None:
            return True
        try:
            await self._broadcast({"type": "avatar:intent", **intent.to_payload()})
        except Exception as exc:  # noqa: BLE001 — 表情失败不影响主链路
            vlog("avatar", f"avatar:intent 广播失败: {exc}")
            return False
        return True

    # ---- RuntimeContract（S15）----------------------------------------------
    def playback_receipt(self, session_id: str, intent_id: str, phase: str,
                         duration_ms: int = 0) -> bool:
        """只接受当前意图回执，旧完成不能释放新的表演。"""
        intent = self._current.get(session_id)
        if intent is None or intent.intent_id != intent_id:
            return False
        if phase == "started" and intent.duration_ms is not None:
            intent.duration_ms = max(1, min(int(duration_ms), 60000))
            self._current_at[session_id] = time.monotonic()
        elif phase in ("finished", "cancelled"):
            self._current.pop(session_id, None)
            self._current_at.pop(session_id, None)
        else:
            return False
        return True

    def runtime_name(self) -> str:
        return "avatar"

    async def cancel(self, session_id: str, reason: str = "") -> None:
        """统一取消：清空该会话当前意图（幂等）。"""
        del reason
        self._current.pop(session_id, None)
        self._current_at.pop(session_id, None)

    async def on_session_close(self, session_id: str) -> None:
        self._current.pop(session_id, None)
        self._current_at.pop(session_id, None)

    def state(self) -> dict:
        return {
            "sessions": len(self._current),
            "performances": len(self._resolver.names()),
            "performed": self._perf_count,
            "current": {
                sid: (it.emotion or it.motion or "")
                for sid, it in self._current.items()
            },
        }
