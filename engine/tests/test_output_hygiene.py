"""S34 测试：输出净化 —— 剥掉被模型模仿的调试注记。

背景（引擎日志实证）：`（本轮操作：…）` 被 TTS 原样念出。
源头已改为 system 备注，本模块是出口侧兜底。
"""
from __future__ import annotations

from yuiro.text_hygiene import has_debug_notes, strip_debug_notes


def test_strips_operation_note() -> None:
    text = "已经切到下一首了。（本轮操作：我调用了 netease_control（action=next），已完成）"
    assert strip_debug_notes(text) == "已经切到下一首了。"


def test_strips_made_up_note() -> None:
    """模型凭空编造的"无工具调用"同样要剥掉（日志里真实出现过）。"""
    assert strip_debug_notes("好呀，那就听着。（本轮操作：无工具调用）") == "好呀，那就听着。"


def test_strips_ascii_variants() -> None:
    assert strip_debug_notes("好的 (本轮操作: done)") == "好的"
    assert strip_debug_notes("好的（本轮操作:done）") == "好的"


def test_note_in_middle_removed() -> None:
    assert strip_debug_notes("前半（本轮操作：X）后半") == "前半后半"


def test_keeps_normal_parentheses() -> None:
    """正常括号内容不受影响（只匹配高度特征化的「本轮操作：」前缀）。"""
    for text in ("这首歌很好听（真的）", "结果如下（共 3 项）", "（笑）你说呢"):
        assert strip_debug_notes(text) == text


def test_has_debug_notes_flag() -> None:
    assert has_debug_notes("……（本轮操作：X）") is True
    assert has_debug_notes("正常回复，没有注记") is False


def test_empty_input_safe() -> None:
    assert strip_debug_notes("") == ""
    assert strip_debug_notes(None) == ""  # type: ignore[arg-type]
    assert has_debug_notes("") is False
