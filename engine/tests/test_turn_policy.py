"""S25 测试：TurnPolicy（回合策略逐字抽离的护栏）。

抽离自 ``AgentLoop.send`` 的实测结论（**必须逐条保住**）：

1. 成功去重：同一 ``(tool, args)`` 成功后不再执行；
2. 失败限流：连续失败达阈值后跳过，且 **skipped 不清失败计数**（否则永远达不阈值）；
3. 询问去重：同一调用已抛出 need_choice/pending 后，同键重调直接跳过
   （防"用户还没回答，模型拿旧参数重调"空转，实测"确认点歌死循环"）；
4. 无进展早停：整轮全 ``skipped``/``done`` → 判为无进展。
"""
from __future__ import annotations

import json

from yuiro.agent.turn_policy import TurnPolicy


# ── 键 ────────────────────────────────────────────────────────────────────
def test_key_for_uses_name_or_app() -> None:
    assert TurnPolicy.key_for("app_open", {"name": "网易云音乐"}) == "app_open:网易云音乐"
    assert TurnPolicy.key_for("app_focus", {"app": "记事本"}) == "app_focus:记事本"
    # 其余参数必须进键：不同 keyword/path/action 不得互相误去重
    assert (
        TurnPolicy.key_for("netease_play", {"keyword": "A"})
        != TurnPolicy.key_for("netease_play", {"keyword": "B"})
    )
    assert (
        TurnPolicy.key_for("file_write", {"path": "a", "content": "1"})
        != TurnPolicy.key_for("file_write", {"path": "b", "content": "1"})
    )
    assert TurnPolicy.key_for("task_list", None) == "task_list:"


# ── 成功去重 ──────────────────────────────────────────────────────────────
def test_done_prevents_repeat() -> None:
    turn = TurnPolicy()
    assert turn.skip_reason("app_open:网易云音乐") is None
    turn.note_result("app_open:网易云音乐", "ok")
    assert turn.skip_reason("app_open:网易云音乐") == "done"
    # 不同参数名不受影响
    assert turn.skip_reason("app_open:记事本") is None
    assert turn.done_count == 1


def test_done_placeholder_is_registered_too() -> None:
    """done 占位（我们去重时回给 LLM 的 status）同样登记，避免二次重复。"""
    turn = TurnPolicy()
    turn.note_result("x:", "done")
    assert turn.skip_reason("x:") == "done"


# ── 失败限流 ──────────────────────────────────────────────────────────────
def test_fail_limit_skips_after_threshold() -> None:
    turn = TurnPolicy()
    turn.note_result("app_focus:云", "error")
    assert turn.skip_reason("app_focus:云") is None  # 第 1 次失败仍允许（可能换个时机）
    turn.note_result("app_focus:云", "error")
    assert turn.skip_reason("app_focus:云") == "skipped"  # 达阈值 → 跳过


def test_skipped_does_not_clear_fail_count() -> None:
    """关键护栏：skipped 若清除计数，会导致无限重试（实测 app_focus 反复聚焦）。"""
    turn = TurnPolicy()
    turn.note_result("k:", "error")
    turn.note_result("k:", "error")
    assert turn.skip_reason("k:") == "skipped"
    turn.note_result("k:", "skipped")  # 跳过的轮次不清计数
    assert turn.skip_reason("k:") == "skipped"


def test_success_clears_fail_count() -> None:
    """成功一次会清除该键的失败计数（同时该键进入成功去重集合）。"""
    turn = TurnPolicy()
    turn.note_result("k:", "error")
    assert turn._fail.get("k:") == 1
    turn.note_result("k:", "ok")
    assert turn._fail.get("k:") is None  # 计数已清零
    assert turn.skip_reason("k:") == "done"  # 且因成功而进入去重


