"""S41 测试：歌单名匹配（字面 + 语义）与「不猜」原则。

用户的真实诉求："我说'播放我账号里的某某歌单'，桌宠能按语义近似到对应的歌单"。
本测试固化三件事：

1. **字面优先**（便宜且准）：完全相等 / 唯一包含 → 直接播；
2. **语义兜底**：纯描述（"晚上助眠听的"）无字面重叠时才启用向量；
3. **不确定就不猜**：多个候选 → 返回列表让用户选。
   （猜错一张歌单 = 整列放错歌，这个代价不值得赌）
"""
from __future__ import annotations

import pytest

from yuiro.tools import netease_tool as nt

LISTS = [
    {"name": "我喜欢的音乐", "id": "A1", "originalId": "1", "trackCount": 300},
    {"name": "学习专用 BGM", "id": "A2", "originalId": "2", "trackCount": 42},
    {"name": "2026 跑步歌单", "id": "A3", "originalId": "3", "trackCount": 88},
    {"name": "晚安", "id": "A4", "originalId": "4", "trackCount": 10},
]


def test_norm_name_strips_decoration() -> None:
    assert nt._norm_name("我喜欢的音乐（Live）") == "我喜欢的音乐live"
    assert nt._norm_name("2026 - 跑步 歌单") == "2026跑步歌单"
    assert nt._norm_name("") == ""


@pytest.mark.asyncio
async def test_exact_match_wins() -> None:
    hit, opts, why = await nt._match_playlist("我喜欢的音乐", LISTS)
    assert hit is not None and hit["id"] == "A1"
    assert opts == [] and why == "字面"


@pytest.mark.asyncio
async def test_unique_contains_match() -> None:
    """「学习」只命中一张 → 直接播，不必多问一句。"""
    hit, _opts, _ = await nt._match_playlist("学习", LISTS)
    assert hit is not None and hit["id"] == "A2"
    assert _opts == []


@pytest.mark.asyncio
async def test_ambiguous_returns_candidates_not_guess() -> None:
    """能命中**多张**时 → 返回候选让用户选，绝不猜。

    注意区分：如果包含匹配只命中**一张**，那说明用户的说法足以唯一定位，
    直接播是对的（见 test_unique_contains_match）——所以这里特意造了
    两张都含「学习」的歌单。
    """
    lists = [
        {"name": "学习专用 BGM", "id": "A2", "trackCount": 42},
        {"name": "学习资料歌单", "id": "A5", "trackCount": 12},
        {"name": "晚安", "id": "A4", "trackCount": 10},
    ]
    hit, opts, why = await nt._match_playlist("学习", lists)
    assert hit is None, "多个候选时不该自作主张"
    assert len(opts) == 2, f"应把两张候选都给出来，实际 {opts}"
    assert "无确定命中" in why


@pytest.mark.asyncio
async def test_semantic_fallback_when_no_literal_overlap(monkeypatch) -> None:
    """纯描述（无字面重叠）→ 走语义向量。这正是用户要的"语义近似"。"""
    table = {
        "晚上助眠听的": [1.0, 0.0],
        "晚安": [0.995, 0.02],
        "我喜欢的音乐": [0.0, 1.0],
        "学习专用 BGM": [0.0, 1.0],
        "2026 跑步歌单": [0.0, 1.0],
    }

    class _FakeEmb:
        async def embed(self, text):
            return table.get(text, [0.0, 1.0])

        async def embed_many(self, texts):
            return [table.get(t, [0.0, 1.0]) for t in texts]

    monkeypatch.setattr(nt, "_get_embedder", lambda: _FakeEmb())
    hit, opts, why = await nt._match_playlist("晚上助眠听的", LISTS)
    assert hit is not None and hit["id"] == "A4", f"应语义命中「晚安」，实际 {hit}"
    assert "语义" in why


