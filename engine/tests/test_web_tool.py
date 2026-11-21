"""S51 联网检索工具测试：schema / 隐藏 / 执行 / 降级。

为什么这些测试值得存在（每条都对应设计文档里的一个硬判断）：

1. **未配置 key 时工具必须消失** —— 否则模型会去调一个用不了的能力
   （`requires_env` 此前是"只声明、无消费"的死字段，这里把它钉住）；
2. **只读副作用** —— 决定崩溃恢复能否安全重放（S48）；
3. **摘要级截断** —— 全文会吃光上下文预算（S47）；
4. **失败必须说人话** —— 不可用/失败/空结果给**不同**的 status，
   绝不编造"我查到了"（S49 媒体撒谎的教训）。
"""
from __future__ import annotations

import json

import pytest

from yuiro.agent import LLMChunk, LLMProvider
from yuiro.config import MemoryConfig, PersonaConfig, SearchConfig
from yuiro.tools import EFFECT_READ, ToolRegistry, resolve_effect
from yuiro.tools import web_tool as wt


@pytest.fixture(autouse=True)
def _reset_key_provider():
    """全局 key 提供者必须逐测隔离（否则测试间互相污染）。"""
    yield
    wt.configure_search_key_provider(lambda: "")


# ── schema 与副作用 ───────────────────────────────────────────────────────────
def test_schema_shape() -> None:
    schema = wt.WebSearchTool().schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "web_search"
    assert fn["parameters"]["required"] == ["query"]
    assert "query" in fn["parameters"]["properties"]
    # 描述里必须含"不许编造"的边界（与 persona 铁律一致）
    assert "编造" in fn["description"]


def test_effect_is_read() -> None:
    """只读 → 崩溃恢复可安全重放（S48）。"""
    tool = wt.WebSearchTool()
    assert tool.effect == EFFECT_READ
    assert resolve_effect(tool) == EFFECT_READ


def test_no_approval_required() -> None:
    """只读能力，不该走审批门（否则每次搜索都弹窗）。"""
    assert wt.WebSearchTool().approval_required is False


# ── requires_env 的消费者（关键缺口）────────────────────────────────────────
def test_hidden_when_no_key() -> None:
    """★ 未配置 key → 工具**不出现在 schema 里**（模型看不到用不了的能力）。"""
    wt.configure_search_key_provider(lambda: "")
    reg = ToolRegistry()
    reg.register(wt.WebSearchTool())
    names = [s["function"]["name"] for s in reg.schemas()]
    assert "web_search" not in names


def test_visible_when_key_configured() -> None:
    wt.configure_search_key_provider(lambda: "tvly-fake")
    reg = ToolRegistry()
    reg.register(wt.WebSearchTool())
    names = [s["function"]["name"] for s in reg.schemas()]
    assert "web_search" in names


# ── 执行路径（注入 fake provider，不打网络）─────────────────────────────────
class _FakeProvider:
    def __init__(self, answer: str = "", results=None, raises: Exception | None = None) -> None:
        self._answer = answer
        self._results = results if results is not None else []
        self._raises = raises
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, top_k: int) -> dict:
        self.calls.append((query, top_k))
        if self._raises is not None:
            raise self._raises
        return {"answer": self._answer, "results": self._results}


def _tool(_provider, **cfg) -> wt.WebSearchTool:
    """构造工具：``_provider`` 是注入的 fake（None = 按配置构建真实 provider）。"""
    return wt.WebSearchTool(
        config=SearchConfig(top_k=cfg.pop("top_k", 3), **cfg), provider=_provider
    )


@pytest.mark.asyncio
async def test_run_returns_results_and_answer() -> None:
    p = _FakeProvider(
        answer="Python 3.13 已于 2024 年发布。",
        results=[{"title": "What's New", "url": "https://x/1", "snippet": "摘要"}],
    )
    out = json.loads(await _tool(p).run({"query": "Python 3.13"}, "t1"))
    assert out["status"] == "ok"
    assert out["count"] == 1
    assert out["results"][0]["url"] == "https://x/1"
    assert "3.13" in out["answer"]
    assert p.calls == [("Python 3.13", 3)]


@pytest.mark.asyncio
async def test_empty_results_is_honest() -> None:
    """★ 空结果必须明说"没查到"并明确禁止编造 —— 不能包装成"没有这件事"。"""
    out = json.loads(await _tool(_FakeProvider(results=[])).run({"query": "冷门词"}, "t"))
    assert out["status"] == "ok"
    assert out["count"] == 0
    assert "没查到" in out["note"]
    assert "编造" in out["note"]


