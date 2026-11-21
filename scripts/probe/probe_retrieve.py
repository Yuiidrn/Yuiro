import asyncio
from yuiro.config import load_config
from yuiro.memory import MemorySystem

async def main():
    cfg = load_config()
    mem = MemorySystem(
        db_path="data/yuiro_memory.db",
        rrf_k=cfg.memory.rrf_k,
        top_k=cfg.memory.auto_inject_top_k,
        facts_subject="用户",
        embedder_model="md5",
    )
    for q in ["网易云音乐。", "下一首", "记事本。"]:
        mems = await mem.retrieve(q, top_k=3)
        print(f"\n查询: {q!r}")
        for m in mems:
            rid = m.meta.get("rowid")
            print(f"  rowid={rid} score={m.score:.3f} text={m.text[:60]!r}")

asyncio.run(main())
