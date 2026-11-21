import asyncio

import pytest

from yuiro.agent import AgentLoop, LLMChunk, LLMProvider
from yuiro.runtime.trace import TraceContext


@pytest.mark.asyncio
async def test_retrieval_and_provider_wait_are_separate():
    trace = TraceContext(session_id="latency-test", mode="voice")

    class Memory:
        async def retrieve(self, text, top_k):
            assert trace.get("memory_retrieve_start") is not None
            assert trace.get("llm_request_start") is None
            await asyncio.sleep(.01)
            return []

    class Registry:
        def schemas(self, *args, **kwargs):
            return []

    class Provider(LLMProvider):
        first = None

        async def stream_text(self, messages, tools=None, **kwargs):
            assert trace.get("memory_retrieve") is not None
            assert trace.get("llm_request_start") is not None
            await asyncio.sleep(.01)
            yield LLMChunk(kind="token", content="你好")
            self.first = trace.get("llm_provider_first_token")
            await asyncio.sleep(.01)
            yield LLMChunk(kind="token", content="。")
            yield LLMChunk(kind="done")

    provider = Provider()
    agent = AgentLoop(provider, Registry(), Memory())
    chunks = [c async for c in agent.send("latency-test", "你好", trace=trace)]
    assert "".join(c.content for c in chunks if c.kind == "token") == "你好。"
    marks = [trace.get(n) for n in ("memory_retrieve_start", "memory_retrieve",
                                  "llm_request_start", "llm_provider_first_token")]
    assert all(value is not None for value in marks)
    assert marks == sorted(marks)
    assert provider.first == trace.get("llm_provider_first_token")
