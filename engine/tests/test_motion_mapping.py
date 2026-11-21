"""S34 测试：动作索引与表演时长（修"动作不稳定"）。

根因：表演包的 ``motion_index=None`` → 前端 ``startRandomMotion`` 随机播该组任意动作，
而 TapBody 里既有 8.6s 的大幅动作、也有 1.1s 几乎不动的 micoff ——
观感即"同一表演有时活、有时像没动"。
"""
from __future__ import annotations

from yuiro.avatar.performance import (
    DEFAULT_PERFORMANCE_MS,
    PerformanceResolver,
    motion_duration_ms,
    parse_motion_spec,
)


# ── 配置值解析 ───────────────────────────────────────────────────────────
def test_parse_motion_spec() -> None:
    assert parse_motion_spec("TapBody") == ("TapBody", None)  # 不带索引 = 随机
    assert parse_motion_spec("TapBody#7") == ("TapBody", 7)
    assert parse_motion_spec("TapBody:3") == ("TapBody", 3)  # 冒号也支持
    assert parse_motion_spec("") == ("", None)
    assert parse_motion_spec("  TapBody#0  ") == ("TapBody", 0)
    # 分隔符后不是数字 → 整串当组名（不抛错）
    assert parse_motion_spec("TapBody#abc") == ("TapBody#abc", None)


def test_motion_duration_lookup() -> None:
    assert motion_duration_ms("TapBody", 5) == 5370
    assert motion_duration_ms("TapBody", 12) == 4700  # singing = m01 副本
    assert motion_duration_ms("TapBody", None) == 0  # 随机无时长
    assert motion_duration_ms("TapBody", 99) == 0  # 越界
    # S49：官方 Hiyori 的 Idle 组也登记了（Hiyori 档案把表演动作配在 Idle#N 上）
    assert motion_duration_ms("Idle", 4) == 5370  # = m06，与 TapBody#5 同一个文件
    assert motion_duration_ms("idle", 8) == 4170  # 组名大小写不敏感
    assert motion_duration_ms("Idle", 99) == 0  # 越界
    assert motion_duration_ms("Flick3", 0) == 0  # 真正未登记的组 → 回落基准时长
    assert motion_duration_ms("", 0) == 0


# ── 内置表演包：只声明语义槽位，不写死模型私有坐标 ───────────────────────
def test_action_performances_use_semantic_slots() -> None:
    """动作型表演声明 ``motion_slot``；没有档案时不下发具体组/索引。

    S53 起内置包不再写 ``TapBody#5``：那个坐标只对肥牛成立，换到只有单一
    ``Motion`` 组的模型（Hotaru）会播到无关动作。具体资源由壳层按模型清单解析。
    """
    r = PerformanceResolver()
    for name in ("celebrate", "greet", "surprise", "comfort", "thinking", "sing"):
        perf = r.resolve(name)
        assert perf.motion_slot, f"{name} 缺少语义动作槽位"
        assert perf.motion == "", f"{name} 不应写死具体动作组，实际 {perf.motion!r}"
        assert perf.motion_index is None


def test_motion_slots_resolve_to_concrete_motion() -> None:
    """档案里配了 ``motion_slots`` 时，槽位解析成具体动作，时长跟着动作走。"""
    r = PerformanceResolver(motion_slots={"celebrate": "Idle#4", "greet": "TapBody#7"})
    perf = r.resolve("celebrate")
    assert (perf.motion, perf.motion_index) == ("Idle", 4)
    assert perf.duration_ms == 5370 + 300  # Idle#4 = m06（5370ms）+ 余量
    assert r.resolve("greet").duration_ms == DEFAULT_PERFORMANCE_MS  # 2100ms < 基准
    # slot_motion 供工具活动联动使用
    assert r.slot_motion("celebrate") == ("Idle", 4)
    assert r.slot_motion("unknown") == ("", None)


def test_emotion_performances_stay_expression_only() -> None:
    """情绪类表演只演表情 —— 说话时一直大幅挥手太吵（有意设计）。"""
    r = PerformanceResolver()
    for name in ("happy", "sad", "excited", "thinking", "bored", "angry", "idle"):
        perf = r.resolve(name)
        assert perf.motion == "", f"{name} 不应配动作，实际 {perf.motion!r}"
        assert perf.duration_ms == DEFAULT_PERFORMANCE_MS


# ── 表演时长跟随动作真实时长 ─────────────────────────────────────────────
def test_duration_follows_motion_length() -> None:
    # 时长由「槽位解析出的具体动作」决定（没有具体动作时只能用基准）
    r = PerformanceResolver(motion_slots={
        "celebrate": "Idle#4",   # 5370ms
        "greet": "Idle#6",       # 2100ms
        "surprise": "Idle#8",    # 4170ms
    })
    assert r.resolve("celebrate").duration_ms == 5370 + 300
    assert r.resolve("greet").duration_ms == DEFAULT_PERFORMANCE_MS
    assert r.resolve("surprise").duration_ms == 4170 + 300
    # 未配置槽位的模型 → 基准时长（壳层会用 manifest 的真实时长覆盖）
    assert PerformanceResolver().resolve("celebrate").duration_ms == DEFAULT_PERFORMANCE_MS


# ── motion_map 覆盖（含索引）─────────────────────────────────────────────
def test_motion_map_override_with_index() -> None:
    r = PerformanceResolver(motion_map={"greet": "TapBody#9"})
    perf = r.resolve("greet")
    assert (perf.motion, perf.motion_index) == ("TapBody", 9)
    assert perf.duration_ms == 4170 + 300  # 时长跟着覆盖后的索引走


def test_motion_map_random_form_still_supported() -> None:
    """不带索引仍支持（随机），但时长退回基准（无从得知具体动作）。"""
    r = PerformanceResolver(motion_map={"greet": "TapBody"})
    perf = r.resolve("greet")
    assert (perf.motion, perf.motion_index) == ("TapBody", None)
    assert perf.duration_ms == DEFAULT_PERFORMANCE_MS


def test_motion_map_keyed_by_emotion_too() -> None:
    """键可用情绪名（如 excited），与表演名等价生效。"""
    r = PerformanceResolver(motion_map={"excited": "TapBody#4"})
    perf = r.resolve("celebrate")  # celebrate 的 emotion 就是 excited
    assert (perf.motion, perf.motion_index) == ("TapBody", 4)


def test_library_lists_all_with_resolved_fields() -> None:
    lib = PerformanceResolver().library()  # 返回 Performance 对象（非 dict）
    # 13 个内置：idle/happy/sad/excited/thinking/bored/angry/celebrate/comfort/
    #             greet/surprise/sing/shy
    assert len(lib) == 13
    greet = next(p for p in lib if p.name == "greet")
    assert greet.motion_slot == "greet"
    assert greet.expression_slot == "happy"
    assert greet.duration_ms == DEFAULT_PERFORMANCE_MS
