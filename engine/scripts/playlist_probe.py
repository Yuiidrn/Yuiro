"""S41 诊断/冒烟：账号歌单 + 名字/语义匹配（含嵌入器体检）。

用途：
- 确认"我的歌单"能读到几个（订阅 + 创建 + 收藏 + 红心，四个入口合并）；
- 体检嵌入器（BGE-M3 子进程）—— **语义匹配的前提**：
  未就绪时 ``embed()`` 会静默降级成 md5 向量（无语义），匹配必然错；
- 用几种说法试匹配，看命中/给候选的行为是否符合预期。

用法：python scripts/playlist_probe.py [查询1 查询2 ...]
"""
from __future__ import annotations

import asyncio
import sys


async def main() -> int:
    from yuiro.tools import netease_tool as nt

    # ── 嵌入器体检（先做，否则后面的语义匹配结论没有意义）──
    emb = nt._get_embedder()
    if emb is None:
        print("嵌入器：不可用（FlagEmbedding 装不上）→ 只能字面匹配")
    else:
        ok = await emb.wait_ready(90.0)
        print(f"嵌入器：{'就绪' if ok else '未就绪'}（{getattr(emb, '_ready_reason', '')}）")
        if ok:
            try:
                vecs = await emb.embed_many(["自习室", "电子音乐", "古典"])
                print(f"  批量嵌入自检：{len(vecs)} 条 × {len(vecs[0])} 维")
            except Exception as exc:  # noqa: BLE001
                print(f"  批量嵌入失败：{exc}")

    try:
        lists = await nt._account_playlists()
    except Exception as exc:  # noqa: BLE001
        print(f"读取账号歌单失败：{exc}")
        return 1

    print(f"\n=== 账号歌单：{len(lists)} 个 ===")
    for r in lists[:20]:
        count = r.get("trackCount")
        print(f"  · {r.get('name')}" + (f"（{count} 首）" if count else ""))

    queries = sys.argv[1:] or ["我喜欢的音乐", "学习"]
    for q in queries:
        hit, opts, why = await nt._match_playlist(q, lists)
        if hit is not None:
            print(f"\n查询「{q}」→ 命中《{hit.get('name')}》（{why}）")
        else:
            names = [str(o.get("name")) for o in opts]
            print(f"\n查询「{q}」→ 需用户选（{why}）：{names}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