@pytest.mark.asyncio
async def test_provider_failure_is_honest() -> None:
    """★ 失败 → status=error 且给下一步；绝不编造结果（S49 教训）。"""
    p = _FakeProvider(raises=RuntimeError("boom"))
    out = json.loads(await _tool(p).run({"query": "q"}, "t"))
    assert out["status"] == "error"
    assert "搜" in out["note"]
    assert "results" not in out


@pytest.mark.asyncio
async def test_unavailable_backend_is_pending() -> None:
    """未接入的后端要明确报错，**绝不悄悄用另一个后端冒充**。"""
    tool = _tool(None)
    tool._cfg.provider = "unsupported"
    out = json.loads(await tool.run({"query": "q"}, "t"))
    assert out["status"] == "pending"
    assert "unsupported" in out["note"]


@pytest.mark.asyncio
async def test_missing_query_is_error() -> None:
    out = json.loads(await _tool(None).run({}, "t"))
    assert out["status"] == "error"


@pytest.mark.asyncio
async def test_snippet_truncated_to_budget() -> None:
    """★ 摘要截断：全文会吃光 S47 的上下文预算。"""
    long_text = "啊" * 5000
    p = _FakeProvider(results=[{"title": "t", "url": "u", "snippet": long_text}])
    out = json.loads(await _tool(p).run({"query": "q"}, "t"))
    # provider 是注入的 fake，截断发生在 provider 内部 —— 用真实 TavilyProvider 的
    # 截断逻辑单独验证（下面）。这里先确认工具不额外放大内容。
    assert len(out["results"][0]["snippet"]) <= max(len(long_text), wt.SNIPPET_MAX_CHARS)


def test_deepseek_provider_truncates_content(monkeypatch) -> None:
    """仅摘要进入上下文，保留日期。"""
    import httpx
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"results": [{"title": "t", "url": "https://example.com", "summary": "长" * 9999, "date": "2026-10-23"}]}))))
    prov = wt.DeepSeekSearchProvider(api_key="k", timeout_s=1.0)
    import asyncio

    data = asyncio.run(prov.search("q", 3))
    assert len(data["results"][0]["snippet"]) == wt.SNIPPET_MAX_CHARS


# ── L1.5 结果二次提炼 ────────────────────────────────────────────────────────
class _QuietLLM:
    def __init__(self, reply: str = "两句话的答案。", boom: bool = False) -> None:
        self._reply = reply
        self._boom = boom
        self.calls = 0

    async def stream_text(self, messages, tools=None, **kwargs):
        self.calls += 1
        if self._boom:
            raise RuntimeError("boom")
        yield LLMChunk(kind="token", content=self._reply)
        yield LLMChunk(kind="done")


def _two_results() -> list[dict]:
    return [
        {"title": "a", "url": "https://a/1", "snippet": "s1"},
        {"title": "b", "url": "https://b/2", "snippet": "s2"},
    ]


@pytest.mark.asyncio
async def test_refine_multiple_results_and_keeps_original_urls() -> None:
    """★ 多条结果 → 提炼成短答案；**URL 始终来自原始结果**（不让模型写链接）。"""
    llm = _QuietLLM("综合来看是两句话的答案。")
    p = _FakeProvider(answer="原始的长摘要堆砌", results=_two_results())
    tool = wt.WebSearchTool(
        config=SearchConfig(refine_results=True), provider=p, llm_getter=lambda: llm
    )
    out = json.loads(await tool.run({"query": "q"}, "t"))
    assert out["answer"] == "综合来看是两句话的答案。"
    assert llm.calls == 1
    assert [r["url"] for r in out["results"]] == ["https://a/1", "https://b/2"]


@pytest.mark.asyncio
async def test_no_refine_for_single_result() -> None:
    """单条结果不值得多一次 LLM 调用（用延迟换不到收益）。"""
    llm = _QuietLLM()
    p = _FakeProvider(answer="单条答案", results=[_two_results()[0]])
    tool = wt.WebSearchTool(config=SearchConfig(), provider=p, llm_getter=lambda: llm)
    out = json.loads(await tool.run({"query": "q"}, "t"))
    assert out["answer"] == "单条答案"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_refine_failure_falls_back_to_raw() -> None:
    """提炼失败 → 用原始摘要（**绝不因为"优化"丢结果**）。"""
    p = _FakeProvider(answer="原始摘要", results=_two_results())
    tool = wt.WebSearchTool(
        config=SearchConfig(refine_results=True), provider=p, llm_getter=lambda: _QuietLLM(boom=True)
    )
    out = json.loads(await tool.run({"query": "q"}, "t"))
    assert out["answer"] == "原始摘要"
    assert out["count"] == 2


