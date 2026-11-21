"""S31 测试：调试台面板依赖的 API 契约（前缀 / 字段名 / 状态语义）。

为什么单独测这个：S31 是前端接线，最大的风险**不是**"组件写错"，
而是"前端假设的字段名与后端不一致"。本次就抓到两个真实 bug：

1. debug router 的前缀是 ``/api``（此前桌宠窗口误写 ``/debug`` → 全部 404）；
2. 任务视图的 ``status`` 覆盖了外层 ``{"status": "ok"}`` → 改用 ``task_status``。

这些测试把契约钉死，避免下次再靠"点一下试试"发现。
"""
from __future__ import annotations

import asyncio
import os
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yuiro.debug_api import router
from yuiro.memory import MemorySystem
from yuiro.memory.relationship import RelationshipMemory
from yuiro.task import TaskRuntime


def _client(**state) -> TestClient:
    """最小 app：只挂 debug router + 需要注入的 state。"""
    app = FastAPI()
    app.include_router(router)
    for key, value in state.items():
        setattr(app.state, key, value)
    return TestClient(app)


# ── 提示词的"留空即回退内置"契约（S52）───────────────────────────────────
def test_config_exposes_prompt_text_defaults() -> None:
    """GET /api/config 必须回传提示词的内置默认文案。

    背景：``system_prompt`` 在 config.toml 里留空时，引擎会用 agent 模块里的内置文案，
    但调试台只拿到空串 → 输入框一片空白，看起来像"没加载出来"（用户实测反馈）。
    前端要靠 ``text_defaults`` 把**实际生效的内容**显示出来，故这里把契约钉死。
    """
    from yuiro.agent import _DEFAULT_PERSONA_PROMPT, _DEFAULT_SYSTEM_PROMPT
    from yuiro.config import AppConfig

    client = _client(app_config=AppConfig())
    body = client.get("/api/config").json()

    defaults = body.get("text_defaults") or {}
    assert defaults.get("persona", {}).get("system_prompt") == _DEFAULT_SYSTEM_PROMPT
    assert defaults.get("persona", {}).get("persona_prompt") == _DEFAULT_PERSONA_PROMPT
    # 文案不能是空串，否则前端回退后仍是空白（等于没修）
    assert len(_DEFAULT_SYSTEM_PROMPT) > 100
    assert len(_DEFAULT_PERSONA_PROMPT) > 50


def test_config_prompt_saved_and_default_are_separate() -> None:
    """两个来源互不干扰：配置留空 → 生效值取内置；配置写了 → 生效值取配置。"""
    from yuiro.config import AppConfig

    cfg = AppConfig()
    cfg.persona.persona_prompt = "我是被写进配置的那一份"

    client = _client(app_config=cfg)
    body = client.get("/api/config").json()

    saved = body["sections"]["persona"]
    defaults = body["text_defaults"]["persona"]
    # 配置里有值的字段：生效值 = 配置值；内置文案仍然保留（供"清空并回退内置"用）
    assert saved["persona_prompt"] == "我是被写进配置的那一份"
    assert defaults["persona_prompt"]  # 内置那份还在，没被配置覆盖掉
    # 配置里留空的字段：生效值由前端回退到内置
    assert saved["system_prompt"] == ""
    assert defaults["system_prompt"]


def _tasks(tmp: str) -> TaskRuntime:
    return TaskRuntime(store_dir=os.path.join(tmp, "tasks"))


# ── 前缀契约（bug 1）──────────────────────────────────────────────────────
def test_router_prefix_is_api_not_debug() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = _client(tasks=_tasks(tmp))
        assert client.get("/api/task/list").status_code == 200
        assert client.get("/debug/task/list").status_code == 404


