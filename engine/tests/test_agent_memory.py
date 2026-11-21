"""AgentLoop 记忆接线集成测试（FakeLLM + 真实 MemorySystem，不依赖外部 key）。

验证：对话 → memory_writer 写入 → 事实抽取 → 检索注入命中（跨会话）。
"""
from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from yuiro.agent import AgentLoop, LLMChunk, LLMProvider, ToolSchema
from yuiro.memory import MemorySystem

#: 本项目 BGE-M3 权重的规范落点（相对 engine 工作目录；与 config.toml 的
#: [memory].embedder = "models/bge-m3" 同一处，见 AGENTS.md）。
_LOCAL_BGE = "models/bge-m3"


class FakeLLM(LLMProvider):
    """按关键词给固定回复的流式 LLM（无网络）。"""

    def __init__(self, replies: dict[str, str]) -> None:
        self._replies = replies
        self.calls: list[str] = []

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        user = str(messages[-1].get("content", ""))
        self.calls.append(user)
        reply = ""
        for key, value in self._replies.items():
            if key in user:
                reply = value
                break
        if not reply:
            reply = "好的。"
        yield LLMChunk(kind="token", content=reply)
        yield LLMChunk(kind="done")


class NoopRegistry:
    def schemas(self, toolset=None):  # noqa: ARG002
        return []

    async def execute(self, name, args, task_id, approval_callback=None):  # noqa: ARG002
        return "{}"


@pytest.mark.asyncio
async def test_agentloop_memory_roundtrip() -> None:
    """记忆链路：纯闲聊**不**写 L2（防污染）；真正写入后语义检索命中。

    2026-10 修订：AgentLoop 现在规定**只有真的执行过工具**的轮次才写 L2 情景记忆
    （`if self._memory_writer is not None and tool_ran:`）——否则"用户要求操作 → 助手
    纯文字回复"这类失败范例会被固化，经检索注入后自我强化。本用例原先把"纯聊天 →
    L2 检索命中"当成契约，与该规定冲突、长期红着。现改为守两条真实契约：

    1. 纯闲聊轮次不产生任何 L2 记忆（反向护栏）；
    2. 真正写入后，**真 BGE-M3** 的语义检索能把"我叫什么名字？"命中"我叫小明"
       （md5 向量做不到，故这里必须加载真权重）。

    ignore_cleanup_errors：Windows 上 SQLite WAL 多连接（L2/L3 两个 store 连同一
    db 文件）关闭后偶发文件锁残留，导致临时目录清理 PermissionError（平台问题，
    生产长驻进程不受影响）；不该让清理失败掩盖断言结果。
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = os.path.join(tmp, "mem.db")
        # ★ 权重用**项目内本地目录**（engine/models/bge-m3，与 config.toml 的
        #   [memory].embedder 同一处），而不是裸 HF repo id "BAAI/bge-m3"：
        #   后者依赖 HF 缓存，而本机 HF 缓存已重定向到 .env-local、C 盘旧副本已清理，
        #   用 repo id 会退化成"加载失败 → md5 兜底 → 检索为空"这种极难归因的失败。
        if not os.path.isdir(_LOCAL_BGE):
            pytest.skip(f"本地 BGE-M3 权重缺失（{_LOCAL_BGE}），语义检索用例跳过")
        memory = MemorySystem(db, rrf_k=60, top_k=3, embedder_model=_LOCAL_BGE)
        # 嵌入子进程加载要几秒：不等就绪，头几轮会静默走 md5 兜底（检索为空）
        if not await memory.embedder.wait_ready(60.0):
            reason = memory.embedder._ready_reason
            memory.close()
            pytest.skip(f"BGE-M3 未能加载（{reason}），语义检索用例跳过")
        try:
            loop = AgentLoop(
                llm=FakeLLM({"我叫": "你好小明！", "我喜欢": "火锅好吃！"}),
                tools_registry=NoopRegistry(),
                memory_retriever=memory,
                memory_writer=memory.remember,
            )
            # 第一轮：自我介绍
            r1 = []
            async for chunk in loop.send("s1", "我叫小明，是一名研究生。"):
                if chunk.kind == "token":
                    r1.append(chunk.content)
            assert "".join(r1) == "你好小明！"
            # 第二轮：偏好
            r2 = []
            async for chunk in loop.send("s1", "我喜欢吃火锅。"):
                if chunk.kind == "token":
                    r2.append(chunk.content)
            assert "".join(r2) == "火锅好吃！"
            # ① 纯闲聊（无工具执行）→ 不写 L2：检索为空
            assert await memory.retrieve("我叫什么名字？", top_k=5) == []

            # ② 真正写入后语义检索命中（走 memory.remember，即工具轮的那条通路）
            await memory.remember("我叫小明，是一名研究生。", "你好小明！", "s1")
            mems = await memory.retrieve("我叫什么名字？", top_k=5)
            texts = " | ".join(m.text for m in mems)
            assert "小明" in texts, f"语义检索未命中：{texts!r}"
            # L3 事实抽取（规则通路）：名字进事实库
            facts = await memory._facts.query(memory.facts_subject)
            fact_map = {f["key"]: f["value"] for f in facts}
            assert fact_map.get("名字") == "小明", f"L3 事实未抽取：{fact_map!r}"
        finally:
            memory.close()


@pytest.mark.asyncio
async def test_agentloop_memory_persists_across_instances() -> None:
    """跨实例（模拟重启）：新 MemorySystem 读同一 db 检索命中。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "mem.db")
        memory1 = MemorySystem(db, top_k=3, embedder_model="md5")
        await memory1.remember("我喜欢吃火锅。", "火锅好吃！")
        memory1.close()
        # 模拟重启
        memory2 = MemorySystem(db, top_k=3, embedder_model="md5")
        # 本测试的意图是「跨实例持久化」而非语义检索，故用字面关键词查询
        #（md5 无语义向量，靠 FTS 字面命中）；语义检索的正确性由真实 BGE-M3
        # 的集成测试另行覆盖。
        mems = await memory2.retrieve("火锅", top_k=3)
        texts = " | ".join(m.text for m in mems)
        assert "火锅" in texts
        memory2.close()
