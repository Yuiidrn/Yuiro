"""直接流式测试：绕过 AgentLoop，直接消费 OpenAIProvider.stream_text，看流式是否返回 tool_call。"""
import asyncio
import json
import sys

from yuiro.agent import OpenAIProvider
from yuiro.config import load_config
from yuiro.keychain import load_llm_key


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "app_open",
            "description": "打开/启动一个软件或应用。只要用户的话语中出现软件名或应用名——"
            "无论是明确命令还是单独说出名词，都必须调用本工具，"
            "name 填应用名/可执行名（如 '网易云音乐'、'notepad'）。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    }
]


async def main():
    cfg = load_config()
    llm = OpenAIProvider(cfg.llm.base_url, cfg.llm.model, load_llm_key() or "")
    cases = sys.argv[1:] or ["记事本。", "网易云音乐。", "下一首"]
    for text in cases:
        print(f"\n[流式] >>> {text!r}")
        tokens = 0
        tool_calls = []
        try:
            async for chunk in llm.stream_text(
                [{"role": "user", "content": text}], tools=TOOLS
            ):
                if chunk.kind == "token":
                    tokens += 1
                elif chunk.kind == "tool_call":
                    tool_calls.append((chunk.tool_name, chunk.tool_args))
        except Exception as e:
            print(f"  [流式] 异常: {type(e).__name__}: {e}")
        print(f"  [流式] tokens={tokens}, tool_calls={tool_calls}")


if __name__ == "__main__":
    asyncio.run(main())
