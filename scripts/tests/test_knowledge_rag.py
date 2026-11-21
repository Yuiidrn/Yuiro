"""知识库 RAG 框架验证：切块入库 → 检索命中 → MemorySystem 双路注入。"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "D:/Project/Yuii/desktop-pet/Yuiro/engine")

from yuiro.memory import KnowledgeStore, MemorySystem


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "kb.db")
        kb = KnowledgeStore(db)
        n = await kb.ingest(
            "Yuiro 是一个复刻 Neuro-sama 的声控桌宠。"
            "语音识别用 faster-whisper，语音合成用 edge-tts，"
            "系统操作经 C++ SystemDaemon MCP 执行并带审批。",
            source="README.md",
        )
        print(f"ingest {n} 块, stats: {kb.stats()}")
        hits = await kb.retrieve("Yuiro 用什么语音识别？", top_k=3)
        for h in hits:
            print(f"  命中 [{h['score']:.3f}] {h['text'][:60]}")
        assert hits and "faster-whisper" in hits[0]["text"]
        # MemorySystem 双路注入（记忆 + 知识）
        ms = MemorySystem(db, knowledge=kb)
        mems = await ms.retrieve("语音识别用什么模型？", top_k=3)
        kinds = [m.meta.get("kind") for m in mems]
        print("注入 kinds:", kinds)
        assert "knowledge" in kinds
        ms.close()  # 关闭 MemorySystem（含 kb 与自身连接）
        print("KNOWLEDGE RAG TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
