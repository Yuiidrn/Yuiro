"""Yuiro engine — emotion / affinity / character growth package.

M5：情绪五维（happy/sad/excited/bored/angry）指数衰减 + 互动加成；
RPG 亲密度/等级养成。情绪经 `emotion:set` 事件驱动壳层表情。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from yuiro.logger import vlog

EMOTIONS = ("happy", "sad", "excited", "bored", "angry")

# 情绪 → 语气提示（默认值；可由 persona.emotion_hints 覆盖注入）
_DEFAULT_EMOTION_HINTS = {
    "happy": "你现在心情不错，语气轻快温暖。",
    "sad": "你现在有点低落，语气温柔安抚。",
    "excited": "你现在很兴奋，语气活泼有精神。",
    "bored": "你现在有点无聊，语气可以俏皮地找点话题。",
    "angry": "你现在有点生气，语气保持冷静克制。",
}

# 情绪 → 壳层表情提示（默认值；可由 persona.expression_map 覆盖注入）
# 默认对齐**默认模型 Hiyori**（它的表情名即语义，是我们手写的 8 个 exp3.json）。
# 肥牛等其它模型走 [persona.profiles.<档案>].expression_map，不再写死在这里。
_DEFAULT_EXPRESSION_MAP = {
    "happy": "happy",
    "sad": "sad",
    "excited": "surprised",   # Hiyori 无"兴奋"，取语义最近的"惊讶"
    "bored": "bored",
    "angry": "angry",
    "thinking": "think",
}


@dataclass
class EmotionState:
    happy: float = 0.2
    sad: float = 0.1
    excited: float = 0.2
    bored: float = 0.2
    angry: float = 0.0

    def values(self) -> dict[str, float]:
        return {k: getattr(self, k) for k in EMOTIONS}

    def dominant(self) -> str:
        """返回主情绪标签（值最高者）。"""
        vals = self.values()
        return max(vals, key=vals.get)  # type: ignore[arg-type]

    def dominant_value(self) -> float:
        return max(self.values().values())


class EmotionEngine:
    """情绪值指数衰减 + 互动加成；主情绪经 style_hint 流入 prompt。"""

    def __init__(
        self,
        decay_rate: float = 0.02,
        hints: dict[str, str] | None = None,
        expression_map: dict[str, str] | None = None,
    ) -> None:
        self.state = EmotionState()
        self.decay_rate = decay_rate
        # 情绪文案 / 表情映射：来自 persona 配置，缺省时回退内置默认。
        self._hints = dict(_DEFAULT_EMOTION_HINTS)
        if hints:
            self._hints.update(hints)
        self._expression_map = dict(_DEFAULT_EXPRESSION_MAP)
        if expression_map:
            self._expression_map.update(expression_map)
        self._last_decay = time.monotonic()

    def decay(self) -> str | None:
        """按距上次衰减的时长做指数衰减；主情绪变化时返回其标签。"""
        now = time.monotonic()
        dt = max(0.0, now - self._last_decay)
        self._last_decay = now
        before = self.state.dominant()
        factor = math.exp(-self.decay_rate * dt)
        for key in EMOTIONS:
            current = getattr(self.state, key)
            setattr(self.state, key, max(0.0, current * factor))
        after = self.state.dominant()
        return after if after != before else None

    def boost(self, key: str, amount: float) -> None:
        """用户互动加成（如 happy +0.3）；值钳位 [0, 1]。"""
        if key not in EMOTIONS:
            return
        current = getattr(self.state, key)
        setattr(self.state, key, min(1.0, max(0.0, current + amount)))

    def set_emotion(self, key: str, value: float) -> None:
        """直接设置情绪值（钳位）。"""
        if key in EMOTIONS:
            setattr(self.state, key, min(1.0, max(0.0, value)))

    def style_hint(self) -> str:
        """返回反映当前主情绪的语气提示片段（注入 prompt）。"""
        d = self.state.dominant()
        return self._hints.get(d, "")

    def expression(self, emotion: str | None = None) -> str:
        """返回情绪对应的 Live2D 表情名（默认用当前主情绪）。"""
        d = emotion or self.state.dominant()
        return self._expression_map.get(d, "")


@dataclass
class Character:
    """RPG 养成：亲密度/经验/等级/属性。"""

    affinity: float = 0.0  # 与用户的情感纽带
    xp: int = 0
    level: int = 1
    attributes: dict[str, float] = field(default_factory=lambda: {
        "intelligence": 5.0,
        "charisma": 5.0,
        "agility": 5.0,
        "stamina": 5.0,
    })

    XP_PER_LEVEL = 100

    def add_xp(self, amount: int) -> bool:
        """加经验；升级返回 True。"""
        self.xp += max(0, amount)
        return self.level_up_if_ready()

    def level_up_if_ready(self) -> bool:
        leveled = False
        while self.xp >= self.XP_PER_LEVEL:
            self.xp -= self.XP_PER_LEVEL
            self.level += 1
            for key in self.attributes:
                self.attributes[key] += 0.5
            vlog("emotion", f"角色升级：Lv.{self.level}（属性 +0.5）")
            leveled = True
        return leveled

    def affinity_state(self) -> str:
        """stranger / acquaintance / friend / partner（按亲密度分段）。"""
        if self.affinity < 10:
            return "stranger"
        if self.affinity < 30:
            return "acquaintance"
        if self.affinity < 60:
            return "friend"
        return "partner"

    def add_affinity(self, amount: float) -> None:
        self.affinity = min(100.0, max(0.0, self.affinity + amount))
