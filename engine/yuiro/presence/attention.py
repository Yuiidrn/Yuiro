"""AttentionPolicy（S20）：该不该打扰用户。

规范依据（``docs/spec/roadmap.md`` Wave 7）：

> 必须克制：``Attention Policy + Cooldown + User Preference + Context Awareness
> + Quiet Hours + Confidence``。

本模块是**纯逻辑**（无 IO、时间可注入）→ 可完全测试。判定顺序（先硬后软）：

1. **Quiet Hours**（静默时段，支持跨午夜）→ 抑制（HIGH 可配置豁免）；
2. **Cooldown**（距上次主动互动太近）→ 抑制；
3. **Confidence**（intent 本身不确信）→ 抑制；
4. **Context Awareness**（用户刚活跃 → 不必打扰）→ **降级为气泡**（不丢弃内容）；
5. **User Preference**（``max_urgency``）→ 超出偏好上限的降级为气泡。

设计取舍：**降级而非丢弃**——用户活跃时把"出声/表演"降为"气泡"，
内容仍然可见，避免"它想说什么却憋住了"的另一种体验缺陷。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from datetime import time as dtime

from yuiro.presence.intent import Channel, ProactiveIntent, Urgency, parse_urgency


@dataclass
class AttentionDecision:
    """一次注意力裁决（``act=False`` 时 intent 为空）。"""

    act: bool
    reason: str = ""
    intent: ProactiveIntent | None = None
    downgraded: bool = False

    @property
    def suppressed(self) -> bool:
        return not self.act


def parse_quiet_hours(spec: str) -> tuple[dtime, dtime] | None:
    """解析 ``"23:00-08:00"``（支持跨午夜）；非法/空 → None（= 不设静默时段）。"""
    text = (spec or "").strip()
    if not text or "-" not in text:
        return None
    left, _, right = text.partition("-")
    try:
        start = dtime.fromisoformat(left.strip())
        end = dtime.fromisoformat(right.strip())
    except ValueError:
        return None
    return start, end


def in_quiet_hours(now: datetime, spec: str) -> bool:
    """当前是否处于静默时段（跨午夜区间正确判定）。"""
    window = parse_quiet_hours(spec)
    if window is None:
        return False
    start, end = window
    t = now.time()
    if start <= end:
        return start <= t <= end
    # 跨午夜：23:00-08:00 → t >= 23:00 或 t <= 08:00
    return t >= start or t <= end


@dataclass
class AttentionPolicy:
    """注意力策略（无状态；可通过 ``[presence]`` 配置构造）。"""

    cooldown_s: float = 900.0  # 两次主动互动最短间隔
    quiet_hours: str = ""  # 例 "23:00-08:00"；空 = 不设
    max_urgency: Urgency = Urgency.NORMAL  # 用户偏好上限（超出降级为气泡）
    min_confidence: float = 0.5  # intent 置信度下限
    suppress_if_active_s: float = 120.0  # 用户活跃窗口（此内不出声/不表演）
    allow_high_in_quiet: bool = False  # 静默时段是否允许 HIGH 突破
    stats: dict = field(default_factory=dict)

    # ---- 查询 ---------------------------------------------------------------
    def quiet_now(self, now: datetime | None = None) -> bool:
        # 静默时段按"本地墙上时间"判定（用户语义）→ 有意不用 tz-aware
        return in_quiet_hours(now or datetime.now(), self.quiet_hours)  # noqa: DTZ005

    # ---- 裁决 ---------------------------------------------------------------
    def decide(
        self,
        intent: ProactiveIntent,
        *,
        now: datetime | None = None,
        mono_now: float | None = None,
        last_intervention: float = 0.0,
        last_activity: float = 0.0,
    ) -> AttentionDecision:
        """裁决一次主动表达。

        ``last_intervention`` / ``last_activity`` 为 ``time.monotonic()`` 基准时刻
        （0 = 从未发生）；``now`` 为本地时间（静默时段用）；均可注入以便测试。
        """
        mono = time.monotonic() if mono_now is None else mono_now
        clock = now or datetime.now()  # noqa: DTZ005 — 静默时段按本地墙上时间
        urgency = intent.urgency

        # 1. 静默时段
        if self.quiet_now(clock) and not (
            self.allow_high_in_quiet and urgency >= Urgency.HIGH
        ):
            return AttentionDecision(False, "静默时段（quiet hours）")

        # 2. 冷却
        if last_intervention and (mono - last_intervention) < self.cooldown_s:
            left = int(self.cooldown_s - (mono - last_intervention))
            return AttentionDecision(False, f"冷却中（还需 {left}s）")

        # 3. 置信度
        if intent.confidence < self.min_confidence:
            return AttentionDecision(
                False, f"置信度不足（{intent.confidence:.2f} < {self.min_confidence:.2f}）"
            )

        # 4. 上下文感知：用户刚活跃 → 降级为气泡（保留内容，不打扰）
        #    已是气泡形态则无需降级（避免"降级了个寂寞"并保留原始 reason 供观测）
        if (
            last_activity
            and (mono - last_activity) < self.suppress_if_active_s
            and urgency < Urgency.HIGH
        ):
            if intent.channel is Channel.BUBBLE:
                return AttentionDecision(True, "允许（用户活跃中，已是最低打扰通道）", intent)
            return AttentionDecision(
                True,
                "用户活跃中 → 降级为气泡",
                intent.downgraded(channel=Channel.BUBBLE),
                downgraded=True,
            )

        # 5. 用户偏好：超出上限的 urgency 降级为气泡
        if urgency > self.max_urgency:
            if intent.channel is Channel.BUBBLE:
                return AttentionDecision(True, "允许（已是最低打扰通道）", intent)
            return AttentionDecision(
                True,
                f"超过偏好上限（{urgency.name} > {self.max_urgency.name}）→ 降级为气泡",
                intent.downgraded(urgency=self.max_urgency, channel=Channel.BUBBLE),
                downgraded=True,
            )

        return AttentionDecision(True, "允许", intent)

    @staticmethod
    def describe(intent: ProactiveIntent) -> str:
        return f"{intent.urgency.name}/{intent.channel.value}"


__all__ = [
    "AttentionDecision",
    "AttentionPolicy",
    "in_quiet_hours",
    "parse_quiet_hours",
    "parse_urgency",
]
