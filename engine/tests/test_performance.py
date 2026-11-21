"""S18 测试：Performance（表演包 / Resolver / 命名表演 / 到期回落 / 事件驱动）。

覆盖两类护栏：
1. 表演解析与广播（expression + motion 组合、配置覆盖、未知名降级）；
2. 本次修复的两个真问题：
   - ACTION 意图会永久压制 EMOTION（一次性表演到期后应允许回落）；
   - TaskRuntime 事件因缺 session_id 从未真正发布。
"""
from __future__ import annotations

import json
import tempfile
import time

import pytest

from yuiro.avatar import (
    AvatarPriority,
    AvatarRuntime,
    PerformanceResolver,
    parse_performance_spec,
)


class _FakeBroadcast:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def __call__(self, payload: dict) -> None:
        self.sent.append(payload)


def _rt(**kw) -> tuple[AvatarRuntime, _FakeBroadcast]:
    bc = _FakeBroadcast()
    params: dict = {
        "expression_map": {"happy": "expression2", "excited": "expression4"},
        "broadcast": bc,
    }
    params.update(kw)
    return AvatarRuntime(**params), bc


# ── Resolver ──────────────────────────────────────────────────────────────
def test_resolver_library_has_builtin_performances() -> None:
    r = PerformanceResolver(expression_map={"excited": "expression4"})
    names = r.names()
    assert "celebrate" in names
    assert "comfort" in names
    assert len(names) >= 9  # spec 的第一批表演包

    perf = r.resolve("celebrate")
    assert perf.emotion == "excited"
    assert perf.expression == "expression4"  # 经 expression_map 解析
    # S53：内置包只声明语义槽位，不写死 TapBody#5 这类模型私有坐标
    assert perf.motion == ""
    assert perf.motion_slot == "celebrate"
    assert perf.duration_ms > 0


def test_resolver_unknown_name_falls_back_to_emotion() -> None:
    r = PerformanceResolver(expression_map={"happy": "expression2"})
    perf = r.resolve("happy")
    assert perf.expression == "expression2"
    # 完全未知的名字也不抛错（LLM 可能给任意词）
    weird = r.resolve("完全没这个词")
    assert weird.expression == ""


def test_motion_map_overrides_group() -> None:
    r = PerformanceResolver(
        expression_map={"excited": "expression4"}, motion_map={"celebrate": "TapBody"}
    )
    assert r.resolve("celebrate").motion == "TapBody"
    # 情绪维度的覆盖同样生效
    r.update(motion_map={"excited": "Idle"})
    assert r.resolve("celebrate").motion == "Idle"


# ── S48：performance_map 自由搭配 ─────────────────────────────────────────
def test_parse_performance_spec() -> None:
    """取值语法："表情, 动作"，缺哪段留空哪段。"""
    assert parse_performance_spec("expression7, TapBody#4") == ("expression7", "TapBody#4")
    assert parse_performance_spec("expression6") == ("expression6", "")  # 无逗号 = 纯表情
    assert parse_performance_spec(", TapBody#7") == ("", "TapBody#7")  # 只给动作
    assert parse_performance_spec("TapBody#4") == ("", "TapBody#4")  # 带索引 → 当动作
    assert parse_performance_spec(" expression7 , TapBody#4 ") == ("expression7", "TapBody#4")
    assert parse_performance_spec("") == ("", "")


def test_performance_map_decouples_expression_from_emotion() -> None:
    """核心问题回归：celebrate / surprise 共用 excited 表情，原本无法单独调其中一个。

    有了 performance_map 后，celebrate 可换"俏皮"而 surprise 保持"惊讶"。
    """
    r = PerformanceResolver(
        expression_map={"excited": "expression5"},  # 惊讶（celebrate 与 surprise 共享）
        performance_map={"celebrate": "expression7, TapBody#4"},
    )
    celebrate = r.resolve("celebrate")
    assert celebrate.expression == "expression7"  # 被自由搭配覆盖
    assert (celebrate.motion, celebrate.motion_index) == ("TapBody", 4)
    assert celebrate.duration_ms == 8570 + 300  # 时长跟着覆盖后的动作走
    # 同一情绪下的其它表演不受牵连
    assert r.resolve("surprise").expression == "expression5"
    assert r.resolve("surprise").motion_slot == "surprise"