# ── 任务契约（bug 2）──────────────────────────────────────────────────────
def test_task_list_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt = _tasks(tmp)
        client = _client(tasks=rt)
        asyncio.run(rt.plan("整理下载文件夹", ["列清单", "归档"]))
        body = client.get("/api/task/list").json()
        assert body["status"] == "ok"  # 外层状态没被任务状态覆盖
        assert body["count"] == 1
        item = body["tasks"][0]
        assert item["task_status"] == "pending_approval"
        assert item["goal"] == "整理下载文件夹"
        assert item["steps"] == ["列清单", "归档"]
        assert item["progress"] == "0/2"


def test_task_approve_can_rewrite_steps() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt = _tasks(tmp)
        client = _client(tasks=rt)
        task = asyncio.run(rt.plan("整理", ["旧A", "旧B"]))
        body = client.post(
            f"/api/task/{task.id}/approve", params={"steps": "新A|新B|新C"}
        ).json()
        assert body["status"] == "ok"
        assert body["task_status"] == "running"
        assert body["steps"] == ["新A", "新B", "新C"]
        # 重复批准 → 明确报错（而不是静默成功）
        again = client.post(f"/api/task/{task.id}/approve").json()
        assert again["status"] == "error"


def test_task_reject_and_retry_endpoints() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rt = _tasks(tmp)
        client = _client(tasks=rt)
        planned = asyncio.run(rt.plan("不放心的事", ["a"]))
        rejected = client.post(f"/api/task/{planned.id}/reject", params={"reason": "再想想"}).json()
        assert rejected["task_status"] == "cancelled"

        running = asyncio.run(rt.create("会失败的事", ["a"]))
        retried = client.post(f"/api/task/{running.id}/retry", params={"reason": "占用了"}).json()
        assert retried["status"] == "ok"
        assert retried["task_status"] == "running"
        assert retried["attempts"] == 1


def test_task_endpoints_without_runtime_are_warn() -> None:
    body = _client().get("/api/task/list").json()
    assert body["status"] == "warn"


# ── 人格基线契约 ──────────────────────────────────────────────────────────
def test_eval_scenarios_and_run() -> None:
    client = _client()
    meta = client.get("/api/eval/personality/scenarios").json()
    assert meta["status"] == "ok"
    assert meta["total"] >= 20
    assert "chat" in meta["by_category"]

    report = client.post(
        "/api/eval/personality", params={"live": "false", "limit": 3}
    ).json()
    assert report["status"] == "ok"
    assert report["total"] == 3
    assert "prompt_hash" in report and "by_category" in report


# ── 记忆洞察契约 ──────────────────────────────────────────────────────────
def test_relationship_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rel = RelationshipMemory(os.path.join(tmp, "rel.json"))
        rel.note_interaction()
        rel.note_task_completed("整理下载文件夹")
        body = _client(relationship=rel).get("/api/memory/relationship").json()
        assert body["status"] == "ok"
        assert body["interactions"] == 1
        assert body["tasks_completed"] == 1
        assert body["days_known"] == 1
        assert "认识 1 天" in body["summary"]


def test_relationship_without_runtime_is_warn() -> None:
    assert _client().get("/api/memory/relationship").json()["status"] == "warn"


def test_showcase_without_memory_is_warn() -> None:
    """未装配记忆时前端应收到 warn（用于显示提示，而不是抛错）。"""
    assert _client().get("/api/memory/showcase").json()["status"] == "warn"


# ── 表演库 / 存在感（S18/S20 面板复用）────────────────────────────────────
def test_performances_and_presence_state_warn_paths() -> None:
    client = _client()
    assert client.get("/api/avatar/performances").json()["status"] == "warn"
    assert client.get("/api/presence/state").json()["status"] == "warn"
    assert client.get("/api/capability/scope").json()["status"] == "ok"


# ── 记忆删除契约（S50：主表与 FTS/向量附属表齐删 + 即时反馈）──────────────
def _memory(tmp: str) -> MemorySystem:
    return MemorySystem(
        os.path.join(tmp, "mem.db"), rrf_k=60, top_k=3, embedder_model="md5"
    )


