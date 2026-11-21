"""S52：输出语言解耦（OutputRenderer，Unit）。

背景与设计见 ``yuiro/audio/render.py`` 的模块说明。本套件只测**渲染器本身**
（不加载真实模型、不发网络请求），覆盖四条硬约束：

1. **默认零调用**：目标语言 == 内部语言（或朗读语言为 auto）时完全透传；
2. **已是对应语言就透传**：英文原文要英文朗读时不发起无谓翻译；
3. **绝不静默**：超时/异常/空结果一律回退原文（宁可念错语言，不能没声音）；
4. **可观测**：calls / cache_hits / failures 计数与告警日志。

pipeline 级别（入队文本、气泡文本、打断）见 ``test_tts_streaming.py``。
"""
from __future__ import annotations

import asyncio

import pytest

from yuiro.agent import LLMChunk
from yuiro.audio.render import OutputRenderer, detect_language


class StubLLM:
    """按脚本产出 token 的假 LLM：记录调用次数，可注入延迟/异常。"""

    def __init__(self, reply: str = "Hello there.", delay: float = 0.0,
                 error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self._reply = reply
        self._delay = delay
        self._error = error

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        self.calls.append(str(messages[-1].get("content", "")))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        yield LLMChunk(kind="token", content=self._reply)
        yield LLMChunk(kind="done")


# ---- Unit：语种判定 ---------------------------------------------------------
def test_detect_language_basics() -> None:
    assert detect_language("你好呀。") == "zh"
    assert detect_language("Hello there.") == "en"
    # 日文必然夹汉字 —— 先认假名才能与中文区分（旧实现把假名混判成 zh）
    assert detect_language("おはよう、今日はいい天気だね") == "ja"
    assert detect_language("カタカナだけ") == "ja"
    # 纯标点/数字/emoji 无法判定；谚文（韩文）暂不支持 → 都不翻译
    assert detect_language("……") == "unknown"
    assert detect_language("123 456") == "unknown"
    assert detect_language("안녕하세요") == "unknown"


# ---- Unit：零调用短路 -------------------------------------------------------
@pytest.mark.asyncio
async def test_default_config_is_passthrough_with_zero_calls() -> None:
    """默认 zh + auto：两个出口都透传，**一次 LLM 调用都不产生**。"""
    llm = StubLLM()
    r = OutputRenderer(llm)
    assert r.enabled is False
    assert await r.render_display("你好呀。") == "你好呀。"
    assert await r.render_speak("你好呀。") == "你好呀。"
    assert llm.calls == []
    assert r.stats["calls"] == 0


@pytest.mark.asyncio
async def test_same_language_passthrough() -> None:
    """目标语言与原文一致（英文原文本就要英文朗读）→ 不调用。"""
    llm = StubLLM()
    r = OutputRenderer(llm, display_language="en", speak_language="en")
    assert await r.render_speak("Hello there.") == "Hello there."
    assert await r.render_display("Hello there.") == "Hello there."
    assert llm.calls == []


@pytest.mark.asyncio
async def test_invalid_target_language_is_passthrough() -> None:
    """配置写错（如 jp）→ 透传，绝不把声音弄没。"""
    llm = StubLLM()
    r = OutputRenderer(llm, speak_language="jp")
    assert await r.render_speak("你好呀。") == "你好呀。"
    assert llm.calls == []


# ---- Unit：真的转换 ---------------------------------------------------------
@pytest.mark.asyncio
async def test_speak_translation_calls_llm_once() -> None:
    llm = StubLLM(reply="Hello there.")
    r = OutputRenderer(llm, speak_language="en")
    assert r.enabled is True
    assert await r.render_speak("你好呀。") == "Hello there."
    assert len(llm.calls) == 1
    assert r.stats["calls"] == 1


@pytest.mark.asyncio
async def test_display_and_speak_are_independent() -> None:
    """展示语言与朗读语言互不影响：同一个 renderer 两个出口各按自己的目标。"""
    llm = StubLLM(reply="Bonjour/Hello")
    r = OutputRenderer(llm, display_language="en", speak_language="ja")
    assert await r.render_display("你好呀。") == "Bonjour/Hello"
    assert await r.render_speak("你好呀。") == "Bonjour/Hello"
    assert len(llm.calls) == 2  # 两个不同出口各一次（不同目标语言，不能共用缓存）


@pytest.mark.asyncio
async def test_cache_hits_skip_second_call() -> None:
    llm = StubLLM(reply="Hello there.")
    r = OutputRenderer(llm, speak_language="en")
    await r.render_speak("你好呀。")
    await r.render_speak("你好呀。")
    assert len(llm.calls) == 1
    assert r.stats["cache_hits"] == 1


@pytest.mark.asyncio
async def test_render_speak_many_keeps_order() -> None:
    """批量渲染保序（并发执行但结果按输入顺序返回）。"""
    llm = StubLLM(reply="X")
    r = OutputRenderer(llm, speak_language="en")
    out = await r.render_speak_many(["第一句。", "第二句。", "第三句。"])
    assert out == ["X", "X", "X"]
    assert llm.calls == ["第一句。", "第二句。", "第三句。"]


# ---- Unit：健壮性（绝不静默） -----------------------------------------------
@pytest.mark.asyncio
async def test_timeout_falls_back_to_original() -> None:
    llm = StubLLM(delay=0.3)
    r = OutputRenderer(llm, speak_language="en", timeout_s=0.05)
    assert await r.render_speak("你好呀。") == "你好呀。"
    assert r.stats["failures"] == 1


@pytest.mark.asyncio
async def test_exception_falls_back_to_original() -> None:
    llm = StubLLM(error=RuntimeError("boom"))
    r = OutputRenderer(llm, speak_language="en")
    assert await r.render_speak("你好呀。") == "你好呀。"
    assert r.stats["failures"] == 1


@pytest.mark.asyncio
async def test_empty_result_falls_back_to_original() -> None:
    llm = StubLLM(reply="   ")
    r = OutputRenderer(llm, speak_language="en")
    assert await r.render_speak("你好呀。") == "你好呀。"
    assert r.stats["failures"] == 1


@pytest.mark.asyncio
async def test_missing_llm_is_passthrough() -> None:
    """未注入 LLM（没有 key）→ 透传，不抛异常、不空段。"""
    r = OutputRenderer(None, speak_language="en")
    assert await r.render_speak("你好呀。") == "你好呀。"


@pytest.mark.asyncio
async def test_wrapping_quotes_are_stripped() -> None:
    """模型偶发加引号/前缀时清掉，避免把引号念出来。"""
    llm = StubLLM(reply='"Hello there."')
    r = OutputRenderer(llm, speak_language="en")
    assert await r.render_speak("你好呀。") == "Hello there."


# ---- Unit：热重载 -----------------------------------------------------------
@pytest.mark.asyncio
async def test_set_languages_hot_reload() -> None:
    llm = StubLLM(reply="Hello there.")
    r = OutputRenderer(llm)
    assert await r.render_speak("你好呀。") == "你好呀。"  # 默认 auto → 透传
    r.set_languages(speak_language="en", display_language="en", mode="full", timeout_s=3.0)
    assert r.mode == "full"
    assert await r.render_speak("你好呀。") == "Hello there."
    assert r.describe()["speak"] == "en"