def test_performance_map_only_expression_keeps_motion_slot() -> None:
    r = PerformanceResolver(performance_map={"greet": "expression6"})
    perf = r.resolve("greet")
    assert perf.expression == "expression6"
    # 只写表情 → 动作仍按语义槽位（由档案 motion_slots 或模型清单解析）
    assert perf.motion == ""
    assert perf.motion_slot == "greet"


def test_performance_map_only_motion_keeps_emotion_expression() -> None:
    r = PerformanceResolver(
        expression_map={"happy": "expression2"},
        performance_map={"greet": ", TapBody#0"},
    )
    perf = r.resolve("greet")
    assert perf.expression == "expression2"  # 表情仍走情绪映射
    assert (perf.motion, perf.motion_index) == ("TapBody", 0)


def test_performance_map_wins_over_motion_map() -> None:
    r = PerformanceResolver(
        motion_map={"greet": "Idle"},  # 优先级更低
        performance_map={"greet": ", TapBody#3"},  # 优先级更高
    )
    assert (r.resolve("greet").motion, r.resolve("greet").motion_index) == ("TapBody", 3)


def test_custom_performance_name_enters_library() -> None:
    """自定表演名必须进表演库，否则调试台 / Alt+G 试演不到。"""
    r = PerformanceResolver(performance_map={"wave": "expression6"})
    assert "wave" in r.names()
    assert len(r.names()) == 14  # 13 内置 + 1 自定
    perf = r.resolve("wave")
    assert perf.expression == "expression6"
    assert perf.motion == "" and perf.motion_slot == ""  # 自定名没有语义槽位
    assert "wave" in [p.name for p in r.library()]


# ── AvatarRuntime.perform ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_perform_sends_expression_and_motion() -> None:
    rt, bc = _rt()
    ok = await rt.perform("s1", "celebrate")
    assert ok is True
    assert len(bc.sent) == 1
    msg = bc.sent[0]
    assert msg["type"] == "avatar:intent"
    assert msg["expression"] == "expression4"
    # S53：语义槽位随载荷下发；不写死具体动作组
    assert msg["expression_slot"] == "playful"
    assert msg["motion_slot"] == "celebrate"
    assert "motion" not in msg
    assert msg["performance"] == "celebrate"
    assert msg["priority"] == int(AvatarPriority.ACTION)
    assert msg["duration_ms"] > 0


@pytest.mark.asyncio
async def test_perform_unknown_name_still_sends_expression() -> None:
    rt, bc = _rt()
    ok = await rt.perform("s1", "excited")  # 未知表演名 → 按情绪解析
    assert ok is True
    assert bc.sent[0]["expression"] == "expression4"


@pytest.mark.asyncio
async def test_action_expires_then_emotion_recovers() -> None:
    """护栏：一次性表演（ACTION）到期后必须允许情绪（EMOTION）回落。

    修复前 ACTION 会永久占用 ``_current``，导致此后所有情绪表情被静默拦截。
    """
    rt, bc = _rt()
    await rt.perform("s1", "celebrate")
    # 表演进行中：情绪变化被更高优先级拦截
    assert await rt.push_emotion("s1", "happy") is False
    # 拨回生效时刻 → 视为已到期
    rt._current_at["s1"] = time.monotonic() - 10
    assert await rt.push_emotion("s1", "happy") is True
    assert bc.sent[-1]["expression"] == "expression2"
    assert bc.sent[-1]["priority"] == int(AvatarPriority.EMOTION)


@pytest.mark.asyncio
async def test_push_action_is_one_shot() -> None:
    rt, bc = _rt()
    await rt.push_action("s1", "TapBody", 3)
    assert bc.sent[0]["motion"] == "TapBody"
    assert bc.sent[0]["motion_index"] == 3
    assert bc.sent[0]["duration_ms"] > 0  # 一次性（可到期）
    rt._current_at["s1"] = time.monotonic() - 10
    assert await rt.push_emotion("s1", "happy") is True


@pytest.mark.asyncio
async def test_update_motion_map_hot_reload() -> None:
    rt, bc = _rt()
    rt.update_motion_map({"celebrate": "Idle"})
    await rt.perform("s1", "celebrate")
    assert bc.sent[0]["motion"] == "Idle"


