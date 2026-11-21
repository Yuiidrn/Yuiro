"""非流式对比测试：用 chat.completions.create（非流式）验证 LLM 对裸名词是否调工具。"""
import asyncio
import json
import sys

from openai import AsyncOpenAI

from yuiro.config import load_config
from yuiro.keychain import load_llm_key


async def main():
    cfg = load_config()
    client = AsyncOpenAI(base_url=cfg.llm.base_url, api_key=load_llm_key() or "")
    tools = [
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
    cases = sys.argv[1:] or ["记事本。", "网易云音乐。", "打开计算器", "下一首"]
    for text in cases:
        resp = await client.chat.completions.create(
            model=cfg.llm.model,
            messages=[{"role": "user", "content": text}],
            tools=tools,
            extra_body={"enable_thinking": False},
        )
        msg = resp.choices[0].message
        if msg.tool_calls:
            for tc in msg.tool_calls:
                print(f"[非流式] {text!r} -> TOOL_CALL: {tc.function.name}({tc.function.arguments})")
        else:
            print(f"[非流式] {text!r} -> 纯文字: {msg.content[:40]!r}")


if __name__ == "__main__":
    asyncio.run(main())