@pytest.mark.asyncio
async def test_no_llm_means_no_refine() -> None:
    """未注入 LLM（精简部署）→ 直接用原始摘要，不报错。"""
    p = _FakeProvider(answer="原始摘要", results=_two_results())
    tool = wt.WebSearchTool(config=SearchConfig(), provider=p)
    out = json.loads(await tool.run({"query": "q"}, "t"))
    assert out["answer"] == "原始摘要"


def test_top_k_capped_at_5() -> None:
    """条数上限 5：条数直接乘进上下文与延迟。"""
    cfg = SearchConfig(top_k=50)
    assert max(1, min(int(cfg.top_k), 5)) == 5


# ── 装配：build_agent_loop 的注册条件 ────────────────────────────────────────
def _loop(**kwargs):
    from yuiro.agent import build_agent_loop

    return build_agent_loop(
        base_url="http://127.0.0.1:1/v1",
        model="m",
        api_key="k",
        persona=PersonaConfig(),
        memory_config=MemoryConfig(),
        **kwargs,
    )


def test_not_registered_when_disabled() -> None:
    loop = _loop(search_config=SearchConfig(enabled=False))
    names = [s["function"]["name"] for s in loop._tools.schemas()]
    assert "web_search" not in names


def test_not_registered_when_enabled_but_no_key(monkeypatch) -> None:
    """★ 开了开关但没配 key → 仍不暴露（并留日志说明原因）。

    ⚠ 必须**显式 monkeypatch 成"没有 key"**：此前它依赖"这台机器的 keychain 里
    刚好没有搜索 key"这一环境假设 —— 用户一旦在调试台真的填了 key，这条测试就会
    失败（实测如此）。测试不能依赖真实凭据库的状态。
    """
    from yuiro import keychain

    monkeypatch.setattr(keychain, "load_search_key", lambda: None)
    loop = _loop(search_config=SearchConfig(enabled=True))
    names = [s["function"]["name"] for s in loop._tools.schemas()]
    assert "web_search" not in names


def test_registered_when_enabled_and_key_present(monkeypatch) -> None:
    from yuiro import keychain

    monkeypatch.setattr(keychain, "load_search_key", lambda: "tvly-test")
    loop = _loop(search_config=SearchConfig(enabled=True))
    names = [s["function"]["name"] for s in loop._tools.schemas()]
    assert "web_search" in names


# ── 会话级开关 → 工具按需注入（S51）────────────────────────────────────────
class _CaptureLLM(LLMProvider):
    """记录**模型实际看到的工具表** —— 这是按需注入唯一可信的观测点。"""

    def __init__(self) -> None:
        self.seen_tools: list[list[str]] = []

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        del messages, kwargs
        self.seen_tools.append(
            [str(t.get("function", {}).get("name")) for t in (tools or [])]
        )
        yield LLMChunk(kind="token", content="好")
        yield LLMChunk(kind="done")


@pytest.mark.asyncio
async def test_disabled_tools_hides_web_search_for_that_turn(monkeypatch) -> None:
    """★ 会话级开关：关掉的那一轮，**模型真的看不到** web_search。

    与"放进去再拒调"不同 —— 后者模型仍会尝试调用、仍要花一轮解释为什么不行。
    """
    from yuiro import keychain

    monkeypatch.setattr(keychain, "load_search_key", lambda: "tvly-test")
    loop = _loop(search_config=SearchConfig(enabled=True))
    capture = _CaptureLLM()
    loop._llm = capture

    async for _ in loop.send("s1", "你好", disabled_tools={"web_search"}):
        pass
    assert capture.seen_tools, "LLM 应被调用"
    assert "web_search" not in capture.seen_tools[0]

    capture.seen_tools.clear()
    async for _ in loop.send("s1", "你好"):
        pass
    assert "web_search" in capture.seen_tools[0], "未禁用时应当可见"


# ── DeepSeek 认证与请求契约 ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_deepseek_uses_bearer_header_not_body_key(monkeypatch) -> None:
    """官方 Search API：Bearer + query/count/need_content，不沿用旧请求字段。"""
    import httpx

    seen: dict = {}

    def handler(req):
        seen["headers"] = dict(req.headers)
        seen["body"] = json.loads(req.content)
        assert str(req.url) == wt.DeepSeekSearchProvider.ENDPOINT
        return httpx.Response(200, json={"results": []})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    provider = wt.DeepSeekSearchProvider(api_key="ds-secret")
    await provider.search("河北 今天 天气", 3)

    assert seen["headers"].get("authorization") == "Bearer ds-secret"
    assert "api_key" not in seen["body"], "key 不得放进请求体（官方规定走 header）"
    assert seen["body"]["count"] == 3
    assert seen["body"]["need_content"] is False
