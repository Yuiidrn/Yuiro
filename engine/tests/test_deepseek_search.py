"""DeepSeek Search 契约、迁移、预算与取消；不读取真实凭证。"""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yuiro.config import AppConfig, load_config, save_config
from yuiro.tools.web_tool import DeepSeekSearchProvider, SearchUnavailable


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        **kw, transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_clean_sources_dates_budget_and_no_content(monkeypatch):
    rows = [None, {"url": "javascript:alert(1)"}, {"url": "https://user:pass@example.com"},
            {"url": "https://example.com/a", "summary": "摘要" * 500, "content": "不应进入模型",
             "date": "2026-10-23", "site_name": "官方"},
            {"url": "https://example.com/a"},
            {"url": "https://example.com/b", "snippet": "备用短摘要"}]
    mock_http(monkeypatch, lambda req: httpx.Response(200, json={"results": rows}))
    result = await DeepSeekSearchProvider(api_key="test").search("query", 3)
    assert len(result["results"]) == 2
    assert len(result["results"][0]["snippet"]) == 300
    assert result["results"][0]["published_at"] == "2026-10-23"
    assert "不应进入模型" not in json.dumps(result, ensure_ascii=False)
    assert result["results"][1]["snippet"] == "备用短摘要"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 429, 500, 504])
async def test_http_errors_sanitized_no_retry(monkeypatch, status):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(status, text="secret-echo user-query-echo")
    mock_http(monkeypatch, handler)
    with pytest.raises(SearchUnavailable) as error:
        await DeepSeekSearchProvider(api_key="secret").search("q", 3)
    assert "secret" not in str(error.value) and "user-query" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"results": "wrong"}])
async def test_malformed_result_rejected(monkeypatch, body):
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(SearchUnavailable):
        await DeepSeekSearchProvider(api_key="test").search("q", 3)


@pytest.mark.asyncio
async def test_cancel_propagates_and_closes_request(monkeypatch):
    entered, closed = asyncio.Event(), asyncio.Event()
    async def handler(req):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
    mock_http(monkeypatch, handler)
    task = asyncio.create_task(DeepSeekSearchProvider(api_key="test").search("q", 3))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
async def test_timeout_bounded(monkeypatch):
    async def handler(req):
        await asyncio.sleep(1)
    mock_http(monkeypatch, handler)
    with pytest.raises(SearchUnavailable, match="超时"):
        await DeepSeekSearchProvider(api_key="test", timeout_s=.01).search("q", 3)


@pytest.mark.parametrize("old", ["tavily", "searxng", "serpapi"])
def test_old_config_migrates_without_old_endpoint(tmp_path, old):
    cfg = AppConfig()
    cfg.search.provider = old
    cfg.search.endpoint = "https://old-provider.example/search"
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    restored = load_config(path, with_character=False)
    assert restored.search.provider == "deepseek"
    assert restored.search.endpoint == DeepSeekSearchProvider.ENDPOINT
    assert restored.search.refine_results is False


def test_old_key_not_reused(monkeypatch):
    import keyring
    from yuiro.keychain import load_search_key
    seen = []
    monkeypatch.setattr(keyring, "get_password", lambda service, user: seen.append(service) or None)
    assert load_search_key() is None
    assert seen == ["yuiro-deepseek-search"]


def test_search_test_requires_auth_and_enabled(monkeypatch):
    from yuiro.debug_api import router
    app = FastAPI()
    app.state.app_config = AppConfig()
    app.state.app_config.server.shared_secret = "test-auth"
    app.include_router(router)
    client = TestClient(app)
    assert client.post("/api/search/test", json={"query": "q"}).status_code == 401
    headers = {"x-yuiro-secret": "test-auth"}
    assert client.post("/api/search/test", headers=headers, json={"query": "q"}).status_code == 409
    app.state.app_config.search.enabled = True
    assert client.post("/api/search/test", headers=headers, json={"query": "x"*129}).status_code == 400