@pytest.mark.asyncio
async def test_semantic_close_call_returns_candidates(monkeypatch) -> None:
    """两个歌单语义都很接近 → 不猜，给候选（避免"差一点点"就放错整列）。"""
    table = {
        "想听的": [1.0, 0.0],
        "晚安": [1.0, 0.002],
        "我喜欢的音乐": [0.998, 0.004],
        "学习专用 BGM": [0.0, 1.0],
        "2026 跑步歌单": [0.0, 1.0],
    }

    class _FakeEmb:
        async def embed(self, text):
            return table.get(text, [0.0, 1.0])

        async def embed_many(self, texts):
            return [table.get(t, [0.0, 1.0]) for t in texts]

    monkeypatch.setattr(nt, "_get_embedder", lambda: _FakeEmb())
    hit, opts, why = await nt._match_playlist("想听的", LISTS)
    assert hit is None and opts, f"接近时应当返回候选，实际 hit={hit} opts={opts}"
    assert "接近" in why


@pytest.mark.asyncio
async def test_no_embedder_still_works_literally(monkeypatch) -> None:
    """向量不可用（装不上 BGE-M3）时，字面匹配仍要正常工作。"""
    monkeypatch.setattr(nt, "_get_embedder", lambda: None)
    hit, _, _ = await nt._match_playlist("晚安", LISTS)
    assert hit is not None and hit["id"] == "A4"


@pytest.mark.asyncio
async def test_semantic_skipped_when_embedder_not_ready(monkeypatch) -> None:
    """嵌入器**未就绪**时不许用语义。

    未就绪的 ``embed()`` 会静默降级成 md5 向量 —— 无语义、相似度≈随机。
    若不管这个，语义匹配会"假装跑过却全错"（实测：说"学习"匹配不到"自习室"）。
    正确行为：返回候选让用户选。
    """

    class _NotReady:
        async def wait_ready(self, timeout_s=8.0):  # noqa: ARG002
            return False

        async def embed(self, text):  # noqa: ARG002
            return [1.0, 0.0]  # 若真被调用，会"命中"任意歌单 —— 测试就是要拦住这种情况

        async def embed_many(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(nt, "_get_embedder", lambda: _NotReady())
    hit, opts, _ = await nt._match_playlist("晚上助眠听的", LISTS)
    assert hit is None and opts, "未就绪时不该用无语义向量乱匹配"


@pytest.mark.asyncio
async def test_empty_inputs_are_safe() -> None:
    assert (await nt._match_playlist("", LISTS))[0] is None
    assert (await nt._match_playlist("随便", []))[0] is None


@pytest.mark.asyncio
async def test_account_playlists_merges_three_sources_and_dedupes(monkeypatch) -> None:
    """账号歌单 = 订阅 + 创建 + 收藏，按名字去重（此前只列"我创建的"）。"""

    async def subed(limit=50):
        return [{"name": "A", "id": "1"}, {"name": "只订阅的", "id": "9"}]

    async def created(limit=50):
        return [{"name": "A", "id": "1b"}, {"name": "B", "id": "2"}]

    async def collected(limit=50):
        return [{"name": "B", "id": "2b"}]

    monkeypatch.setattr(nt.api, "playlist_subed", subed)
    monkeypatch.setattr(nt.api, "playlist_created", created)
    monkeypatch.setattr(nt.api, "playlist_collected", collected)

    names = sorted(r["name"] for r in await nt._account_playlists())
    assert names == ["A", "B", "只订阅的"]


@pytest.mark.asyncio
async def test_resolve_playlist_encrypted_maps_plain_id(monkeypatch) -> None:
    """明文 originalId → 加密 id（取歌曲列表的接口要加密 id）。"""

    async def account(limit=50):
        return [{"name": "X", "id": "ENC-1", "originalId": "PLAIN-1"}]

    monkeypatch.setattr(nt, "_account_playlists", account)
    assert await nt._resolve_playlist_encrypted("PLAIN-1") == "ENC-1"
    assert await nt._resolve_playlist_encrypted("ENC-1") == "ENC-1"
