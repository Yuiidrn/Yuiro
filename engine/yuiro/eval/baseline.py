"""人格基线：场景集 + 规则判定 + 汇总（S30 / PB0）。

三条设计原则：

1. **可离线测试**：判定逻辑（关键词 / 长度 / 工具调用）是纯函数，不依赖 LLM
   —— 评测器本身有单测，才不会"用坏了的尺子量身高"；
2. **可对比**：报告带 ``model`` 与 ``prompt_hash`` —— 换模型或改 Prompt 后，
   两份报告能直接对比（这是"人格有没有变好"的唯一客观抓手）；
3. **只测可判定的**：主观维度（语气够不够毒舌）不在规则里假装修得出来，
   留给后续 LLM-judge。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

# 默认场景集（随包分发；JSONL：一行一个场景）
DEFAULT_SCENARIOS = Path(__file__).parent / "scenarios" / "personality_baseline.jsonl"

# 场景类别（spec 列的十类）
CATEGORIES = (
    "chat",  # 日常聊天
    "comfort",  # 安慰
    "sass",  # 吐槽 / 毒舌
    "argue",  # 争论
    "refuse",  # 拒绝
    "surprise",  # 惊讶
    "tool",  # 工具调用
    "task_fail",  # 任务失败
    "task_done",  # 任务成功
    "memory",  # 长期记忆
)


@dataclass
class Scenario:
    """一个固定场景：输入 + **可判定**的期望。"""

    id: str
    category: str
    input: str
    expect: dict = field(default_factory=dict)
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Scenario:
        return cls(
            id=str(d.get("id", "")),
            category=str(d.get("category", "chat")),
            input=str(d.get("input", "")),
            expect=dict(d.get("expect", {}) or {}),
            note=str(d.get("note", "")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "input": self.input,
            "expect": self.expect,
            "note": self.note,
        }


@dataclass
class ScenarioResult:
    scenario: Scenario
    reply: str
    tool_calls: list[str] = field(default_factory=list)
    passed: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.scenario.id,
            "category": self.scenario.category,
            "input": self.scenario.input,
            "reply": self.reply,
            "tool_calls": self.tool_calls,
            "passed": self.passed,
            "reasons": self.reasons,
        }


# ---- 场景集 ---------------------------------------------------------------
def load_scenarios(path: str | Path | None = None) -> list[Scenario]:
    """加载场景集（JSONL；``#`` 开头为注释，坏行跳过）。"""
    p = Path(path) if path else DEFAULT_SCENARIOS
    items: list[Scenario] = []
    if not p.is_file():
        return items
    try:
        raw = p.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — 读不到就当作空集
        return items
    for line in raw.splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            items.append(Scenario.from_dict(json.loads(text)))
        except Exception:  # noqa: BLE001, S112 — 单行损坏不影响其余场景
            continue
    return items


def prompt_hash(*texts: str) -> str:
    """Prompt 指纹：Prompt 一变，指纹就变（报告据此判断"是不是同一个被测对象"）。"""
    h = hashlib.sha256()
    for t in texts:
        h.update((t or "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:12]


# ---- 规则判定 -------------------------------------------------------------
def judge_reply(
    scenario: Scenario, reply: str, tool_calls: list[str] | None = None
) -> list[str]:
    """规则判定：返回失败原因列表（空 = 通过）。纯函数、可离线单测。

    支持的 ``expect`` 字段：

    ``must_not_empty`` / ``min_length`` / ``max_length`` /
    ``must_include_any``（任一命中即可，避免锁死具体措辞）/
    ``must_not_include``（禁忌表达，如安慰场景不该"哈哈"）/
    ``should_call_tool`` / ``no_tool``。
    """
    reasons: list[str] = []
    exp = scenario.expect or {}
    text = (reply or "").strip()
    calls = [str(c) for c in (tool_calls or [])]

    if exp.get("must_not_empty", True) and not text and not calls:
        reasons.append("回复为空")

    min_len = int(exp.get("min_length", 0) or 0)
    if min_len and len(text) < min_len:
        reasons.append(f"过短（{len(text)} < {min_len}）")

    max_len = int(exp.get("max_length", 0) or 0)
    if max_len and len(text) > max_len:
        reasons.append(f"过长（{len(text)} > {max_len}）")

    any_of = [str(w) for w in (exp.get("must_include_any") or []) if str(w)]
    if any_of and not any(w in text for w in any_of):
        reasons.append("缺少预期表达（任一：" + "/".join(any_of) + "）")

    for word in exp.get("must_not_include") or []:
        if str(word) and str(word) in text:
            reasons.append(f"出现禁忌表达「{word}」")

    want_tool = str(exp.get("should_call_tool", "") or "")
    if want_tool and want_tool not in calls:
        reasons.append(f"未调用预期工具 {want_tool}")

    if exp.get("no_tool") and calls:
        reasons.append("不该调用工具却调用了 " + "/".join(calls))

    return reasons


def evaluate_reply(
    scenario: Scenario, reply: str, tool_calls: list[str] | None = None
) -> ScenarioResult:
    """对一次回复评分（判定 + 包装结果）。"""
    reasons = judge_reply(scenario, reply, tool_calls)
    return ScenarioResult(
        scenario=scenario,
        reply=reply,
        tool_calls=[str(c) for c in (tool_calls or [])],
        passed=not reasons,
        reasons=reasons,
    )


# ---- 汇总 ----------------------------------------------------------------
def summarize(
    results: list[ScenarioResult], *, model: str = "", prompt_fingerprint: str = ""
) -> dict:
    """汇总成一份可归档、可对比的报告。"""
    by_cat: dict[str, dict] = {}
    for r in results:
        bucket = by_cat.setdefault(r.scenario.category, {"total": 0, "passed": 0})
        bucket["total"] += 1
        if r.passed:
            bucket["passed"] += 1
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    return {
        "model": model,
        "prompt_hash": prompt_fingerprint,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "by_category": {
            name: {
                **bucket,
                "pass_rate": round(bucket["passed"] / bucket["total"], 3)
                if bucket["total"]
                else 0.0,
            }
            for name, bucket in sorted(by_cat.items())
        },
        "failures": [r.to_dict() for r in results if not r.passed],
    }
