"""C0：双角色持久化、切换事务、旧草稿与嵌入资源 ownership。"""
from __future__ import annotations

import asyncio
import copy
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yuiro.character_switch import CharacterSwitch
from yuiro.characters import CharacterStore
from yuiro.config import AppConfig, load_config, save_config
from yuiro.debug_api import router


@pytest.fixture
def cards(tmp_path):
    path = tmp_path / "config.toml"
    cfg = AppConfig()
    cfg.memory.embedder = "md5"
    cfg.persona.persona_prompt = "保留用户原人设"
    cfg.tts.siliconflow_key = "must-not-enter-role-card"
    save_config(cfg, path)
    store = CharacterStore(path)
    assert store.ensure(cfg) == "hiyori"
    return store, store.resolve("hiyori", cfg)


def test_bootstrap_preserves_original_and_separates_hotaru(cards):
    store, hiyori = cards
    hotaru = store.resolve("hotaru", hiyori)
    assert hiyori.persona.persona_prompt == "保留用户原人设"
    assert "Hotaru Shiomi" in hotaru.persona.model_path
    assert hotaru.persona.expression_map == {}
    assert hotaru.persona.profiles == {}
    assert hiyori.memory.db_path != hotaru.memory.db_path
    assert hotaru.persona.voice != hiyori.persona.voice
    assert hotaru.tts.siliconflow_key == hiyori.tts.siliconflow_key == "must-not-enter-role-card"
    assert "must-not-enter-role-card" not in (store.root / "hiyori.toml").read_text()
    store.ensure(hiyori)
    assert store.resolve("hiyori", hiyori).persona.persona_prompt == "保留用户原人设"


def test_edit_a_b_a_and_restart(cards):
    store, cfg = cards
    cfg.llm.model = "hiyori-brain"
    cfg.persona.performance_map = {"hello": "happy, Idle#6"}
    save_config(cfg)
    other = store.resolve("hotaru", cfg)
    other.llm.model = "hotaru-brain"
    other.persona.performance_map = {"quiet": ""}
    other.persona.voice = "independent-voice"
    save_config(other)
    store.commit("hotaru")
    restarted = load_config(store.config_path)
    assert restarted.llm.model == "hotaru-brain"
    assert restarted.persona.voice == "independent-voice"
    assert restarted.persona.performance_map == {"quiet": ""}
    store.commit("hiyori")
    back = load_config(store.config_path)
    assert back.llm.model == "hiyori-brain"
    assert back.persona.performance_map == {"hello": "happy, Idle#6"}


def test_shared_device_and_permissions_not_copied_to_card(cards):
    store, cfg = cards
    cfg.vad.barge_in_enabled = True
    cfg.capability.profile = "strict"
    save_config(cfg)
    back = load_config(store.config_path)
    assert back.vad.barge_in_enabled
    assert back.capability.profile == "strict"
    assert "[server]" not in (store.root / "hiyori.toml").read_text()
    other = store.resolve("hotaru", back)
    assert other.capability.profile == "strict"


@pytest.mark.parametrize("role", ["../config", "", "/hiyori", "HOTARU"])
def test_reject_unknown_ids(cards, role):
    store, cfg = cards
    with pytest.raises(ValueError):
        store.resolve(role, cfg)


def make_service(store, cfg, *, activate=None, prepare=None, quiesce=None):
    return CharacterSwitch(store, cfg, prepare=prepare or AsyncMock(return_value={}),
                           quiesce=quiesce or AsyncMock(), activate=activate or AsyncMock(),
                           notify=AsyncMock())


@pytest.mark.asyncio
async def test_transaction_commits_after_activation(cards):
    store, cfg = cards
    order = []

    async def activate(role, bundle):
        assert store.active() == "hiyori"
        assert cfg._character_id == "hotaru"
        order.append(role)

    service = make_service(store, cfg, activate=activate)
    result = await service.switch("hotaru")
    assert order == ["hotaru"]
    assert result["active_id"] == "hotaru"
    assert result["revision"] == 1
    assert result["switch_ms"] >= 0
    service.quiesce.assert_awaited_once()
    service.notify.assert_awaited_once_with("hotaru", 1)


