"""单测：AgentLoop 对挂起 LLM 的工具续问是否 30s 超时兜底。"""
from __future__ import annotations

import asyncio
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "D:/Project/Yuii/desktop-pet/Yuiro/engine")

from yuiro.agent import AgentLoop, LLMChunk


class HangingLLM:
    """第一轮返回 tool_call，第二轮永久挂起（模拟 qwen 工具续问卡死）。"""

    def __init__(self) -> None:
        self.rounds = 0

    async def stream_text(self, messages, tools=None, **kw):
        self.rounds += 1
        if self.rounds == 1:
            yield LLMChunk(kind="tool_call", tool_name="todo", tool_args={"action": "list"})
            yield LLMChunk(kind="done")
            return
        await asyncio.sleep(3600)  # 挂起
        yield LLMChunk(kind="done")


class FakeReg:
    def schemas(self):
        return []

    async def execute(self, *a, **k):
        return '{"status": "ok"}'


async def main() -> None:
    loop = AgentLoop(HangingLLM(), FakeReg(), None)
    t0 = time.perf_counter()
    parts = []
    try:
        async for ch in loop.send("s", "下一首"):
            parts.append((ch.kind, ch.content[:40]))
    finally:
        print(f"耗时 {time.perf_counter() - t0:.1f}s")
    print("chunks:", parts[:6])
    ok = time.perf_counter() - t0 < 45
    print("TIMEOUT 生效" if ok else "超时未生效！")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
