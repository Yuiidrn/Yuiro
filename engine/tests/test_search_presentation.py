"""来源卡意图区分与只朗读正文；纯函数及真实 AgentLoop 事件回归。"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from yuiro.agent import AgentLoop
from yuiro.audio import TTSTaskManager, split_sentences
from yuiro.audio.speech_text import sentence_boundary, speech_body
from yuiro.search_presentation import wants_source_card


@pytest.mark.parametrize("text,expected", [
    ("查一下今天北京天气", False), ("联网确认 Python 最新版本", False),
    ("帮我找 DeepSeek 官方文档和教程", True), ("给我参考来源", True),
    ("对比两个软件", True), ("不用来源卡，只告诉我结论", False),
    ("搜索官网，只回答结果", False), ("show sources for this claim", True),
])
def test_intent(text, expected):
    assert wants_source_card(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("正文。https://example.com?q=a&b=2", "正文。"),
    ("参考[官方文档](https://example.com/a)。", "参考官方文档。"),
    ("[https://example.com](https://example.com)", ""),
    ("正文[1]。\n参考来源：\n- 官方文档 https://example.com", "正文。"),
    ("你好，今天晴天。", "你好，今天晴天。"),
    ("www.example.com/path", ""),
    ("官网 platform.deepseek.com，版本 3.14.0。", "官网 ，版本 3.14.0。"),
])
def test_speech_body(text, expected):
    assert speech_body(text) == expected


def test_url_not_split_into_speakable_query_fragments():
    assert sentence_boundary("https://example.com?q=a;v=b\n答案。") == 27
    parts = split_sentences("答案在这里。https://example.com/" + "a"*100)
    assert not any("example" in p or "aaa" in p for p in parts)


@pytest.mark.asyncio
async def test_link_only_segment_never_calls_tts():
    provider = SimpleNamespace(synthesize_segment=AsyncMock())
    manager = TTSTaskManager(provider)
    await manager.enqueue(1, "https://example.com")
    segment = await manager.wait_next()
    assert segment.wav == b""
    provider.synthesize_segment.assert_not_called()


@pytest.mark.asyncio
async def test_real_card_emitter_is_gated_and_preserves_metadata():
    loop = object.__new__(AgentLoop)
    loop._events = SimpleNamespace(publish=AsyncMock())
    payload = json.dumps({"status": "ok", "results": [{"title": "官方文档", "url": "https://example.com",
                                                       "snippet": "摘要", "published_at": "2026-10-23"}]})
    await loop._emit_result_card("sid", 2, "web_search", payload)
    loop._events.publish.assert_not_awaited()
    await loop._emit_result_card("sid", 2, "web_search", payload, show_sources=True)
    event = loop._events.publish.await_args.args[0]
    assert event.session_id == "sid" and event.generation == 2
    assert event.payload["items"][0]["published_at"] == "2026-10-23"
