"""验收 S38：真实 LLM + 真实工具链，整理 D:/Project/Yuii/desktop-pet/test。

- 默认**只读阶段**：扫描 + 分类方案（不动任何文件）；
- ``--execute``：真的执行整理（file_move 走事务，可 transaction_rollback 回滚）。

用法：python _accept_organize.py [--execute]
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

TARGET = r"D:\Project\Yuii\desktop-pet\test"


async def main() -> None:
    from yuiro.agent import build_agent_loop
    from yuiro.config import NeteaseConfig, load_config
    from yuiro.keychain import load_llm_key
    from yuiro.native import NativeBackend
    from yuiro.task import TaskRuntime
    from yuiro.transaction import TxnStore

    cfg = load_config()
    key = load_llm_key()
    if not key:
        print("!! 没有可用的 LLM key，无法跑真实验收")
        return
    if not os.path.isdir(TARGET):
        print(f"!! 目标目录不存在: {TARGET}")
        return

    execute = "--execute" in sys.argv
    tmp = tempfile.mkdtemp(prefix="yuiro_acc_")
    backend = NativeBackend(
        file_roots=[TARGET], txn_store=TxnStore(os.path.join(tmp, "txn"))
    )
    loop = build_agent_loop(
        base_url=cfg.llm.base_url,
        model=cfg.llm.model,
        api_key=key,
        temperature=cfg.llm.temperature,
        system_backend=backend,
        persona=cfg.persona,
        memory_config=cfg.memory,
        context_config=cfg.context,
        task_runtime=TaskRuntime(events=None),
        netease_config=NeteaseConfig(enabled=False),  # 聚焦文件整理
        capability_config=None,
    )

    if execute:
        question = (
            f"现在**真的执行**整理：把 {TARGET} 里的文件按类型分到子文件夹里。"
            "先扫描确认清单，然后用 file_move 批量移动（一次调用可以传多个文件）。"
            "完成后告诉我一共移动了几件、分成了哪几类。"
        )
    else:
        question = (
            f"帮我看看 {TARGET} 这个目录里有什么，给我一个分类整理方案。"
            "**这一轮只扫描和分析，先不要移动或删除任何文件**——"
            "告诉我你建议分成哪几类、每类各几个文件。"
        )

    print("=" * 72)
    print("用户：", question)
    print("=" * 72)
    reply: list[str] = []
    async for chunk in loop.send("acc-1", question):
        if chunk.kind == "tool_call":
            print(f"\n[调用工具] {chunk.tool_name} {str(chunk.tool_args)[:220]}")
        elif chunk.kind == "tool_result":
            text = str(chunk.content)
            print(f"[工具结果] {text[:400]}{'…' if len(text) > 400 else ''}")
        elif chunk.kind == "token":
            reply.append(chunk.content)
    print("\n" + "=" * 72)
    print("它说：", "".join(reply))
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
