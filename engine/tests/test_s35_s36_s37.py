"""S35–S37 测试：任务续跑 / 媒体信息 / 延迟相关的守卫。

- S35：任务类工具被调用后，引擎注入「任务续跑」提示（否则"计划建完就停"）；
- S36：歌名传给 mpv（否则 media-title 是哈希文件名）；状态带 ready 标记；
- S37：首段切分收紧（TTFA 由第一段合成耗时决定）；_speak 接受调用方传入的 trace。
"""
from __future__ import annotations

import asyncio

import pytest

from yuiro.agent import AgentLoop, LLMChunk, LLMProvider


class _ScriptLLM(LLMProvider):
    """按脚本返回 tool_call 或 token 的流式 LLM（与 test_agent_chat_reply 同型）。"""

    def __init__(self, script: list[dict]) -> None:
        self._script = script
        self._idx = 0
        self.last_messages: list[dict] = []
        self.rounds = 0

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        del tools, kwargs
        self.last_messages = [dict(m) for m in messages]
        self.rounds += 1
        if self._idx >= len(self._script):
            yield LLMChunk(kind="token", content="兜底。")
            yield LLMChunk(kind="done")
            return
        step = self._script[self._idx]
        self._idx += 1
        if "tool" in step:
            yield LLMChunk(
                kind="tool_call",
                content="",
                tool_name=step["tool"],
                tool_args=step.get("args", {}),
            )
        else:
            yield LLMChunk(kind="token", content=step["token"])
        yield LLMChunk(kind="done")


class _Registry:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def schemas(self, toolset=None):  # noqa: ARG002
        return []

    async def execute(self, name, args, task_id, approval_callback=None):  # noqa: ARG002
        self.executed.append(name)
        return '{"status": "ok"}'


# ── S35：任务续跑 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_task_tool_triggers_progress_nudge() -> None:
    """调用任务工具后，下一轮 messages 里应出现「任务续跑」提示。

    背景：TaskRuntime 是状态机 + Journal，自己不驱动执行 —— 实测"计划确认，任务已创建"
    之后再无任何工具调用（用户感知到的"空壳"）。
    """
    llm = _ScriptLLM(
        [
            {"tool": "task_create", "args": {"goal": "整理下载文件夹", "steps": ["扫描", "归档"]}},
            {"token": "开始扫描。"},
        ]
    )
    loop = AgentLoop(
        llm=llm, tools_registry=_Registry(), memory_retriever=None, history_inject=False
    )
    async for _ in loop.send("s1", "帮我一步步整理下载文件夹"):
        pass

    joined = "\n".join(str(m.get("content", "")) for m in llm.last_messages)
    assert "任务续跑" in joined, f"应注入任务续跑提示，实际 messages：{llm.last_messages!r}"
    # 提示必须以 system 角色下发（不污染用户可见对话）
    assert any(
        m.get("role") == "system" and "任务续跑" in str(m.get("content", ""))
        for m in llm.last_messages
    )


@pytest.mark.asyncio
async def test_non_task_tool_does_not_nudge() -> None:
    """普通工具（如 app_open）不应触发续跑 —— 否则每轮都多烧一次 LLM。"""
    llm = _ScriptLLM(
        [
            {"tool": "app_open", "args": {"name": "记事本"}},
            {"token": "开好了。"},
        ]
    )
    loop = AgentLoop(
        llm=llm, tools_registry=_Registry(), memory_retriever=None, history_inject=False
    )
    async for _ in loop.send("s1", "打开记事本"):
        pass

    joined = "\n".join(str(m.get("content", "")) for m in llm.last_messages)
    assert "任务续跑" not in joined


# ── S36：歌名传给 mpv + 状态就绪标记 ─────────────────────────────────────
@pytest.mark.asyncio
async def test_play_urls_passes_force_media_title(monkeypatch) -> None:
    """不带歌名时 mpv 的 media-title 会退化成直链文件名（哈希 .mp3）。"""
    from yuiro.netease import player

    captured: list[list] = []

    async def fake_ipc(cmds, timeout_s=3.0):  # noqa: ARG001
        captured.extend(cmds)
        return [{"error": "success"} for _ in cmds]

    async def fake_ensure() -> bool:
        return True

    async def fake_state() -> dict:
        return {"status": "playing", "title": "晴天"}

    monkeypatch.setattr(player, "_ipc", fake_ipc)
    monkeypatch.setattr(player, "ensure_mpv_async", fake_ensure)
    monkeypatch.setattr(player, "get_state", fake_state)

    ok = await player.play_urls(
        ["http://x/1.mp3", "http://x/2.mp3"], ["周杰伦 - 晴天", "稻香"]
    )
    assert ok is True
    titles = [c for c in captured if len(c) >= 5 and "force-media-title" in str(c[-1])]
    assert len(titles) == 2, f"两首都要带歌名，实际命令：{captured!r}"
    assert "force-media-title=周杰伦 - 晴天" in str(titles[0])


@pytest.mark.asyncio
async def test_get_state_ready_flag(monkeypatch) -> None:
    """刚切歌时 duration 为 0，ready=False —— 别让 LLM 说成"这首 0 秒的歌"。"""
    from yuiro.netease import player

    monkeypatch.setattr(player, "pipe_alive", lambda: True)

    async def fake_ipc(cmds, timeout_s=3.0):  # noqa: ARG001
        data = {
            "pause": False,
            "media-title": "晴天",
            "time-pos": 12.0,
            "duration": 269.0,
            "playlist-count": 5,
            "playlist-pos": 0,
        }
        return [
            {"error": "success", "request_id": i, "data": data[c[1]]}
            for i, c in enumerate(cmds)
        ]

    monkeypatch.setattr(player, "_ipc", fake_ipc)
    st = await player.get_state()
    assert st["title"] == "晴天"
    assert st["duration"] == 269.0
    assert st["ready"] is True
    assert st["queueLength"] == 5


# ── S37：首段收紧 + trace 归属 ────────────────────────────────────────────
def test_first_segment_can_be_tightened() -> None:
    """TTFA 由**第一段**的合成耗时决定：首段过长时按更小阈值再切。"""
    from yuiro.audio import _FIRST_SEG_MAX, split_sentences

    text = "这是一个很长的第一句话，它带着逗号，而且还有第二个分句，整体明显超过了上限。"
    segs = split_sentences(text)
    assert len(segs) == 1, f"该测试需要单段前提，实际：{segs!r}"
    assert len(segs[0]) > _FIRST_SEG_MAX

    tightened = split_sentences(segs[0], max_len=_FIRST_SEG_MAX)
    assert len(tightened) > 1
    assert all(len(s) <= _FIRST_SEG_MAX + 8 for s in tightened)


def test_speak_accepts_caller_trace() -> None:
    """_speak 必须由调用方传 trace。

    修复前它在内部 ``get_trace(session_id)``：用户连续说话时新一轮 trace 已覆盖，
    上一轮的 TTS 会把 ``tts_start`` 打到新对象上（实测 tts_start=75ms，早于 speech_start）。
    """
    import inspect

    from yuiro.audio import VoicePipeline

    params = inspect.signature(VoicePipeline._speak).parameters
    assert "trace" in params, "_speak 应接受调用方传入的 trace"
    assert params["trace"].default is None, "trace 应为可选参数（主动说话路径无 trace）"


def test_audio_module_importable() -> None:
    """冒烟：三条链路改完后模块仍可导入。"""
    from yuiro import audio
    from yuiro.netease import player

    assert asyncio.iscoroutinefunction(player.play_urls)
    assert hasattr(audio, "split_sentences")
