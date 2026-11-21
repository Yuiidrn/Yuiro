"""S47：token 用量与**前缀缓存命中**观测。

为什么这套观测值得单独写测试：

上下文注入顺序（稳定段前置）是延迟优化里杠杆最大的一条，但它的收益**看不见**
—— 除非能把 provider 返回的缓存命中数读出来。而这条链路上有若干"静默失败"的
坑（字段名各家不同、携带 usage 的 chunk 没有 choices、端点根本不支持上报），
任何一个没走到，结果都是"日志里始终没有 cache_hit"，然后优化变成盲改。

因此这里逐一钉住：
- 各家 provider 字段名归一（DeepSeek / OpenAI / Anthropic）；
- **usage 必须在 `not chunk.choices: continue` 之前捕获**（最易踩的坑）；
- 缺字段/不支持时**安静退化**（不报错、不改旧日志格式）。
"""
from __future__ import annotations

import pytest

from yuiro.agent import LLMChunk, OpenAIProvider
from yuiro.runtime.trace import TraceContext


# ---- TraceContext：用量归一 ---------------------------------------------------
def test_usage_defaults_empty_and_cache_line_quiet() -> None:
    """没有任何用量时：cache_line 返回空串，summary 保持旧格式（不出现 cache_hit）。"""
    t = TraceContext(session_id="s1", mode="chat")
    assert t.usage == {}
    assert t.cache_line() == ""
    t.mark("turn_start")
    assert "cache_hit" not in t.summary()


def test_cache_line_deepseek_fields() -> None:
    """DeepSeek：prompt_cache_hit_tokens / prompt_cache_miss_tokens。"""
    t = TraceContext(session_id="s1", mode="chat")
    t.set_usage({
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "prompt_cache_hit_tokens": 800,
        "prompt_cache_miss_tokens": 200,
    })
    line = t.cache_line()
    assert "prompt=1000" in line
    assert "completion=50" in line
    assert "cache_hit=800" in line
    assert "80%" in line, f"应算出命中率，实际：{line}"


def test_cache_line_openai_nested_details() -> None:
    """OpenAI：命中数在 prompt_tokens_details.cached_tokens 里（嵌套）。"""
    t = TraceContext(session_id="s1", mode="chat")
    t.set_usage({
        "prompt_tokens": 400,
        "completion_tokens": 10,
        "prompt_tokens_details": {"cached_tokens": 300},
    })
    assert "cache_hit=300" in t.cache_line()
    assert "75%" in t.cache_line()


def test_cache_line_anthropic_field() -> None:
    """Anthropic：cache_read_input_tokens。"""
    t = TraceContext(session_id="s1", mode="chat")
    t.set_usage({"prompt_tokens": 200, "cache_read_input_tokens": 100})
    assert "cache_hit=100" in t.cache_line()


def test_set_usage_merges_and_tolerates_garbage() -> None:
    """多次记录合并；None / 非 dict 一律静默（观测绝不能反过来打断业务）。"""
    t = TraceContext(session_id="s1", mode="chat")
    t.set_usage({"prompt_tokens": 10})
    t.set_usage({"completion_tokens": 3})
    assert t.usage == {"prompt_tokens": 10, "completion_tokens": 3}
    t.set_usage(None)
    t.set_usage("垃圾")  # type: ignore[arg-type] — 故意传错类型
    assert t.usage == {"prompt_tokens": 10, "completion_tokens": 3}


def test_cache_line_survives_weird_types() -> None:
    """字段是非数字时不能抛异常（只吞掉，退化为无缓存行）。"""
    t = TraceContext(session_id="s1", mode="chat")
    t.set_usage({"prompt_tokens": "很多", "prompt_cache_hit_tokens": None})
    assert isinstance(t.cache_line(), str)  # 不抛即可


# ---- OpenAIProvider：usage 捕获 ----------------------------------------------
class _FakeUsage:
    def __init__(self, data: dict) -> None:
        self._data = data

    def model_dump(self) -> dict:
        return dict(self._data)


class _FakeDelta:
    def __init__(self, content: str = "") -> None:
        self.content = content
        self.tool_calls = None


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.delta = _FakeDelta(content)


class _FakeChunk:
    """对齐 OpenAI 流式 chunk：usage 只在独立 chunk 上，且该 chunk 的 choices 为空。"""

    def __init__(self, content: str = "", usage: _FakeUsage | None = None,
                 no_choices: bool = False) -> None:
        self.choices = [] if no_choices else [_FakeChoice(content)]
        self.usage = usage


class _FakeStream:
    def __init__(self, chunks: list) -> None:
        self._it = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self) -> None:
        return None


class _FakeCompletions:
    def __init__(self, chunks: list) -> None:
        self._chunks = chunks
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeStream(self._chunks)


