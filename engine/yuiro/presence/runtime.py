"""PresenceRuntime（S20）：事件驱动的存在感。

规范依据（``docs/spec/roadmap.md`` Wave 7）：

```
Presence → Event → Attention Policy → Should interact?
用户离开 20min 回来 → "回来啦。"
Build completed     → "欸，刚刚编译成功了。"
```

**不是**"LLM 每秒问一次我要不要说话"（spec 明确禁止）。本 Runtime：

- **事件驱动**：``task.completed`` / ``task.failed`` / ``session.*`` 触发候选 intent；
- **定时 tick 只做一件事**：判断"用户空闲多久了"（存在感的时间维度）；
- **一切输出经 AttentionPolicy**：想说 ≠ 说出口（克制是设计的一部分）；
- 交付：``proactive:intent`` 广播（气泡）+ 可选表演（S18 表演库）。

与其他 Runtime 的关系：本 Runtime 只产出 Intent，不直接触碰 Live2D / TTS
（与 AvatarRuntime / SpeechRuntime 同构）。
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from yuiro.logger import vlog
from yuiro.presence.attention import AttentionDecision, AttentionPolicy
from yuiro.presence.intent import (
    Channel,
    ProactiveIntent,
    Urgency,
    parse_channel,
    parse_urgency,
)

Broadcast = Callable[[dict], Awaitable[None]]

# 会重置"用户活跃"信号的事件（用户在场 = 不必打扰）
_ACTIVITY_EVENTS = (
    "session.started",
    "session.closed",
    "user.message",
    "agent.turn_started",
)


class PresenceRuntime:
    def __init__(
        self,
        *,
        policy: AttentionPolicy | None = None,
        broadcast: Broadcast | None = None,
        avatar_getter=None,
        voice_speaker=None,
        idle_trigger_s: float = 1800.0,
        tick_s: float = 60.0,
        on_task_done: bool = True,
        respond_window_s: float = 120.0,
    ) -> None:
        self._policy = policy or AttentionPolicy()
        self._broadcast = broadcast
        self._avatar_getter = avatar_getter
        # S22：voice 通道（async (session_id, text) -> None；缺省则 voice 表达退化为气泡）
        self._voice_speaker = voice_speaker
        self._respond_window_s = float(respond_window_s)
        self._idle_trigger_s = float(idle_trigger_s)
        self._tick_s = max(5.0, float(tick_s))
        self._on_task_done = on_task_done
        self._last_activity = time.monotonic()
        self._last_intervention = 0.0
        self._idle_announced = False
        self._task: asyncio.Task | None = None
        self._counters = {"candidates": 0, "delivered": 0, "suppressed": 0, "downgraded": 0}
        self._last_decision = ""
        # S22：Intervention quality —— 上次主动表达后用户是否在窗口内回应（近似"有用率"）
        self._pending_response: float | None = None
        self._responded = 0

    # ---- 生命周期 -----------------------------------------------------------
    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())
        vlog(
            "presence",
            f"Presence 已启动（空闲触发 {int(self._idle_trigger_s)}s / "
            f"冷却 {int(self._policy.cooldown_s)}s / "
            f"静默时段 {self._policy.quiet_hours or '未设'}）",
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        vlog("presence", "Presence 已停止")

    async def _run(self) -> None:
        """定时 tick：只负责"用户空闲了多久"这一件事。"""
        while True:
            try:
                await asyncio.sleep(self._tick_s)
                await self.check_idle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 单轮异常不终止循环
                vlog("presence", f"tick 异常: {exc}")

    async def check_idle(self) -> AttentionDecision | None:
        """空闲检测（tick 循环调用；也可直接调用以便测试）。

        返回本次的裁决（``None`` = 未到空闲阈值 / 已提过 / 关闭了空闲触发）。
        """
        if self._idle_trigger_s <= 0 or self._idle_announced:
            return None
        idle = time.monotonic() - self._last_activity
        if idle < self._idle_trigger_s:
            return None
        self._idle_announced = True  # 每次空闲只提一次（用户回来会重置）
        return await self.submit(
            ProactiveIntent(
                text="回来啦。",
                reason="idle_return",
                urgency=Urgency.LOW,
                channel=Channel.BUBBLE,
                performance="greet",
            ),
            confidence=0.7,
        )

    # ---- 输入 ---------------------------------------------------------------
    def note_user_activity(self) -> None:
        """用户互动：重置空闲计时（并允许下一次空闲再提一次）。

        S22：若用户在最近一次主动表达的响应窗口内发言 → 记为"有响应"
        （Intervention quality 的数据来源：主动表达是否有用）。
        """
        mono = time.monotonic()
        self._last_activity = mono
        self._idle_announced = False
        if self._pending_response is not None:
            if (mono - self._pending_response) <= self._respond_window_s:
                self._responded += 1
            self._pending_response = None

    async def on_event(self, event) -> None:
        """EventBus 订阅回调（内部按类型分派；未关心的类型直接返回）。"""
        et = str(getattr(event, "type", "") or "")
        if et in _ACTIVITY_EVENTS:
            self.note_user_activity()
            return
        payload = getattr(event, "payload", None) or {}
        session_id = str(getattr(event, "session_id", "") or "")
        if et == "task.completed" and self._on_task_done:
            goal = str(payload.get("goal", "")).strip()
            text = f"欸，{goal} 办好了。" if goal else "欸，刚才那件事办好了。"
            await self.submit(
                ProactiveIntent(
                    text=text,
                    reason="task_done",
                    urgency=Urgency.NORMAL,
                    channel=Channel.BUBBLE,
                ),
                session_id=session_id,
                confidence=0.9,
            )
        elif et.startswith("system."):
            # S22：系统事件通用入口（spec 举例：「Build completed → 欸，刚刚编译成功了」）。
            # 事件只需带 hint/text（要说什么），是否真说出口由 AttentionPolicy 决定。
            hint = str(payload.get("hint") or payload.get("text") or "").strip()
            if hint:
                await self.submit(
                    ProactiveIntent(
                        text=hint,
                        reason=et,
                        urgency=parse_urgency(payload.get("urgency") or "low"),
                        channel=parse_channel(payload.get("channel") or "bubble"),
                    ),
                    session_id=session_id,
                    confidence=0.8,
                )
        elif et == "task.failed":
            goal = str(payload.get("goal", "")).strip()
            text = (
                f"{goal} 那边卡住了，要我看看吗？" if goal else "刚才那件事没成，要我看看吗？"
            )
            await self.submit(
                ProactiveIntent(
                    text=text,
                    reason="task_failed",
                    urgency=Urgency.LOW,
                    channel=Channel.BUBBLE,
                    performance="comfort",
                ),
                session_id=session_id,
                confidence=0.8,
            )

    # ---- 裁决与交付 ---------------------------------------------------------
    async def submit(
        self, intent: ProactiveIntent, *, session_id: str = "", confidence: float | None = None
    ) -> AttentionDecision:
        """提交一个候选 intent → AttentionPolicy 裁决 → （通过则）交付。"""
        self._counters["candidates"] += 1
        if session_id and not intent.session_id:
            intent.session_id = session_id
        if confidence is not None:
            intent.confidence = confidence
        decision = self._policy.decide(
            intent,
            last_intervention=self._last_intervention,
            last_activity=self._last_activity,
        )
        self._last_decision = decision.reason
        if not decision.act or decision.intent is None:
            self._counters["suppressed"] += 1
            vlog("presence", f"[主动克制] {intent.reason or '?'}：{decision.reason}")
            return decision
        if decision.downgraded:
            self._counters["downgraded"] += 1
        self._counters["delivered"] += 1
        self._last_intervention = time.monotonic()
        self._pending_response = self._last_intervention  # S22：等待用户回应（有用率）
        await self._deliver(decision.intent)
        return decision

    async def _deliver(self, intent: ProactiveIntent) -> None:
        vlog(
            "presence",
            f"[主动表达] {intent.urgency.name}/{intent.channel.value} "
            f"{intent.text!r}（{intent.reason}）",
        )
        if self._broadcast is not None:
            try:
                await self._broadcast(intent.to_payload())
            except Exception as exc:  # noqa: BLE001 — 广播失败不影响主链路
                vlog("presence", f"proactive:intent 广播失败: {exc}")
        # S22：voice 通道——真正出声（失败/未注入则内容仍经气泡可见，不丢失）
        if intent.channel is Channel.VOICE and self._voice_speaker is not None:
            try:
                await self._voice_speaker(intent.session_id, intent.text)
            except Exception as exc:  # noqa: BLE001 — 出声失败退化为气泡
                vlog("presence", f"主动说话失败（已退化为气泡）: {exc}")
        if intent.performance:
            avatar = self._avatar_getter() if callable(self._avatar_getter) else None
            if avatar is not None:
                try:
                    await avatar.perform(intent.session_id, intent.performance, source="presence")
                except Exception:  # noqa: BLE001, S110 — 表演失败不影响存在感
                    pass

    # ---- 调试 ---------------------------------------------------------------
    def state(self) -> dict:
        mono = time.monotonic()
        return {
            "idle_s": int(mono - self._last_activity),
            "cooldown_left_s": max(0, int(self._policy.cooldown_s - (mono - self._last_intervention)))
            if self._last_intervention
            else 0,
            "quiet_now": self._policy.quiet_now(),
            "quiet_hours": self._policy.quiet_hours,
            "max_urgency": self._policy.max_urgency.name.lower(),
            "idle_trigger_s": int(self._idle_trigger_s),
            "last_decision": self._last_decision,
            "counters": dict(self._counters),
            # S22：Intervention quality（近似"有用率"：主动表达后用户是否回应）
            "intervention_quality": {
                "delivered": self._counters["delivered"],
                "responded": self._responded,
                "useful_rate": round(self._responded / self._counters["delivered"], 2)
                if self._counters["delivered"]
                else 0.0,
            },
        }

    # ---- RuntimeContract（S15）----------------------------------------------
    def runtime_name(self) -> str:
        return "presence"

    async def cancel(self, session_id: str, reason: str = "") -> None:
        """取消会话：清空该会话的待表达（当前无队列，仅清 idle 标记）。"""
        del session_id, reason
        self._idle_announced = True  # 不因取消而立刻又提一次

    async def on_session_close(self, session_id: str) -> None:
        self.note_user_activity()
