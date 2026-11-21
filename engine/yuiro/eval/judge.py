"""主观维度评分（S32）：LLM-as-judge。

**为什么需要**：规则判定只能抓"明显不对"（过长 / 禁忌表达 / 没调工具），
抓不住"**味道变了**"——而人格退化最典型的表现恰恰是味道。

四个维度（贴合 Yuiro 的人设与"桌面宠物"这一使用场景）：

| 维度 | 问什么 |
|---|---|
| ``persona`` | 像不像她（表面乖巧、实则腹黑毒舌、思维跳脱），而不是通用助手 |
| ``emotion`` | 情绪反应是否贴合场景（安慰时温柔、被夸时得意、被否定时有骨气） |
| ``naturalness`` | 像真人在说话，还是像客服 / FAQ 模板 |
| ``conciseness`` | 桌面场景下是否啰嗦（长回复是负担） |

三条工程约束：

1. **严格 JSON 契约**：解析失败即放弃该次评分（不猜、不计 0 分污染平均）；
2. **只评通过规则判定的场景**：连规则都过不了的回复没必要花 token；
3. **一次请求评完四维**（而非四次请求）——成本可控。
"""
from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from yuiro.logger import vlog

# 评分维度（顺序即展示顺序）
DIMENSIONS = ("persona", "emotion", "naturalness", "conciseness")
DIMENSION_LABELS = {
    "persona": "人格一致性",
    "emotion": "情绪贴合",
    "naturalness": "自然度",
    "conciseness": "简洁",
}

# 从 LLM 输出中提取 JSON 对象（宽松）
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

JUDGE_SYSTEM = "你是严格的评审，只输出 JSON，不解释、不客套。"

# 注入式 LLM 调用：async (prompt) -> str
Ask = Callable[[str], Awaitable[str]]


@dataclass
class JudgeScore:
    """单个场景的主观评分（一次请求覆盖四个维度）。"""

    scenario_id: str
    scores: dict[str, int] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    ok: bool = False  # 解析成功
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "scores": self.scores,
            "reasons": self.reasons,
            "ok": self.ok,
            "note": self.note,
        }


def build_judge_prompt(scenario_input: str, reply: str, persona_hint: str = "") -> str:
    """构造评审 prompt（含**评分锚点**——没有锚点的打分不可信）。"""
    persona = persona_hint.strip() or "（未提供人设摘要，按「桌面助手」通用标准评估）"
    return (
        "下面是这个桌宠助手的人设摘要：\n"
        f"{persona}\n\n"
        f"用户说：{scenario_input}\n"
        f"它回复：{reply}\n\n"
        "请按 4 个维度打分（**1-5 的整数**，5 最好）：\n"
        "- persona（人格一致性）：5=明显是「她」（表面乖巧、实则腹黑毒舌、思维跳脱）；"
        "3=普通助手但不出戏；1=完全像通用客服\n"
        "- emotion（情绪贴合）：5=情绪反应精准贴合场景（安慰时温柔、被夸时得意、被否定时有骨气）；"
        "3=基本合适但平淡；1=情绪错位（如安慰时说「哈哈」）\n"
        "- naturalness（自然度）：5=像真人随口说话；3=有点模板味；1=明显 FAQ / 客服腔\n"
        "- conciseness（简洁）：5=该短就短、不啰嗦；3=略长；1=长篇大论（桌面场景很烦）\n\n"
        "严格只输出 JSON，格式：\n"
        '{"persona":{"score":4,"reason":"一句话"},'
        '"emotion":{"score":4,"reason":"…"},'
        '"naturalness":{"score":3,"reason":"…"},'
        '"conciseness":{"score":5,"reason":"…"}}'
    )


def parse_judge_json(raw: str) -> dict[str, tuple[int, str]]:
    """解析评审输出 → ``{维度: (分数, 理由)}``；非法维度一律跳过（不猜）。"""
    text = (raw or "").strip()
    if not text:
        return {}
    match = _JSON_BLOCK.search(text)
    if match is None:
        return {}
    try:
        data = json.loads(match.group(0))
    except Exception:  # noqa: BLE001 — 非合法 JSON 放弃
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, tuple[int, str]] = {}
    for dim in DIMENSIONS:
        item = data.get(dim)
        if not isinstance(item, dict):
            continue
        try:
            score = int(item.get("score"))
        except Exception:  # noqa: BLE001, S112 — 分数非法则跳过该维度（不猜）
            continue
        if 1 <= score <= 5:
            out[dim] = (score, str(item.get("reason", ""))[:120])
    return out


async def judge_reply(
    ask: Ask,
    scenario_id: str,
    scenario_input: str,
    reply: str,
    *,
    persona_hint: str = "",
) -> JudgeScore:
    """对一次回复做主观评分（``ask`` 由调用方注入，便于测试与替换模型）。"""
    prompt = build_judge_prompt(scenario_input, reply, persona_hint)
    try:
        raw = await ask(prompt)
    except Exception as exc:  # noqa: BLE001 — 评审失败不影响跑批
        vlog("eval", f"[评审] {scenario_id} 调用失败：{exc}")
        return JudgeScore(scenario_id=scenario_id, ok=False, note=f"调用失败：{exc}")
    parsed = parse_judge_json(str(raw))
    if not parsed:
        vlog("eval", f"[评审] {scenario_id} 输出无法解析（已跳过）")
        return JudgeScore(scenario_id=scenario_id, ok=False, note="输出无法解析")
    return JudgeScore(
        scenario_id=scenario_id,
        scores={k: v[0] for k, v in parsed.items()},
        reasons={k: v[1] for k, v in parsed.items()},
        ok=True,
    )


def make_llm_judge(ask: Ask, persona_hint: str = "") -> Callable[..., Awaitable[JudgeScore]]:
    """把 ``ask`` 包装成 runner 可直接用的 judge 回调。

    ``persona_hint``：人设摘要（评审据此判断"像不像她"）。
    """

    async def _judge(scenario, reply: str) -> JudgeScore:
        return await judge_reply(
            ask, scenario.id, scenario.input, reply, persona_hint=persona_hint
        )

    return _judge


def aggregate(scores: list[JudgeScore]) -> dict:
    """聚合评分：每维度平均分 + 总体 + 最差项（只统计解析成功的）。"""
    ok = [s for s in scores if s.ok and s.scores]
    if not ok:
        return {
            "judged": 0,
            "skipped": len(scores),
            "dimensions": {},
            "overall": 0.0,
            "worst": [],
        }
    dims: dict[str, float] = {}
    for dim in DIMENSIONS:
        vals = [s.scores[dim] for s in ok if dim in s.scores]
        if vals:
            dims[dim] = round(sum(vals) / len(vals), 2)
    overall = round(sum(dims.values()) / len(dims), 2) if dims else 0.0
    worst: list[dict] = []
    for s in ok:
        for dim, value in s.scores.items():
            if value <= 2:
                worst.append(
                    {
                        "scenario_id": s.scenario_id,
                        "dimension": dim,
                        "score": value,
                        "reason": s.reasons.get(dim, ""),
                    }
                )
    worst.sort(key=lambda w: w["score"])
    return {
        "judged": len(ok),
        "skipped": len(scores) - len(ok),
        "dimensions": dims,
        "overall": overall,
        "worst": worst[:8],
    }
