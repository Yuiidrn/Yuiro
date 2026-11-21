"""S09：ArtifactStore（落盘/分片/LRU）+ clip_tool_result 接入 + artifact_read 工具。

对应 docs/plan/S09-artifact-store.md。
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from yuiro.artifact import ArtifactStore
from yuiro.context import ContextEngine
from yuiro.tools.artifact_tool import ArtifactReadTool


@pytest.fixture()
def adir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


def _store(tmp: str, max_items: int = 50) -> ArtifactStore:
    return ArtifactStore(store_dir=os.path.join(tmp, "artifacts"), max_items=max_items)


# ---- 存储 -------------------------------------------------------------------
def test_put_get_read_slice(adir) -> None:
    s = _store(adir)
    art = s.put("file_read", "0123456789")
    assert art.size == 10
    assert s.get(art.id).content == "0123456789"
    assert s.read_slice(art.id, 0, 4) == "0123"
    assert s.read_slice(art.id, 8, 100) == "89"  # length 超出 → 截断
    assert s.read_slice(art.id, 100, 10) == ""  # start 越界
    assert s.read_slice("nope", 0, 10) == ""


def test_prune_lru(adir) -> None:
    s = _store(adir, max_items=2)
    a1 = s.put("t", "one")
    a2 = s.put("t", "two")
    a3 = s.put("t", "three")
    assert s.get(a1.id) is None  # 最旧被清理
    assert s.get(a2.id) is not None
    assert s.get(a3.id) is not None


def test_persist_and_restore(adir) -> None:
    s = _store(adir)
    art = s.put("file_read", "hello artifact")
    s2 = _store(adir)  # 模拟重启
    restored = s2.get(art.id)
    assert restored is not None
    assert restored.content == "hello artifact"


# ---- clip_tool_result -------------------------------------------------------
def test_clip_with_store(adir) -> None:
    s = _store(adir)
    e = ContextEngine(
        system_prompt="S", persona_prompt="P", tool_result_max_chars=10, artifacts=s
    )
    out = e.clip_tool_result("x" * 100, "file_read")
    assert "已存入 artifact" in out
    assert "artifact_read" in out
    aid = out.split("artifact：")[1].split("；")[0]
    assert s.get(aid) is not None
    assert s.get(aid).content == "x" * 100  # 完整内容可回读


def test_clip_without_store_is_plain_truncate() -> None:
    e = ContextEngine(system_prompt="S", persona_prompt="P", tool_result_max_chars=10)
    out = e.clip_tool_result("y" * 100, "file_read")
    assert "已截断" in out
    assert "artifact" not in out


def test_clip_short_passthrough(adir) -> None:
    s = _store(adir)
    e = ContextEngine(
        system_prompt="S", persona_prompt="P", tool_result_max_chars=100, artifacts=s
    )
    assert e.clip_tool_result("short", "t") == "short"
    assert s.list() == []  # 短结果不产生 artifact


# ---- 工具 -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_artifact_read_tool(adir) -> None:
    s = _store(adir)
    art = s.put("file_read", "A" * 50)
    tool = ArtifactReadTool(store=s)
    out = json.loads(await tool.run({"artifact_id": art.id, "start": 10, "length": 20}, "t"))
    assert out["status"] == "ok"
    assert out["content"] == "A" * 20
    assert out["end"] == 30
    assert out["total"] == 50
    assert "还有 20 字符未显示" in out["note"]
    assert "start=30" in out["note"]
    # 读完最后一段
    out2 = json.loads(await tool.run({"artifact_id": art.id, "start": 30, "length": 20}, "t"))
    assert "还有 0 字符" in out2["note"]
    # 不存在
    out3 = json.loads(await tool.run({"artifact_id": "nope"}, "t"))
    assert out3["status"] == "error"
    # 空 id
    out4 = json.loads(await tool.run({}, "t"))
    assert out4["status"] == "error"


@pytest.mark.asyncio
async def test_artifact_read_tool_without_store() -> None:
    out = json.loads(await ArtifactReadTool().run({"artifact_id": "x"}, "t"))
    assert out["status"] == "pending"


def test_artifact_tool_schema() -> None:
    s = ArtifactReadTool().schema()
    assert s["function"]["name"] == "artifact_read"
    assert "artifact_id" in s["function"]["parameters"]["properties"]


def test_build_agent_loop_registers_artifact_tool(adir) -> None:
    from yuiro.agent import build_agent_loop
    from yuiro.config import MemoryConfig, PersonaConfig

    s = _store(adir)
    loop = build_agent_loop(
        base_url="http://127.0.0.1:1/v1",
        model="m",
        api_key="k",
        persona=PersonaConfig(),
        memory_config=MemoryConfig(),
        artifact_store=s,
    )
    names = [x["function"]["name"] for x in loop._tools.schemas()]
    assert "artifact_read" in names
    assert loop._context._artifacts is s
