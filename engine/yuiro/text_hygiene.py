"""输出文本净化（S34）：剥掉模型模仿出来的"调试注记"。

背景（S34 从引擎日志定位）：引擎为了让多轮历史保持连贯，曾把工具痕迹以
``（本轮操作：我调用了 X，已完成）`` 的形态**拼进 history 的 assistant 消息**。
模型随后**模仿了这个格式**，并在回复里自行生成 —— 甚至凭空编造
``（本轮操作：无工具调用）``。后果不只是难看：**它会被 TTS 念出来**
（用户直接听到"左括号本轮操作冒号…"）。

修复分两层，互为保险：

1. **源头**（``agent/__init__.py``）：history 里 assistant 内容保持干净，
   工具痕迹改为独立的 ``system`` 备注 —— 模型知道上轮做了什么，但不会把它
   当成"我该说的格式"；
2. **出口**（本模块）：即使模型从更早的 history 学到这个格式，
   也在送前端 / 送 TTS 之前剥掉。

实现说明：注记**内部可能还有括号**（常见的 ``（本轮操作：我调用了 X（action=next），已完成）``），
所以不能用"匹配到第一个右括号"的正则 —— 这里用括号配对扫描，且只从特征化的
``（本轮操作：`` 起算，不会误伤用户正常的括号内容。
"""
from __future__ import annotations

import re

#: 注记开头（高度特征化，避免误伤普通括号）
_OPEN = re.compile(r"[（(]\s*本轮操作\s*[:：]")

#: 其它可能被模仿的内部注记（按需追加，避免过度清洗）
_EXTRA_OPEN = (
    re.compile(r"[（(]\s*当前(?:正在)?使用工具\s*[:：]"),
)

_OPEN_CHARS = "（("
_CLOSE_CHARS = "）)"

#: 注记长度上限（防止异常输入导致超长扫描；超过视为不是注记）
_MAX_NOTE_LEN = 400


def _find_close(text: str, start: int) -> int:
    """从 ``start``（左括号位置）向后找**配对**的右括号，返回其下标（找不到 -1）。"""
    depth = 0
    limit = min(len(text), start + _MAX_NOTE_LEN)
    for i in range(start, limit):
        ch = text[i]
        if ch in _OPEN_CHARS:
            depth += 1
        elif ch in _CLOSE_CHARS:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _strip_pattern(text: str, open_re: re.Pattern[str]) -> str:
    """反复剥掉由 ``open_re`` 定位、括号配对完整的注记片段。"""
    out = text
    pos = 0
    while True:
        match = open_re.search(out, pos)
        if match is None:
            return out
        close = _find_close(out, match.start())
        if close < 0:
            return out  # 括号不闭合：不动（宁可留一点，也不误删用户内容）
        out = out[: match.start()] + out[close + 1 :]
        pos = match.start()


def strip_debug_notes(text: str) -> str:
    """剥掉模型模仿出的调试注记并清理多余空白。"""
    if not text:
        return ""
    out = _strip_pattern(text, _OPEN)
    for pattern in _EXTRA_OPEN:
        out = _strip_pattern(out, pattern)
    # 清洗后可能留下连续空白
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def has_debug_notes(text: str) -> bool:
    """是否含有调试注记（供日志告警：出现即说明模型仍在模仿）。"""
    if not text:
        return False
    return _OPEN.search(text) is not None or any(p.search(text) for p in _EXTRA_OPEN)
