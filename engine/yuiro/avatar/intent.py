"""AvatarIntent：表情/动作的语义意图（引擎 → 前端 Live2D adapter）。

分层原则（Stable Kernel vs Pluggable Edge）：

- 本对象只承载**语义**（emotion / 表情名 / 优先级）；
- "emotion → 模型表情名"的映射由 ``[persona.expression_map]`` 配置决定，
  换模型只改配置，引擎代码不动；
- 前端 adapter 负责翻译为具体 Live2D 调用，并在资源缺失时容错退回。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4
from enum import IntEnum


class AvatarPriority(IntEnum):
    """意图优先级：低优先级不覆盖未完成的高优先级意图。"""

    IDLE = 0  # 呼吸 / idle 循环
    EMOTION = 1  # 情绪表情（持续状态）
    SPEECH = 2  # 语音链路状态（listening / thinking）
    ACTION = 3  # 一次性表演（预留：招手 / 唱歌等）
    USER = 4  # 用户交互（点击 / 拖动）
    SYSTEM = 5  # 系统级（启动 / 错误）


@dataclass
class AvatarIntent:
    """一次"希望 Live2D 表现成什么样"的语义请求。"""

    source: str  # emotion | speech | agent | system
    emotion: str | None = None  # 语义情绪 / 状态（happy / thinking / ...）
    expression: str | None = None  # 模型表情名（"" = 回落默认/reset；None = 不改）
    # S53：表情语义槽位。具体名不可用（模型没配 / 名字不存在）时下发，
    # 由壳层按当前模型清单解析成实际表情名。
    expression_slot: str | None = None
    motion: str | None = None  # 动作组名（S14 起触发：如 "TapBody"）
    motion_index: int | None = None  # 组内动作索引（None = 该组随机）
    # S53：动作语义槽位（idle/greet/celebrate/comfort/surprise/thinking/sing/angry/nod/look）
    motion_slot: str | None = None
    # 表演名（调试/日志用，不影响渲染逻辑）
    performance: str | None = None
    priority: AvatarPriority = AvatarPriority.EMOTION
    session_id: str = ""
    generation: int = 0
    duration_ms: int | None = None  # 一次性动作有效期
    intent_id: str = field(default_factory=lambda: uuid4().hex)

    def to_payload(self) -> dict:
        """序列化为 avatar:intent 事件载荷（空字段不发送）。"""
        data: dict = {"source": self.source, "priority": int(self.priority)}
        data.update(intent_id=self.intent_id, session_id=self.session_id, generation=self.generation)
        if self.emotion:
            data["emotion"] = self.emotion
        if self.expression is not None:
            data["expression"] = self.expression
        if self.expression_slot:
            data["expression_slot"] = self.expression_slot
        if self.motion:
            data["motion"] = self.motion
        if self.motion_index is not None:
            data["motion_index"] = self.motion_index
        if self.motion_slot:
            data["motion_slot"] = self.motion_slot
        if self.performance:
            data["performance"] = self.performance
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        return data
