"""S32 测试：LLM-as-judge（主观维度）+ 场景集扩充。

护栏重点：
1. **解析必须严格**：非法/越界/缺维度的评分一律跳过（不猜、不用 0 分污染平均）；
2. **评审失败不影响跑批**（评测器本身必须稳）；
3. **只对通过规则判定的场景做评审**（成本控制 —— 明显不合格的没必要花 token）。
"""
from __future__ import annotations

import pytest

from yuiro.eval import load_scenarios, run_baseline
from yuiro.eval.baseline import Scenario
from yuiro.eval.judge import (
    DIMENSIONS,
    JudgeScore,
    aggregate,
    build_judge_prompt,
    judge_reply,
    make_llm_judge,
    parse_judge_json,
)


# ── 场景集扩充（S32）──────────────────────────────────────────────────────
def test_scenario_set_expanded() -> None:
    items = load_scenarios()
    assert len(items) >= 60, "S32 起场景集应 ≥60 条"
    by_cat: dict[str, int] = {}
    for s in items:
        by_cat[s.category] = by_cat.get(s.category, 0) + 1
    # 十类每类至少 5 条（spec 目标是 100–300，继续扩充记入遗留）
    for cat, n in by_cat.items():
        assert n >= 5, f"类别 {cat} 只有 {n} 条"
    assert len(by_cat) >= 10


# ── 评审输出解析 ──────────────────────────────────────────────────────────
def test_parse_judge_json_standard() -> None:
    raw = (
        '{"persona":{"score":4,"reason":"有点味道"},'
        '"emotion":{"score":5,"reason":"很贴"},'
        '"naturalness":{"score":3,"reason":"略模板"},'
        '"conciseness":{"score":5,"reason":"干脆"}}'
    )
    parsed = parse_judge_json(raw)
    assert parsed["persona"] == (4, "有点味道")
    assert parsed["emotion"][0] == 5
    assert set(parsed) == set(DIMENSIONS)


def test_parse_judge_json_tolerates_markdown_and_partial() -> None:
    raw = '好的\n```json\n{"persona":{"score":3,"reason":"x"}}\n```'
    parsed = parse_judge_json(raw)
    assert parsed == {"persona": (3, "x")}  # 缺的维度就是缺，不补 0


def test_parse_judge_json_rejects_invalid() -> None:
    assert parse_judge_json("") == {}
    assert parse_judge_json("我不会打分") == {}
    assert parse_judge_json('{"persona":{"score":9}}') == {}  # 越界
    assert parse_judge_json('{"persona":{"score":"高"}}') == {}  # 非数字
    assert parse_judge_json('{"persona":"很好"}') == {}  # 结构不对


def test_build_judge_prompt_has_anchors() -> None:
    prompt = build_judge_prompt("你好", "你好呀", "表面乖巧、实则腹黑毒舌")
    assert "表面乖巧" in prompt
    assert "1-5" in prompt  # 评分锚点
    assert "persona" in prompt and "conciseness" in prompt


# ── 单次评审 ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_judge_reply_ok() -> None:
    async def ask(prompt: str) -> str:
        assert "用户说：你好" in prompt
        return '{"persona":{"score":4,"reason":"还行"}}'

    score = await judge_reply(ask, "chat-01", "你好", "你好呀")
    assert score.ok is True
    assert score.scores == {"persona": 4}
    assert score.reasons["persona"] == "还行"


@pytest.mark.asyncio
async def test_judge_reply_call_failure_is_isolated() -> None:
    async def bad_ask(prompt: str) -> str:
        raise RuntimeError("llm down")

    score = await judge_reply(bad_ask, "chat-01", "你好", "你好呀")
    assert score.ok is False
    assert "调用失败" in score.note


@pytest.mark.asyncio
async def test_judge_reply_unparseable_output() -> None:
    async def ask(prompt: str) -> str:
        return "我觉得挺好的，大概 4 分吧"

    score = await judge_reply(ask, "chat-01", "你好", "你好呀")
    assert score.ok is False
    assert "解析" in score.note


