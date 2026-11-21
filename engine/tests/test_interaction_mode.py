"""S46 测试：InteractionMode 分类。

分类器本身很简单，但它决定了**输入走哪条路径** —— 所以测试的重点不是"分得准不准"，
而是**两条安全性质**：

1. **不确定 → 倾向 CHAT**。CHAT 不改变路径（工具照常可见），所以误判成 CHAT
   最多损失一点优化；反过来把"想操作的用户"判成别的才是危险的。
2. **预路由命中 = ACTION**（最强的单步信号），不允许被其它词覆盖 ——
   否则"下一首"这种极明确指令会被误判。

`describe()` 也一并测：它写进日志/文档，必须如实反映"哪些形态其实还没分化"，
免得读者以为五种形态都已经落地了。
"""
from __future__ import annotations

import pytest

from yuiro.agent import AgentLoop, LLMChunk, LLMProvider
from yuiro.agent.interaction_mode import InteractionMode, classify, describe


def test_routed_is_action() -> None:
    """★ 预路由命中直接判 ACTION —— 这是最强的单步信号。"""
    assert classify("下一首", routed=True) is InteractionMode.ACTION
    assert classify("打开记事本", routed=True) is InteractionMode.ACTION


def test_routed_wins_over_other_signals() -> None:
    """即使文本里混有多步/计划词，只要预路由命中就是 ACTION。

    （预路由只覆盖"极明确的单步指令"，它的判断优先级高于用词启发式。）
    """
    assert classify("把剩下的全部暂停", routed=True) is InteractionMode.ACTION
    assert classify("先给我个方案，然后暂停", routed=True) is InteractionMode.ACTION


def test_plan_signals() -> None:
    assert classify("帮我规划一下整理方案") is InteractionMode.PLAN
    assert classify("先给我一个步骤") is InteractionMode.PLAN


def test_task_signals() -> None:
    assert classify("帮我整理下载文件夹") is InteractionMode.TASK
    assert classify("把剩下的都归位") is InteractionMode.TASK
    assert classify("批量重命名这些文件") is InteractionMode.TASK


def test_default_is_chat() -> None:
    """★ 安全性质：认不出来就是 CHAT（不削减能力）。"""
    for text in ("你好呀", "今天天气不错", "你觉得孤独吗", "放首周杰伦的晴天"):
        assert classify(text) is InteractionMode.CHAT, f"{text!r} 不该被判成会改变路径的形态"


def test_empty_and_blank_are_chat() -> None:
    assert classify("") is InteractionMode.CHAT
    assert classify("   ") is InteractionMode.CHAT


def test_describe_is_honest_about_unimplemented() -> None:
    """describe 必须说明 BACKGROUND **尚未实现** —— 文档/日志不能给人"已落地"的错觉。"""
    assert "尚未实现" in describe(InteractionMode.BACKGROUND)
    assert "立即执行" in describe(InteractionMode.ACTION)
    assert "暂未分化" in describe(InteractionMode.CHAT), "CHAT 目前与其它形态同路径，要如实说"


def test_all_modes_have_description() -> None:
    for mode in InteractionMode:
        assert describe(mode) and describe(mode) != "未知"


# ── 行为：ACTION 的「立即执行」语义（收尾轮不暴露工具）────────────────────
class _RecLLM(LLMProvider):
    """记录每次 LLM 调用是否**收到了工具表**。"""

    def __init__(self) -> None:
        self.tools_seen: list[bool] = []

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        self.tools_seen.append(tools is not None)
        yield LLMChunk(kind="token", content="好嘞。")
        yield LLMChunk(kind="done")


class _Reg:
    """最小注册表：提供 netease_control（预路由会命中它）。"""

    def schemas(self, toolset=None):  # noqa: ARG002
        return [{
            "type": "function",
            "function": {"name": "netease_control", "description": "播放控制",
                         "parameters": {"type": "object",
                                        "properties": {"action": {"type": "string"}}}},
        }]

    async def execute(self, name, args, task_id, approval_callback=None):  # noqa: ARG002
        return '{"status": "ok"}'


@pytest.mark.asyncio
async def test_action_closing_round_hides_tools() -> None:
    """★ ACTION：工具跑完的**收尾轮**不该再看到工具表。

    否则模型会再调一次同一个工具去"确认" —— 实测日志里正是第 1 轮 `played=true`、
    第 2 轮又调 `netease_play`，被去重挡回 `{"status":"done"}`，白烧一轮 token。
    这里断言：整个 ACTION 回合只有**一次** LLM 调用（收尾轮），且**不带工具**。
    """
    llm = _RecLLM()
    loop = AgentLoop(llm=llm, tools_registry=_Reg(), memory_retriever=None)
    async for _ in loop.send("s1", "下一首"):  # 命中预路由 → ACTION
        pass

    assert llm.tools_seen == [False], (
        f"ACTION 应只调一次 LLM（收尾轮）且不带工具，实际 tools_seen={llm.tools_seen}"
    )


@pytest.mark.asyncio
async def test_chat_keeps_tools_visible() -> None:
    """CHAT 不受影响，工具照常可见 —— **分类只用于加速与约束，绝不削减能力**。"""
    llm = _RecLLM()
    loop = AgentLoop(llm=llm, tools_registry=_Reg(), memory_retriever=None)
    async for _ in loop.send("s1", "你好呀"):
        pass

    assert llm.tools_seen == [True], (
        f"CHAT 必须保留工具可见性，实际 tools_seen={llm.tools_seen}"
    )

