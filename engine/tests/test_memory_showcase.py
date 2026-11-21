"""S17：Memory Showcase —— 端到端验证"它真的记得"。

四个场景（对应 docs/plan/S17-memory-showcase.md）：

- A 三天后仍记得（显式记忆 + 时间推进）
- B 琐事会淡忘，但显式记忆永不删（Lifecycle 协同）
- C 重启（新实例同 db）后仍能检索与注入
- D 端到端：显式记忆 → ContextEngine 组装出专用分段
- E Replay：一次会话的事件可完整回放（Showcase 的可观测底座）
"""
from __future__ import annotations

import os
import tempfile

import pytest

from yuiro.memory import MemorySystem


def _mem(db: str) -> MemorySystem:
    return MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")


def _age(mem: MemorySystem, days: float) -> None:
    """把全部记忆的时间戳拨回 days 天前（模拟时间流逝；复用同一连接避免锁冲突）。"""
    conn = mem.store.conn
    conn.execute("UPDATE messages SET ts = ts - ?", (days * 86400,))
    conn.execute("UPDATE facts SET updated_at = updated_at - ?", (days * 86400,))
    conn.commit()


@pytest.mark.asyncio
async def test_showcase_remembers_after_three_days() -> None:
    """场景 A：说"记住 X"→ 三天后追问仍能检索到（且走 explicit 通道）。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "m.db")
        mem = _mem(db)
        await mem.remember("记住：我下周要参加算法竞赛", "好，我记住了！")
        _age(mem, 3)  # 三天后
        hits = await mem.retrieve("我下周要做什么？")
        texts = " ".join(h.text for h in hits)
        assert "算法竞赛" in texts
        assert any(h.meta.get("kind") == "explicit" for h in hits)
        mem.close()


@pytest.mark.asyncio
async def test_showcase_forgets_trivial_but_keeps_explicit() -> None:
    """场景 B：200 天后琐事被淡忘，用户明确要求记住的仍在。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "m.db")
        mem = _mem(db)
        await mem.remember("今天天气不错", "是呀，适合出门")
        await mem.remember("记住：我的生日是 3 月 6 日", "记下了")
        _age(mem, 200)
        result = await mem.forget()
        assert result["episodes_removed"] >= 1
        texts = " ".join(
            str(r["text"]) for r in mem.store.conn.execute("SELECT text FROM messages")
        )
        assert "3 月 6 日" in texts  # 显式记忆仍在
        assert "天气不错" not in texts  # 琐事被淡忘
        mem.close()


@pytest.mark.asyncio
async def test_showcase_survives_restart() -> None:
    """场景 C：重启（新实例同 db）后仍能检索显式记忆。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "m.db")
        mem = _mem(db)
        await mem.remember("记住：我在学 Live2D", "好")
        mem.close()
        mem2 = _mem(db)  # 模拟重启
        hits = await mem2.retrieve("我在学什么？")
        assert any("Live2D" in h.text for h in hits)
        assert len(mem2.list_explicit()) >= 1
        mem2.close()


@pytest.mark.asyncio
async def test_showcase_context_injection_end_to_end() -> None:
    """场景 D：端到端 —— 显式记忆经 ContextEngine 组装为专用分段。"""
    from yuiro.context import ContextBudget, ContextEngine

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "m.db")
        mem = _mem(db)
        await mem.remember("记住：我对花生过敏", "记住了，会注意")
        hits = await mem.retrieve("晚饭吃什么？")
        engine = ContextEngine(
            system_prompt="SYS", persona_prompt="PERS", budget=ContextBudget(total=6000)
        )
        messages = await engine.build(
            session_id="s1", user_text="晚饭吃什么？", memory_items=hits
        )
        joined = " ".join(str(m.get("content", "")) for m in messages)
        assert "花生过敏" in joined
        assert "答应用户记住的事" in joined
        mem.close()


@pytest.mark.asyncio
async def test_showcase_event_replay() -> None:
    """场景 E：EventLog 可完整回放一次会话的事件序列（可观测底座）。"""
    from yuiro.runtime import AgentEvent, EventBus
    from yuiro.runtime.event_log import EventLog

    with tempfile.TemporaryDirectory() as tmp:
        log = EventLog(store_dir=os.path.join(tmp, "events"))
        bus = EventBus()
        bus.subscribe_all(log.sink)
        for t in ("session.started", "memory.explicit_saved", "agent.stale_discarded"):
            await bus.publish(AgentEvent(type=t, source="showcase", session_id="sc1"))
        events = log.replay("sc1")
        assert [e["type"] for e in events] == [
            "session.started",
            "memory.explicit_saved",
            "agent.stale_discarded",
        ]
        assert all(e["session_id"] == "sc1" for e in events)