@pytest.mark.asyncio
async def test_make_llm_judge_passes_persona_hint() -> None:
    seen: list[str] = []

    async def ask(prompt: str) -> str:
        seen.append(prompt)
        return '{"persona":{"score":5,"reason":"像"}}'

    judge = make_llm_judge(ask, persona_hint="腹黑毒舌但心软")
    sc = Scenario(id="s1", category="chat", input="在吗", expect={})
    score = await judge(sc, "在的")
    assert score.ok is True
    assert "腹黑毒舌但心软" in seen[0]


# ── 聚合 ──────────────────────────────────────────────────────────────────
def _score(sid: str, **dims: int) -> JudgeScore:
    return JudgeScore(
        scenario_id=sid,
        scores=dict(dims),
        reasons={d: "理由" for d in dims},
        ok=True,
    )


def test_aggregate_dimensions_and_overall() -> None:
    result = aggregate(
        [
            _score("a", persona=4, emotion=5, naturalness=3, conciseness=5),
            _score("b", persona=2, emotion=3, naturalness=3, conciseness=5),
        ]
    )
    assert result["judged"] == 2
    assert result["dimensions"]["persona"] == 3.0
    assert result["dimensions"]["emotion"] == 4.0
    assert result["dimensions"]["conciseness"] == 5.0
    assert result["overall"] == 3.75


def test_aggregate_partial_dimensions() -> None:
    """某维度只在部分场景出现时，只按出现的算（不补 0）。"""
    result = aggregate([_score("a", persona=4), _score("b", emotion=2)])
    assert result["dimensions"] == {"persona": 4.0, "emotion": 2.0}
    assert result["overall"] == 3.0


def test_aggregate_worst_items() -> None:
    result = aggregate(
        [
            _score("a", persona=1, emotion=2),
            _score("b", persona=5, emotion=5),
        ]
    )
    worst = result["worst"]
    assert worst[0]["scenario_id"] == "a"
    assert worst[0]["dimension"] == "persona"
    assert worst[0]["score"] == 1
    assert len(worst) == 2  # persona=1 与 emotion=2


def test_aggregate_ignores_failed_scores() -> None:
    result = aggregate(
        [
            _score("a", persona=4),
            JudgeScore(scenario_id="b", ok=False, note="调用失败"),
        ]
    )
    assert result["judged"] == 1
    assert result["skipped"] == 1
    assert result["dimensions"]["persona"] == 4.0


def test_aggregate_when_all_failed() -> None:
    result = aggregate([JudgeScore(scenario_id="a", ok=False)])
    assert result == {
        "judged": 0,
        "skipped": 1,
        "dimensions": {},
        "overall": 0.0,
        "worst": [],
    }


# ── runner 集成 ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_judge_only_called_for_passed_scenarios() -> None:
    """成本控制：规则上就不合格的场景不做评审。"""
    scenarios = [
        Scenario(id="pass", category="chat", input="a", expect={"min_length": 1}),
        Scenario(id="fail", category="chat", input="b", expect={"min_length": 100}),
    ]
    called: list[str] = []

    async def responder(text: str) -> str:
        return "短回复"

    async def judge(sc, reply: str) -> JudgeScore:
        called.append(sc.id)
        return JudgeScore(scenario_id=sc.id, scores={"persona": 4}, ok=True)

    report = await run_baseline(responder, scenarios=scenarios, judge=judge)
    assert called == ["pass"]
    assert report["judge"]["judged"] == 1
    assert report["judge"]["dimensions"]["persona"] == 4.0


@pytest.mark.asyncio
async def test_without_judge_report_has_no_judge_key() -> None:
    async def responder(text: str) -> str:
        return "回复"

    report = await run_baseline(
        responder,
        scenarios=[Scenario(id="a", category="chat", input="x", expect={"min_length": 1})],
    )
    assert "judge" not in report


@pytest.mark.asyncio
async def test_judge_exception_does_not_break_batch() -> None:
    async def responder(text: str) -> str:
        return "回复"

    async def bad_judge(sc, reply: str):
        raise RuntimeError("judge boom")

    report = await run_baseline(
        responder,
        scenarios=[Scenario(id="a", category="chat", input="x", expect={"min_length": 1})],
        judge=bad_judge,
    )
    assert report["passed"] == 1  # 规则结果不受影响
    assert report["judge"]["judged"] == 0
