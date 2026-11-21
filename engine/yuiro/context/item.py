"""ContextItem：带元数据的上下文片段（S06）。

"Memory 只负责找；ContextEngine 负责用不用、用多少、放哪里。"
"""
from __future__ import annotations

from dataclasses import dataclass, field


def estimate_tokens(text: str) -> int:
    """粗略 token 估算（中文 ≈ 1 字/token，其他 ≈ 4 字符/token）。

    仅用于预算比较与可观测指标，不追求与真实 tokenizer 一致。
    """
    if not text:
        return 0
    cjk = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            cjk += 1
    other = len(text) - cjk
    return max(1, cjk + other // 4)


@dataclass
class ContextBudget:
    """Hot Context 总预算（估算 token；数字可配，原则是"预算被管理"）。"""

    total: int = 6000


@dataclass
class ContextItem:
    """一段进入（或候选进入）LLM 上下文的片段。"""

    source: str  # persona | memory | state | conversation | user
    scope: str  # session | global | task
    content: str = ""
    priority: int = 50  # 越大越重要（裁剪时从低到高丢）
    token_cost: int = 0
    mandatory: bool = False  # True 时永不裁剪（system/persona/本轮用户输入）
    freshness: float = 0.0  # 新鲜度（0–1；检索/时间维度，供排序参考）
    relevance: float = 0.0  # 相关性（检索得分；供排序参考）
    label: str = ""  # 日志用短标签（system/persona/facts/...）
    role: str = "system"  # 输出 messages 的 role（history 用其原始 role）
    raw: dict | None = field(default=None)  # history 的原始消息 dict（非 None 时直接输出）

    def __post_init__(self) -> None:
        if not self.token_cost:
            self.token_cost = estimate_tokens(self.content)
