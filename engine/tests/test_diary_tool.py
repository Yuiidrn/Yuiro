"""S51 日记回顾工具测试：只给摘要 / 隐私过滤 / 失败不编造。

最关键的一条是 **`local_only` 不得把内容交给模型** ——
它若漏了，用户"仅保存"的私密日记会被模型当成谈资读出来（隐私事故）。
"""
from __future__ import annotations

import json

import pytest

from yuiro.config import MemoryConfig, PersonaConfig
from yuiro.diary import PRIVACY_LOCAL_ONLY, PRIVACY_SHARED, DiaryStore
from yuiro.tools.diary_tool import DiaryRecallTool


@pytest.fixture()
def store(tmp_path):
    s = DiaryStore(tmp_path / "d.db")
    yield s
    s.close()


def _tool(store) -> DiaryRecallTool:
    return DiaryRecallTool(store_getter=lambda: store)


@pytest.mark.asyncio
async def test_pending_when_not_configured() -> None:
    """日记未启用 → pending（明确说明，而不是假装"没写过"）。"""
    out = json.loads(await DiaryRecallTool().run({}, "t"))
    assert out["status"] == "pending"


@pytest.mark.asyncio
async def test_shared_returns_summary(store: DiaryStore) -> None:
    store.save(
        raw_text="今天去公园跑步",
        summary="公园跑步",
        mood_tags=["轻松"],
        privacy=PRIVACY_SHARED,
    )
    out = json.loads(await _tool(store).run({"query": "跑步"}, "t"))
    assert out["status"] == "ok" and out["count"] == 1
    item = out["items"][0]
    assert item["shared"] is True
    assert item["summary"] == "公园跑步"
    assert item["mood"] == ["轻松"]


@pytest.mark.asyncio
async def test_local_only_returns_existence_without_content(store: DiaryStore) -> None:
    """★ 「仅保存」：说明它存在，但**不把内容交给模型**（§9.2.4）。"""
    store.save(
        raw_text="很私密的一段话内容",
        summary="私密摘要",
        privacy=PRIVACY_LOCAL_ONLY,
    )
    out = json.loads(await _tool(store).run({}, "t"))
    assert out["count"] == 1
    item = out["items"][0]
    assert item["shared"] is False
    assert not item.get("summary")
    blob = json.dumps(out, ensure_ascii=False)
    assert "很私密的一段话内容" not in blob, "私密内容绝不能进入模型上下文"
    assert "私密摘要" not in blob


@pytest.mark.asyncio
async def test_empty_result_is_honest(store: DiaryStore) -> None:
    out = json.loads(await _tool(store).run({"query": "不存在的内容"}, "t"))
    assert out["status"] == "ok" and out["count"] == 0
    assert "没找到" in out["note"]


@pytest.mark.asyncio
async def test_search_failure_is_honest(store: DiaryStore, monkeypatch) -> None:
    """检索失败**绝不编造"你写过…"** —— 如实报错。"""

    def _boom(*_a, **_k):
        raise RuntimeError("db is locked")

    monkeypatch.setattr(store, "search", _boom)
    out = json.loads(await _tool(store).run({"query": "x"}, "t"))
    assert out["status"] == "error"
    assert "items" not in out


@pytest.mark.asyncio
async def test_bad_limit_falls_back(store: DiaryStore) -> None:
    store.save(raw_text="今天去公园跑步", privacy=PRIVACY_SHARED)
    out = json.loads(await _tool(store).run({"limit": "很多"}, "t"))
    assert out["status"] == "ok"


def test_registered_in_agent_loop() -> None:
    """注册即"她能用它帮用户翻日记"（延迟绑定 getter，顺序无关）。"""
    from yuiro.agent import build_agent_loop

    loop = build_agent_loop(
        base_url="http://127.0.0.1:1/v1",
        model="m",
        api_key="k",
        persona=PersonaConfig(),
        memory_config=MemoryConfig(),
        diary_getter=lambda: None,
    )
    names = [s["function"]["name"] for s in loop._tools.schemas()]
    assert "diary_recall" in names


def test_effect_is_read() -> None:
    """只读 → 崩溃恢复可安全重放（S48）。"""
    from yuiro.tools import EFFECT_READ, resolve_effect

    tool = DiaryRecallTool()
    assert tool.effect == EFFECT_READ
    assert resolve_effect(tool) == EFFECT_READ