def test_delete_episode_removes_message_fts_and_vector() -> None:
    """★ S50 护栏：单条删除必须**三表齐删**（messages / fts / vec）。

    此前只删 messages 主表 —— 用户在调试台删掉的记忆，向量还躺在
    ``messages_vec`` 里（生产库实测 152 条孤儿），直接看库就像"删除没落库"；
    孤儿向量还占着 rowid 污染语义检索。响应须带 ``deleted`` 数量供前端即时反馈。
    """
    with tempfile.TemporaryDirectory() as tmp:
        memory = _memory(tmp)
        rid = asyncio.run(memory.retriever.add("我喜欢吃火锅"))
        client = _client(memory=memory)
        body = client.delete(f"/api/memory/episodes/{rid}").json()
        assert body["ok"] is True and body["deleted"] == 1
        for table in ("messages", "messages_fts", "messages_vec"):
            n = memory.store.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE rowid = ?", (rid,)
            ).fetchone()[0]
            assert n == 0, f"{table} 残留该 rowid —— 删除未连带附属表"
        memory.close()


def test_clear_memory_wipes_all_tables_and_reports_count() -> None:
    """★ S50 护栏：全清必须**四表齐删**，并返回删除数量。

    全清后新记忆 rowid 从头编号 —— 若向量表未清，新文本会与旧向量**错位关联**
    （新记忆拿到旧语义），这是比"残留"更隐蔽的检索失真。
    """
    with tempfile.TemporaryDirectory() as tmp:
        memory = _memory(tmp)
        asyncio.run(memory.remember("我喜欢吃火锅。", "火锅好吃！"))
        client = _client(memory=memory)
        body = client.delete("/api/memory").json()
        assert body["ok"] is True
        assert body["deleted"]["episodes"] == 1
        for table in ("messages", "messages_fts", "messages_vec", "facts"):
            n = memory.store.conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            assert n == 0, f"{table} 未清空"
        memory.close()


class _StubLoop:
    """AgentLoop 的最小替身：只验证"全清联动了会话内存"。"""

    def __init__(self) -> None:
        self.called = False

    def clear_session_memory(self) -> int:
        self.called = True
        return 5


def test_clear_memory_resets_relationship_and_session_history() -> None:
    """★ S50 护栏（用户实测回归）：全清必须联动**关系记忆**与**会话内存**。

    用户在调试台清空全部记忆后，回复仍出现"认识六天、聊了一百三十九次"
    （来自 ``relationship.json``，独立文件不在 SQLite）与"I_drcen/VIP"
    （来自会话内存 history 里 NCM profile 的工具结果）。漏掉任何一处
    都不算"清空"—— 端与端的操作必须与数据一致。
    """
    with tempfile.TemporaryDirectory() as tmp:
        memory = _memory(tmp)
        rel = RelationshipMemory(os.path.join(tmp, "rel.json"))
        rel.note_interaction()
        rel.note_interaction()
        loop = _StubLoop()
        client = _client(memory=memory, relationship=rel, agent_loop=loop)
        body = client.delete("/api/memory").json()
        assert body["ok"] is True
        assert body["deleted"]["relationship_reset"] is True
        assert body["deleted"]["history_turns"] == 5
        assert loop.called is True
        assert rel.state.interactions == 0
        assert rel.summary() == "", "关系记忆重置后不得再注入任何总结"
        memory.close()


