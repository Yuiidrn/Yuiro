"""一轮对话的显式状态（S42 / P0-A）—— 把「推进策略」从散落的布尔里收回来。

**为什么需要它**：``AgentLoop.send()`` 里原本平铺着这些状态变量：

    task_nudges / task_nudge_line / last_task_line / write_nudges /
    write_nudge_pending / wrote_anything / claim_nudges / claim_nudge_pending
    round_tool_results

它们其实只描述**三个同构的「推进策略」**（任务续跑 / 写操作后续跑 / 幻觉纠错），
每一个都是"计数 + 上限 + 待注入提示"。

平铺的代价不是"不优雅"，而是**直接导致打地鼠**（S18→S41 的真实经历）：

1. **加一个策略要在 200 行循环里改 5 处**（声明、注入、判据、计数、日志）——
   漏一处就是"提示注入了但没生效"或"计数器永远不到上限"这类难查的 bug；
2. **判据埋在 async 生成器里，无法单测** —— 只能靠真机跑对话看日志；
3. **状态看不全** —— 调试时得 grep 才知道有几个标志在影响流程。

抽成对象后：**新增策略 = 加一个字段 + 一段提示文案**，且判据可独立测试。

S47 / B3 追加 ``TurnBudget``：**同一个文件里放"一轮对话的全部跨轮状态"** ——
推进策略（该不该再推一次）与预算（还能不能继续）都是"这一轮的处境"，
分开放又会回到"状态看不全"的老问题。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class Nudge:
    """一个推进策略的状态：**计数 + 上限 + 待注入提示**。

    「nudge」= 当模型该动手却没动手时，注入一条系统提示把它推回正轨
    （而不是在提示词里再写一条"遇到 X 要调 Y"——那是打补丁）。

    每个策略自管额度，避免某个策略失控把上下文塞满。
    """

    name: str
    limit: int
    used: int = 0
    queued: str = ""

    @property
    def armed(self) -> bool:
        """是否有待注入的提示（等价于原先的 ``*_pending`` 布尔标志）。"""
        return bool(self.queued)

    @property
    def exhausted(self) -> bool:
        """额度是否已用尽。"""
        return self.used >= self.limit

    def can_push(self) -> bool:
        """还能不能再推一次。"""
        return self.used < self.limit

    def push(self, content: str) -> bool:
        """记一次额度并把提示排进队列；额度用尽或内容为空则**不改任何状态**并返回 False。"""
        if not self.can_push() or not content.strip():
            return False
        self.used += 1
        self.queued = content
        return True

    def take(self) -> str:
        """取出待注入提示并清空（取后 ``armed`` 变为 False）。"""
        content, self.queued = self.queued, ""
        return content


@dataclass
class TurnState:
    """一轮对话里所有「跨轮推进」状态的唯一归属。

    生命周期 = 一次 ``send()``。每一轮 LLM 调用前用 :meth:`injections` 取提示、
    调用后用 ``push`` 排新的提示，中间不再有任何裸变量参与决策。
    """

    #: 任务续跑：任务类工具被调用后，推模型**立刻执行当前步骤**而不是只描述计划
    task: Nudge = field(default_factory=lambda: Nudge("任务续跑", 3))
    #: 写操作后续跑：本轮发生过写操作后，每次"只说不动"就推一次，直到收敛总结
    write: Nudge = field(default_factory=lambda: Nudge("写操作续跑", 3))
    #: 幻觉纠错：零工具调用却声称"已完成"，丢弃该文本并续跑一轮（只纠一次）
    claim: Nudge = field(default_factory=lambda: Nudge("幻觉纠错", 1))

    #: 本轮是否真的发生过写操作 —— 一个**准确的事实信号**（不用"未完成关键词"，
    #: 那在实测里是打地鼠：换种说法就漏网）。
    wrote_anything: bool = False
    #: 本轮已产生的工具结果（已截断），注入下一轮 messages。
    tool_results: list[str] = field(default_factory=list)
    #: 上一次的任务进度行 —— 用于去重：进度没变过就不必重复推。
    last_task_line: str = ""

    #: 注入下一轮的工具结果条数上限（过多会挤占上下文预算）
    MAX_TOOL_RESULTS: ClassVar[int] = 3

    def add_tool_result(self, text: str) -> None:
        """记录一条工具结果供下一轮使用；超出上限则丢弃（保留最早的更有信息量）。"""
        if len(self.tool_results) < self.MAX_TOOL_RESULTS:
            self.tool_results.append(text)

    def injections(self) -> list[str]:
        """按固定顺序取出所有待注入提示，**取完即清空**。

        顺序有讲究：任务续跑在最前（它是"正在进行的正事"），
        写操作续跑居中，纠错放最后（只在其它推进信号都不存在时才该生效）。
        """
        out: list[str] = []
        for nudge in (self.task, self.write, self.claim):
            if nudge.armed:
                out.append(nudge.take())
        return out

    def summary(self) -> str:
        """一行摘要，写日志用 —— 让"这一轮被推了几次、为什么"一眼可见。"""
        parts = [f"{n.name}={n.used}/{n.limit}" for n in (self.task, self.write, self.claim)]
        if self.wrote_anything:
            parts.append("有过写操作")
        return "，".join(parts)


@dataclass
class TurnBudget:
    """一轮对话的**总预算**（S47 / B3）：时间 / token / 工具轮数。

    **为什么需要它**：此前唯一的上限是"工具轮数 ≤ 3"，而单轮 LLM 可以跑到 30s、
    单轮上下文可以到 6000 tokens —— 也就是**最坏情况这一轮能烧掉 90 秒和上万
    token**，期间用户面对的是没有任何解释的等待。前沿 harness 的共识是
    **"预算是一等公民"**：接近上限时让模型自己收尾并如实告知，而不是硬撑到超时。

    三个维度刻意独立，因为它们对应三种不同的坏体验：
    - ``max_seconds``：用户体感（等多久算久）；
    - ``max_tokens``：成本（工具轮会不断把上下文撑大）；
    - ``max_rounds``：绕圈（模型反复调同一个工具时的刹车）。

    ⚠ 与 ``context.ContextBudget`` 的分工：那个管**一次**组装出来的上下文多大
    （空间）；这个管**整轮**（可能含多轮工具）累计花多久、多少 token（时间与成本）。
    两者互补，不是重复。
    """

    max_seconds: float = 90.0
    max_tokens: int = 60000
    max_rounds: int = 3

    started_at: float = field(default_factory=time.monotonic)
    used_tokens: int = 0
    rounds: int = 0
    #: 结束原因（空串 = 正常走完）—— 用于日志与"如实告知"。
    stop_reason: str = ""

    #: 用量达到该比例就开始提醒模型收尾（**渐进收尾优于到点硬掐**）。
    WARN_RATIO: ClassVar[float] = 0.7

    def elapsed(self) -> float:
        """已耗时（秒）。"""
        return time.monotonic() - self.started_at

    def add_usage(self, usage: dict | None) -> None:
        """累加一轮 LLM 的 token 用量。

        缺字段/类型异常一律静默 —— 观测绝不能反过来打断业务。
        （真实场景里 provider 可能不返回 usage，见 S47 的降级说明。）
        """
        try:
            u = usage or {}
            total = u.get("total_tokens")
            if total is None:
                total = int(u.get("prompt_tokens") or 0) + int(
                    u.get("completion_tokens") or 0
                )
            self.used_tokens += int(total or 0)
        except (TypeError, ValueError):
            return

    def exhausted(self) -> str:
        """返回耗尽原因（``""`` = 尚有预算）。**每轮开始前**调用。

        刻意返回**原因字符串**而不是 bool：预算耗尽必须能如实告知用户
        （"因为什么停下来"），而不是变成一个无声的 break。
        """
        if self.rounds >= self.max_rounds:
            self.stop_reason = f"轮数达上限（{self.max_rounds} 轮）"
        elif self.elapsed() >= self.max_seconds:
            self.stop_reason = f"耗时达上限（{self.max_seconds:.0f}s）"
        elif self.used_tokens >= self.max_tokens:
            self.stop_reason = f"token 达上限（{self.max_tokens}）"
        else:
            return ""
        return self.stop_reason

    def warning(self) -> str:
        """接近上限时给模型的**收尾提示**（``""`` = 不必提醒）。

        为什么是"渐进提醒"而不是"到点掐断"：硬掐断会让用户收到半截回复；
        提前提醒则让模型自己收尾，用户拿到的是完整句子 —— 这正是前沿做法里
        "budgeted loop" 与"超时抛异常"的区别。
        """
        reasons: list[str] = []
        if self.elapsed() >= self.max_seconds * self.WARN_RATIO:
            reasons.append("时间已用去大半")
        if self.used_tokens >= self.max_tokens * self.WARN_RATIO:
            reasons.append("本轮开销已用去大半")
        if self.rounds >= self.max_rounds - 1:
            reasons.append("这是最后的工具轮次")
        if not reasons:
            return ""
        return (
            "（预算提醒）" + "、".join(reasons) + "。请**尽快收尾**："
            "优先把已经做成的事如实讲清楚，并说明还有什么没做完 —— "
            "不要把没做完的说成做完了。"
        )

    def summary(self) -> str:
        """一行摘要，写日志用。"""
        return (
            f"耗时={self.elapsed():.1f}s 轮数={self.rounds}/{self.max_rounds} "
            f"tokens={self.used_tokens}/{self.max_tokens}"
            + (f" 停止={self.stop_reason}" if self.stop_reason else "")
        )

    def clone(self) -> TurnBudget:
        """复制一份**干净**的预算：保留上限、清零用量与计时。

        用途：``AgentLoop`` 持有一份"配置模板"（来自 config.toml），每轮 ``send``
        复制一份实际使用 —— 否则用量会在回合之间累积，第二次对话一开始就"耗尽"。
        """
        return TurnBudget(
            max_seconds=self.max_seconds,
            max_tokens=self.max_tokens,
            max_rounds=self.max_rounds,
        )
