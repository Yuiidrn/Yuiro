"""S26 测试：Relationship Memory（我们之间发生过什么）。

覆盖：计数与派生、天数里程碑、跨重启持久化、注入文本、ContextEngine 分段与优先级，
以及"与 Conversation Memory 的区别"（不检索、always-on、无记录时不注入）。
"""
from __future__ import annotations

import os
import tempfile

import pytest

from yuiro.memory.relationship import RelationshipMemory


def _rm(path: str) -> RelationshipMemory:
    return RelationshipMemory(path)


# ── 基本计数与派生 ────────────────────────────────────────────────────────
def test_first_interaction_sets_first_seen() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rm = _rm(os.path.join(tmp, "rel.json"))
        assert rm.summary() == ""  # 从没聊过 → 不注入
        rm.note_interaction()
        assert rm.state.interactions == 1
        assert rm.state.first_seen > 0
        assert rm.days_known == 1
        assert "认识 1 天" in rm.summary()
        assert "聊过 1 次" in rm.summary()


def test_task_and_explicit_counters() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rm = _rm(os.path.join(tmp, "rel.json"))
        rm.note_interaction()
        rm.note_task_completed("整理下载文件夹")
        rm.note_task_completed()
        rm.note_explicit_memory()
        text = rm.summary()
        assert "一起完成过 2 件事" in text
        assert "让你记住 1 件事" in text
        # 第一次完成 → 里程碑
        assert any("第一次一起完成一件事" in m for m in rm.state.milestones)
        assert "整理下载文件夹" in " ".join(rm.state.milestones)


def test_first_task_milestone_only_once() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rm = _rm(os.path.join(tmp, "rel.json"))
        rm.note_task_completed("A")
        rm.note_task_completed("B")
        first = [m for m in rm.state.milestones if m.startswith("第一次一起完成")]
        assert len(first) == 1


# ── 天数里程碑 ────────────────────────────────────────────────────────────
def test_day_milestones_by_time_travel() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rm = _rm(os.path.join(tmp, "rel.json"))
        rm.note_interaction()
        # 模拟"认识 8 天前"
        rm.state.first_seen -= 7 * 86400
        new = rm.note_interaction()
        assert "认识第 3 天" in new
        assert "认识第 7 天" in new
        # 同日再互动不重复记
        assert rm.note_interaction() == []


def test_day_milestone_not_repeated_across_restart() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rel.json")
        rm = _rm(path)
        rm.note_interaction()
        rm.state.first_seen -= 7 * 86400
        rm.note_interaction()
        rm2 = _rm(path)  # 重启后 last_milestone_day 已记过
        assert rm2.note_interaction() == []


# ── 持久化 ────────────────────────────────────────────────────────────────
def test_persists_across_restart() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rel.json")
        rm = _rm(path)
        rm.note_interaction()
        rm.note_task_completed("写报告")
        rm2 = _rm(path)
        assert rm2.state.interactions == 1
        assert rm2.state.tasks_completed == 1
        assert "写报告" in " ".join(rm2.state.milestones)


def test_corrupted_file_is_tolerated() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rel.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        rm = _rm(path)  # 不抛错，按全新关系处理
        assert rm.state.interactions == 0


def test_summary_limits_milestone_tail() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rm = _rm(os.path.join(tmp, "rel.json"))
        rm.note_interaction()
        rm.state.milestones = ["m1", "m2", "m3", "m4", "m5"]
        text = rm.summary()
        assert "m5" in text and "m4" in text and "m3" in text
        assert "m1" not in text  # 只回看最近 3 条


def test_to_dict_view() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rm = _rm(os.path.join(tmp, "rel.json"))
        rm.note_interaction()
        view = rm.to_dict()
        assert view["interactions"] == 1
        assert view["days_known"] == 1
        assert "认识 1 天" in view["summary"]


# ── ContextEngine 集成 ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_context_injects_relationship_segment() -> None:
    from yuiro.context import ContextBudget, ContextEngine

    with tempfile.TemporaryDirectory() as tmp:
        rm = _rm(os.path.join(tmp, "rel.json"))
        rm.note_interaction()
        rm.note_task_completed("整理下载文件夹")

        engine = ContextEngine(
            system_prompt="SYS", persona_prompt="PERS", budget=ContextBudget(total=6000)
        )
        messages = await engine.build(
            session_id="s1",
            user_text="在吗",
            relationship_summary=rm.summary(),
        )
        joined = " ".join(str(m.get("content", "")) for m in messages)
        assert "我们的关系" in joined
        assert "认识 1 天" in joined


@pytest.mark.asyncio
async def test_context_skips_empty_relationship() -> None:
    from yuiro.context import ContextBudget, ContextEngine

    engine = ContextEngine(
        system_prompt="SYS", persona_prompt="PERS", budget=ContextBudget(total=6000)
    )
    messages = await engine.build(session_id="s1", user_text="在吗", relationship_summary="")
    joined = " ".join(str(m.get("content", "")) for m in messages)
    assert "我们的关系" not in joined


def test_relationship_priority_between_task_and_facts() -> None:
    """关系是稳定背景：低于当前目标与明确记忆，高于普通事实。"""
    from yuiro.context.engine import P_EXPLICIT, P_FACT, P_RELATION, P_TASK

    assert P_TASK > P_EXPLICIT > P_RELATION > P_FACT