@pytest.mark.asyncio
async def test_prepare_failure_does_not_stop_current_character(cards):
    store, cfg = cards
    service = make_service(store, cfg, prepare=AsyncMock(side_effect=ValueError("missing asset")))
    with pytest.raises(ValueError):
        await service.switch("hotaru")
    service.quiesce.assert_not_awaited()
    assert store.active() == "hiyori"
    assert not service.switching


@pytest.mark.asyncio
async def test_failed_activation_rolls_back_config_and_pointer(cards):
    store, cfg = cards
    old = copy.deepcopy(cfg)

    async def activate(role, bundle):
        if role == "hotaru":
            raise RuntimeError("provider failed")

    service = make_service(store, cfg, activate=activate)
    with pytest.raises(RuntimeError):
        await service.switch("hotaru")
    assert cfg.persona == old.persona
    assert cfg.llm == old.llm
    assert store.active() == "hiyori"
    assert service.revision == 0
    service.notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_switches_are_serialized(cards):
    store, cfg = cards
    entered, release = asyncio.Event(), asyncio.Event()

    async def quiesce():
        entered.set()
        await release.wait()

    service = make_service(store, cfg, quiesce=quiesce)
    first = asyncio.create_task(service.switch("hotaru"))
    await entered.wait()
    second = asyncio.create_task(service.switch("hiyori"))
    assert service.switching
    release.set()
    await asyncio.gather(first, second)
    assert service.revision == 2
    assert store.active() == "hiyori"


