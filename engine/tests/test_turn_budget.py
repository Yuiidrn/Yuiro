"""S47 / B3：TurnBudget —— 一轮对话的总预算（时间 / token / 轮数）。

**为什么值得单独测**：此前唯一的上限是"工具轮数 ≤ 3"，于是最坏情况一轮可以
跑 90 秒、烧上万 token，而用户面对的是**没有任何解释的等待**。预算化要解决
两件事，两件都在这里钉住：

1. **能停下** —— 三个维度各自生效，且返回**原因**而不是 bool（停下必须能如实告知）；
2. **优雅地停** —— 接近上限先给模型"收尾提醒"，而不是到点掐断给用户半截回复。

另外钉住 `add_usage` 的容错：provider 返回的 usage 字段并不统一，甚至可能没有；
**观测数据异常绝不能反过来打断业务**（这正是 S47 里反复强调的那条线）。
"""
from __future__ import annotations

import asyncio

import pytest

from yuiro.agent.turn_state import TurnBudget


def test_fresh_budget_not_exhausted() -> None:
    b = TurnBudget(max_rounds=3, max_seconds=90, max_tokens=60000)
    assert b.exhausted() == ""
    assert b.warning() == ""  # 刚开一轮不该催模型收尾


def test_round_limit_returns_reason() -> None:
    """★ 耗尽必须返回**原因字符串**（而不是 bool）—— 停下要能向用户交代。"""
    b = TurnBudget(max_rounds=2)
    b.rounds = 2
    reason = b.exhausted()
    assert reason and "轮数" in reason
    assert b.stop_reason == reason


def test_token_limit_accumulates_across_rounds() -> None:
    b = TurnBudget(max_tokens=1000)
    b.add_usage({"total_tokens": 600})
    assert b.exhausted() == ""
    b.add_usage({"total_tokens": 500})
    assert "token" in b.exhausted()


def test_add_usage_falls_back_to_prompt_plus_completion() -> None:
    """没有 total_tokens 时用 prompt+completion（provider 字段并不统一）。"""
    b = TurnBudget()
    b.add_usage({"prompt_tokens": 100, "completion_tokens": 20})
    assert b.used_tokens == 120


def test_add_usage_tolerates_garbage() -> None:
    """观测数据异常绝不能反过来打断业务。"""
    b = TurnBudget()
    b.add_usage(None)
    b.add_usage({"total_tokens": "很多"})  # type: ignore[dict-item]
    b.add_usage({"prompt_tokens": None})
    assert b.used_tokens == 0


@pytest.mark.asyncio
async def test_time_limit() -> None:
    b = TurnBudget(max_seconds=0.01)
    await asyncio.sleep(0.02)
    assert "耗时" in b.exhausted()


def test_warning_is_gradual() -> None:
    """接近上限时给出**收尾提示**（渐进优于掐断）。"""
    b = TurnBudget(max_rounds=3, max_seconds=90, max_tokens=1000)
    assert b.warning() == ""
    b.add_usage({"total_tokens": 800})  # 越过 WARN_RATIO=0.7
    w = b.warning()
    assert w and "收尾" in w
    # 收尾提醒必须明确禁止谎报完成（这是本项目的底线之一）
    assert "不要把没做完的说成做完了" in w


def test_warning_when_last_round() -> None:
    b = TurnBudget(max_rounds=3)
    b.rounds = 2
    assert "最后的工具轮次" in b.warning()


def test_summary_reports_stop_reason() -> None:
    b = TurnBudget(max_rounds=1)
    b.rounds = 1
    b.exhausted()
    s = b.summary()
    assert "轮数=1/1" in s and "停止" in s


# ---- clone（AgentLoop 每轮拿一份干净的预算）-----------------------------------
def test_clone_resets_usage_but_keeps_limits() -> None:
    """clone 保留上限、**清零用量与计时**。

    为什么必需：``AgentLoop`` 持有的是"配置模板"，每轮 ``send`` 复制一份使用；
    若直接复用同一对象，用量会跨回合累积 —— 第二次对话刚开口就"预算耗尽"。
    """
    b = TurnBudget(max_rounds=5, max_seconds=10, max_tokens=100)
    b.rounds = 4
    b.add_usage({"total_tokens": 99})
    b.stop_reason = "旧的停止原因"

    c = b.clone()
    assert (c.max_rounds, c.max_seconds, c.max_tokens) == (5, 10, 100)
    assert c.rounds == 0 and c.used_tokens == 0 and c.stop_reason == ""
    assert c.elapsed() < 1.0
    # 原对象不受影响（模板永远是干净的）
    assert b.rounds == 4 and b.used_tokens == 99


# ---- [agent] 配置 -----------------------------------------------------------
def test_agent_config_defaults_and_parse(tmp_path) -> None:
    """[agent] 段可配置；缺省时回退默认值（不写这段也能正常跑）。"""
    from yuiro.config import AgentConfig, load_config

    d = AgentConfig()
    assert (d.max_seconds, d.max_tokens, d.max_rounds) == (90.0, 60000, 3)

    p = tmp_path / "config.toml"
    p.write_text("[agent]\nmax_seconds = 12.5\nmax_rounds = 7\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.agent.max_seconds == 12.5
    assert cfg.agent.max_rounds == 7
    assert cfg.agent.max_tokens == 60000  # 未写的键沿用默认
