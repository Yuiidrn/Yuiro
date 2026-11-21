"""ProactiveIntent（S20）：Presence 的输出契约。

规范依据（``docs/spec/roadmap.md`` Wave 7 · ``architecture-goal.md`` §3.7）：

- Presence 的输出统一为 ``ProactiveIntent{urgency, interruptibility, channel}``；
- **低 urgency 只抬头 / 气泡，高 urgency 才 TTS**；
- "主动 ≠ 高频打扰"：intent 只是"想说什么"，是否真的说出口由 AttentionPolicy 决定
  （两者分离，便于测试与调优）。

这与 AvatarIntent / SpeechIntent 同一设计语言：**Intent 是意图，不是动作**。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class Urgency(IntEnum):
    """打扰等级（越大越值得打断用户）。"""

    LOW = 1  # 只在气泡/表情层面表达（几乎不打扰）
    NORMAL = 2  # 气泡 + 轻微表演（回头看一眼的程度）
    HIGH = 3  # 值得出声打断（真正重要的事）


class Channel(str, Enum):
    """交付通道（spec：低 urgency 只抬头/气泡，高 urgency 才 TTS）。"""

    BUBBLE = "bubble"  # 说话云框（默认；不打断）
    PERFORMANCE = "performance"  # 表情 + 动作（可见但不出声）
    VOICE = "voice"  # 出声（v1 交付层降级为 bubble + performance，见 Plan 遗留）


_URGENCY_ORDER = (Urgency.LOW, Urgency.NORMAL, Urgency.HIGH)


def parse_urgency(value) -> Urgency:
    """宽松解析 urgency（配置/外部输入）：名字、数字、非法值 → NORMAL。"""
    if isinstance(value, Urgency):
        return value
    if isinstance(value, int):
        for u in _URGENCY_ORDER:
            if int(u) == value:
                return u
        return Urgency.NORMAL
    text = str(value or "").strip().lower()
    for u in _URGENCY_ORDER:
        if u.name.lower() == text:
            return u
    return Urgency.NORMAL


def parse_channel(value) -> Channel:
    text = str(value or "").strip().lower()
    for c in Channel:
        if c.value == text:
            return c
    return Channel.BUBBLE


@dataclass
class ProactiveIntent:
    """一次"我想主动说点什么"的语义请求（是否说出口由 AttentionPolicy 决定）。"""

    text: str
    reason: str = ""  # 触发原因（可观测：idle / task_done / ...）
    urgency: Urgency = Urgency.LOW
    channel: Channel = Channel.BUBBLE
    performance: str = ""  # 可选表演名（S18 表演库；空 = 不做动作）
    interruptibility: float = 0.0  # 0–1：此刻打断用户的代价估计（供策略参考）
    confidence: float = 1.0  # 0–1：这个 intent 本身的置信度
    session_id: str = ""
    source: str = "presence"

    def downgraded(self, *, urgency: Urgency | None = None,
                   channel: Channel | None = None, reason: str = "") -> ProactiveIntent:
        """返回降级副本（不修改自身）——用于"想说但先克制一点"。"""
        return ProactiveIntent(
            text=self.text,
            reason=reason or self.reason,
            urgency=urgency if urgency is not None else self.urgency,
            channel=channel if channel is not None else self.channel,
            performance=self.performance,
            interruptibility=self.interruptibility,
            confidence=self.confidence,
            session_id=self.session_id,
            source=self.source,
        )

    def to_payload(self) -> dict:
        """序列化为 ``proactive:intent`` 事件载荷（空字段不发送）。"""
        data: dict = {
            "type": "proactive:intent",
            "text": self.text,
            "urgency": self.urgency.name.lower(),
            "channel": self.channel.value,
            "reason": self.reason,
            "source": self.source,
        }
        if self.performance:
            data["performance"] = self.performance
        if self.session_id:
            data["session_id"] = self.session_id
        return data
