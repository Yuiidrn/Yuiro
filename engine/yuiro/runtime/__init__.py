"""Yuiro Runtime 内核包（Wave 0 起逐步落地）。

当前含：
- ``TraceContext``（S01：交互级可观测性基线，只观测不改行为）
- ``AgentSession`` / ``SessionManager``（S02：统一 Session / Generation）
- ``AgentEvent`` / ``EventBus``（S02：agent-native 内存事件总线）

Session / Events / Cancellation 等完整规划见 ``docs/spec/target-file-preview.md`` §3。
"""
from yuiro.runtime.events import AgentEvent, EventBus
from yuiro.runtime.session import AgentSession, SessionManager, SessionState
from yuiro.runtime.trace import TraceContext

__all__ = [
    "AgentEvent",
    "AgentSession",
    "EventBus",
    "SessionManager",
    "SessionState",
    "TraceContext",
]
