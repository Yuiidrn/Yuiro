"""Eval 包（S30）：人格基线（personality-baseline）。

规范依据（``docs/spec/阶段性总评和后续方向.md``）：

> **PB0 永远先做 Baseline**：先建立 ``personality-baseline``（100–300 个固定场景：
> 日常聊天/安慰/吐槽/争论/拒绝/惊讶/工具调用/任务失败/任务成功/长期记忆），
> 比较 ``Cloud Model + Prompt`` 与未来 ``Local Model + LoRA``，否则没有实验基线。

- ``Scenario`` / ``judge_reply`` / ``summarize``：场景集与**规则判定**（纯逻辑、可离线测试）；
- ``run_baseline``：跑一遍基线（responder 由调用方注入：真 LLM / AgentLoop / 假实现）；
- 场景集：``scenarios/personality_baseline.jsonl``（随包分发，进版本控制）。

设计取舍：**只测"可判定"的**。人格是主观的，但"安慰场景不该哈哈哈""说打开记事本就该调工具"
是可判定的；主观维度（语气是否够毒舌）留给后续的 LLM-judge。
"""
from yuiro.eval.baseline import (
    DEFAULT_SCENARIOS,
    Scenario,
    ScenarioResult,
    evaluate_reply,
    judge_reply,
    load_scenarios,
    prompt_hash,
    summarize,
)
from yuiro.eval.judge import (
    DIMENSION_LABELS,
    DIMENSIONS,
    JudgeScore,
    make_llm_judge,
    parse_judge_json,
)
from yuiro.eval.judge import aggregate as aggregate_judge_scores
from yuiro.eval.judge import judge_reply as judge_reply_llm
from yuiro.eval.runner import run_baseline

__all__ = [
    "DEFAULT_SCENARIOS",
    "DIMENSIONS",
    "DIMENSION_LABELS",
    "JudgeScore",
    "Scenario",
    "ScenarioResult",
    "aggregate_judge_scores",
    "evaluate_reply",
    "judge_reply",
    "judge_reply_llm",
    "load_scenarios",
    "make_llm_judge",
    "parse_judge_json",
    "prompt_hash",
    "run_baseline",
    "summarize",
]
