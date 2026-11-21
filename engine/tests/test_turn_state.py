"""S42 / P0-A 测试：推进策略的显式状态。

这些判据原本埋在 `AgentLoop.send()` 的 async 生成器里 —— 只能靠真机跑对话看日志，
所以历史上"补丁改错"很难被发现（S18→S41 打地鼠的机制性原因之一）。
抽成 `TurnState` 后，判据在这里就能测完。
"""
from __future__ import annotations

from yuiro.agent.turn_state import Nudge, TurnState


# ── Nudge：额度与队列 ─────────────────────────────────────────────────
def test_push_counts_and_queues() -> None:
    n = Nudge("测试", limit=2)
    assert n.can_push() and not n.armed

    assert n.push("第一条") is True
    assert n.used == 1 and n.armed and n.queued == "第一条"


def test_push_respects_limit_and_leaves_state_untouched() -> None:
    """额度用尽后 push 必须**完全不改状态**（否则计数会越界，注入次数失控）。"""
    n = Nudge("测试", limit=1)
    assert n.push("唯一的一次") is True
    n.take()

    assert n.can_push() is False and n.exhausted is True
    assert n.push("不该生效") is False
    assert n.used == 1 and n.queued == ""


def test_push_rejects_empty_content() -> None:
    n = Nudge("测试", limit=3)
    assert n.push("   ") is False
    assert n.used == 0


def test_take_clears_armed() -> None:
    n = Nudge("测试", limit=3)
    n.push("提示")
    assert n.armed is True
    assert n.take() == "提示"
    assert n.armed is False and n.take() == ""


# ── TurnState：注入顺序与去重 ──────────────────────────────────────────
def test_injections_are_ordered_and_consumed_once() -> None:
    """顺序必须是 任务 → 写操作 → 纠错；且取过一次就不再重复注入。"""
    st = TurnState()
    st.task.push("任务提示")
    st.write.push("写提示")
    st.claim.push("纠错提示")

    assert st.injections() == ["任务提示", "写提示", "纠错提示"]
    assert st.injections() == [], "取过即清空，不能重复注入"


def test_injections_skip_unarmed() -> None:
    st = TurnState()
    st.write.push("只有写提示")
    assert st.injections() == ["只有写提示"]


def test_task_nudge_dedupes_by_progress_line() -> None:
    """任务续跑靠进度行去重：进度没变就不该再推（原 last_task_line 的语义）。"""
    st = TurnState()
    line = "2/5｜正在移动文件"
    if line != st.last_task_line:
        st.last_task_line = line
        assert st.task.push(f"当前进度：{line}") is True

    # 进度未变 → 调用方不该 push（这里固化判据本身）
    assert line == st.last_task_line
    assert st.task.used == 1


def test_tool_results_capped() -> None:
    """工具结果最多 3 条（再多会挤爆上下文预算）。"""
    st = TurnState()
    for i in range(5):
        st.add_tool_result(f"结果{i}")
    assert st.tool_results == ["结果0", "结果1", "结果2"]


def test_summary_reports_usage() -> None:
    st = TurnState()
    st.task.push("x")
    st.wrote_anything = True
    s = st.summary()
    assert "任务续跑=1/3" in s and "有过写操作" in s


def test_default_limits_match_historical_behaviour() -> None:
    """上限必须与重构前的硬编码一致 —— 否则行为会静默改变。"""
    st = TurnState()
    assert (st.task.limit, st.write.limit, st.claim.limit) == (3, 3, 1)
