"""Avatar Runtime 包（S05 起）：表情/动作的语义意图通道。

- ``AvatarIntent`` / ``AvatarPriority``：语义层的意图与优先级；
- ``Performance`` / ``PerformanceResolver``：命名表演包（S18）——语义名 → 表情/动作组合；
- ``AvatarRuntime``：意图工厂 + 仲裁 + 广播（引擎侧唯一出口）;
- 前端（Live2D adapter）负责把 expression 名翻译为具体 Live2D 调用并容错。

规范：``docs/spec/architecture-goal.md`` §3.9、``docs/spec/roadmap.md`` Era 1 Perform、
``docs/plan/S05-avatar-intent.md``、``docs/plan/S18-performance.md``。
"""
from yuiro.avatar.intent import AvatarIntent, AvatarPriority
from yuiro.avatar.performance import (
    BUILTIN_PERFORMANCE_NAMES,
    DEFAULT_PERFORMANCE_MS,
    EMOTION_EXPRESSION_SLOT,
    EXPRESSION_SLOTS,
    EXTRA_DURATIONS_MS,
    IDLE_DURATIONS_MS,
    MOTION_SLOTS,
    TAPBODY_DURATIONS_MS,
    Performance,
    PerformanceResolver,
    motion_duration_ms,
    parse_motion_spec,
    parse_performance_spec,
)
from yuiro.avatar.runtime import AvatarRuntime

__all__ = [
    "BUILTIN_PERFORMANCE_NAMES",
    "DEFAULT_PERFORMANCE_MS",
    "EMOTION_EXPRESSION_SLOT",
    "EXPRESSION_SLOTS",
    "EXTRA_DURATIONS_MS",
    "IDLE_DURATIONS_MS",
    "MOTION_SLOTS",
    "TAPBODY_DURATIONS_MS",
    "AvatarIntent",
    "AvatarPriority",
    "AvatarRuntime",
    "Performance",
    "PerformanceResolver",
    "motion_duration_ms",
    "parse_motion_spec",
    "parse_performance_spec",
]
