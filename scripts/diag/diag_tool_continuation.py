"""诊断 qwen 兼容端点的 tool 续问（两轮对话：tool_call → 回填 → 最终回复）。"""
from __future__ import annotations

import asyncio
import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "D:/Project/Yuii/desktop-pet/Yuiro/engine")

from yuiro.agent import OpenAIProvider, ToolSchema
from yuiro.config import load_config
from yuiro.keychain import load_llm_key


async def main() -> None:
    key = load_llm_key()
    if not key:
        print("NO KEY")
        return
    cfg = load_config()
    print(f"LLM: {cfg.llm.base_url} / {cfg.llm.model}")
    llm = OpenAIProvider(cfg.llm.base_url, cfg.llm.model, key)
    tool_schema = [
        ToolSchema(
            function={
                "type": "function",
                "function": {
                    "name": "system_action",
                    "description": '执行系统操作。args 示例 app_open: {"name": "notepad"}',
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string", "enum": ["app_open"]},
                            "args": {"type": "object"},
                        },
                        "required": ["tool", "args"],
                    },
                },
            }
        )
    ]
    messages = [
        {"role": "system", "content": "你是桌宠 Yuiro，回答简短亲切。"},
        {"role": "user", "content": "打开记事本"},
    ]
    print("--- 第一轮（期望 tool_call）---")
    t0 = time.perf_counter()
    calls = []
    async for ch in llm.stream_text(messages, tools=tool_schema):
        if ch.kind == "token":
            print("token:", ch.content)
        if ch.kind == "tool_call":
            calls.append(ch)
    print(f"第一轮耗时 {time.perf_counter() - t0:.1f}s, tool_calls: {[(c.tool_name, c.tool_args) for c in calls]}")
    if not calls:
        print("无工具调用，结束")
        return
    messages.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": calls[0].tool_name,
                        "arguments": json.dumps(calls[0].tool_args, ensure_ascii=False),
                    },
                }
            ],
        }
    )
    messages.append(
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{"status": "ok", "stdout": "已打开 notepad"}',
        }
    )
    print("--- 第二轮（期望最终回复）---")
    t0 = time.perf_counter()
    text = ""
    got_any = False
    try:
        async for ch in llm.stream_text(messages):
            got_any = True
            if ch.kind == "token":
                text += ch.content
    except Exception as exc:  # noqa: BLE001
        print(f"第二轮异常: {type(exc).__name__}: {exc}")
        return
    print(f"第二轮耗时 {time.perf_counter() - t0:.1f}s, 有输出={got_any}, 回复: {text!r}")


if __name__ == "__main__":
    asyncio.run(main())
