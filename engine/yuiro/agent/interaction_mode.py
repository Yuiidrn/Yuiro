"""InteractionMode：先判断「这是什么类型的输入」，再决定走哪条路径（S46）。

**为什么需要它**：spec §3.5 的原话是「**不能把所有输入当成同一种 Chat Turn**」。
在此之前，所有输入都走同一条 `AgentLoop.send()` 路径，靠关键词预路由和 nudge
事后补救 —— 这正是"新增一种交互形态就得再补一条规则"的结构性原因。

五种形态（spec §3.5）：

```
CHAT       简单问题
ACTION     简单工具操作 → Immediate Action
PLAN       复杂敏感任务 → Plan → Approval → Task
TASK       多步执行 → Long-running Task
BACKGROUND 独立耗时任务 → 后台执行 + 进度通知
```

---

**本 Sprint 的范围（刻意保守）**：

1. **先把概念显式化** —— 分类 + 日志 + 事件，**不改变行为**（可观测、可单测）；
2. **只对 ACTION 落地它的路径差异**（"Immediate Action"：**收尾轮不再暴露工具**）。
   这一条直接消除"工具明明成功了却又调一次去确认"的空转；
3. CHAT / PLAN / TASK **保持现状** —— 它们各自已有机制（直聊 / 审批门 / TaskRuntime 驱动）；
4. BACKGROUND **尚未实现**：分类器会识别并记录，但不改变行为。

**为什么这么保守**：分类错误会让输入**走错路径**。最危险的方向是
"把真正想操作的用户判成 CHAT" —— 那等于削减了能力。所以本模块遵守两条：

- **不确定 → 倾向 CHAT**（CHAT 不改路径，工具照常可见，误判不会削减能力）；
- **分类只用于加速与约束，绝不用于削减能力** —— 所有模式都保留完整工具可见性，
  唯一例外是 ACTION 的**收尾轮**（那时它已经执行完了，不需要再动工具）。
"""
from __future__ import annotations

from enum import Enum


class InteractionMode(str, Enum):
    """一次用户输入的交互形态。"""

    CHAT = "chat"
    ACTION = "action"
    PLAN = "plan"
    TASK = "task"
    BACKGROUND = "background"


#: 多步 / 批量的结构性信号 —— 出现这些词，输入通常不是一步能做完的。
#: 刻意只收"明确指向多步"的词，不含"帮我"这类泛化说法（那属于 CHAT/ACTION 都可能的灰区）。
_TASK_SIGNALS = (
    "整理", "整理一下", "批量", "批处理", "一个个", "依次", "逐个", "分别",
    "全部", "所有", "剩下", "剩下的", "分门别类", "归档",
)

#: 计划 / 方案类信号 —— 用户要的是"先给我看法"而不是"现在就动手"。
_PLAN_SIGNALS = ("计划", "规划", "方案", "步骤", "先别执行", "先给我", "怎么做好")


def classify(text: str, *, routed: bool = False) -> InteractionMode:
    """判断一次输入属于哪种交互形态。

    ``routed``：关键词预路由是否已命中。这是**最强的 ACTION 信号**
    （预路由本身只覆盖"极明确的单步指令"，见 `_keyword_route` 的说明），
    因此直接采纳，不再做其它判断。

    其余情况按**结构性用词**判断，顺序为 计划 → 多步 → 默认 CHAT：

    - 命中计划类词 → ``PLAN``（用户要的是方案，不是立刻执行）；
    - 命中多步类词 → ``TASK``；
    - 其它 → ``CHAT``。

    ★ **不确定时倾向 CHAT 是安全的**：CHAT 不改变路径（工具照常可见），
    所以误判成 CHAT 不会让用户"想做操作却做不到"，最多是不做那点优化。
    """
    if routed:
        return InteractionMode.ACTION

    t = (text or "").strip()
    if not t:
        return InteractionMode.CHAT

    if any(w in t for w in _PLAN_SIGNALS):
        return InteractionMode.PLAN
    if any(w in t for w in _TASK_SIGNALS):
        return InteractionMode.TASK
    return InteractionMode.CHAT


def describe(mode: InteractionMode) -> str:
    """一句话说明该形态当前的**实际路径**（写日志与文档用，避免读者误解为"已完全分化"）。"""
    return {
        InteractionMode.CHAT: "直聊（路径与其它形态相同，暂未分化）",
        InteractionMode.ACTION: "立即执行（收尾轮不再暴露工具）",
        InteractionMode.PLAN: "计划/审批（沿用现有 approval 门）",
        InteractionMode.TASK: "多步任务（沿用 TaskRuntime 驱动）",
        InteractionMode.BACKGROUND: "后台执行（**尚未实现**，当前不改变行为）",
    }.get(mode, "未知")
