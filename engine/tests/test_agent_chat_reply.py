"""AgentLoop（auto 并行架构）+ 预路由 + 循环终止 + 记忆分层注入测试。

架构说明：本套件已从「tool_choice=required 强制 + chat_reply 逃生舱」迁移到
auto 并行架构——LLM 自由输出闲聊文本，工具调用按需旁路触发，两者不再互斥。
不依赖外部 LLM key，用 FakeLLM 模拟各场景。验证：
1. 纯闲聊：LLM 直接输出文本，不调任何工具，单轮结束（无多余循环）。
2. 命令意图（预路由命中）→ 确定性触发真实工具。
3. 工具执行成功去重 / 失败限流 / 非 JSON 返回归一为 text 防空转。
4. 无进展早停：重复无效调用不再耗尽轮数。
5. 记忆分层注入：默认过滤 L2 情景，只注入 L3 事实/知识；episodic_inject 时全量。
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid

import pytest

from yuiro.agent import AgentLoop, LLMChunk, LLMProvider, ToolSchema
from yuiro.memory import Memory, MemorySystem


class FakeRequiredLLM(LLMProvider):
    """按脚本返回 tool_call 或 token 的流式 LLM（auto 架构下自由输出）。

    ``script``：list of rounds。每 round 是 {"tool": "<名称>", "args": {...}} 或
    {"token": "闲聊文本"}。按调用次序顺延返回。
    """

    def __init__(self, script: list[dict]) -> None:
        self._script = script
        self._idx = 0
        self.calls: list[str] = []
        self.last_kwargs: dict = {}
        self.last_messages: list[dict] = []

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        self.calls.append(str(messages[-1].get("content", "")))
        self.last_messages = [dict(m) for m in messages]
        self.last_kwargs = kwargs
        if self._idx >= len(self._script):
            yield LLMChunk(kind="token", content="兜底回复。")
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


class FakeRegistry:
    """记录真实工具执行，返回成功 JSON。"""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def schemas(self, toolset=None):  # noqa: ARG002
        return [
            {
                "type": "function",
                "function": {
                    "name": "app_open",
                    "description": "打开应用",
                    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}},
                },
            },
        ]

    async def execute(self, name, args, task_id, approval_callback=None):  # noqa: ARG002
        self.executed.append(name)
        return '{"status": "ok"}'


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['暂停', '请帮我处理音乐'])
async def test_disabled_music_cannot_bypass_schema_via_prefill_or_llm(text):
    class MediaRegistry(FakeRegistry):
        def schemas(self, toolset=None):
            return [{'type':'function','function':{'name':name,'description':name,
                    'parameters':{'type':'object','properties':{}}}}
                    for name in ['netease_control','netease_play']]
    reg=MediaRegistry()
    llm=FakeRequiredLLM([{'tool':'netease_play','args':{}},{'token':'请点击网易云播放。'}])
    loop=AgentLoop(llm=llm, tools_registry=reg, memory_retriever=None)
    async for _ in loop.send('disabled-media',text,
                            disabled_tools={'netease_play','netease_control'}):
        pass
    assert not reg.executed
    assert any('当前音乐界面' in m.get('content','') for m in llm.last_messages
               if isinstance(m.get('content'),str))


def _tmp_db() -> str:
    """用唯一固定路径避免 Windows 下 tempfile teardown 与 SQLite 锁冲突。"""
    return os.path.join(tempfile.gettempdir(), f"yuiro_test_{uuid.uuid4().hex}.db")


def _cleanup(db: str) -> None:
    if os.path.exists(db):
        try:
            os.remove(db)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_pure_chat_single_round() -> None:
    """纯闲聊：LLM 直接输出人设文本，不调工具，单轮结束（auto 架构核心行为）。"""
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()
        llm = FakeRequiredLLM([
            {"token": "今天天气真好呀，要一起聊聊天吗？"},
        ])
        loop = AgentLoop(
            llm=llm,
            tools_registry=reg,
            memory_retriever=memory,
            memory_writer=memory.remember,
        )
        out = []
        async for c in loop.send("s1", "在吗？陪我聊会天"):
            if c.kind == "token":
                out.append(c.content)
        text = "".join(out)
        assert "天气真好" in text, f"闲聊文本未输出，得到：{text!r}"
        assert reg.executed == [], f"纯闲聊不应执行任何工具，却执行了：{reg.executed}"
        # auto 架构：tool_choice 恒为 auto（不再有 required 强制）
        assert llm.last_kwargs.get("tool_choice") == "auto", (
            f"tool_choice 应恒为 auto，实际：{llm.last_kwargs}"
        )
        # 纯闲聊单轮结束：不应为凑工具而续问
        assert len(llm.calls) == 1, f"纯闲聊应单轮结束，实际调 LLM {len(llm.calls)} 次"
        memory.close()
    finally:
        _cleanup(db)


@pytest.mark.asyncio
async def test_keyword_prefill_bypasses_llm() -> None:
    """命令意图走预路由，不调 LLM，直接执行真实工具。"""
    llm = FakeRequiredLLM([{"token": "不应到达这里"}])
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()
        loop = AgentLoop(
            llm=llm,
            tools_registry=reg,
            memory_retriever=memory,
            memory_writer=memory.remember,
        )
        async for _ in loop.send("s1", "打开网易云音乐"):
            pass
        assert reg.executed == ["app_open"], (
            f"预路由应确定性触发 app_open，实际：{reg.executed}"
        )
        # 预路由：第 1 轮不调 LLM，LLM 仅在工具执行后的 tool_result 回传轮被调用一次。
        # 断言 LLM 调用次数为 1（首轮被预路由跳过），且调用时 messages 首条非 tool 回传。
        assert len(llm.calls) == 1, (
            f"预路由首轮应跳过 LLM，实际 LLM 被调用 {len(llm.calls)} 次：{llm.calls}"
        )
        memory.close()
    finally:
        _cleanup(db)


class FakeMemory:
    """模拟记忆检索，返回混合类型 Memory（L2 情景无 kind / L3 fact / knowledge）。"""

    def __init__(self, mems: list) -> None:
        self._mems = mems

    async def retrieve(self, text, top_k=3):  # noqa: ARG002
        return self._mems

    def close(self) -> None:  # noqa: D401
        pass


def _mem(text: str, kind=None) -> Memory:
    meta = {"rowid": 1, "ts": 1.0, "salience": 1.0, "distance": 0.5, "fts_rank": 1.0}
    if kind is not None:
        meta["kind"] = kind
    return Memory(text=text, score=1.0, meta=meta)


@pytest.mark.asyncio
async def test_whitelist_bare_noun_triggers_app_open() -> None:
    """裸名词命中应用名白名单 → 确定性触发 app_open，不弹审批。"""
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()
        loop = AgentLoop(
            llm=FakeRequiredLLM([{"token": "不应到这里"}]),
            tools_registry=reg,
            memory_retriever=memory,
            memory_writer=memory.remember,
        )
        async for _ in loop.send("s1", "记事本"):
            pass
        assert reg.executed == ["app_open"], f"记事本应触发 app_open，实际：{reg.executed}"
        memory.close()
    finally:
        _cleanup(db)


@pytest.mark.asyncio
async def test_chit_chat_not_mistaken_for_app_open() -> None:
    """回归修复：中文句子不再被预路由误判为 app_open（如'你会感到孤独吗'）。"""
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()
        loop = AgentLoop(
            llm=FakeRequiredLLM([{"token": "嗯，我也会有这种感受呢。"}]),
            tools_registry=reg,
            memory_retriever=memory,
            memory_writer=memory.remember,
        )
        async for _ in loop.send("s1", "你会感到孤独吗"):
            pass
        assert reg.executed == [], (
            f"中文句子不应触发 app_open，实际：{reg.executed}"
        )
        memory.close()
    finally:
        _cleanup(db)


@pytest.mark.asyncio
async def test_generalized_no_tool_sentences_do_not_open_app() -> None:
    """泛化：多种无工具意图的中文句子都不触发 app_open（非穷举特例）。"""
    no_tool = [
        "你会感到孤独吗",
        "你想听歌吗",
        "我有点难过",
        "今天天气怎么样",
        "帮我看看明天会不会下雨",
        "你是谁呀",
        "我好无聊",
        "能不能陪我聊聊天",
    ]
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()
        llm = FakeRequiredLLM([{"token": "嗯嗯，我在听你说。"}])
        loop = AgentLoop(
            llm=llm, tools_registry=reg, memory_retriever=memory,
            memory_writer=memory.remember,
        )
        for sent in no_tool:
            reg.executed.clear()
            async for _ in loop.send(f"s-{sent[:4]}", sent):
                pass
            assert reg.executed == [], (
                f"句子 {sent!r} 不应触发 app_open，实际：{reg.executed}"
            )
        memory.close()
    finally:
        _cleanup(db)


@pytest.mark.asyncio
async def test_generalized_real_commands_still_work() -> None:
    """泛化：真实命令仍必须命中（明确动词 + 白名单裸名词）。"""
    should_open = {
        "打开记事本": "记事本",
        "启动计算器": "计算器",
        "记事本": "记事本",
        "网易云音乐": "网易云音乐",
        "打开微信": "微信",
    }
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()
        llm = FakeRequiredLLM([{"token": "好的，马上开。"}])
        loop = AgentLoop(
            llm=llm, tools_registry=reg, memory_retriever=memory,
            memory_writer=memory.remember,
        )
        for sent, app in should_open.items():
            reg.executed.clear()
            async for _ in loop.send(f"s-{sent[:4]}", sent):
                pass
            assert reg.executed == ["app_open"], (
                f"命令 {sent!r} 应触发 app_open，实际：{reg.executed}"
            )
        memory.close()
    finally:
        _cleanup(db)


@pytest.mark.asyncio
async def test_episodic_filtered_by_default() -> None:
    """默认（episodic_inject=False）：L2 情景被过滤，只注入 fact/knowledge 分通道。"""
    llm = FakeRequiredLLM([{"token": "应答"}])
    mems = [
        _mem("用户上次打开微信只说了句'在吗'（光说不做范例）"),  # 无 kind → L2 情景
        _mem("用户名字叫小明", kind="fact"),
        _mem("用户喜欢用网易云音乐听歌", kind="knowledge"),
    ]
    loop = AgentLoop(
        llm=llm,
        tools_registry=FakeRegistry(),
        memory_retriever=FakeMemory(mems),
        memory_writer=None,
        episodic_inject=False,  # 默认关闭
    )
    async for _ in loop.send("s1", "你好"):
        pass
    system_blocks = "\n".join(
        m.get("content", "") for m in llm.last_messages if m.get("role") == "system"
    )
    assert "光说不做范例" not in system_blocks, "L2 情景不应注入"
    assert "【用户画像·已知事实】" in system_blocks, "应出现事实通道"
    assert "小明" in system_blocks, "L3 事实应注入"
    assert "【知识库】" in system_blocks, "应出现知识通道"
    assert "网易云音乐" in system_blocks, "知识库应注入"


@pytest.mark.asyncio
async def test_episodic_injected_when_enabled() -> None:
    """episodic_inject=True：L2 情景注入到独立「过往对话记录」通道。"""
    llm = FakeRequiredLLM([{"token": "应答"}])
    mems = [
        _mem("用户上次打开微信只说了句'在吗'（光说不做范例）"),
        _mem("用户名字叫小明", kind="fact"),
    ]
    loop = AgentLoop(
        llm=llm,
        tools_registry=FakeRegistry(),
        memory_retriever=FakeMemory(mems),
        memory_writer=None,
        episodic_inject=True,  # 显式开启
    )
    async for _ in loop.send("s1", "你好"):
        pass
    system_blocks = "\n".join(
        m.get("content", "") for m in llm.last_messages if m.get("role") == "system"
    )
    # 注入提示已改为中性描述（标题从「·仅供参考」简化），且保留"历史≠已完成"的防护语义
    assert "【过往对话记录】" in system_blocks, "episodic_inject=True 应出现情境通道"
    assert "光说不做范例" in system_blocks, "episodic_inject=True 时 L2 情景应注入"


@pytest.mark.asyncio
async def test_approval_mode_auto_bypasses_gate() -> None:
    """问题3：auto 模式审批门直接返回 True（不弹窗）。"""
    from yuiro.approval import approval_gate, set_approval_mode

    set_approval_mode("auto")
    # 无 WS 连接时，manual 会返回 False（找不到会话）；auto 必须直接通过
    ok = await approval_gate("app_open", {"name": "记事本"}, "no-such-session")
    assert ok is True, f"auto 模式应直接通过审批，实际：{ok}"
    set_approval_mode("auto")  # 复位，避免污染其他测试


@pytest.mark.asyncio
async def test_approval_mode_legacy_native_bypasses_gate() -> None:
    """回归：历史遗留的 native 模式也应自动通过（config.toml 残留不弹窗）。"""
    from yuiro.approval import approval_gate, set_approval_mode

    set_approval_mode("native")  # 旧值，曾导致 auto 失效仍弹窗
    ok = await approval_gate("app_open", {"name": "记事本"}, "no-such-session")
    assert ok is True, f"native 残留应自动通过，实际：{ok}"
    set_approval_mode("auto")  # 复位


@pytest.mark.asyncio
async def test_approval_mode_manual_rejects_without_conn() -> None:
    """问题3：manual 模式在无 WS 连接时拒绝（保持原有弹窗语义）。"""
    from yuiro.approval import approval_gate, set_approval_mode

    set_approval_mode("manual")
    ok = await approval_gate("app_open", {"name": "记事本"}, "no-such-session")
    assert ok is False, f"manual 模式无连接时应拒绝，实际：{ok}"
    set_approval_mode("auto")  # 复位


@pytest.mark.asyncio
async def test_remember_writes_natural_language_episode_for_tool() -> None:
    """工具轮：L2 应存为自然语言事件，而非 "[已调用工具: app_open(...)]" 机器日志。

    用 md5 嵌入（测试环境确定性、不依赖 bge-m3 模型），查询取字面相关词
    （FTS trigram 可命中），验证自然语言形式确实落库。
    """
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        # tool_trace 传入的已是自然语言事件（由 AgentLoop._describe_tool_event 生成）
        await memory.remember(
            "打开网易云音乐", "好嘞～", "s1", tool_trace="我帮用户打开了网易云音乐"
        )
        hits = await memory.retrieve("网易云", top_k=3)
        texts = "".join(m.text for m in hits)
        assert "我帮用户打开了网易云音乐" in texts, f"应存自然语言事件，实际：{texts!r}"
        assert "打开网易云音乐" in texts, f"应保留用户当时的原话，实际：{texts!r}"
        # 机器日志格式不应再出现
        assert "[已调用工具" not in texts, f"不应再写入机器日志格式，实际：{texts!r}"
        memory.close()
    finally:
        _cleanup(db)


def test_describe_tool_event_is_natural_language() -> None:
    """工具调用 → 自然语言事件（成功/失败不同措辞）。"""
    from yuiro.agent import AgentLoop
    assert AgentLoop._describe_tool_event(
        "app_open", {"name": "网易云音乐"}, "done"
    ) == "我帮用户打开了网易云音乐"
    assert "没成功" in (AgentLoop._describe_tool_event(
        "app_open", {"name": "记事本"}, "error") or "")
    assert AgentLoop._describe_tool_event(
        "media_control", {"action": "next"}, "ok"
    ) == "我帮用户切到下一首"
    # 未知的 action 也要有兜底，不能返回 None 导致该轮记忆丢失
    assert AgentLoop._describe_tool_event("media_control", {"action": "unknown"}, "ok")


class FakeTextFormChatReplyLLM(LLMProvider):
    """模拟 LLM 反复请求同一工具调用（工具返回非 JSON 纯文本，如 "[todo] 无待办"）。

    用于验证非 JSON 返回结果被归一为 text 状态并登记去重，不再空转耗尽轮数。
    """

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        if self._idx == 0:
            # 第 1 轮：调一个返回纯文本（非 JSON）的工具
            yield LLMChunk(kind="tool_call", content="", tool_name="app_open",
                           tool_args={"name": "某应用"})
        else:
            # 后续轮次：LLM 仍重复同一调用（模拟旧架构下的空转退化）
            yield LLMChunk(kind="tool_call", content="", tool_name="app_open",
                           tool_args={"name": "某应用"})
        self._idx += 1
        yield LLMChunk(kind="done")

    _idx = 0


@pytest.mark.asyncio
async def test_non_json_tool_result_is_deduplicated() -> None:
    """回归：工具返回非 JSON 纯文本（如 "[todo] 无待办"）时，旧逻辑将其记为 "?"
    导致限流与去重双双失效、空转耗尽轮数。新逻辑归一为 text 状态并登记去重，
    重复调用不再反复执行。"""
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()

        async def _exec(n, a, tid, approval_callback=None):  # type: ignore[misc]
            reg.executed.append(n)
            return "[todo] 无待办"  # 纯文本，非 JSON

        reg.execute = _exec  # type: ignore[method-assign]
        loop = AgentLoop(
            llm=FakeTextFormChatReplyLLM(),
            tools_registry=reg,
            memory_retriever=memory,
            memory_writer=memory.remember,
        )
        async for _ in loop.send("s1", "记一下我喜欢吃火锅"):
            pass
        # 首次执行后即登记去重；重复调用不应再执行（旧架构会空转 6 轮）
        assert len(reg.executed) == 1, (
            f"非 JSON 返回应归一并去重（仅执行 1 次），实际执行 {len(reg.executed)} 次：{reg.executed}"
        )
        memory.close()
    finally:
        _cleanup(db)


@pytest.mark.asyncio
async def test_no_progress_early_stop() -> None:
    """无进展早停：本轮工具调用全部为重复/限流时立即终止，不续问。"""
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()
        loop = AgentLoop(
            llm=FakeAppFocusFailLLM(),
            tools_registry=reg,
            memory_retriever=memory,
            memory_writer=memory.remember,
        )
        # app_focus 连续失败：限流生效后应早停，不再续问到轮数上限
        async for _ in loop.send("s1", "打开网易云音乐"):
            pass
        focus_count = reg.executed.count("app_focus")
        assert focus_count <= 2, (
            f"app_focus 连续失败应被限流+早停（≤2），实际执行 {focus_count} 次：{reg.executed}"
        )
        memory.close()
    finally:
        _cleanup(db)


class FakeAppFocusFailLLM(LLMProvider):
    """模拟 app_open 成功后，LLM 反复调 app_focus（找不到窗口）直到耗尽轮数的退化行为。"""

    _idx = 0

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        if self._idx == 0:
            # 第 1 轮：app_open（预路由已触发，此轮实际不调 LLM；但为复现退化，
            # 模拟「app_open 成功后又被 LLM 在第 2 轮起反复 app_focus」）
            yield LLMChunk(kind="tool_call", content="", tool_name="app_focus",
                           tool_args={"name": "网易云音乐"})
        else:
            yield LLMChunk(kind="tool_call", content="", tool_name="app_focus",
                           tool_args={"name": "网易云音乐"})
        self._idx += 1
        yield LLMChunk(kind="done")


@pytest.mark.asyncio
async def test_app_focus_failure_loop_is_throttled() -> None:
    """回归：app_open 成功后 LLM 反复 app_focus 失败，应被失败限流中断（不耗尽 6 轮）。"""
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        # 真实工具：app_open 成功，app_focus 失败
        reg = FakeRegistry()
        orig_execute = reg.execute
        async def _exec(n, a, tid, approval_callback=None):  # type: ignore[misc]
            reg.executed.append(n)
            return (
                '{"status": "ok", "stdout": "已打开 cloudmusic"}' if n == "app_open"
                else '{"status": "error", "stdout": "未找到标题含 \\"网易云音乐\\" 的可见窗口"}'
            )
        reg.execute = _exec
        loop = AgentLoop(
            llm=FakeAppFocusFailLLM(),
            tools_registry=reg,
            memory_retriever=memory,
            memory_writer=memory.remember,
        )
        async for _ in loop.send("s1", "打开网易云音乐"):
            pass
        # app_open 必须成功执行；app_focus 因限流不应连续执行超过 2 次
        assert "app_open" in reg.executed, f"app_open 应执行，实际：{reg.executed}"
        focus_count = reg.executed.count("app_focus")
        assert focus_count <= 2, (
            f"app_focus 连续失败应被限流（≤2），实际执行 {focus_count} 次：{reg.executed}"
        )
        memory.close()
    finally:
        _cleanup(db)


@pytest.mark.asyncio
async def test_remember_keeps_chat_form_for_pure_text() -> None:
    """纯闲聊（tool_trace 空）存为口语化转述，不是 "用户:/助手:" 日志体。"""
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        await memory.remember("今天心情不错", "那太好了～", "s1")
        hits = await memory.retrieve("心情", top_k=3)
        texts = "".join(m.text for m in hits)
        assert "今天心情不错" in texts, f"应保留用户原话，实际：{texts!r}"
        assert "那太好了" in texts, f"应保留助手回复，实际：{texts!r}"
        assert "[已调用工具" not in texts, "纯闲聊不应写入工具痕迹"
        memory.close()
    finally:
        _cleanup(db)


class FakeDupOpenLLM(LLMProvider):
    """模拟真实日志：'打开网易云疑云' 预路由命中 app_open(疑云) 失败后，
    LLM 第 2 轮纠正为 app_open(网易云音乐) 成功，但第 3 轮起仍反复重复
    同一个 app_open(网易云音乐) —— 应被成功去重，不再重复执行。"""

    _idx = 0

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        if self._idx == 0:
            yield LLMChunk(kind="tool_call", content="", tool_name="app_open",
                           tool_args={"name": "网易云音乐"})
        else:
            yield LLMChunk(kind="tool_call", content="", tool_name="app_open",
                           tool_args={"name": "网易云音乐"})
        self._idx += 1
        yield LLMChunk(kind="done")


@pytest.mark.asyncio
async def test_app_open_success_is_deduplicated() -> None:
    """回归：app_open 成功后，LLM 再重复调同一 app_open 应被去重（返回 done，
    不重复执行），而不是反复 ShellExecute 打开同一应用耗尽轮数。"""
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()
        orig_execute = reg.execute

        async def _exec(n, a, tid, approval_callback=None):  # type: ignore[misc]
            reg.executed.append(n)
            # 首次 open 返回 error，后续返回 ok
            if len([x for x in reg.executed if x == "app_open"]) == 1:
                return '{"status": "error", "stdout": "ShellExecute 失败（错误码 2）"}'
            return '{"status": "ok", "stdout": "已打开 cloudmusic"}'

        reg.execute = _exec
        loop = AgentLoop(
            llm=FakeDupOpenLLM(),
            tools_registry=reg,
            memory_retriever=memory,
            memory_writer=memory.remember,
        )
        async for _ in loop.send("s1", "打开网易云疑云"):
            pass
        open_count = reg.executed.count("app_open")
        # 第 1 次执行（疑云→失败），第 2 次执行（网易云音乐→成功）后去重，
        # 后续重复调用应不再执行。故 app_open 最多执行 2 次。
        assert open_count <= 2, (
            f"app_open 成功后重复调用应被去重（≤2），实际执行 {open_count} 次：{reg.executed}"
        )
        memory.close()
    finally:
        _cleanup(db)


@pytest.mark.asyncio
async def test_tool_choice_thinking_incompat_degrade() -> None:
    """回归：tool_choice=required 与 thinking mode 冲突（如 deepseek）时，
    stream_text 应去掉 tool_choice 降级重试，而不是直接抛异常结束循环。"""
    from yuiro.agent import OpenAIProvider

    # 记录降级重试时的调用参数
    calls: list[dict] = []

    class _FakeResp:
        def __aiter__(self):  # noqa: D102
            # 空流：__aiter__ 返回 self，__anext__ 立即结束
            return self
        async def __anext__(self):  # noqa: D102
            raise StopAsyncIteration
        async def close(self):  # noqa: D102
            pass

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**params):
                    calls.append(params)
                    if params.get("tool_choice") == "required":
                        # 首次带 required 时抛 thinking 冲突错误
                        raise Exception(
                            "Error code: 400 - The tool_choice parameter does not "
                            "support being set to required or object in thinking mode"
                        )
                    return _FakeResp()

    # 绕过 __init__（内部硬编码创建真实 AsyncOpenAI），用 object.__new__ 注入假 client
    llm = object.__new__(OpenAIProvider)
    llm._client = _FakeClient()
    llm._model = "deepseek-v4-flash-0731"
    llm._temperature = 0.1
    llm._base_url = "https://api.deepseek.com/v1"

    chunks: list[str] = []
    async for c in llm.stream_text([], tools=None, tool_choice="required"):
        chunks.append(c.kind)
    # 首次调用带 required 被降级，第二次调用去掉 tool_choice
    assert len(calls) == 2, f"应降级重试一次，实际调用 {len(calls)} 次"
    assert "tool_choice" not in calls[1], f"降级后不应带 tool_choice，实际：{calls[1]}"
    assert "done" in chunks, f"降级后应正常产出 done chunk，实际：{chunks}"


@pytest.mark.asyncio
async def test_state_note_injected_after_tool() -> None:
    """工具成功执行后，状态摘要作为独立 system 段注入后续轮次。"""
    # 第一轮：app_open 被预路由触发；第二轮（工具结果回传后）LLM 收到状态摘要
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        llm = FakeRequiredLLM([
            {"token": "已为你打开网易云音乐"},
            {"token": "还需要什么吗？"},
        ])
        loop = AgentLoop(
            llm=llm,
            tools_registry=FakeRegistry(),
            memory_retriever=memory,
            memory_writer=memory.remember,
        )
        async for _ in loop.send("s1", "打开网易云音乐"):
            pass
        # 第二轮 LLM 调用时的 messages 应包含状态摘要
        sys2 = "\n".join(
            m.get("content", "")
            for m in llm.last_messages
            if m.get("role") == "system"
        )
        assert "已成功打开并运行：网易云音乐" in sys2, f"状态摘要未注入，得到：{sys2!r}"
        memory.close()
    finally:
        _cleanup(db)


@pytest.mark.asyncio
async def test_history_inject_toggle() -> None:
    """history_inject=False 时不注入原始 history；True 时注入。"""
    reg = FakeRegistry()
    hist = [{"role": "user", "content": "历史用户句"}, {"role": "assistant", "content": "历史助手句"}]

    # False：不注入
    llm_f = FakeRequiredLLM([{"token": "应答"}])
    loop_f = AgentLoop(
        llm=llm_f, tools_registry=reg, memory_retriever=FakeMemory([]),
        memory_writer=None, history_inject=False,
    )
    loop_f._history["s1"] = list(hist)
    async for _ in loop_f.send("s1", "你好"):
        pass
    joined_f = "\n".join(m.get("content", "") for m in llm_f.last_messages)
    assert "历史用户句" not in joined_f, "history_inject=False 时不应注入 history"

    # True：注入
    llm_t = FakeRequiredLLM([{"token": "应答"}])
    loop_t = AgentLoop(
        llm=llm_t, tools_registry=reg, memory_retriever=FakeMemory([]),
        memory_writer=None, history_inject=True,
    )
    loop_t._history["s1"] = list(hist)
    async for _ in loop_t.send("s1", "你好"):
        pass
    joined_t = "\n".join(m.get("content", "") for m in llm_t.last_messages)
    assert "历史用户句" in joined_t, "history_inject=True 时应注入 history"


class FakeFactLLM(LLMProvider):
    """模拟事实抽取 LLM：返回「键: 值」格式，用于验证 LLM 抽取链路。"""

    def __init__(self, output: str) -> None:
        self._output = output
        self.prompts: list[str] = []

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        self.prompts.append(str(messages[-1].get("content", "")))
        yield LLMChunk(kind="token", content=self._output)
        yield LLMChunk(kind="done")


@pytest.mark.asyncio
async def test_llm_fact_extraction_captures_implicit_profile() -> None:
    """回归：隐含画像（"广东人→不吃辣"）规则正则抓不到，应由 LLM 抽取捕获。"""
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        # LLM 输出需符合「摘要：… / 事实：键: 值」格式（与 _extract_episode_and_facts 约定一致）
        memory._fact_llm = FakeFactLLM(
            "摘要：用户强调自己是广东人，不吃辣锅。\n"
            "事实：籍贯: 广东人\n"
            "事实：口味: 不吃辣，偏好清淡"
        )
        await memory.remember(
            "不对，我可是土生的广东人，我怎么可能会点辣锅呢？", "原来如此～", "s1"
        )
        # 等待后台异步抽取任务完成
        await asyncio.sleep(0.1)
        facts = await memory._facts.query(memory.facts_subject)
        fact_map = {f["key"]: f["value"] for f in facts}
        assert fact_map.get("籍贯") == "广东人", f"LLM 抽取的籍贯未写入，实际：{fact_map}"
        # "口味" 会被同义 key 归并到 "饮食偏好"（防 key 爆炸）
        assert "不吃辣" in fact_map.get("饮食偏好", ""), (
            f"隐含口味事实未捕获（应为归一后的 饮食偏好），实际：{fact_map}"
        )
        memory.close()
    finally:
        _cleanup(db)


def test_fact_key_alias_normalization() -> None:
    """同义 key 应归并到统一主 key，避免同一画像散落多个 key 导致检索不全。"""
    from yuiro.memory import MemorySystem as _MS
    assert _MS._normalize_key("家乡") == "籍贯"
    assert _MS._normalize_key("爱好") == "喜欢"
    assert _MS._normalize_key("籍贯") == "籍贯"  # 主 key 保持原样


@pytest.mark.asyncio
async def test_rhetorical_question_keeps_facts() -> None:
    """回归：反问句（"我怎么可能点辣锅呢"）不应被当作提问整体丢弃。

    旧逻辑对所有疑问句一律 return []，导致以反问语气陈述的事实全部丢失。
    """
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        facts = memory._extract_facts("我是广东人，不吃辣")
        assert facts, "陈述句应能抽到事实"
        # 真提问仍应被排除
        q = memory._extract_facts("我叫什么名字？")
        assert q == [], f"真提问不应抽取事实，实际：{q}"
        memory.close()
    finally:
        _cleanup(db)


@pytest.mark.asyncio
async def test_tool_turn_is_recorded_into_history() -> None:
    """B：工具轮也要进多轮历史（精简摘要形态），否则下一轮接不上话。

    旧实现 `if not tool_calls:` 把工具轮整体排除，导致点歌这类交互式流程
    在用户回答时已看不到上一轮发生了什么。
    """
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        loop = AgentLoop(
            llm=FakeRequiredLLM([{"token": "好嘞～"}]),
            tools_registry=FakeRegistry(),
            memory_retriever=memory,
            memory_writer=None,
            history_inject=True,
        )
        # "打开网易云音乐" 命中预路由 → 工具轮
        async for _ in loop.send("s1", "打开网易云音乐"):
            pass
        hist = loop._history.get("s1", [])
        assert hist, f"工具轮应写入 history，实际为空：{hist!r}"
        joined = "\n".join(str(m.get("content", "")) for m in hist)
        assert "打开网易云音乐" in joined, f"应保留用户请求，实际：{joined!r}"
        # S34 行为变更（非回归）：工具痕迹改挂 **system** 角色，不再拼进 assistant 内容。
        # 旧形态「（本轮操作：…）」会被模型模仿并在回复里自行生成（甚至编造
        # "（本轮操作：无工具调用）"），最后被 TTS 念出来 —— 见 docs/plan/S34。
        assert any(
            m.get("role") == "system" and "工具执行情况" in str(m.get("content"))
            for m in hist
        ), f"应以 system 备注记录工具痕迹，实际 roles={[m.get('role') for m in hist]}：{hist!r}"
        joined_assistant = "\n".join(
            str(m.get("content", "")) for m in hist if m.get("role") == "assistant"
        )
        assert "本轮操作" not in joined_assistant, (
            f"assistant 内容不应含调试注记（会被模型模仿）：{joined_assistant!r}"
        )
        assert '"status"' not in joined, f"不应写入原始工具 JSON，实际：{joined!r}"
        memory.close()
    finally:
        _cleanup(db)


class FakeNeedChoiceLLM(LLMProvider):
    """第 1 轮调 netease_play 返回 need_choice（要用户选版本）；
    第 2 轮模拟用户说"确认"后的正常回复。"""

    _idx = 0
    last_messages: list = []

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        self.last_messages = [dict(m) for m in messages]
        if self._idx == 0:
            yield LLMChunk(kind="tool_call", content="", tool_name="netease_play",
                           tool_args={"keyword": "晴天"})
        else:
            yield LLMChunk(kind="token", content="好，就放你选的那个版本～")
        self._idx += 1
        yield LLMChunk(kind="done")


@pytest.mark.asyncio
async def test_pending_choice_is_registered_and_injected() -> None:
    """C：工具返回 need_choice 时登记"待确认事项"，下一轮注入提示模型接着原任务。

    对应实测场景：点歌搜到非指定版本→询问→用户回"确认"→模型却答非所问。
    """
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()

        async def _exec(n, a, tid, approval_callback=None):  # type: ignore[misc]
            reg.executed.append(n)
            if n == "netease_play":
                return json.dumps(
                    {"status": "need_choice",
                     "message": "「晴天」原唱版本没有版权，以下是相近可播版本，请让用户确认",
                     "options": [
                         {"name": "晴天 (Live版)", "artist": "周杰伦",
                          "song_id": 186016, "encrypted_id": "3a9f00c2e3b1"},
                     ]},
                    ensure_ascii=False,
                )
            return '{"status": "ok"}'

        reg.execute = _exec  # type: ignore[method-assign]
        llm = FakeNeedChoiceLLM()
        loop = AgentLoop(
            llm=llm,
            tools_registry=reg,
            memory_retriever=memory,
            memory_writer=None,
            history_inject=True,
        )
        async for _ in loop.send("s1", "帮我点一首晴天"):
            pass
        # ① 待确认事项已登记，且**带上了可选项的具体 ID**——否则用户回"确认"后
        #    模型手里没有 song_id，只能拿关键词重调 → 再次 need_choice 死循环
        #    （实测"播放廖俊涛的《谁》→确认"空转 3 轮的根因）。
        pending = loop._state.pending("s1")
        assert "确认" in pending, f"应登记待确认事项，实际：{pending!r}"
        assert "song_id=186016" in pending, f"待确认应含可选项 ID，实际：{pending!r}"
        assert "encrypted_id=3a9f00c2e3b1" in pending, f"应含 encrypted_id，实际：{pending!r}"

        # ② 用户回"确认" → 下一轮上下文应注入【等待用户确认】
        async for _ in loop.send("s1", "就第一个吧"):
            pass
        joined = "\n".join(
            str(m.get("content", "")) for m in llm.last_messages
        )
        assert "等待用户确认" in joined, f"应注入待确认通道，实际：{joined!r}"
        assert "晴天" in joined, f"待确认内容应含原问询，实际：{joined!r}"
        assert "song_id=186016" in joined, f"注入通道应含可选项 ID，实际：{joined!r}"
        memory.close()
    finally:
        _cleanup(db)


def test_pending_expires_after_max_turns() -> None:
    """待确认事项不应无限期挂着：超过 PENDING_MAX_TURNS 轮自动失效。"""
    from yuiro.agent.tool_events import StateNotes
    notes = StateNotes()
    notes.set_pending("s1", "要放哪个版本？")
    for _ in range(StateNotes.PENDING_MAX_TURNS):
        notes.age_pending("s1")
    assert notes.pending("s1") == "要放哪个版本？", "未超限不应失效"
    notes.age_pending("s1")  # 再多一轮 → 超限
    assert notes.pending("s1") == "", "超过存活轮数后应失效"


class FakeRepeatNeedChoiceLLM(LLMProvider):
    """模拟"确认点歌死循环"：连续多轮用**完全相同参数**重调 netease_play。"""

    def __init__(self, rounds: int) -> None:
        self._rounds = rounds
        self._idx = 0

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        if self._idx < self._rounds:
            self._idx += 1
            yield LLMChunk(kind="tool_call", content="", tool_name="netease_play",
                           tool_args={"keyword": "廖俊涛 谁"})
        else:
            yield LLMChunk(kind="token", content="好啦～")
        yield LLMChunk(kind="done")


@pytest.mark.asyncio
async def test_repeat_need_choice_call_is_skipped() -> None:
    """need_choice 抛给用户后，同回合内同参重调应被去重（asked），不再真实执行。

    对应实测：用户说"确认"后模型拿旧 keyword 连打 3 轮 netease_play，
    每轮都 need_choice，全部真实执行 → 空转 + 收尾兜底语撒谎"刚帮你弄好了"。
    """
    db = _tmp_db()
    try:
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model="md5")
        reg = FakeRegistry()

        async def _exec(n, a, tid, approval_callback=None):  # type: ignore[misc]
            reg.executed.append(n)
            return json.dumps(
                {"status": "need_choice", "message": "请让用户确认要放哪一首",
                 "options": [{"name": "谁 (Live版)", "artist": "廖俊涛",
                              "song_id": 566436427, "encrypted_id": "CD49E03E"}]},
                ensure_ascii=False,
            )

        reg.execute = _exec  # type: ignore[method-assign]
        loop = AgentLoop(
            llm=FakeRepeatNeedChoiceLLM(rounds=3),
            tools_registry=reg,
            memory_retriever=memory,
            memory_writer=None,
        )
        results: list[str] = []
        async for chunk in loop.send("s1", "确认"):
            if chunk.kind == "tool_result":
                results.append(chunk.content)
        # 第 1 次真实执行；第 2 次同参重调被 asked 去重 → 该轮无进展 → 提前早停
        # （LLM 仍收到 1 条去重占位结果，可据此向用户转述选项）
        assert reg.executed == ["netease_play"], f"只应真实执行 1 次，实际：{reg.executed!r}"
        assert len(results) == 2, f"应只到第 2 轮即早停，实际：{len(results)}"
        assert json.loads(results[1])["status"] == "skipped"
        assert "重复" in json.loads(results[1])["note"]
        memory.close()
    finally:
        _cleanup(db)
