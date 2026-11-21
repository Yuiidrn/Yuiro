"""Presence 包（S20）：存在感 / 主动互动的 Runtime 化。

由 M5 的 ``proactive/``（定时观察 → 启发式打招呼）演化而来：

```
Event ──▶ PresenceRuntime ──▶ ProactiveIntent ──▶ AttentionPolicy ──▶ 交付
                                                  ├─ proactive:intent（气泡）
                                                  └─ avatar.perform（表演，S18）
```

- ``ProactiveIntent`` / ``Urgency`` / ``Channel``：输出契约（低 urgency 只气泡，高才出声）；
- ``AttentionPolicy``：该不该打扰（Cooldown / Quiet Hours / 用户偏好 / 上下文 / 置信度）；
- ``PresenceRuntime``：事件驱动调度 + 交付（不直接触碰 Live2D / TTS）。

规范：``docs/spec/roadmap.md`` Wave 7、``docs/plan/S20-presence.md``。
"""
from yuiro.presence.attention import (
    AttentionDecision,
    AttentionPolicy,
    in_quiet_hours,
    parse_quiet_hours,
)
from yuiro.presence.intent import Channel, ProactiveIntent, Urgency, parse_channel, parse_urgency
from yuiro.presence.runtime import PresenceRuntime

__all__ = [
    "AttentionDecision",
    "AttentionPolicy",
    "Channel",
    "PresenceRuntime",
    "ProactiveIntent",
    "Urgency",
    "in_quiet_hours",
    "parse_channel",
    "parse_quiet_hours",
    "parse_urgency",
]
