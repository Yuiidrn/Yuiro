"""S51 日记编排测试：解构容错 / 隐私三档 / **记忆联动**。

本文件的重点是**联动**（用真实 MemorySystem 验证"记忆真的被写/被删"），
因为这里最容易出"看起来对了但实际没同步"的问题：

- `local_only` 绝不能碰记忆库；
- `shared → local_only` **必须删掉已写记忆**（否则是谎报隐私）；
- 删日记要连带删记忆；
- **解构失败绝不能丢掉用户的日记**。
"""
from __future__ import annotations

import pytest

from yuiro.agent import LLMChunk, LLMProvider
from yuiro.diary import (
    PRIVACY_DISCARD,
    PRIVACY_LOCAL_ONLY,
    PRIVACY_SHARED,
    DiaryStore,
)
from yuiro.diary.service import DiaryService
from yuiro.memory import MemorySystem

_GOOD_JSON = (
    '{"polished_text":"今天去公园跑步，很轻松。","summary":"公园跑步","mood_tags":["轻松"],'
    '"topics":["跑步"],"entities":[{"type":"place","name":"公园"}],'
    '"followup_question":"明天还去跑吗？","narrative_type":"short"}'
)


class _FakeLLM(LLMProvider):
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.prompts: list[str] = []

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        del tools, kwargs
        self.prompts.append(str(messages[-1].get("content", "")))
        yield LLMChunk(kind="token", content=self._payload)
        yield LLMChunk(kind="done")


@pytest.fixture()
def env(tmp_path):
    store = DiaryStore(tmp_path / "diary.db")
    mem = MemorySystem(str(tmp_path / "mem.db"), rrf_k=60, top_k=3, embedder_model="md5")
    svc = DiaryService(store, memory=mem, llm=_FakeLLM(_GOOD_JSON))
    yield svc, store, mem
    mem.close()
    store.close()


def _mem_count(mem: MemorySystem) -> int:
    return int(mem.store.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])


def _mem_texts(mem: MemorySystem) -> list[str]:
    return [
        str(r["text"])
        for r in mem.store.conn.execute("SELECT text FROM messages").fetchall()
    ]


# ── 提交路径 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_submit_local_only_never_touches_memory(env) -> None:
    """★ 「仅保存」的语义 = 她检索不到 —— 由**不写入**保证（最小权限）。"""
    svc, store, mem = env
    res = await svc.submit("今天去公园跑步", privacy=PRIVACY_LOCAL_ONLY)
    assert res["ok"] and res["diary_id"] > 0
    assert res["memory_written"] is False
    assert _mem_count(mem) == 0, "local_only 绝不能碰记忆库"
    row = store.get(res["diary_id"])
    assert row["summary"] == "公园跑步"
    assert row["mood_tags"] == ["轻松"]
    assert row["memory_written"] is False


@pytest.mark.asyncio
async def test_submit_shared_writes_memory_with_source_mark(env) -> None:
    """`shared` → 写 L2，且文本带**来源标注**（避免她说"我看了你的日记"）。"""
    svc, store, mem = env
    res = await svc.submit("今天去公园跑步", privacy=PRIVACY_SHARED)
    assert res["memory_written"] is True
    assert _mem_count(mem) == 1
    assert "[来自用户的日记" in _mem_texts(mem)[0]
    assert store.get(res["diary_id"])["memory_written"] is True


@pytest.mark.asyncio
async def test_submit_discard_persists_nothing(env) -> None:
    """阅后即焚：不落库、不写记忆。"""
    svc, store, mem = env
    res = await svc.submit("不想留下的一段话", privacy=PRIVACY_DISCARD)
    assert res["ok"] and res["discard"] is True
    assert store.stats()["total"] == 0
    assert _mem_count(mem) == 0


@pytest.mark.asyncio
async def test_deconstruct_failure_still_saves_diary(env) -> None:
    """★ 解构失败**绝不丢日记**：原文照存，结构化留空。"""
    svc, store, _mem = env
    svc._llm = _FakeLLM("对不起我不会输出 JSON")
    res = await svc.submit("今天很难忘", privacy=PRIVACY_LOCAL_ONLY)
    assert res["ok"] and res["deconstructed"] is False
    row = store.get(res["diary_id"])
    assert row["raw_text"] == "今天很难忘"
    assert row["polished_text"] == "今天很难忘", "无解构时应回退原文"
    assert row["mood_tags"] == []


def test_parse_json_tolerates_code_fence() -> None:
    """模型爱用 ```json 围栏 —— 必须容忍（否则每次都当解构失败）。"""
    raw = '好的：\n```json\n{"summary":"x"}\n```\n以上。'
    assert DiaryService._parse_json(raw) == {"summary": "x"}
    assert DiaryService._parse_json("完全不是 JSON") == {}


# ── ★ 隐私联动（最易出错处）────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_change_privacy_shared_to_local_removes_memory(env) -> None:
    """★ 改成"仅保存"必须**删掉已写记忆** —— 否则是谎报隐私（§9.1.4）。"""
    svc, store, mem = env
    did = (await svc.submit("今天去公园跑步", privacy=PRIVACY_SHARED))["diary_id"]
    assert _mem_count(mem) == 1

    res = await svc.change_privacy(did, PRIVACY_LOCAL_ONLY)
    assert res["ok"] and res["from"] == PRIVACY_SHARED and res["to"] == PRIVACY_LOCAL_ONLY
    assert res["memory_removed"] == 1
    assert _mem_count(mem) == 0, "改成私密后记忆必须真的没了"
    assert store.get(did)["memory_written"] is False
    # 三表齐删（S50 教训）：FTS 也不得残留
    assert mem.store.conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_change_privacy_local_to_shared_writes_memory(env) -> None:
    svc, _store, mem = env
    did = (await svc.submit("今天去公园跑步", privacy=PRIVACY_LOCAL_ONLY))["diary_id"]
    assert _mem_count(mem) == 0
    res = await svc.change_privacy(did, PRIVACY_SHARED)
    assert res["memory_written"] == 1
    assert _mem_count(mem) == 1


@pytest.mark.asyncio
async def test_change_privacy_missing_diary(env) -> None:
    svc, _store, _mem = env
    res = await svc.change_privacy(9999, PRIVACY_SHARED)
    assert res["ok"] is False


@pytest.mark.asyncio
async def test_delete_diary_also_removes_memory(env) -> None:
    """删日记默认**连带删记忆**（符合直觉，§9.6）。"""
    svc, store, mem = env
    did = (await svc.submit("今天去公园跑步", privacy=PRIVACY_SHARED))["diary_id"]
    assert _mem_count(mem) == 1
    res = await svc.delete(did)
    assert res["ok"] and res["memory_removed"] == 1
    assert store.get(did) is None
    assert _mem_count(mem) == 0


# ── 总评 ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_closing_review_is_persisted(env) -> None:
    svc, store, _mem = env
    did = (await svc.submit("今天去公园跑步", privacy=PRIVACY_LOCAL_ONLY))["diary_id"]
    res = await svc.closing_review(did)
    assert res["ok"] is True
    assert store.get(did)["closing_review"], "总评应落库（可回看，不重复播报）"


@pytest.mark.asyncio
async def test_closing_review_without_llm_is_not_fatal(env) -> None:
    """总评失败**不阻塞流程**（§8.2.3）：返回 ok=False，调用方退回简短回应。"""
    svc, _store, _mem = env
    svc._llm = None
    did = (await svc.submit("今天去公园跑步", privacy=PRIVACY_LOCAL_ONLY))["diary_id"]
    res = await svc.closing_review(did)
    assert res["ok"] is False