class _FakeChat:
    def __init__(self, chunks: list) -> None:
        self.completions = _FakeCompletions(chunks)


class _FakeClient:
    def __init__(self, chunks: list) -> None:
        self.chat = _FakeChat(chunks)


def _provider(chunks: list) -> OpenAIProvider:
    """绕过 __init__（不建真 client），注入假流。"""
    p = OpenAIProvider.__new__(OpenAIProvider)
    p._client = _FakeClient(chunks)  # type: ignore[assignment]
    p._model = "fake-model"
    p._temperature = 0.1
    p._base_url = "http://fake"
    return p


async def _collect(p: OpenAIProvider) -> list[LLMChunk]:
    return [c async for c in p.stream_text([{"role": "user", "content": "hi"}])]


@pytest.mark.asyncio
async def test_stream_captures_usage_on_choicesless_chunk() -> None:
    """★ 核心护栏：携带 usage 的 chunk **没有 choices**，usage 仍必须被捕获。

    这是最容易踩的坑：若把取 usage 的代码放在 `if not chunk.choices: continue`
    之后，就永远读不到缓存命中数 —— 表面"接了 usage"，日志里却始终为空。
    """
    p = _provider([
        _FakeChunk("你好"),
        _FakeChunk(usage=_FakeUsage({
            "prompt_tokens": 900,
            "completion_tokens": 12,
            "prompt_cache_hit_tokens": 700,
        }), no_choices=True),
    ])
    chunks = await _collect(p)
    assert [c.kind for c in chunks] == ["token", "done"]
    assert chunks[-1].usage is not None, "usage 在无 choices 的 chunk 上，必须仍被捕获"
    assert chunks[-1].usage["prompt_cache_hit_tokens"] == 700


@pytest.mark.asyncio
async def test_stream_requests_usage_and_degrades_gracefully() -> None:
    """会请求 usage 上报；且**不支持时安静退化**（不能让对话因此失败）。"""
    p = _provider([_FakeChunk("hi")])
    await _collect(p)
    sent = p._client.chat.completions.calls[0]  # type: ignore[attr-defined]
    assert sent.get("stream_options") == {"include_usage": True}


@pytest.mark.asyncio
async def test_stream_without_usage_still_works() -> None:
    """端点完全不返回 usage（降级后）→ done chunk 的 usage 为 None，流程照常。"""
    p = _provider([_FakeChunk("hi")])
    chunks = await _collect(p)
    assert chunks[-1].kind == "done"
    assert chunks[-1].usage is None


@pytest.mark.asyncio
async def test_trace_receives_usage_from_provider() -> None:
    """端到端：provider 的 usage → TraceContext → 一行可读的缓存命中率。"""
    p = _provider([
        _FakeChunk("回复"),
        _FakeChunk(usage=_FakeUsage({
            "prompt_tokens": 1000,
            "completion_tokens": 20,
            "prompt_cache_hit_tokens": 900,
        }), no_choices=True),
    ])
    t = TraceContext(session_id="s1", mode="chat")
    async for c in p.stream_text([{"role": "user", "content": "hi"}]):
        if c.kind == "done" and c.usage:
            t.set_usage(c.usage)
    assert "cache_hit=900" in t.summary()
    assert "90%" in t.summary()


@pytest.mark.asyncio
async def test_stream_degrades_when_usage_request_rejected() -> None:
    """端点拒绝 usage 上报（常见 400）→ 去掉 stream_options 重试，对话不受影响。

    这不是理论风险：我们当前用的是**阿里云百炼兼容端点**，它对 usage 上报的支持
    与 OpenAI 主站并不一致。降级后少一个观测无所谓，**绝不能因此让整轮对话失败**
    —— 这是"观测必须可降级"原则的护栏。
    """
    BadRequestError = type("BadRequestError", (Exception,), {})

    class _Rejecting:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if "stream_options" in kwargs:
                raise BadRequestError("Unsupported parameter: stream_options")
            return _FakeStream([_FakeChunk("hi")])

    comp = _Rejecting()
    p = OpenAIProvider.__new__(OpenAIProvider)
    p._client = type("C", (), {"chat": type("Ch", (), {"completions": comp})()})()  # type: ignore[assignment]
    p._model = "m"
    p._temperature = 0.1
    p._base_url = "x"

    chunks = [c async for c in p.stream_text([{"role": "user", "content": "hi"}])]
    assert chunks[-1].kind == "done"
    assert chunks[-1].usage is None, "退化后拿不到 usage 是预期内的"
    assert len(comp.calls) == 2, "第一次被拒 → 应去掉 stream_options 重试一次"
    assert "stream_options" not in comp.calls[1]
    assert "stream_options" in comp.calls[0]
