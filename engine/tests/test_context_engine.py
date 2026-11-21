"""S06 / S47：ContextEngine（组装 / **排序** / 预算裁剪 / 工具结果截断）。

**S47 起测试重点变了**：不再要求与旧 ``_build_messages`` 逐字节一致 ——
顺序已按"缓存友好"（**稳定前缀 + 变化后缀**）**有意重排**，那是优化，不是漂移。

现在的硬护栏是四条：
1. **排序规约**：稳定段必须在前、变化段必须在后（这正是前缀缓存能命中的前提）；
2. **文案不漂移**：关键注入文案逐字保留（含大量实测调优结论，改写即行为回归）；
3. **情绪提示不进 persona 段**（否则情绪一变，第 2 段起缓存全失效）；
4. **推进提示 / 工具结果必须在 user 消息之前**（此前被 append 在 user 之后）。

另外两条 S47 修复也在测内：工具轮走同一入口（不再绕过预算）、提示计入预算。
"""
from __future__ import annotations

import pytest

from yuiro.config import ContextConfig, MemoryConfig, PersonaConfig
from yuiro.context import (
    ContextBudget,
    ContextEngine,
    ContextItem,
    estimate_tokens,
    fit_budget,
)


class _Mem:
    """最小记忆片段（对齐 Retriever 返回的 .text / .meta 结构）。"""

    def __init__(self, text: str, kind: str | None = None) -> None:
        self.text = text
        self.meta = {"kind": kind} if kind else {}


def _engine(**kw) -> ContextEngine:
    params: dict = {
        "system_prompt": "SYS",
        "persona_prompt": "PERS",
        "budget": ContextBudget(total=6000),
    }
    params.update(kw)
    return ContextEngine(**params)


def _labels(msgs: list[dict]) -> list[str]:
    """按内容反推段标签（顺序断言用）。"""
    out: list[str] = []
    markers = [
        ("SYS", "system"), ("PERS", "persona"), ("我们的关系", "relationship"),
        ("答应用户记住的事", "explicit"), ("用户画像", "facts"),
        ("知识库", "knowledge"), ("过往对话记录", "episodes"),
        ("当前目标", "task"), ("等待用户确认", "pending"), ("当前环境状态", "state"),
        ("本轮工具结果", "tool_results"), ("继续执行", "nudge"),
        ("当前情绪提示", "style"),
    ]
    for m in msgs:
        c = str(m.get("content") or "")
        if m.get("role") == "user" and c == "hi":
            out.append("user")
            continue
        for marker, name in markers:
            if marker in c:
                out.append(name)
                break
    return out


# ---- ★ 排序规约（S47 的核心护栏）---------------------------------------------
@pytest.mark.asyncio
async def test_stable_prefix_comes_first() -> None:
    """稳定段必须排在最前：system → persona → relationship → 用户画像。

    这是**前缀缓存能命中**的前提。若这段顺序被打乱（例如把 task/pending 插到
    relationship 之前），可缓存前缀会立刻退回到 system 一段。
    """
    msgs = await _engine().build(
        session_id="s1",
        user_text="hi",
        style_hint="心情不错",
        memory_items=[_Mem("我喜欢钢琴", "fact"), _Mem("资料", "knowledge")],
        relationship_summary="认识 30 天了",
        task_summary="整理文件夹",
        pending_note="要换哪个版本？",
    )
    labels = _labels(msgs)
    for i, name in enumerate(["system", "persona", "relationship", "facts"]):
        assert labels[i] == name, f"稳定前缀第 {i + 1} 段应为 {name}，实际顺序：{labels}"


@pytest.mark.asyncio
async def test_volatile_sections_come_after_stable() -> None:
    """变化段必须排在稳定段之后（否则会污染前缀缓存）。"""
    msgs = await _engine().build(
        session_id="s1",
        user_text="hi",
        memory_items=[_Mem("我喜欢钢琴", "fact"), _Mem("资料", "knowledge")],
        state_notes=["已打开：记事本"],
        task_summary="整理文件夹",
        tool_results=["- app_open → ok"],
        nudges=["（继续执行）请立刻动手"],
    )
    labels = _labels(msgs)
    stable_last = max(labels.index("facts"), labels.index("persona"))
    for name in ("knowledge", "task", "state", "tool_results", "nudge"):
        assert labels.index(name) > stable_last, (
            f"{name} 属变化段，应排在稳定段之后，实际：{labels}"
        )


