"""S11：Capability Policy（风险分级 / 四档决策 / 可见性 / AgentLoop 拦截）。

对应 docs/plan/S11-capability-policy.md。
"""
from __future__ import annotations

import json

import pytest

from yuiro.agent import AgentLoop, LLMChunk, LLMProvider
from yuiro.capability import CapabilityView, Policy, RiskLevel


# ---- 风险分级 ---------------------------------------------------------------
def test_risk_table() -> None:
    p = Policy()
    assert p.risk_of("file_read") == RiskLevel.LOW
    assert p.risk_of("media_control") == RiskLevel.LOW
    assert p.risk_of("app_open") == RiskLevel.MEDIUM
    assert p.risk_of("file_write") == RiskLevel.MEDIUM
    assert p.risk_of("terminal_exec") == RiskLevel.HIGH
    assert p.risk_of("未登记工具") == RiskLevel.MEDIUM  # 保守默认


# ---- 四档决策矩阵 -----------------------------------------------------------
def test_normal_matrix() -> None:
    p = Policy(profile="normal")
    assert p.decide("file_read").action == "allow"
    assert p.decide("file_write").action == "ask"
    assert p.decide("app_open").action == "ask"
    assert p.decide("terminal_exec").action == "ask"
    assert not p.decide("file_write").denied
    assert p.decide("file_write").requires_approval


def test_read_only_denies_writes() -> None:
    p = Policy(profile="read_only")
    assert p.decide("file_read").action == "allow"
    d = p.decide("file_write")
    assert d.action == "deny" and d.denied
    assert "超出当前权限档位" in d.reason
    assert p.decide("file_create").action == "deny"
    assert p.decide("app_open").action == "deny"
    assert p.decide("terminal_exec").action == "deny"


def test_privacy_denies_writes() -> None:
    p = Policy(profile="privacy")
    assert p.decide("file_write").action == "deny"


def test_trusted_allows_medium_asks_high() -> None:
    p = Policy(profile="trusted")
    assert p.decide("file_write").action == "allow"
    assert p.decide("app_open").action == "allow"
    assert p.decide("terminal_exec").action == "ask"


def test_unknown_profile_falls_back_normal() -> None:
    p = Policy(profile="nonsense")
    assert p.profile_name == "normal"
    assert p.profile_missing is True
    assert Policy().profile_name == "normal"
    assert Policy(profile=None).profile_missing is False


# ---- CapabilityView ---------------------------------------------------------
class _Reg:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    def schemas(self, toolset=None):
        return [{"type": "function", "function": {"name": n}} for n in self._names]


def test_view_filters_denied() -> None:
    reg = _Reg(["file_read", "file_write", "app_open", "media_control"])
    view = CapabilityView(reg, Policy(profile="read_only"))
    assert [s["function"]["name"] for s in view.visible_schemas()] == [
        "file_read",
        "media_control",
    ]
    assert set(view.hidden_tools()) == {"file_write", "app_open"}


def test_view_without_policy_or_registry() -> None:
    assert len(CapabilityView(_Reg(["a", "b"]), None).visible_schemas()) == 2
    assert CapabilityView(None, Policy()).visible_schemas() == []
    assert CapabilityView(None, Policy()).hidden_tools() == []


# ---- AgentLoop 集成 ---------------------------------------------------------
class _ScriptLLM(LLMProvider):
    """第一轮发起 tool_call，之后返回文本。"""

    def __init__(self, tool: str) -> None:
        self._tool = tool
        self._idx = 0

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        self._idx += 1
        if self._idx == 1:
            yield LLMChunk(kind="tool_call", content="", tool_name=self._tool, tool_args={})
        else:
            yield LLMChunk(kind="token", content="好的")
        yield LLMChunk(kind="done")


class _CaptureLLM(LLMProvider):
    """记录 LLM 实际看到的工具表。"""

    def __init__(self, seen: dict) -> None:
        self._seen = seen

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        self._seen["tools"] = [t["function"]["name"] for t in (tools or [])]
        yield LLMChunk(kind="token", content="好")
        yield LLMChunk(kind="done")


class _RecordingRegistry:
    def __init__(self, names: list[str]) -> None:
        self.executed: list[str] = []
        self._names = names

    def schemas(self, toolset=None):
        return [{"type": "function", "function": {"name": n}} for n in self._names]

    async def execute(self, name, args, task_id, approval_callback=None):
        self.executed.append(name)
        return json.dumps({"status": "ok"})


def _loop(llm, reg, policy=None) -> AgentLoop:
    return AgentLoop(
        llm=llm,
        tools_registry=reg,
        memory_retriever=None,
        system_prompt="S",
        persona_prompt="P",
        policy=policy,
    )


@pytest.mark.asyncio
async def test_denied_tool_not_executed() -> None:
    """read_only 档：被拒工具不执行，返回结构化 denied 结果。"""
    reg = _RecordingRegistry(["file_write"])
    loop = _loop(_ScriptLLM("file_write"), reg, Policy(profile="read_only"))
    chunks = [c async for c in loop.send("s1", "写个文件")]
    assert reg.executed == []
    results = [c.content for c in chunks if c.kind == "tool_result"]
    assert results and any("denied" in r for r in results)


@pytest.mark.asyncio
async def test_ask_tool_executes_in_auto_mode() -> None:
    """normal 档 + 无审批门（等价 auto 模式）：ask 的工具照常执行（零行为变化）。"""
    reg = _RecordingRegistry(["file_write"])
    loop = _loop(_ScriptLLM("file_write"), reg, Policy(profile="normal"))
    _ = [c async for c in loop.send("s1", "写个文件")]
    assert reg.executed == ["file_write"]


@pytest.mark.asyncio
async def test_llm_tool_table_filtered() -> None:
    """read_only 档：被拒工具不出现在 LLM 的工具表里。"""
    reg = _RecordingRegistry(["file_read", "file_write"])
    seen: dict = {}
    loop = _loop(_CaptureLLM(seen), reg, Policy(profile="read_only"))
    _ = [c async for c in loop.send("s1", "你好")]
    assert seen["tools"] == ["file_read"]


@pytest.mark.asyncio
async def test_no_policy_keeps_full_tool_table() -> None:
    """无 policy（旧路径）：工具表全量，行为与 S10 前一致。"""
    reg = _RecordingRegistry(["file_read", "file_write"])
    seen: dict = {}
    loop = _loop(_CaptureLLM(seen), reg)
    _ = [c async for c in loop.send("s1", "你好")]
    assert seen["tools"] == ["file_read", "file_write"]


# ---- 配置 / 装配 -------------------------------------------------------------
def test_config_defaults() -> None:
    from yuiro.config import CapabilityConfig

    assert CapabilityConfig().profile == "normal"


def test_build_agent_loop_wires_policy() -> None:
    from yuiro.agent import build_agent_loop
    from yuiro.config import CapabilityConfig, MemoryConfig, PersonaConfig

    loop = build_agent_loop(
        base_url="http://127.0.0.1:1/v1",
        model="m",
        api_key="k",
        persona=PersonaConfig(),
        memory_config=MemoryConfig(),
        capability_config=CapabilityConfig(profile="read_only"),
    )
    assert loop._policy is not None
    assert loop._policy.profile_name == "read_only"