@pytest.mark.asyncio
async def test_performance_map_at_construction_and_hot_reload() -> None:
    """performance_map 既能装配时注入，也能人设热重载替换（调试台保存即生效）。"""
    rt, bc = _rt(performance_map={"celebrate": "expression7, TapBody#4"})
    await rt.perform("s1", "celebrate")
    assert bc.sent[0]["expression"] == "expression7"
    assert (bc.sent[0]["motion"], bc.sent[0]["motion_index"]) == ("TapBody", 4)

    rt.update_performance_map({"celebrate": "expression6"})  # 只改表情
    await rt.perform("s1", "celebrate")
    assert bc.sent[-1]["expression"] == "expression6"


@pytest.mark.asyncio
async def test_custom_performance_is_performable() -> None:
    """自定表演名要能真的演出来（能被 perform 解析成表情 + 动作）。"""
    rt, bc = _rt(performance_map={"wave": "expression2, TapBody#7"})
    assert await rt.perform("s1", "wave") is True
    assert bc.sent[0]["expression"] == "expression2"
    assert (bc.sent[0]["motion"], bc.sent[0]["motion_index"]) == ("TapBody", 7)


def test_state_and_performances_view() -> None:
    rt, _ = _rt()
    names = [p["name"] for p in rt.performances()]
    assert "celebrate" in names
    st = rt.state()
    assert st["performances"] >= 9
    assert st["performed"] == 0


# ── 工具 ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_avatar_perform_tool_ok_and_pending() -> None:
    from yuiro.tools.avatar_tool import AvatarPerformTool

    rt, bc = _rt()
    tool = AvatarPerformTool(avatar_getter=lambda: rt)
    assert tool.name == "avatar_perform"
    assert tool.approval_required is False
    assert "celebrate" in tool.schema()["function"]["parameters"]["properties"]["performance"]["enum"]

    # task_id 实参 = session_id（AgentLoop 约定）
    out = json.loads(await tool.run({"performance": "celebrate"}, "sess-9"))
    assert out["status"] == "ok"
    assert bc.sent[0]["source"] == "agent"

    pending = AvatarPerformTool(avatar_getter=None)
    out2 = json.loads(await pending.run({"performance": "celebrate"}, "s"))
    assert out2["status"] == "pending"


def test_avatar_perform_tool_exposes_custom_performance_names() -> None:
    """自定表演名要进工具的 enum，否则"DIY 出来的表演"LLM 点不到。"""
    from yuiro.tools.avatar_tool import AvatarPerformTool

    rt, _ = _rt(performance_map={"shy": "expression6", "wave": ", TapBody#7"})
    tool = AvatarPerformTool(avatar_getter=lambda: rt)
    enum = tool.schema()["function"]["parameters"]["properties"]["performance"]["enum"]
    assert "shy" in enum
    assert "wave" in enum
    assert "celebrate" in enum  # 内置名不丢


# ── 事件驱动（S18 修复的第二个真问题）────────────────────────────────────
@pytest.mark.asyncio
async def test_task_completed_event_carries_session_id() -> None:
    """护栏：TaskRuntime 事件此前因缺 session_id 被 except 静默吞掉，从未发布。"""
    from yuiro.runtime import EventBus
    from yuiro.task import TaskRuntime

    bus = EventBus()
    seen: list = []

    async def handler(event) -> None:
        seen.append(event)

    bus.subscribe("task.completed", handler)

    with tempfile.TemporaryDirectory() as tmp:
        rt = TaskRuntime(store_dir=tmp, events=bus)
        task = await rt.create("整理下载文件夹", ["列清单"], session_id="sess-1")
        await rt.complete(task.id, "搞定了")

    assert len(seen) == 1
    assert seen[0].type == "task.completed"
    assert seen[0].session_id == "sess-1"
    assert seen[0].payload["task_id"] == task.id


@pytest.mark.asyncio
async def test_task_completed_triggers_celebrate() -> None:
    """端到端：task.completed → avatar.perform("celebrate")（事件驱动，非 if 判断）。"""
    from yuiro.runtime import EventBus
    from yuiro.task import TaskRuntime

    rt, bc = _rt()
    bus = EventBus()

    async def on_completed(event) -> None:
        await rt.perform(event.session_id, "celebrate", source="system")

    bus.subscribe("task.completed", on_completed)

    with tempfile.TemporaryDirectory() as tmp:
        tasks = TaskRuntime(store_dir=tmp, events=bus)
        task = await tasks.create("写报告", ["拟提纲"], session_id="sess-2")
        await tasks.complete(task.id)

    assert len(bc.sent) == 1
    assert bc.sent[0]["expression"] == "expression4"
    assert bc.sent[0]["motion_slot"] == "celebrate"