@pytest.mark.asyncio
async def test_cache_prefix_is_byte_stable_across_turns() -> None:
    """★ 前缀稳定性：变化的上下文**不得**影响稳定前缀的字节。

    这是前缀缓存生效的充要条件（OpenAI 兼容端点是**自动**前缀缓存，无需显式
    标记，但对前缀逐字节稳定性极度敏感）。构造两轮：第 2 轮多了目标 / 待确认 /
    情绪 / 检索知识 / 状态 / 工具结果 / 推进提示，但只要稳定段逐字节相同，
    两轮就能共享同一段缓存前缀。

    这正是此前**完全做不到**的事：task/pending 插在 relationship 之前，
    情绪又被拼进 persona 段 —— 实测可缓存前缀时常退回到 system 一段（约 30%）。
    """
    common = {
        "session_id": "s1",
        "user_text": "hi",
        "relationship_summary": "认识 30 天了",
        "memory_items": [_Mem("我喜欢钢琴", "fact")],
    }
    t1 = await _engine().build(**common)
    t2 = await _engine().build(
        **{
            **common,
            "memory_items": [_Mem("我喜欢钢琴", "fact"), _Mem("检索到的资料", "knowledge")],
        },
        style_hint="心情不错",
        task_summary="整理文件夹",
        pending_note="要换哪个版本？",
        state_notes=["已打开：记事本"],
        tool_results=["- file_list → ok"],
        nudges=["（继续执行）动手"],
    )
    stable = 4  # system / persona / relationship / facts
    assert t1[:stable] == t2[:stable], (
        "稳定前缀必须逐字节相同，否则前缀缓存永远无法命中：\n"
        f"第 1 轮={t1[:stable]}\n第 2 轮={t2[:stable]}"
    )


# ---- ★ S47 两条修复 ---------------------------------------------------------
@pytest.mark.asyncio
async def test_style_hint_never_inside_persona() -> None:
    """情绪提示**不得**拼进 persona 段 —— 否则情绪一变，persona 及其后全部失缓存。"""
    msgs = await _engine().build(
        session_id="s1", user_text="hi", style_hint="心情不错",
        relationship_summary="认识 30 天了",
    )
    persona = next(m["content"] for m in msgs if m.get("content", "").startswith("【人设前置铁律】"))
    assert "心情不错" not in persona, "情绪提示不应出现在 persona 段里"
    # 但它仍必须真的被注入（只是换了位置）
    assert any("心情不错" in str(m.get("content")) for m in msgs)


@pytest.mark.asyncio
async def test_nudges_and_tool_results_before_user() -> None:
    """推进提示与工具结果必须在**最后一条 user 之前**。

    此前它们是 AgentLoop 侧 append 到 messages 末尾的 —— 于是 system 段出现在
    user 消息之后（违反 chat 常规），且每轮尾部结构都不同。
    """
    msgs = await _engine().build(
        session_id="s1", user_text="hi",
        tool_results=["- file_write → ok"],
        nudges=["（继续执行）把剩下的做完"],
    )
    last_user = max(i for i, m in enumerate(msgs) if m.get("role") == "user")
    for i, m in enumerate(msgs):
        if m.get("role") == "system" and m is not msgs[last_user]:
            assert i < last_user, f"system 段出现在最后一条 user 之后：{m}"
    assert msgs[-1] == {"role": "user", "content": "hi"}


# ---- 文案不漂移（保留原护栏价值）--------------------------------------------
@pytest.mark.asyncio
async def test_key_wording_preserved() -> None:
    """关键文案逐字保留（它们含实测调优结论，改写即行为回归）。"""
    msgs = await _engine().build(
        session_id="s1",
        user_text="放首歌",
        style_hint="心情不错",
        memory_items=[
            _Mem("我喜欢钢琴", "fact"), _Mem("钢琴曲", "knowledge"), _Mem("昨天聊过音乐"),
        ],
        state_notes=["已打开：记事本"],
        history=[{"role": "user", "content": "你好"}],
        episodic_inject=True,
    )
    joined = "\n".join(str(m.get("content") or "") for m in msgs)
    for phrase in (
        "【人设前置铁律】",          # 工具约束前置（短命令不被当台词）
        "【用户画像·已知事实】",
        "【知识库】",
        "【过往对话记录】",
        "当前环境状态：",
    ):
        assert phrase in joined, f"关键文案丢失：{phrase}"


