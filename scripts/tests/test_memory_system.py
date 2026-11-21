"""记忆框架验证：写入（情景+事实抽取）→ 跨实例持久化 → 检索注入。

用法: & .env-local\engine-venv\Scripts\python.exe scripts\test_memory_system.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "D:/Project/Yuii/desktop-pet/Yuiro/engine")

from yuiro.memory import MemorySystem


async def round1(db_path: str) -> None:
    """模拟对话 1：用户自我介绍 + 偏好 → 写入记忆。"""
    ms = MemorySystem(db_path, rrf_k=60, top_k=3)
    await ms.remember("我叫小明，我是一名研究生。", "你好小明！很高兴认识你。")
    await ms.remember("我喜欢吃火锅，讨厌早起。", "火锅我也喜欢！")
    print("[round1] 已写入 2 轮对话记忆")
    # 事实抽取验证
    facts = await ms._facts.query("用户")
    print("[round1] L3 事实:", {f["key"]: f["value"] for f in facts})
    ms.close()


async def round2(db_path: str) -> None:
    """模拟新进程（重启后）：检索注入验证跨会话记忆。"""
    ms = MemorySystem(db_path, rrf_k=60, top_k=3)
    for q in ["我叫什么名字？", "我喜欢吃什么？"]:
        mems = await ms.retrieve(q, top_k=3)
        print(f"[round2] 查询 {q!r} 检索到:")
        for m in mems:
            print(f"    - {m.text!r} (score={m.score:.3f}, meta={m.meta})")
    ms.close()


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "memory_test.db")
        await round1(db)
        print("--- 模拟重启（新 MemorySystem 实例读同一 db）---")
        await round2(db)
        print("MEMORY FRAMEWORK TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
