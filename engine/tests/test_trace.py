"""S01：TraceContext 单元测试（只观测，不改行为）。

对应 docs/plan/S01-voice-latency-observatory.md。
"""
from yuiro.runtime.trace import TraceContext


def test_marks_and_summary() -> None:
    t = TraceContext(session_id="abcdef123456", mode="chat")
    t.mark("turn_start")
    t.mark("llm_first_token")
    t.mark("reply_sent")
    s = t.summary()
    assert "trace=" in s
    assert "session=abcdef12" in s
    assert "mode=chat" in s
    assert "turn_start=" in s
    assert "llm_first_token=" in s
    assert "reply_sent=" in s
    assert t.get("turn_start") is not None


def test_duplicate_mark_keeps_first() -> None:
    t = TraceContext(session_id="s", mode="voice")
    t.mark("tts_start")
    first = t.get("tts_start")
    t.mark("tts_start")
    assert t.get("tts_start") == first


def test_summary_without_marks_is_safe() -> None:
    t = TraceContext(session_id="s", mode="chat")
    assert "trace=" in t.summary()
    assert t.elapsed_ms() == 0.0


def test_stage_order_is_stable() -> None:
    """汇总按预定义阶段顺序展示，与 mark 调用顺序无关。"""
    t = TraceContext(session_id="s", mode="voice")
    t.mark("tts_end")
    t.mark("speech_end")
    s = t.summary()
    assert s.index("speech_end") < s.index("tts_end")


def test_emit_does_not_raise() -> None:
    """emit 只读输出，任何环境都不得抛异常（观测失败不阻断业务）。"""
    t = TraceContext(session_id="s", mode="chat")
    t.mark("turn_start")
    t.emit()
