"""S10：NativeBackend（行为对齐 / dry-run / 路径边界 / 装配切换）。

对应 docs/plan/S10-native-system-backend.md。
"""
from __future__ import annotations

import os
import tempfile

import pytest

from yuiro.native import NativeBackend, ops


@pytest.fixture()
def workdir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


def _backend(root: str) -> NativeBackend:
    return NativeBackend(file_roots=[root])


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---- 别名与 trace -----------------------------------------------------------
def test_resolve_app_aliases() -> None:
    assert ops.resolve_app("记事本") == "notepad"
    assert ops.resolve_app("计算器") == "calc"
    assert ops.resolve_app("网易云音乐") == "cloudmusic"
    assert ops.resolve_app("微信") == "wechat"
    assert ops.resolve_app("QQ") == "qq"
    assert ops.resolve_app("某未知应用") == "某未知应用"  # 未命中原样返回


def test_trace_id_shape() -> None:
    tid = ops.new_trace_id()
    assert "-" in tid
    assert len(tid) >= 20


# ---- dry-run 文案（与 C++ 对齐）---------------------------------------------
@pytest.mark.asyncio
async def test_dry_run_messages(workdir) -> None:
    b = _backend(workdir)
    p = os.path.join(workdir, "a.txt")

    r = await b.call("app_open", {"name": "记事本"}, dry_run=True)
    assert (r.status, r.stdout) == ("dry-run", 'dry-run：将打开 "notepad"')

    r = await b.call("app_focus", {"name": "网易云音乐"}, dry_run=True)
    assert r.status == "dry-run" and '将聚焦窗口 "网易云音乐"' in r.stdout

    r = await b.call("media_control", {"action": "next"}, dry_run=True)
    assert r.status == "dry-run" and "请求 next" in r.stdout and "不使用全局播放键回退" in r.stdout

    r = await b.call("media_control", {"action": "now_playing"}, dry_run=True)
    assert r.status == "dry-run" and "SMTC" in r.stdout

    r = await b.call("file_create", {"path": p, "content": "x"}, dry_run=True)
    assert r.status == "dry-run" and "将创建文件" in r.stdout

    r = await b.call("file_write", {"path": p, "content": "x"}, dry_run=True)
    assert r.status == "dry-run" and "将写入文件" in r.stdout

    r = await b.call("file_read", {"path": p}, dry_run=True)
    assert r.status == "dry-run" and "将读取文件" in r.stdout


@pytest.mark.asyncio
async def test_dry_run_does_not_touch_disk(workdir) -> None:
    b = _backend(workdir)
    p = os.path.join(workdir, "nope.txt")
    r = await b.call("file_create", {"path": p, "content": "x"}, dry_run=True)
    assert r.status == "dry-run"
    assert not os.path.exists(p)


# ---- 文件往返 ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_file_roundtrip(workdir) -> None:
    b = _backend(workdir)
    p = os.path.join(workdir, "sub", "a.txt")
    r1 = await b.call("file_create", {"path": p, "content": "你好"})
    assert r1.status == "ok" and "已创建文件" in r1.stdout
    assert os.path.exists(p)
    assert r1.stdout.endswith("（6 字节）")  # utf-8 字节数（与 C++ 对齐）

    r2 = await b.call("file_read", {"path": p})
    assert r2.status == "ok" and r2.stdout == "你好"

    r3 = await b.call("file_write", {"path": p, "content": "覆盖"})
    assert r3.status == "ok"
    assert _read_text(p) == "覆盖"


@pytest.mark.asyncio
async def test_file_read_missing(workdir) -> None:
    b = _backend(workdir)
    r = await b.call("file_read", {"path": os.path.join(workdir, "missing.txt")})
    assert r.status == "error" and "无法读取文件" in r.stdout


# ---- 路径边界 ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_path_denied_outside_root(workdir) -> None:
    b = _backend(workdir)
    outside = os.path.join(os.path.dirname(workdir), "evil.txt")
    for tool in ("file_create", "file_write", "file_read"):
        r = await b.call(tool, {"path": outside, "content": "x"})
        assert r.status == "denied", f"{tool} 应拒绝越界路径"
        assert "不在允许目录内" in r.stdout


