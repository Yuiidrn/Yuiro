"""基线跑批（S30）：把 responder 注入进来跑一遍场景集。

**为什么注入 responder 而不是内置 LLM 调用**：

- 真跑（云模型 / AgentLoop）→ 由调试 API 传入真实 responder；
- 离线测试 → 传一个假 responder，评测逻辑本身即可验证（不需要 API key）；
- 未来本地模型对比 → 换 responder 即可，评测代码零改动（PB0 的"可对比"要求）。

responder 约定：``async (text) -> str | tuple[str, list[str]]``
（返回元组时第二项为工具调用名列表，用于 ``should_call_tool`` / ``no_tool`` 判定）。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from yuiro.eval.baseline import (
    Scenario,
    evaluate_reply,
    load_scenarios,
    summarize,
)
from yuiro.logger import vlog

Responder = Callable[[str], Awaitable[object]]


async def run_baseline(
    responder: Responder,
    *,
    scenarios: list[Scenario] | None = None,
    path: str | None = None,
    model: str = "",
    prompt_fingerprint: str = "",
    limit: int = 0,
    skip_categories: tuple[str, ...] = (),
    judge=None,
    on_result=None,
) -> dict:
    """逐场景跑一遍基线，返回汇总报告（含失败清单）。

    ``limit``：只跑前 N 个场景（冒烟时用，避免一次打太多请求）；
    ``skip_categories``：跳过的类别（**默认调用方应跳过 ``tool``**——
    工具类场景会真实操作系统，评测不该有副作用）；
    ``judge``：可选的 ``async (Scenario, reply) -> JudgeScore`` 主观评分回调
    （**只对通过规则判定的场景调用**，避免为明显不合格的回复花 token）；
    ``on_result``：可选的 ``(ScenarioResult) -> None`` 回调（用于流式打印进度）。
    """
    items = scenarios if scenarios is not None else load_scenarios(path)
    if skip_categories:
        skip = set(skip_categories)
        items = [s for s in items if s.category not in skip]
    if limit and limit > 0:
        items = items[:limit]

    results = []
    scores: list = []  # S32：主观评分（JudgeScore）
    for sc in items:
        error_note = ""
        try:
            out = await responder(sc.input)
        except Exception as exc:  # noqa: BLE001 — 单场景失败记为失败项，而非整体中断
            out = f"<error: {exc}>"
            error_note = f"responder 异常：{exc}"
        if isinstance(out, tuple):
            reply, calls = out[0], list(out[1] or [])
        else:
            reply, calls = str(out), []
        result = evaluate_reply(sc, str(reply), calls)
        if error_note:
            # 异常必须是失败：不能因为"<error: …>"长度够长就判通过
            result.passed = False
            result.reasons.append(error_note)
        results.append(result)
        # S32：主观评分只针对"规则上已经合格"的回复（成本控制）
        if judge is not None and result.passed:
            try:
                scores.append(await judge(sc, str(reply)))
            except Exception as exc:  # noqa: BLE001 — 评审失败不影响跑批
                vlog("eval", f"[评审] {sc.id} 异常（已跳过）：{exc}")
        if on_result is not None:
            try:
                on_result(result)
            except Exception:  # noqa: BLE001, S110 — 进度回调失败不影响跑批
                pass

    report = summarize(results, model=model, prompt_fingerprint=prompt_fingerprint)
    if judge is not None:
        from yuiro.eval.judge import aggregate

        report["judge"] = aggregate(scores)
    vlog(
        "eval",
        f"[人格基线] {report['passed']}/{report['total']} 通过"
        f"（{report['pass_rate']:.0%}，model={model or '?'}，prompt={prompt_fingerprint or '?'}）",
    )
    return report
