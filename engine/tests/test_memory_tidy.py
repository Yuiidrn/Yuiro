"""S51 空闲期记忆整理：``MemorySystem.tidy`` + ``MemoryIdleScheduler``。

覆盖三件事（每条都对应一个"错了就会悄悄毁数据"的判断）：

1. **归一只删不写** —— 语义重复时保留"信息更全的原话"，不做摘要、不改写（零幻觉）；
2. **删除必须四表齐删** —— messages / fts / vec 同步，不留孤儿向量（S50 的教训）；
3. **调度语义** —— "会话间隙"意味着**期间又说话就不算间隙**；单飞 + 最小间隔防连发。
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from yuiro.agent import LLMChunk
from yuiro.memory import MemorySystem
from yuiro.memory.idle import MemoryIdleScheduler


def _memory(tmp: str, **kw) -> MemorySystem:
    return MemorySystem(str(Path(tmp) / "mem.db"), rrf_k=60, top_k=3,
                        embedder_model="md5", **kw)


def _counts(memory: MemorySystem) -> tuple[int, int, int]:
    conn = memory.store.conn
    n_msg = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    n_fts = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    n_vec = conn.execute("SELECT COUNT(*) FROM messages_vec").fetchone()[0]
    return int(n_msg), int(n_fts), int(n_vec)


# ── ① 语义重复归一 ────────────────────────────────────────────────────────────
def test_tidy_merges_identical_episodes_and_keeps_tables_in_sync() -> None:
    """★ 完全相同的两条 → 归一成一条，且 **fts/vec 一起收敛**（不留孤儿）。

    这正是不用"合并后再写摘要"的原因：归一 = 去重（只删不写），
    因此不产生新文本、不需要重算向量，也就没有"文本与向量不一致"的风险。
    """
    with tempfile.TemporaryDirectory() as tmp:
        memory = _memory(tmp)
        same = "我今天去公园跑了五公里，回来路上买了豆浆"
        asyncio.run(memory.retriever.add(same))
        asyncio.run(memory.retriever.add(same))
        assert _counts(memory) == (2, 2, 2)

        res = asyncio.run(memory.tidy())
        assert res["merged"] == 1
        assert _counts(memory) == (1, 1, 1), "主表/FTS/向量必须同步，不能留孤儿向量"
        memory.close()


def test_tidy_keeps_the_more_informative_original() -> None:
    """★ 两条"像但不等长"时，**保留信息更全的那条原话**（不改写、不摘要）。"""
    with tempfile.TemporaryDirectory() as tmp:
        memory = _memory(tmp)
        long_text = "我最近在学做菜，今天试着做了番茄炒蛋，盐放多了但还能吃"
        short_text = "我最近在学做菜，今天试着做了番茄炒蛋"
        # 造一对"语义重复"：md5 向量无语义，用**完全相同**的向量来模拟近乎重复
        vec = asyncio.run(memory.embedder.embed(long_text))
        memory.store.add_message(long_text, vec)
        memory.store.add_message(short_text, vec)  # 同向量 → 距离 0 → 判为重复

        asyncio.run(memory.tidy())
        rows = memory.store.message_rows([1, 2])
        texts = [str(r["text"]) for r in rows]
        assert texts == [long_text], "应保留信息更全的原话，且不做改写"
        memory.close()


# ── ② 长期无人回顾 → 压缩 ────────────────────────────────────────────────────
def test_tidy_compresses_stale_memories_into_one_summary() -> None:
    """★ 够老 + **从没被检索命中过** + ≥3 条 → 压成一条摘要，原条目删除。

    "从没被检索命中"这项必须存在：只看年龄会压掉"很久以前但常被想起"的事，
    那恰恰是最该留着的。
    """
    with tempfile.TemporaryDirectory() as tmp:
        class _FakeLLM:
            async def stream_text(self, messages, tools=None):
                yield LLMChunk(kind="token", content="那阵子我常聊跑步和晚饭吃什么。")
                yield LLMChunk(kind="done")

        memory = _memory(tmp, fact_llm=_FakeLLM())
        old_ts = time.time() - 120 * 86400  # 120 天前（阈值 45 天）
        for t in ["今天跑步了", "晚饭吃了面", "又去跑步了"]:
            vec = asyncio.run(memory.embedder.embed(t))
            memory.store.add_message(t, vec, ts=old_ts, salience=1.0)
        assert _counts(memory) == (3, 3, 3)

        res = asyncio.run(memory.tidy())
        assert res["compressed"] == 3
        assert _counts(memory) == (1, 1, 1), "压缩后原条目必须删干净（四表齐删）"
        left = memory.store.message_rows([1, 2, 3, 4])
        assert any("跑步" in str(r["text"]) for r in left), "摘要应保留主题"
        memory.close()


def test_tidy_does_not_compress_when_recently_recalled() -> None:
    """★ 反向护栏：被检索命中过的记忆**不该**被当冷门压掉。

    没有这条，一次 retrieve 之后仍然压缩 = 把用户刚想起的事也吞了。
    """
    with tempfile.TemporaryDirectory() as tmp:
        memory = _memory(tmp)
        old_ts = time.time() - 120 * 86400
        rid = memory.store.add_message("很久以前的跑步记录", None, ts=old_ts, salience=1.0)
        memory.store.mark_accessed([rid])  # 曾被检索命中过
        stale = memory.store.stale_messages(
            older_than_ts=time.time() - 45 * 86400, max_access=0, limit=50
        )
        assert stale == [], "有过访问计数的记忆不属于'长期无人回顾'"
        memory.close()


# ── ③ 调度语义 ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_activity_during_idle_resets_the_timer() -> None:
    """★ "会话间隙"的核心语义：**期间又说话了 → 这一次不算间隙**（重新计时）。"""
    calls: list[int] = []

    async def _tidy() -> dict:
        calls.append(1)
        return {"merged": 0}

    sched = MemoryIdleScheduler(_tidy, idle_s=0.08, min_interval_s=0.0)
    sched.note_activity()
    await asyncio.sleep(0.03)
    sched.note_activity()  # 又说话了 → 前一个计时作废
    await asyncio.sleep(0.04)
    assert calls == [], "间隙被新活动打断，不应触发整理"
    await asyncio.sleep(0.1)
    assert calls == [1], "真正静默够久之后应触发一次"
    await sched.stop()


@pytest.mark.asyncio
async def test_scheduler_is_single_flight_and_throttled() -> None:
    """★ 单飞 + 最小间隔：连发信号不会跑多轮（否则每条消息都扫一遍全库）。"""
    calls: list[int] = []

    async def _tidy() -> dict:
        calls.append(1)
        await asyncio.sleep(0.05)
        return {"merged": 0}

    sched = MemoryIdleScheduler(_tidy, idle_s=0.01, min_interval_s=60.0)
    sched.note_activity()
    await asyncio.sleep(0.02)
    sched.note_activity()  # 上一轮还在跑
    await asyncio.sleep(0.08)
    assert len(calls) == 1, "单飞：同一时刻只有一轮"

    sched.note_activity()  # 已在最小间隔窗口内
    await asyncio.sleep(0.05)
    assert len(calls) == 1, "最小间隔内不再触发"
    await sched.stop()
