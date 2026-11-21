"""Unit tests for the pure-logic pieces of the Yuiro engine skeleton."""
from __future__ import annotations

from yuiro.agent.response_categorizer import categorize_response

RESPONSE = (
    "好的，我帮你打开记事本。"
    "<think>用户想要打开记事本，这是一个明确指令。</think>"
    "正在打开…"
    "<reasoning>调用 app_open 工具</reasoning>"
    "已打开。"
)


def test_categorize_strips_reasoning_from_speech():
    cat = categorize_response(RESPONSE)
    assert "好的" in cat.speech
    assert "打开记事本" in cat.speech
    assert "正在打开" in cat.speech
    # reasoning/thought tags must NOT leak into speech (so they aren't spoken)
    assert "用户想要打开" not in cat.speech
    assert "调用 app_open" not in cat.speech
    # reasoning content is captured separately
    assert "用户想要打开记事本" in cat.reasoning
    assert "调用 app_open 工具" in cat.reasoning


def test_categorize_no_tags_passthrough():
    cat = categorize_response("你好呀")
    assert cat.speech == "你好呀"
    assert cat.reasoning == ""


def test_categorize_unclosed_tag_is_speech():
    # Unclosed tag should not be stripped (robustness)
    cat = categorize_response("末尾有 <think 没闭合")
    assert "<think" in cat.speech