# ── 询问去重（need_choice/pending）─────────────────────────────────────────
def test_asked_dedupes_repeat_need_choice() -> None:
    """同一调用抛出 need_choice 后，同键重调应跳过（防"确认点歌死循环"）。"""
    turn = TurnPolicy()
    key = TurnPolicy.key_for("netease_play", {"keyword": "廖俊涛 谁"})
    assert turn.skip_reason(key) is None
    turn.note_result(key, "need_choice")
    assert turn.skip_reason(key) == "asked"  # 用户还没回答，重调直接跳过
    asked = json.loads(TurnPolicy.skip_result("asked"))
    assert asked["status"] == "skipped"
    assert "重复" in asked["note"]
    # S48 修复：占位 note 必须引导模型"回看真实结果、不要臆造成功"
    assert "不要臆造成功" in asked["note"]
    assert TurnPolicy.skip_trace("asked") == "已询问待确认"


def test_asked_does_not_leak_across_keys() -> None:
    turn = TurnPolicy()
    turn.note_result(TurnPolicy.key_for("netease_play", {"keyword": "A"}), "need_choice")
    # 换了参数的调用不受影响（同键才去重）
    assert turn.skip_reason(TurnPolicy.key_for("netease_play", {"keyword": "B"})) is None
    # need_choice 算实质进展（真的向用户抛了问题）
    assert turn.progress_made is True


# ── 无进展早停 ────────────────────────────────────────────────────────────
def test_progress_semantics() -> None:
    turn = TurnPolicy()

    turn.begin_round()
    turn.note_result("a:", "ok")
    assert turn.progress_made is True  # 实质推进

    turn.begin_round()
    turn.note_result("a:", "done")  # 重复 → 不算推进
    assert turn.progress_made is False

    turn.begin_round()
    turn.note_result("b:", "skipped")  # 限流 → 不算推进
    assert turn.progress_made is False

    turn.begin_round()
    turn.note_result("c:", "error")  # 失败也算"真实尝试过"
    assert turn.progress_made is True

    turn.begin_round()
    turn.note_result("d:", "text")  # 纯文本返回算推进（防"空转被误判"）
    assert turn.progress_made is True


def test_begin_round_resets_progress() -> None:
    turn = TurnPolicy()
    turn.note_result("a:", "ok")
    assert turn.progress_made is True
    turn.begin_round()
    assert turn.progress_made is False


# ── 状态摘要触发 ──────────────────────────────────────────────────────────
def test_note_result_reports_state_update_need() -> None:
    """返回 True 表示调用方需要更新状态摘要（与原逻辑逐字一致）。"""
    turn = TurnPolicy()
    assert turn.note_result("a:", "ok") is True
    assert turn.note_result("b:", "text") is True
    assert turn.note_result("c:", "opened") is True
    assert turn.note_result("d:", "done") is False  # 去重占位不算新成功
    assert turn.note_result("e:", "skipped") is False
    assert turn.note_result("f:", "error") is False
    assert turn.note_result("g:", "?") is False


# ── 跳过结果文案 ──────────────────────────────────────────────────────────
def test_skip_result_payloads() -> None:
    done = json.loads(TurnPolicy.skip_result("done"))
    assert done["status"] == "done"
    # S48 修复：done 占位不再说"已完成"（那会被收尾总结误解成"已成功"而撒谎）
    assert "已跳过" in done["note"]
    assert "臆造成功" in done["note"]

    skipped = json.loads(TurnPolicy.skip_result("skipped"))
    assert skipped["status"] == "skipped"
    assert "连续失败" in skipped["note"]

    assert TurnPolicy.skip_trace("done") == "已去重"
    assert TurnPolicy.skip_trace("skipped") == "限流"


def test_state_view() -> None:
    turn = TurnPolicy()
    turn.note_result("a:", "ok")
    turn.note_result("b:", "error")
    turn.note_result("b:", "error")
    state = turn.state()
    assert state["done"] == 1
    assert state["failed"] == 1
    assert state["progress"] is True
