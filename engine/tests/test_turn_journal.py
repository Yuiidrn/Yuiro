"""S47 / B4：TurnJournal —— 回合级流水（"这一轮做到哪"）。

**为什么值得测**：现有持久化有三层 —— 任务级（TaskRuntime + Journal）、
会话级（SessionManager.revive）、事件级（EventLog）—— **唯独缺"这一轮"**。
引擎崩溃/重启后，进行中的回合全部丢失，只能从头重来；而工具是有副作用的
（写文件、放歌、发消息），重来就可能**重复执行**。

测试重点是 `replay_unfinished` 这个**纯函数**：它就是 durable execution 里
**replay boundary** 的判据（"可以安全重放的起点"）。刻意做成纯函数、不碰 IO，
才能像这样被穷举覆盖 —— 与 P0-A 把判据搬出 async 生成器是同一个理由。
"""
from __future__ import annotations

import pytest

from yuiro.agent.turn_journal import (
    TURN_COMPLETED,
    TURN_STARTED,
    TURN_STEP,
    TurnJournal,
    replay_unfinished,
)


def _ev(etype: str, **payload):
    return {
        "ts": 1000.0,
        "type": etype,
        "session_id": "s1",
        "generation": 1,
        "payload": payload,
    }


# ---- replay_unfinished（纯函数，B4 的核心判据）--------------------------------
def test_no_events_means_nothing_unfinished() -> None:
    assert replay_unfinished([]) is None
    assert replay_unfinished(None) is None  # type: ignore[arg-type]


def test_started_without_completed_is_unfinished() -> None:
    """★ 只有 started、没有 completed → 这就是 replay boundary。"""
    rec = replay_unfinished([_ev(TURN_STARTED, text="帮我整理文件夹")])
    assert rec is not None
    assert rec.text == "帮我整理文件夹"
    assert rec.finished is False
    assert rec.steps == []


def test_completed_turn_is_not_unfinished() -> None:
    """正常走完的回合不该被当成"未完成"（否则每次重启都会误触发续跑）。"""
    rec = replay_unfinished([
        _ev(TURN_STARTED, text="你好"),
        _ev(TURN_STEP, tool="app_open", status="ok"),
        _ev(TURN_COMPLETED, reply="打开好了"),
    ])
    assert rec is None


def test_steps_are_collected_in_order() -> None:
    """已完成的步骤要按发生顺序留下 —— 它们代表**已经发生的副作用**。"""
    rec = replay_unfinished([
        _ev(TURN_STARTED, text="整理"),
        _ev(TURN_STEP, tool="file_list", status="ok", preview="..."),
        _ev(TURN_STEP, tool="file_move", status="ok", preview="..."),
    ])
    assert rec is not None
    assert [s["tool"] for s in rec.steps] == ["file_list", "file_move"]


def test_new_started_supersedes_previous_unfinished() -> None:
    """同一会话只有一轮进行中：新的 started 会取代上一个没结束的。"""
    rec = replay_unfinished([
        _ev(TURN_STARTED, text="第一轮"),
        _ev(TURN_STEP, tool="file_list", status="ok"),
        _ev(TURN_STARTED, text="第二轮"),
    ])
    assert rec is not None
    assert rec.text == "第二轮", "应以上一轮之后的新回合为准"
    assert rec.steps == [], "新回合的步骤应从头开始计"


def test_steps_before_started_are_ignored() -> None:
    """没有 started 的孤儿 step 不该被算进任何回合（防御损坏/截断的事件流）。"""
    rec = replay_unfinished([_ev(TURN_STEP, tool="file_list", status="ok")])
    assert rec is None


def test_describe_is_human_readable() -> None:
    rec = replay_unfinished([
        _ev(TURN_STARTED, text="整理文件夹"),
        _ev(TURN_STEP, tool="file_move", status="ok"),
    ])
    assert rec is not None
    text = rec.describe()
    assert "整理文件夹" in text and "file_move" in text
    assert "尚未完成" in text


# ---- TurnJournal：IO 层（写入 + 查询）---------------------------------------
class _FakeLog:
    def __init__(self, events):
        self._events = events

    def load(self, _session_id, *, limit=200):
        del limit  # 对齐 EventLog.load 的签名；测试不需要分页
        return self._events


@pytest.mark.asyncio
async def test_journal_emits_events_to_bus() -> None:
    """写入走 EventBus：三类事件都要发出去。"""
    class _Bus:
        def __init__(self):
            self.types: list[str] = []

        async def publish(self, event):
            self.types.append(event.type)

    bus = _Bus()
    j = TurnJournal(events=bus)
    await j.started("s1", 1, "你好")
    await j.step("s1", 1, tool="app_open", status="ok")
    await j.completed("s1", 1, reply="好了")
    assert bus.types == [TURN_STARTED, TURN_STEP, TURN_COMPLETED]


