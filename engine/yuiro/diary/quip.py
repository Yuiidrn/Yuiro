"""日记吐槽模式（S51）：门控 + 情绪安全阀。

设计：`docs/features/diary-feature-design.md` §8.1。三条核心（都不直观）：

1. **失败模式只有一个：说太多** —— 所以实现的重点不是"怎么吐槽"，而是
   **门控**："该不该在这一刻出声"。持续快速输入 = 心流中 → **闭嘴优先**。
2. **情绪安全阀（红线）**：负面情绪时降级为温柔/沉默 —— 在用户难过时吐槽是产品灾难。
   无法判断时**保守处理（沉默）**：宁可漏掉一次互动，也不要冒犯。
3. **它只是"一句话的生成"**：不落库、不进 history、不触发工具。
   编排在别处（本模块保持纯逻辑，便于测试与复用）。
"""
from __future__ import annotations

import asyncio
import math
import re
import time

from yuiro.logger import vlog

#: 负面情绪线索词（轻量判定，不等 LLM 解构 —— 那在用户确认之后，太晚）。
#: ★ 命中即沉默：**宁可误判为负面**（§8.1.4）。
_NEGATIVE_HINTS: tuple[str, ...] = (
    "难过", "崩溃", "焦虑", "烦躁", "很烦", "好累", "累死", "想哭", "哭了", "压力",
    "失眠", "睡不着", "头疼", "胃疼", "失败", "讨厌", "孤独", "害怕", "委屈",
    "生气", "愤怒", "后悔", "撑不住", "不想活", "绝望", "丢人", "崩溃了",
)

#: 模型可用这句话表达"我选择不说"（给模型一个沉默的出口，比强行憋一句话好）。
_SILENT_MARK = "（不说话）"

_QUIP_PROMPT = """你在陪用户写日记。下面是 TA 刚写的一段，请用**一句极短的话**（≤15 字）回应。

硬要求：
- 只输出这一句话本身：不加引号、不加解释、不加表情符号堆砌；
- 贴合这段具体内容，像身旁的人轻轻接一句；不要复述或连着追问；
- 可以轻松俏皮，但不嘲讽、不比较、不使用“比躺着强”等评判；
- 绝不评价日记写得如何、绝不给建议、绝不说教（"你应该…"一律禁止）；
- 如果你觉得 TA 情绪不太好，就只回一句温和的话；若觉得此刻不该说话，
  就只回复：{silent}

TA 刚写的：
---
{text}
---""".replace("{silent}", _SILENT_MARK)


def mood_is_safe(text: str) -> bool:
    """这段内容是否适合吐槽（False = 情绪安全阀触发，应当沉默）。"""
    t = (text or "").strip()
    if not t:
        return False
    return not any(h in t for h in _NEGATIVE_HINTS)


class QuipGate:
    """吐槽门控（纯逻辑，可单测；不依赖时间流逝的隐式状态）。

    四条规则**全部满足**才允许出声：
    1. 用户停笔 ≥ ``min_idle_s``（有喘息窗口才说话 —— 心流中不说话）；
    2. 距上次吐槽 ≥ ``min_interval_s``（频率上限）；
    3. 与上次吐槽的文本不同（同一段不重复吐）；
    4. 文本长度 ≥ ``min_chars``（不对"嗯""好"这种短回应搭话）。
    """

    def __init__(
        self, *, min_idle_s: float = 1.8, min_interval_s: float = 60.0, min_chars: int = 6
    ) -> None:
        self.min_idle_s = float(min_idle_s)
        self.min_interval_s = float(min_interval_s)
        self.min_chars = int(min_chars)
        self._last_at: float = 0.0
        self._last_text: str = ""

    def should_quip(self, *, text: str, idle_s: float, now: float | None = None) -> bool:
        t = (text or "").strip()
        if len(t) < self.min_chars:
            return False
        if not math.isfinite(idle_s) or idle_s < self.min_idle_s:
            return False  # 还在写 → 心流中
        now = time.monotonic() if now is None else now
        if self._last_at and (now - self._last_at) < self.min_interval_s:
            return False
        return t != self._last_text

    def note_quip(self, *, text: str, now: float | None = None) -> None:
        self._last_at = time.monotonic() if now is None else now
        self._last_text = (text or "").strip()

    def reset(self) -> None:
        """离开日记模式时复位（下次进入不该继承上次的节流状态）。"""
        self._last_at = 0.0
        self._last_text = ""


class QuipService:
    """吐槽生成（门控 → 情绪安全阀 → 轻量 LLM → 校验）。"""

    def __init__(self, *, llm=None, gate: QuipGate | None = None, timeout_s: float = 4.0) -> None:
        self.timeout_s = timeout_s
        self._inflight = False
        self._llm = llm
        self._gate = gate or QuipGate()

    @property
    def gate(self) -> QuipGate:
        return self._gate

    async def maybe_quip(self, text: str, *, idle_s: float) -> str | None:
        """返回该说的一句话；**不该说/生成失败时返回 None**（调用方据此什么都不做）。

        普通失败静默；取消继续向上传播，不干扰写日记。
        """
        if self._llm is None:
            return None
        # ① 情绪安全阀优先于一切门控：内容难过 → 直接沉默（连 LLM 都不调）。
        if not mood_is_safe(text):
            vlog("diary", "[吐槽] 情绪安全阀触发 → 保持沉默")
            return None
        # ② 门控
        if not self._gate.should_quip(text=text, idle_s=idle_s):
            return None
        # 一次只生成一句；不排队，不因停笔重试堆积请求。
        if self._inflight:
            return None
        self._inflight = True
        started = time.monotonic()
        vlog("diary", "[插话] 开始生成")
        try:
            parts: list[str] = []
            stream = self._llm.stream_text(
                [{"role": "system", "content": _QUIP_PROMPT.replace("{text}", "见用户消息")},
                 {"role": "user", "content": text[-600:]}],
                max_tokens=64,
            )
            try:
                async with asyncio.timeout(self.timeout_s):
                    async for chunk in stream:
                        if getattr(chunk, "kind", "") != "token":
                            continue
                        if not parts:
                            vlog("diary", f"[插话] 首字 {(time.monotonic()-started)*1000:.0f}ms")
                        parts.append(str(getattr(chunk, "content", "")))
                        candidate = "".join(parts).strip().strip('"“”')
                        sentence = re.match(r"^(.{1,30}?[。！？!?])", candidate)
                        if sentence and _SILENT_MARK not in candidate:
                            parts = [sentence.group(1)]
                            break  # 一句完整即结束，不等多余解释。
                        if len(candidate) > 30:
                            break
            finally:
                await stream.aclose()
            out = "".join(parts).strip().strip('"“”')
        except asyncio.CancelledError:
            vlog("diary", "[插话] 已取消")
            raise
        except TimeoutError:
            vlog("diary", f"[插话] 超时静默 {(time.monotonic()-started)*1000:.0f}ms")
            return None
        except Exception as exc:  # 不记录日记正文或供应商完整错误内容。
            vlog("diary", f"[插话] 生成跳过：{type(exc).__name__}")
            return None
        finally:
            self._inflight = False
        # ④ 校验：模型可以选"不说话"；过长的话也不放出去（那就不是"极短"了）
        if not out or _SILENT_MARK in out or len(out) > 30:
            reason = "空输出" if not out else "模型选择沉默" if _SILENT_MARK in out else "超过30字"
            vlog("diary", f"[插话] 未展示：{reason}，长度={len(out)}")
            return None
        vlog("diary", f"[插话] 完成 {(time.monotonic()-started)*1000:.0f}ms")
        self._gate.note_quip(text=text)
        return out
