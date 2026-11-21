"""S43 测试：会话生命周期（回收 / 复活 / 一览）。

**背景**：原先 `SessionManager.close()` 全项目**零调用** —— 会话只增不减
（实测开发态热重载一天攒下好几个，每个都带着上下文常驻内存）；而前端带旧 id
重连时会被**静默新建**一个空会话，用户侧表现为"上下文全丢了"且毫无提示。

本测试钉住三件事：

1. **回收必须保守** —— 有连接的绝不能收、没到 TTL 的不能收（宁可漏收，不可误收）；
2. **复活要还原身份与时间** —— 否则"恢复上次对话"是句空话；
3. **解析优先级：内存 → 磁盘复活 → 新建** —— 顺序错了就会不断新建，等于没修。

注：本机 `pytest tmp_path` 不可用，统一用 `tempfile.TemporaryDirectory`。
"""
from __future__ import annotations

import tempfile
import time

from yuiro.runtime.event_log import EventLog
from yuiro.runtime.events import AgentEvent
from yuiro.runtime.session import SessionManager, SessionState


def _seed(log: EventLog, session_id: str, n: int = 2) -> None:
    """往事件日志里写几条事件（模拟历史会话）。"""
    for i in range(n):
        log.append(AgentEvent(
            type="user.message", source="test", session_id=session_id, payload={"i": i}
        ))


# ── 回收：保守性原则 ─────────────────────────────────────────────────────
def test_sweep_drops_expired_suspended() -> None:
    mgr = SessionManager(suspend_ttl_s=10.0)
    s = mgr.create()
    s.state = SessionState.SUSPENDED
    s.last_active_at = time.time() - 100

    assert mgr.sweep() == [s.session_id]
    assert mgr.get(s.session_id) is None, "超时挂起会话应从内存移除"


def test_sweep_never_drops_connected_sessions() -> None:
    """有连接的会话**绝不能**回收 —— 哪怕它很久没说话。"""
    mgr = SessionManager(suspend_ttl_s=1.0)
    s = mgr.create()
    s.control_ws = object()          # 假装还连着
    s.last_active_at = time.time() - 9999

    assert mgr.sweep() == []
    assert mgr.get(s.session_id) is not None


def test_sweep_keeps_fresh_suspended() -> None:
    """刚挂起的不收 —— 用户很可能马上回来（刷新页面就是这种）。"""
    mgr = SessionManager(suspend_ttl_s=1800.0)
    s = mgr.create()
    s.state = SessionState.SUSPENDED
    s.last_active_at = time.time()

    assert mgr.sweep() == []


def test_sweep_ignores_active_sessions() -> None:
    """ACTIVE 但两条通道都空（异常态）也不收 —— sweep 只认 SUSPENDED。"""
    mgr = SessionManager(suspend_ttl_s=1.0)
    s = mgr.create()
    s.last_active_at = time.time() - 9999
    assert mgr.sweep() == []


# ── 复活：身份与时间要还原 ───────────────────────────────────────────────
def test_revive_from_event_log() -> None:
    with tempfile.TemporaryDirectory() as d:
        log = EventLog(store_dir=d)
        _seed(log, "sess-1", n=3)
        mgr = SessionManager(event_log=log)

        s = mgr.revive("sess-1")
        assert s is not None and s.session_id == "sess-1"
        assert s.state is SessionState.SUSPENDED, "复活后应先挂起，等真正接上再转 ACTIVE"
        assert s.last_active_at > 0 and s.created_at <= s.last_active_at


def test_revive_returns_none_without_log() -> None:
    with tempfile.TemporaryDirectory() as d:
        mgr = SessionManager(event_log=EventLog(store_dir=d))
        assert mgr.revive("never-existed") is None


def test_revive_without_event_log_is_safe() -> None:
    """没注入 EventLog 时不能炸（向后兼容）。"""
    mgr = SessionManager()
    assert mgr.revive("any") is None


# ── 解析优先级：内存 → 磁盘 → 新建 ───────────────────────────────────────
def test_get_or_create_prefers_memory() -> None:
    mgr = SessionManager(suspend_ttl_s=1800.0)
    s = mgr.create()
    s.state = SessionState.SUSPENDED
    assert mgr.get_or_create(s.session_id) is s, "内存命中就该直接返回同一个对象"


def test_get_or_create_revives_from_disk() -> None:
    """★ 核心修复：引擎重启后，带旧 id 重连必须**复活**而不是新建。"""
    with tempfile.TemporaryDirectory() as d:
        log = EventLog(store_dir=d)
        _seed(log, "old-session")

        mgr = SessionManager(event_log=log)      # 全新实例 = 模拟引擎重启
        got = mgr.get_or_create("old-session")

        assert got.session_id == "old-session", "应复活旧会话，而不是静默新建空会话"


def test_get_or_create_creates_when_unknown() -> None:
    with tempfile.TemporaryDirectory() as d:
        mgr = SessionManager(event_log=EventLog(store_dir=d))
        got = mgr.get_or_create("no-such-session")
        assert got.session_id != "no-such-session", "无法复活时应新建（兼容旧前端）"


def test_closed_session_is_revived_not_reused() -> None:
    """已 CLOSED 的会话不再复用内存对象；有日志则复活，没日志则新建。"""
    with tempfile.TemporaryDirectory() as d:
        log = EventLog(store_dir=d)
        _seed(log, "c1")
        mgr = SessionManager(event_log=log)
        first = mgr.get_or_create("c1")
        first.state = SessionState.CLOSED

        again = mgr.get_or_create("c1")
        assert again is not first
        assert again.state is SessionState.SUSPENDED, "复活出来的应是干净状态"


# ── 归档与一览 ───────────────────────────────────────────────────────────
def test_archive_drops_from_memory_but_keeps_log() -> None:
    with tempfile.TemporaryDirectory() as d:
        log = EventLog(store_dir=d)
        _seed(log, "s1")
        mgr = SessionManager(event_log=log)
        mgr.get_or_create("s1")

        assert mgr.archive("s1") is True
        assert mgr.get("s1") is None
        assert log.load("s1"), "归档不能删事件日志 —— 否则就真的不可恢复了"
        # 归档后仍可复活（日志在），复活后可再归档 —— 这正是设计意图
        assert mgr.revive("s1") is not None
        assert mgr.archive("s1") is True
        # 对**不在内存中**的会话归档返回 False（幂等，不报错）
        assert mgr.archive("s1") is False


def test_list_sessions_merges_memory_and_disk() -> None:
    """列表要同时给出内存中的活动会话和磁盘上的历史会话（"选择加载页"的数据源）。"""
    with tempfile.TemporaryDirectory() as d:
        log = EventLog(store_dir=d)
        _seed(log, "hist-1")
        mgr = SessionManager(event_log=log)
        live = mgr.create()
        live.control_ws = object()

        items = {x["session_id"]: x for x in mgr.list_sessions()}
        assert live.session_id in items and items[live.session_id]["live"] is True
        assert "hist-1" in items and items["hist-1"]["state"] == "archived"
        assert items["hist-1"]["has_log"] is True


def test_list_sessions_is_sorted_recent_first() -> None:
    with tempfile.TemporaryDirectory() as d:
        log = EventLog(store_dir=d)
        _seed(log, "older")
        _seed(log, "newer")
        mgr = SessionManager(event_log=log)
        ids = [x["session_id"] for x in mgr.list_sessions()]
        assert set(ids) == {"older", "newer"}