@pytest.mark.asyncio
async def test_journal_without_bus_is_silent() -> None:
    """没注入 EventBus 时静默跳过（持久化不能反过来打断对话）。"""
    j = TurnJournal(events=None, event_log=None)
    await j.started("s1", 1, "x")  # 不应抛异常
    await j.step("s1", 1, tool="t")
    await j.completed("s1", 1)
    assert j.unfinished("s1") is None


@pytest.mark.asyncio
async def test_journal_publish_failure_is_swallowed() -> None:
    """EventBus 抛异常时也必须吞掉 —— 回合不能因为"记日志失败"而崩。"""

    class _BadBus:
        async def publish(self, _event):
            raise RuntimeError("bus down")

    j = TurnJournal(events=_BadBus())
    await j.started("s1", 1, "x")  # 不应抛出
    await j.completed("s1", 1)


def test_unfinished_uses_event_log() -> None:
    """有 EventLog 时能查出未完成的回合（这是 B4 对外的价值出口）。"""
    log = _FakeLog([_ev(TURN_STARTED, text="整理文件夹"),
                    _ev(TURN_STEP, tool="file_list", status="ok")])
    j = TurnJournal(event_log=log)
    rec = j.unfinished("s1")
    assert rec is not None and rec.text == "整理文件夹"
    assert [s["tool"] for s in rec.steps] == ["file_list"]


def test_recent_turns_includes_finished() -> None:
    """诊断面板要看完整流水（含已完成的回合）。"""
    log = _FakeLog([
        _ev(TURN_STARTED, text="第一轮"),
        _ev(TURN_COMPLETED, reply="好"),
        _ev(TURN_STARTED, text="第二轮"),
    ])
    j = TurnJournal(event_log=log)
    turns = j.recent_turns("s1")
    assert [t.text for t in turns] == ["第一轮", "第二轮"]
    assert turns[0].finished is True
    assert turns[1].finished is False


# ---- ResumePlan（S48 / 方案 D：按副作用分级决定怎么续）------------------------
def test_resume_plan_all_read_is_auto_safe() -> None:
    """★ 全是只读步骤 → **不必打扰用户**，可直接续。

    若这条不成立（读个文件也要问），防护就退化成唠叨，最后没人看。
    """
    log = _FakeLog([
        _ev(TURN_STARTED, text="看看我的文件"),
        _ev(TURN_STEP, tool="file_list", status="ok", effect="read"),
        _ev(TURN_STEP, tool="file_read", status="ok", effect="read"),
    ])
    plan = TurnJournal(event_log=log).resume_plan("s1")
    assert plan is not None
    assert plan.auto_safe is True
    assert len(plan.replayable) == 2
    assert plan.risky == []
    assert plan.question() == ""


def test_resume_plan_external_is_risky_and_asks() -> None:
    """★ 有对外副作用 → 必须问用户（重做可能重复放歌 / 重复发消息）。"""
    log = _FakeLog([
        _ev(TURN_STARTED, text="放首歌"),
        _ev(TURN_STEP, tool="netease_search", status="ok", effect="read"),
        _ev(TURN_STEP, tool="netease_play", status="ok", effect="external"),
    ])
    plan = TurnJournal(event_log=log).resume_plan("s1")
    assert plan is not None
    assert plan.auto_safe is False
    assert len(plan.replayable) == 1 and len(plan.risky) == 1
    q = plan.question()
    assert "netease_play" in q and "继续" in q
    assert "未完" in plan.describe()


def test_resume_plan_infers_for_legacy_events() -> None:
    """S48 之前的事件没有 ``effect`` 字段 → **按工具名保守推断**。

    既不能一律当危险（会把老记录全吓一遍），也不能一律当安全（漏防护）。
    """
    log = _FakeLog([
        _ev(TURN_STARTED, text="老的记录"),
        _ev(TURN_STEP, tool="file_read", status="ok"),      # 无 effect
        _ev(TURN_STEP, tool="netease_play", status="ok"),   # 无 effect
    ])
    plan = TurnJournal(event_log=log).resume_plan("s1")
    assert plan is not None
    assert [s["tool"] for s in plan.replayable] == ["file_read"]
    assert [s["tool"] for s in plan.risky] == ["netease_play"]


def test_resume_plan_none_when_nothing_unfinished() -> None:
    log = _FakeLog([_ev(TURN_STARTED, text="x"), _ev(TURN_COMPLETED, reply="完")])
    assert TurnJournal(event_log=log).resume_plan("s1") is None
