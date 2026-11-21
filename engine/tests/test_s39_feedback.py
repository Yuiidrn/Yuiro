"""S39 测试：任务驱动（F4）+ 活动反馈（G4）。

- **任务驱动**：判据是**任务状态**（真实进度），不是"猜它想不想继续"；
- **活动反馈**：工具执行前发 `agent.activity`（前端状态行的数据源）。
"""
from __future__ import annotations

import asyncio
import json
import tempfile

import pytest

from yuiro.agent import AgentLoop, LLMChunk, LLMProvider
from yuiro.agent.activity import activity_motion_slot, activity_text, is_long_task_tool
from yuiro.runtime.events import EventBus
from yuiro.task import TaskRuntime


# ── 活动文案（G4 的基础）────────────────────────────────────────────────
def test_activity_text_known_tools() -> None:
    assert activity_text("file_list") == "正在查看目录…"
    assert activity_text("file_move").startswith("正在移动")
    assert activity_text("netease_play").startswith("正在")


def test_activity_text_unknown_falls_back() -> None:
    """未登记工具回退为通用文案 —— 不抛错、也不泄漏工具内部名。"""
    assert activity_text("brand_new_tool") == "正在处理…"
    assert activity_text("") == ""


def test_activity_motion_only_for_notable_tools() -> None:
    """S53 起只给语义槽位，不再给模型私有的数值索引。"""
    assert activity_motion_slot("file_read") == "look"   # 查看
    assert activity_motion_slot("file_move") == "look"   # 处理中（没有"手部"槽位）
    assert activity_motion_slot("app_open") == "greet"   # 对外操作
    assert activity_motion_slot("task_list") is None     # 瞬时操作不配动作（避免乱动）
    assert is_long_task_tool("file_list") is True
    assert is_long_task_tool("task_list") is False


# ── 测试替身 ─────────────────────────────────────────────────────────────
class _ScriptLLM(LLMProvider):
    def __init__(self, script: list[dict]) -> None:
        self._s = script
        self._i = 0
        self.last_messages: list[dict] = []
        self.rounds = 0

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        del tools, kwargs
        self.last_messages = [dict(m) for m in messages]
        self.rounds += 1
        if self._i >= len(self._s):
            yield LLMChunk(kind="token", content="好。")
            yield LLMChunk(kind="done")
            return
        step = self._s[self._i]
        self._i += 1
        if "tool" in step:
            yield LLMChunk(kind="tool_call", content="",
                           tool_name=step["tool"], tool_args=step.get("args", {}))
        else:
            yield LLMChunk(kind="token", content=step["token"])
        yield LLMChunk(kind="done")


class _Registry:
    """最小注册表；``task_create`` 会真的建任务（否则任务不存在，驱动无从验证）。"""

    def __init__(self, tasks=None) -> None:
        self._tasks = tasks
        self.executed: list[str] = []

    def schemas(self, toolset=None):
        return []

    async def execute(self, name, args, task_id, approval_callback=None):
        self.executed.append(name)
        if name == "task_create" and self._tasks is not None:
            task = await self._tasks.create(
                goal=str(args.get("goal", "")),
                steps=[str(s) for s in (args.get("steps") or [])],
                session_id="s1",
            )
            return json.dumps({"status": "ok", "task_id": task.id}, ensure_ascii=False)
        return '{"status": "ok"}'


# ── 任务驱动（F4）────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_task_driven_continuation_carries_progress() -> None:
    """创建任务后应注入**带真实进度**的续跑提示（"0/2｜扫描文件"）。"""
    tmp = tempfile.mkdtemp(prefix="yuiro_s39_")
    tasks = TaskRuntime(store_dir=tmp)
    llm = _ScriptLLM([
        {"tool": "task_create", "args": {"goal": "整理下载文件夹", "steps": ["扫描文件", "分类移动"]}},
        {"token": "扫完了，接下来我把它们分一下。"},
    ])
    loop = AgentLoop(
        llm=llm, tools_registry=_Registry(tasks), memory_retriever=None,
        task_runtime=tasks, history_inject=False,
    )
    async for _ in loop.send("s1", "帮我整理下载文件夹"):
        pass

    joined = "\n".join(str(m.get("content", "")) for m in llm.last_messages)
    assert "任务续跑" in joined, f"应注入任务驱动提示，实际：{llm.last_messages!r}"
    assert "0/2" in joined, "续跑提示应带上真实进度（否则模型不知道做到哪了）"
    assert "扫描文件" in joined, "续跑提示应带上当前步骤描述"


@pytest.mark.asyncio
async def test_no_task_no_task_driven_nudge() -> None:
    """没有活跃任务时不该有任务驱动提示（否则每轮白烧一次 LLM）。"""
    llm = _ScriptLLM([{"token": "你好呀。"}])
    loop = AgentLoop(
        llm=llm, tools_registry=_Registry(), memory_retriever=None, history_inject=False
    )
    async for _ in loop.send("s1", "你好"):
        pass
    joined = "\n".join(str(m.get("content", "")) for m in llm.last_messages)
    assert "任务续跑" not in joined


# ── 活动反馈（G4）────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_activity_event_emitted_before_tool_runs() -> None:
    """工具执行前应发 `agent.activity`（前端状态行靠它）。"""
    events = EventBus()
    seen: list[dict] = []

    async def on_activity(event) -> None:
        seen.append(getattr(event, "payload", {}) or {})

    events.subscribe("agent.activity", on_activity)
    llm = _ScriptLLM([
        {"tool": "app_open", "args": {"name": "记事本"}},
        {"token": "开好了。"},
    ])
    loop = AgentLoop(
        llm=llm, tools_registry=_Registry(), memory_retriever=None,
        events=events, history_inject=False,
    )
    async for _ in loop.send("s1", "打开记事本"):
        pass
    await asyncio.sleep(0.05)

    assert seen, "应发出 agent.activity 事件"
    assert seen[0]["text"] == "正在打开应用…"
    assert seen[0]["tool"] == "app_open"
    # S53：只下发语义槽位（具体动作由主进程按当前模型档案/清单解析）
    assert seen[0]["motion_slot"] == "greet"  # 对外操作 → 招呼
    assert "motion" not in seen[0]


@pytest.mark.asyncio
async def test_activity_event_without_eventbus_is_silent() -> None:
    """没有 EventBus 时静默（反馈不该影响执行）。"""
    llm = _ScriptLLM([{"tool": "app_open", "args": {"name": "记事本"}}, {"token": "好。"}])
    loop = AgentLoop(
        llm=llm, tools_registry=_Registry(), memory_retriever=None, history_inject=False
    )
    async for _ in loop.send("s1", "打开记事本"):
        pass  # 不抛异常即通过
