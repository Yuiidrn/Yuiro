"""S42 / P1 测试：工具返回值规约。

规约的全部价值在于「引擎与壳层只认规约、不认具体工具」——
所以测试要钉住的不是格式美观，而是**规约与消费端的一致性**：

1. 四个状态与关键字段名稳定（改名 = 砸掉所有反馈）；
2. `need_choice` 必须带 options（否则用户没得选，等于没抛出问题）；
3. 规约字段必须真的被引擎的卡片映射认得 —— 这条防的是最隐蔽的失配：
   "规约文档更新了，但引擎/前端没跟上"，表现就是用户侧"给了壳、没反馈"。
"""
from __future__ import annotations

import json

from yuiro.tools.result import err, need_choice, ok, pending


def _load(text: str) -> dict:
    return json.loads(text)


def test_ok_carries_message_and_extra_fields() -> None:
    d = _load(ok("已播放《晴天》", now="晴天", count=1))
    assert d["status"] == "ok" and d["message"] == "已播放《晴天》"
    assert d["now"] == "晴天" and d["count"] == 1, "额外字段应平铺（兼容历史工具）"


def test_err_is_honest_status() -> None:
    d = _load(err("这首歌拿不到播放地址"))
    assert d["status"] == "error" and "拿不到" in d["message"]


def test_pending_marks_not_finished() -> None:
    d = _load(pending("已交给播放器，但还没出声"))
    assert d["status"] == "pending"


def test_need_choice_always_has_options() -> None:
    opts = [{"name": "24小时自习室", "id": "A1"}, {"name": "六级词汇", "id": "A2"}]
    d = _load(need_choice("没找到唯一匹配的歌单", opts))
    assert d["status"] == "need_choice"
    assert d["options"] == opts, "抛出选择题就必须带上选项"


def test_empty_options_are_omitted() -> None:
    """没有选项时不该留一个空数组（会让消费端误判"有选项但没给"）。"""
    d = _load(ok("搞定"))
    assert "options" not in d and "artifacts" not in d


def test_engine_recognizes_the_options_field() -> None:
    """★ 关键：规约字段必须真的被引擎的卡片映射认得。

    若这条红了，说明规约与引擎脱节 —— 典型症状是新工具在界面上"没有反馈"，
    而排查要从工具追到引擎映射表，代价很高。
    """
    from yuiro.agent import AgentLoop

    assert "options" in AgentLoop._RESULT_CARD_KEYS, (
        "规约里的 options 未被引擎的 _RESULT_CARD_KEYS 收录 —— "
        "按规约返回的工具结果将不会渲染成可点卡片"
    )


def test_all_helpers_return_json_strings() -> None:
    """工具层的返回值约定是 JSON 字符串（AgentLoop 直接 json.loads）。"""
    for text in (ok("a"), err("b"), pending("c"), need_choice("d", [{"name": "x"}])):
        assert isinstance(text, str)
        assert isinstance(_load(text), dict)