def test_relationship_memory_reset_persists() -> None:
    """RelationshipMemory.reset() 落盘：重载实例（模拟重启）后仍是零。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rel.json")
        rel = RelationshipMemory(path)
        rel.note_interaction()
        rel.note_task_completed("整理")
        rel.reset()
        reopened = RelationshipMemory(path)
        assert reopened.state.interactions == 0
        assert reopened.state.tasks_completed == 0
        assert reopened.summary() == ""


# ── 日记契约（S51：结构化保存 + 回顾 + 隐私联动）────────────────────────────
class _DiaryLLM:
    """随输入生成（**不能返回固定 JSON**：那样"第二篇"会带着第一篇的正文，
    让搜索类测试假阳性 —— 这正是写这段测试时踩到的）。"""

    async def stream_text(self, messages, tools=None, **kwargs):
        import json

        from yuiro.agent import LLMChunk

        prompt = str(messages[-1].get("content", ""))
        # 解构 prompt 末尾是 `---\n原文\n---`，据此取回原文
        parts = prompt.rsplit("---", 2)
        body = parts[1].strip() if len(parts) >= 3 else prompt
        payload = json.dumps(
            {
                "polished_text": body,
                "summary": body,
                "mood_tags": ["轻松"],
                "topics": ["跑步"] if "跑步" in body else [],
                "entities": [],
                "followup_question": "",
                "narrative_type": "short",
            },
            ensure_ascii=False,
        )
        yield LLMChunk(kind="token", content=payload)
        yield LLMChunk(kind="done")


def _diary_client(tmp: str):
    from yuiro.diary import DiaryStore
    from yuiro.diary.service import DiaryService

    store = DiaryStore(os.path.join(tmp, "diary.db"))
    svc = DiaryService(store, memory=None, llm=_DiaryLLM())
    return _client(diary=svc, diary_store=store), store


def test_diary_endpoints_warn_without_service() -> None:
    """未装配日记时给 warn（前端显示提示），不是 500。"""
    assert _client().get("/api/diary/list").json()["status"] == "warn"
    assert _client().get("/api/diary/stats").json()["status"] == "warn"


def test_diary_submit_list_detail_delete() -> None:
    """提交 → 列表 → 详情 → 删除（含刷新后列表变空）。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        client, _store = _diary_client(tmp)

        assert client.get("/api/diary/list").json()["count"] == 0

        body = client.post(
            "/api/diary",
            json={"raw_text": "今天去公园跑步", "privacy": "local_only"},
        ).json()
        assert body["status"] == "ok" and body["diary_id"] > 0

        items = client.get("/api/diary/list").json()
        assert items["count"] == 1
        assert "跑步" in items["items"][0]["summary"]
        assert items["items"][0]["mood_tags"] == ["轻松"]

        detail = client.get(f"/api/diary/{body['diary_id']}").json()
        assert detail["diary"]["raw_text"] == "今天去公园跑步"
        assert detail["tags"]["topic"] == ["跑步"]

        assert client.delete(f"/api/diary/{body['diary_id']}").json()["status"] == "ok"
        assert client.get("/api/diary/list").json()["count"] == 0


def test_diary_search_short_chinese_word() -> None:
    """★ 回顾搜索对 2 字中文词也必须有效（FTS trigram 对 <3 字符返回空）。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        client, _store = _diary_client(tmp)
        client.post("/api/diary", json={"raw_text": "今天去公园跑步", "privacy": "local_only"})
        client.post("/api/diary", json={"raw_text": "加班到很晚", "privacy": "local_only"})
        hits = client.get("/api/diary/list", params={"q": "跑步"}).json()
        assert hits["count"] == 1


def test_diary_privacy_change_is_reported() -> None:
    """改档位要**如实回报**动了多少记忆（前端据此提示用户）。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        client, _store = _diary_client(tmp)
        did = client.post(
            "/api/diary", json={"raw_text": "今天去公园跑步", "privacy": "shared"}
        ).json()["diary_id"]
        res = client.post(
            f"/api/diary/{did}/privacy", params={"value": "local_only"}
        ).json()
        assert res["status"] == "ok"
        assert res["from"] == "shared" and res["to"] == "local_only"


def test_diary_submit_rejects_empty_and_bad_privacy() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        client, _store = _diary_client(tmp)
        assert client.post("/api/diary", json={"raw_text": "  "}).json()["status"] == "error"
        bad = client.post(
            "/api/diary", json={"raw_text": "x", "privacy": "nonsense"}
        ).json()
        assert bad["status"] == "error"
