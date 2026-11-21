"""媒体链路诊断（S45）：ID 形态 → 取播放地址 → mpv 状态。

**为什么需要它**：网易云这套接口里有两套 ID，而各接口只认其中一种：

- ``song_id`` / ``originalId`` —— **明文** ID（搜索结果里的 originalId、URL 里的数字）
- ``encrypted_id`` / ``id`` —— **加密** ID（一长串 hex）

现状是**两者靠"约定"传递、没有统一解析层** —— 一旦某处传错形态，
症状就是"日志里明明有完整信息，播放器却没反应"或
"给了 song_id 却报『请给 song_id』"（实测日志）。这个脚本把每一步的
**实际返回值**打出来，让"哪一层拿不到东西"一目了然，而不是靠猜。

用法：
    python scripts/media_probe.py                  # 只查 ID 与播放地址（不播放）
    python scripts/media_probe.py "LIFE" --play    # 顺便真的播一次
"""
from __future__ import annotations

import asyncio
import json
import sys


async def main() -> int:
    from yuiro.netease import api, player

    query = next((a for a in sys.argv[1:] if not a.startswith("--")), "LIFE")
    do_play = "--play" in sys.argv

    print(f"=== 1. 搜索「{query}」 ===")
    try:
        records = await api.search_song(query, 5)
    except Exception as exc:  # noqa: BLE001
        print(f"  搜索失败：{exc}")
        return 1
    if not records:
        print("  没搜到结果")
        return 1
    for r in records[:3]:
        print(f"  name={r.get('name')!r} artist={[a.get('name') for a in (r.get('artists') or []) if isinstance(a, dict)]!r}")
        print(f"    originalId(明文)={r.get('originalId')!r}  id(加密)={str(r.get('id'))[:24]}…  playFlag={r.get('playFlag')}")

    top = records[0]
    plain = str(top.get("originalId") or "")
    enc = str(top.get("id") or "")

    print("\n=== 2. 两种 ID 形态分别喂给 song_detail ===")
    for label, sid in (("加密 id", enc), ("明文 originalId", plain)):
        try:
            d = await api.song_detail(sid)
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:<16} → 调用异常：{str(exc)[:80]}")
            continue
        has_url = bool(d.get("playUrl"))
        print(f"  {label:<16} → 返回字段 {sorted(d)[:6] if d else '(空)'}")
        print(f"  {'':<16}   name={d.get('name')!r} playUrl={'有' if has_url else '**没有**'}")
        if has_url:
            print(f"  {'':<16}   ✓ 这个形态可用")

    print("\n=== 3. mpv 当前状态 ===")
    try:
        st = await player.get_state()
        print("  " + json.dumps(st, ensure_ascii=False)[:300])
        print(f"  status={st.get('status')!r} volume={st.get('volume')!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"  取状态失败：{exc}")

    if not do_play:
        print("\n（未播放；加 --play 可实测一次）")
        return 0

    print("\n=== 4. 实测播放（加密 id 优先）===")
    ok, briefs, titles = await _play(enc, plain)
    print(f"  play_urls 返回 {ok}；曲目 {titles}")
    st = await player.get_state()
    print(f"  播放后状态：status={st.get('status')!r} title={st.get('title')!r} volume={st.get('volume')!r}")
    return 0 if ok else 1


async def _play(enc: str, plain: str) -> tuple[bool, list, list]:
    """按"加密优先、明文兜底"的顺序取直链并播放。"""
    from yuiro.netease import api, player

    for sid in (enc, plain):
        if not sid:
            continue
        try:
            d = await api.song_detail(sid)
        except Exception:  # noqa: BLE001
            continue
        url = d.get("playUrl")
        if url:
            return await player.play_urls([url], [str(d.get("name") or "")]), [], [d.get("name")]
    return False, [], []


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
