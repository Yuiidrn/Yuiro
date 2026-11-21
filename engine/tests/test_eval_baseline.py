"""S30 测试：人格基线（PB0）——场景集 / 规则判定 / 汇总 / 跑批。

两条关键护栏：
1. **评测逻辑可离线验证**（不依赖 LLM）—— 否则"用坏了的尺子量身高"；
2. **场景集本身的质量**（id 唯一、类别合法、expect 可判定）—— 数据错了，报告再漂亮也没意义。
"""
from __future__ import annotations

import asyncio

import pytest

from yuiro.eval import (
    Scenario,
    evaluate_reply,
    judge_reply,
    load_scenarios,
    prompt_hash,
    run_baseline,
    summarize,
)
from yuiro.eval.baseline import CATEGORIES


def _sc(expect: dict, category: str = "chat") -> Scenario:
    return Scenario(id="t-1", category=category, input="测试", expect=expect)


# ── 场景集数据质量 ────────────────────────────────────────────────────────
def test_scenario_set_is_wellformed() -> None:
    items = load_scenarios()
    assert len(items) >= 20, "起步集至少 20 条"
    ids = [s.id for s in items]
    assert len(ids) == len(set(ids)), "场景 id 必须唯一"
    for s in items:
        assert s.input.strip(), f"{s.id} 缺输入"
        assert s.category in CATEGORIES, f"{s.id} 类别非法：{s.category}"
        assert isinstance(s.expect, dict) and s.expect, f"{s.id} 缺可判定约束"


def test_scenario_set_covers_categories() -> None:
    cats = {s.category for s in load_scenarios()}
    # spec 的十类里，本期至少覆盖 8 类（其余靠扩充）
    assert len(cats & set(CATEGORIES)) >= 8


# ── 规则判定 ──────────────────────────────────────────────────────────────
def test_judge_passes_on_good_reply() -> None:
    sc = _sc({"min_length": 2, "max_length": 50, "must_include_any": ["你好"], "no_tool": True})
    assert judge_reply(sc, "你好呀，我在这儿。") == []


def test_judge_rejects_empty_and_too_short() -> None:
    assert judge_reply(_sc({}), "") != []
    assert any("过短" in r for r in judge_reply(_sc({"min_length": 10}), "嗯"))


def test_judge_rejects_too_long() -> None:
    reasons = judge_reply(_sc({"max_length": 5}), "这是一句很长很长的回复内容")
    assert any("过长" in r for r in reasons)


def test_judge_requires_expected_phrase_or_taboo() -> None:
    sc = _sc({"must_include_any": ["是啊", "确实"]})
    assert judge_reply(sc, "别的说法") != []
    taboo = _sc({"must_not_include": ["哈哈"]})
    assert any("禁忌" in r for r in judge_reply(taboo, "哈哈，太好了"))


def test_judge_tool_requirements() -> None:
    want = _sc({"should_call_tool": "app_open"}, category="tool")
    assert judge_reply(want, "好", []) != []
    assert judge_reply(want, "好", ["app_open"]) == []
    forbidden = _sc({"no_tool": True}, category="chat")
    assert judge_reply(forbidden, "嗯", ["app_open"]) != []


def test_judge_tool_satisfies_empty_reply() -> None:
    """调了工具但没说话，不算"回复为空"（工具已产生动作）。"""
    sc = _sc({"should_call_tool": "app_open"}, category="tool")
    assert judge_reply(sc, "", ["app_open"]) == []


# ── 汇总与指纹 ────────────────────────────────────────────────────────────
def test_prompt_hash_tracks_changes() -> None:
    a = prompt_hash("sys", "persona")
    assert a == prompt_hash("sys", "persona")
    assert a != prompt_hash("sys", "persona v2")


def test_evaluate_and_summarize() -> None:
    ok = evaluate_reply(_sc({"min_length": 1}), "好的")
    bad = evaluate_reply(_sc({"min_length": 100}), "短", )
    report = summarize([ok, bad], model="m1", prompt_fingerprint="abc")
    assert report["total"] == 2
    assert report["passed"] == 1
    assert report["pass_rate"] == 0.5
    assert report["by_category"]["chat"]["total"] == 2
    assert len(report["failures"]) == 1
    assert report["failures"][0]["id"] == "t-1"


# ── 跑批（注入 responder，可离线）─────────────────────────────────────────
@pytest.mark.asyncio
async def test_run_baseline_offline_all_pass() -> None:
    scenarios = [
        Scenario(id="a", category="chat", input="你好", expect={"min_length": 1}),
        Scenario(id="b", category="comfort", input="难受", expect={"min_length": 1}),
    ]

    async def good(text: str) -> str:
        return f"关于「{text}」我这样说"

    report = await run_baseline(good, scenarios=scenarios, model="fake")
    assert report["passed"] == 2
    assert report["model"] == "fake"


@pytest.mark.asyncio
async def test_run_baseline_skip_categories() -> None:
    scenarios = [
        Scenario(id="a", category="chat", input="你好", expect={"min_length": 1}),
        Scenario(id="b", category="tool", input="打开记事本", expect={"should_call_tool": "app_open"}),
    ]

    async def good(text: str) -> str:
        return f"回复 {text}"

    report = await run_baseline(good, scenarios=scenarios, skip_categories=("tool",))
    assert report["total"] == 1  # 工具类被跳过（避免真实执行系统操作）
    assert report["passed"] == 1


@pytest.mark.asyncio
async def test_run_baseline_tool_calls_from_tuple() -> None:
    scenarios = [
        Scenario(id="t", category="tool", input="打开记事本", expect={"should_call_tool": "app_open"})
    ]

    async def with_tools(text: str):
        del text
        return "好的，打开了", ["app_open"]

    report = await run_baseline(with_tools, scenarios=scenarios)
    assert report["passed"] == 1


@pytest.mark.asyncio
async def test_run_baseline_responder_error_is_isolated() -> None:
    scenarios = [
        Scenario(id="a", category="chat", input="你好", expect={"min_length": 1}),
        Scenario(id="b", category="chat", input="在吗", expect={"min_length": 1}),
    ]

    calls = {"n": 0}

    async def flaky(text: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return "正常回复"

    report = await run_baseline(flaky, scenarios=scenarios)
    assert report["total"] == 2  # 单场景异常不中断整批
    assert report["failed"] == 1
    assert report["passed"] == 1


@pytest.mark.asyncio
async def test_run_baseline_limit_and_callback() -> None:
    scenarios = [
        Scenario(id=f"s{i}", category="chat", input=f"输入{i}", expect={"min_length": 1})
        for i in range(5)
    ]
    seen: list[str] = []

    async def good(text: str) -> str:
        return f"回复 {text}"

    report = await run_baseline(good, scenarios=scenarios, limit=2, on_result=lambda r: seen.append(r.scenario.id))
    assert report["total"] == 2
    assert seen == ["s0", "s1"]


def test_cli_list_mode_smoke(capsys) -> None:
    """CLI 的离线链路（--list 不需要 LLM）。"""
    import sys

    from yuiro.eval.__main__ import main

    argv = sys.argv
    try:
        sys.argv = ["yuiro.eval", "--list"]
        code = main()
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert code == 0
    assert "场景集" in out


def test_run_baseline_is_awaitable() -> None:
    """最小契约检查：run_baseline 是 async 函数（供 API/线程安全调用）。"""
    assert asyncio.iscoroutinefunction(run_baseline)
