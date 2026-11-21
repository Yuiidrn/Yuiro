"""CLI：跑人格基线（S30 / PB0）。

用法（在 ``engine/`` 目录下）：

```
python -m yuiro.eval                 # 离线：回声 responder，只验证评测链路
python -m yuiro.eval --list          # 列出场景集
python -m yuiro.eval --live          # 真跑（需已配置 LLM key；默认跳过工具类场景）
python -m yuiro.eval --live --limit 5
python -m yuiro.eval --live --include-tools   # 危险：会真实执行系统工具
```
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from yuiro.eval.baseline import load_scenarios, prompt_hash
from yuiro.eval.judge import DIMENSION_LABELS
from yuiro.eval.runner import run_baseline


def _print_report(report: dict) -> None:
    print(
        f"\n=== 人格基线（PB0） ===\n"
        f"model={report.get('model') or '?'}  prompt={report.get('prompt_hash') or '?'}\n"
        f"通过 {report['passed']}/{report['total']}（{report['pass_rate']:.0%}）"
    )
    for cat, stat in report.get("by_category", {}).items():
        print(f"  {cat:<10} {stat['passed']}/{stat['total']}  ({stat['pass_rate']:.0%})")
    failures = report.get("failures", [])
    if failures:
        print(f"\n未通过（{len(failures)}）：")
        for f in failures:
            print(f"  [{f['id']}] {f['input'][:30]!r}")
            print(f"      回复: {f['reply'][:80]!r}")
            for r in f["reasons"]:
                print(f"      - {r}")

    # S32：主观维度（LLM-as-judge）
    judge = report.get("judge")
    if judge:
        dims = judge.get("dimensions") or {}
        if dims:
            print("\n主观评分（LLM-as-judge，1-5）：")
            for dim, val in dims.items():
                print(f"  {DIMENSION_LABELS.get(dim, dim):<8} {val}")
            print(f"  {'总体':<8} {judge.get('overall')}")
            for w in judge.get("worst", []):
                print(
                    f"  ⚠ [{w['scenario_id']}] {w['dimension']}={w['score']} {w['reason']}"
                )
        else:
            print(
                f"\n主观评分：无有效结果（judged={judge.get('judged')} "
                f"skipped={judge.get('skipped')}）"
            )


async def _main(args: argparse.Namespace) -> int:
    items = load_scenarios()
    if args.list:
        print(f"场景集：{len(items)} 条")
        for s in items:
            print(f"  [{s.category:<9}] {s.id:<14} {s.input[:36]}")
        return 0

    if not args.live:
        async def _echo(text: str) -> str:
            return f"（离线回声）{text}"

        report = await run_baseline(
            _echo, model="echo", limit=args.limit, skip_categories=() if args.include_tools else ("tool",)
        )
        _print_report(report)
        print("\n提示：--live 才会真的调用模型（当前是离线链路自检）。")
        return 0

    # 真跑：用配置里的 LLM（单轮 responder；不启 AgentLoop，避免工具副作用）
    from yuiro.agent.chat_service import build_responder
    from yuiro.config import load_config
    from yuiro.keychain import load_llm_key

    cfg = load_config()
    key = load_llm_key() or ""
    if not key:
        print("未配置 LLM API key，无法 --live（可先用离线模式验证链路）。")
        return 2
    responder = build_responder(
        cfg.llm,
        key,
        (cfg.persona.system_prompt or "") + "\n\n" + (cfg.persona.persona_prompt or ""),
    )

    async def _respond(text: str) -> str:
        return await responder.reply(text)

    # S32：主观评分用**独立 system prompt**（"你是严格评审"），
    # 不复用人设 prompt —— 否则等于让它自评自夸。
    judge_fn = None
    if args.judge:
        from yuiro.eval.judge import JUDGE_SYSTEM, make_llm_judge

        judge_responder = build_responder(cfg.llm, key, JUDGE_SYSTEM)

        async def _ask(prompt: str) -> str:
            return await judge_responder.reply(prompt)

        judge_fn = make_llm_judge(_ask, persona_hint=(cfg.persona.persona_prompt or "")[:600])
        print("（已启用主观维度评分：每个场景会额外请求一次评审）")

    report = await run_baseline(
        _respond,
        model=cfg.llm.model,
        prompt_fingerprint=prompt_hash(cfg.persona.system_prompt, cfg.persona.persona_prompt),
        limit=args.limit,
        skip_categories=() if args.include_tools else ("tool",),
        judge=judge_fn,
    )
    _print_report(report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="人格基线（personality-baseline, PB0）")
    parser.add_argument("--list", action="store_true", help="列出场景集")
    parser.add_argument("--live", action="store_true", help="真跑（调用 LLM）")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 个场景")
    parser.add_argument(
        "--include-tools",
        action="store_true",
        help="包含工具类场景（会真实执行系统操作，慎用）",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="额外做主观维度评分（LLM-as-judge，需配合 --live）",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_main(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