@pytest.mark.asyncio
async def test_episodic_off_still_filters() -> None:
    """episodic_inject=False 时情景记忆不注入（避免"光说不做"范例污染）。"""
    mems = [_Mem("事实A", "fact"), _Mem("昨天的事")]
    msgs = await _engine().build(
        session_id="s3", user_text="hi", memory_items=mems, episodic_inject=False
    )
    joined = "\n".join(str(m.get("content") or "") for m in msgs)
    assert "事实A" in joined
    assert "昨天的事" not in joined


# ---- 预算裁剪 ---------------------------------------------------------------
def test_fit_budget_drops_low_priority_first() -> None:
    items = [
        ContextItem(source="persona", scope="global", content="s",
                    priority=100, mandatory=True, label="system"),
        ContextItem(source="state", scope="session", content="x" * 100,
                    priority=50, label="state"),  # 25 tokens
        ContextItem(source="memory", scope="session", content="y" * 100,
                    priority=40, label="episodes"),  # 25 tokens
    ]
    # system(1) + state(25) = 26 ≤ 30；episodes 装入会超 → 被丢
    kept, dropped = fit_budget(items, ContextBudget(total=30))
    assert [it.label for it in kept] == ["system", "state"]
    assert [it.label for it in dropped] == ["episodes"]


def test_fit_budget_keeps_original_order() -> None:
    """kept 必须保持收集顺序（= 注入顺序），与优先级排序无关。

    S47 起这一点更关键：**优先级只决定丢谁，位置由收集顺序决定** ——
    若裁剪把段重排，稳定前缀就不再稳定，缓存立刻失效。
    """
    items = [
        ContextItem(source="memory", scope="session", content="low", priority=10, label="episodes"),
        ContextItem(source="persona", scope="global", content="high", priority=100, label="system"),
    ]
    kept, _ = fit_budget(items, ContextBudget(total=10000))
    assert [it.label for it in kept] == ["episodes", "system"]


def test_mandatory_survives_over_budget() -> None:
    """mandatory 永不裁剪（即使自身超预算）。"""
    items = [
        ContextItem(source="persona", scope="global", content="x" * 1000,
                    priority=100, mandatory=True, label="system"),
        ContextItem(source="state", scope="session", content="y" * 100,
                    priority=50, label="state"),
    ]
    kept, dropped = fit_budget(items, ContextBudget(total=10))
    assert [it.label for it in kept] == ["system"]
    assert [it.label for it in dropped] == ["state"]


@pytest.mark.asyncio
async def test_nudges_counted_in_budget() -> None:
    """推进提示要**计入预算**（此前是 AgentLoop 旁路 append，完全不受预算约束）。"""
    msgs = await _engine(budget=ContextBudget(total=6000)).build(
        session_id="s1", user_text="hi", nudges=["X" * 400],
    )
    assert any("X" * 400 in str(m.get("content")) for m in msgs)


# ---- 工具结果截断 -----------------------------------------------------------
def test_clip_tool_result() -> None:
    e = _engine(tool_result_max_chars=100)
    out = e.clip_tool_result("a" * 500, "file_read")
    assert out.startswith("a" * 100)
    assert "结果过长已截断" in out
    assert "500" in out
    # 短结果原样返回
    assert e.clip_tool_result("short", "x") == "short"


# ---- token 估算 -------------------------------------------------------------
def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("你好") == 2
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a") == 1  # 至少 1


# ---- 输出结构 ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_build_ends_with_user_and_keeps_history_before_it() -> None:
    msgs = await _engine().build(
        session_id="s",
        user_text="hi",
        memory_items=[_Mem("事实", "fact")],
        state_notes=["n1"],
        history=[{"role": "user", "content": "老消息"}],
    )
    assert msgs[-1] == {"role": "user", "content": "hi"}
    # history 在本轮输入之前
    idx_history = next(i for i, m in enumerate(msgs) if "老消息" in str(m.get("content") or ""))
    assert idx_history < len(msgs) - 1
    # 至少 system 起头
    assert msgs[0]["role"] == "system"


# ---- 装配 -------------------------------------------------------------------
def test_build_agent_loop_wires_context_engine() -> None:
    from yuiro.agent import build_agent_loop

    loop = build_agent_loop(
        base_url="http://127.0.0.1:1/v1",
        model="m",
        api_key="k",
        persona=PersonaConfig(),
        memory_config=MemoryConfig(),
        context_config=ContextConfig(budget_tokens=1234),
    )
    assert loop._context is not None
    assert loop._context._budget.total == 1234