@pytest.mark.asyncio
async def test_cancelled_switch_restores_old_identity(cards):
    store, cfg = cards
    entered = asyncio.Event()

    async def activate(role, bundle):
        if role == "hotaru":
            entered.set()
            await asyncio.Event().wait()

    service = make_service(store, cfg, activate=activate)
    task = asyncio.create_task(service.switch("hotaru"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.active() == cfg._character_id == "hiyori"
    assert not service.switching


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_runtime(cards, monkeypatch):
    store, cfg = cards
    service = make_service(store, cfg)
    monkeypatch.setattr(store, "commit", lambda role: (_ for _ in ()).throw(OSError("disk error")))
    with pytest.raises(OSError):
        await service.switch("hotaru")
    assert store.active() == cfg._character_id == "hiyori"
    assert service.activate.await_args_list[-1].args == ("hiyori", None)


def client_for(store, cfg):
    app = FastAPI()
    app.include_router(router)
    app.state.app_config = cfg
    app.state.characters = make_service(store, cfg)
    return TestClient(app), app


def test_stale_save_rejected_without_mutation(cards):
    store, cfg = cards
    client, _app = client_for(store, cfg)
    body = {"patch": {"persona": {"name": "must-not-save"}},
            "character_id": "hotaru", "character_revision": 0}
    assert client.put("/api/config", json=body).status_code == 409
    assert cfg.persona.name != "must-not-save"
    body["character_id"] = "hiyori"
    body["character_revision"] = -1
    assert client.put("/api/config", json=body).status_code == 409
    assert client.get("/api/config").json()["character"]["active_id"] == "hiyori"


def test_character_switch_auth_and_unknown_id(cards):
    store, cfg = cards
    cfg.server.shared_secret = "test-only-secret"
    client, _app = client_for(store, cfg)
    assert client.post("/api/characters/switch", json={"id": "hotaru"}).status_code == 401
    headers = {"x-yuiro-secret": cfg.server.shared_secret}
    assert client.post("/api/characters/switch", json={"id": "../escape"}, headers=headers).status_code == 400
    response = client.post("/api/characters/switch", json={"id": "hotaru"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["active_id"] == "hotaru"


@pytest.mark.asyncio
async def test_borrowed_embedder_has_independent_stores_and_not_closed(tmp_path):
    from yuiro.memory import Embedder, KnowledgeStore, MemorySystem

    embedder = Embedder(None)
    memories = []
    try:
        for role in ("hiyori", "hotaru"):
            db = str(tmp_path / f"{role}.db")
            knowledge = KnowledgeStore(db, embedder_model=None, embedder=embedder)
            memories.append(MemorySystem(db, embedder_model=None, embedder=embedder, knowledge=knowledge))
        await memories[0].remember("火锅", "喜欢火锅")
        assert await memories[1].retrieve("火锅") == []
        assert await memories[0].retrieve("火锅")
        memories[1].close()
        memories.pop()
        assert await memories[0].retrieve("火锅")
    finally:
        for memory in memories:
            memory.close()
        embedder.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_agent", [False, True])
async def test_actual_composition_root_switch_without_cloud_or_user_data(tmp_path, monkeypatch, with_agent):
    """运行真实 main 装配和切换回调；隔离 cwd、禁用 keychain、不启动服务/预热。"""
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    import yuiro.agent
    import yuiro.keychain

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(yuiro.keychain, "load_llm_key", lambda: "test-no-network" if with_agent else None)
    monkeypatch.setattr(yuiro.agent, "OpenAIProvider", lambda *a, **k: SimpleNamespace())
    calls = []

    def build(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(_history={}, _state={}, _generations={}, _llm=None)

    monkeypatch.setattr(yuiro.agent, "build_agent_loop", build)
    cfg = AppConfig()
    cfg.memory.embedder = "md5"
    cfg.presence.enabled = False
    cfg.proactive.enabled = False
    save_config(cfg, tmp_path / "config.toml")
    source = Path(__file__).resolve().parents[1] / "yuiro/main.py"
    spec = importlib.util.spec_from_file_location("yuiro._c0_isolated_main", source)
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
    service = main.app.state.characters
    hiyori_avatar = main.app.state.avatar
    hiyori_memory = getattr(main.app.state, "memory", None)
    if with_agent:
        main.app.state.agent_loop._history["hiyori-only"] = [{"content": "private"}]
    session = main.app.state.sessions.create()
    ws = SimpleNamespace(close=AsyncMock())
    session.control_ws = ws
    blocked = asyncio.create_task(asyncio.Event().wait())
    main._character_workers.add(blocked)
    try:
        await service.switch("hotaru")
        assert blocked.cancelled()
        ws.close.assert_awaited_once_with(code=1012, reason="character switch")
        hotaru_memory = main.app.state.memory
        assert service.store.active() == "hotaru"
        assert main.app.state.avatar is not hiyori_avatar
        assert main.app.state.runtimes.get("agent")._loop is main.app.state.agent_loop
        assert main.app.state.runtimes.get("task")._rt is main.app.state.tasks
        assert "Hotaru Shiomi" in main.app_config.persona.model_path
        if with_agent:
            assert "hiyori-only" not in main.app.state.agent_loop._history
            assert hotaru_memory.embedder is hiyori_memory.embedder
            assert calls[-1]["memory_system"] is hotaru_memory
            assert calls[-1]["relationship"] is main.app.state.relationship
            assert calls[-1]["event_log"] is main.app.state.event_log
            assert calls[-1]["search_config"] is main.app_config.search
        await service.switch("hiyori")
        assert main.app.state.avatar is hiyori_avatar
        assert main.app.state.memory is not hotaru_memory
        if with_agent:
            assert "hiyori-only" in main.app.state.agent_loop._history
        await service.switch("hotaru")
        assert main.app.state.memory is hotaru_memory
        if with_agent:
            from yuiro.diary import DiaryStore
            from yuiro.diary.service import DiaryService
            from yuiro.diary.session import DiarySession

            diary_store = DiaryStore(tmp_path / "diary.db")
            diary = DiaryService(diary_store, memory=hotaru_memory,
                                 forget_memory=main._forget_character_diary_text)
            main.app.state.diary = diary
            draft = DiarySession(service=diary)
            draft._segments = ["未提交的用户草稿"]
            main.app.state.diary_session = draft
            try:
                saved = await diary.submit("今天测试共享日记", privacy="shared")
                row = diary_store.get(saved["diary_id"])
                text = row["source_meta"]["memory_text"]
                await hiyori_memory.retriever.add(text)
                await service.switch("hiyori")
                assert main.app.state.diary_session._segments == ["未提交的用户草稿"]
                # 模拟另一个角色尚未热加载，撤销路径仍须清除其磁盘记录。
                main._character_cache["hotaru"]["memory"] = None
                try:
                    changed = await diary.change_privacy(saved["diary_id"], "local_only")
                    assert changed["memory_removed"] == 2
                finally:
                    main._character_cache["hotaru"]["memory"] = hotaru_memory
                assert not diary_store.get(saved["diary_id"])["memory_written"]
            finally:
                diary_store.close()
    finally:
        await main._shutdown_character_resources()