@pytest.mark.asyncio
async def test_path_traversal_denied(workdir) -> None:
    b = _backend(workdir)
    r = await b.call("file_read", {"path": os.path.join(workdir, "..", "..", "evil.txt")})
    assert r.status == "denied"


def test_path_allowed_semantics(workdir) -> None:
    assert ops.path_allowed(os.path.join(workdir, "a", "b.txt"), [workdir])
    assert not ops.path_allowed(os.path.join(workdir, "..", "x.txt"), [workdir])
    # 前缀近似目录必须拒绝（防 C:/safe_evil 绕过）
    assert not ops.path_allowed(workdir + "_evil", [workdir])


# ---- 参数与未知 -------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_params(workdir) -> None:
    b = _backend(workdir)
    assert (await b.call("app_open", {})).status == "error"
    assert (await b.call("app_focus", {})).status == "error"
    assert (await b.call("media_control", {})).status == "error"
    assert (await b.call("file_read", {})).status == "error"


@pytest.mark.asyncio
async def test_unknown_action_and_tool(workdir) -> None:
    b = _backend(workdir)
    r = await b.call("media_control", {"action": "fly"})
    assert r.status == "error" and "未知 action" in r.stdout
    r2 = await b.call("window_screenshot", {})
    assert r2.status == "error" and "不支持的工具" in r2.stdout


# ---- 协议 / 装配 -------------------------------------------------------------
def test_supported_tools_match_daemon() -> None:
    """native ⊇ daemon：daemon 能做的 native 必须都能做，差异只允许是**单向**的。

    S33 起 native 多两个文件原语（``file_move`` / ``file_delete``）——
    C++ daemon 侧尚未实现（daemon 是可选后端，native 为默认）。
    用集合断言固化这一点：哪天 daemon 加了工具而 native 漏了，这里会红。
    """
    b = NativeBackend()
    daemon_tools = {
        "app_open", "app_focus", "media_control", "file_create", "file_read", "file_write",
    }
    assert daemon_tools <= b.SUPPORTED
    assert b.SUPPORTED - daemon_tools == {"file_move", "file_delete", "file_list"}
    assert b.is_running is True  # 兼容 SystemDaemonClient 的 property 探活接口


def test_config_defaults() -> None:
    from yuiro.config import SystemDaemonConfig

    cfg = SystemDaemonConfig()
    assert cfg.backend == "native"
    assert cfg.file_roots == ["."]


def test_build_agent_loop_registers_native_backend(workdir) -> None:
    from yuiro.agent import build_agent_loop
    from yuiro.config import MemoryConfig, PersonaConfig

    b = _backend(workdir)
    loop = build_agent_loop(
        base_url="http://127.0.0.1:1/v1",
        model="m",
        api_key="k",
        persona=PersonaConfig(),
        memory_config=MemoryConfig(),
        system_backend=b,
    )
    names = [s["function"]["name"] for s in loop._tools.schemas()]
    assert {
        "app_open", "app_focus", "media_control", "file_create", "file_read", "file_write",
    } <= set(names)


@pytest.mark.asyncio
async def test_backend_switch_legacy_daemon_path(workdir) -> None:
    """system_daemon= 旧路径仍可用（兼容不破）。"""
    from yuiro.agent import build_agent_loop
    from yuiro.config import MemoryConfig, PersonaConfig
    from yuiro.systemd.client import SystemActionResult

    class _FakeDaemon:
        async def call(self, tool: str, args: dict, dry_run: bool = False) -> SystemActionResult:
            return SystemActionResult(trace_id="t", status="ok", stdout="from-daemon")

    loop = build_agent_loop(
        base_url="http://127.0.0.1:1/v1",
        model="m",
        api_key="k",
        persona=PersonaConfig(),
        memory_config=MemoryConfig(),
        system_daemon=_FakeDaemon(),
    )
    out = await loop._tools.execute("app_open", {"name": "x"}, "t")
    assert "from-daemon" in out
