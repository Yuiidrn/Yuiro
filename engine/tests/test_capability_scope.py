"""S19 测试：CapabilityScope（参数级资源域 + 越界拦截）。

关键护栏：
1. **默认宽松**（未声明的域不限）—— 保证不打断现有工作流（向后兼容）；
2. **硬红线**（系统目录）—— 即使配置 ["*"] 也拒绝；
3. 越界优先于风险档位（配置不允许 ≠ 需要审批）。
"""
from __future__ import annotations

import json

import pytest

from yuiro.agent.tool_dispatch import ToolDispatcher
from yuiro.capability import CapabilityScope, Policy, RiskLevel
from yuiro.capability.scope import ResourceDomain, arg_key_for


# ── 默认宽松（向后兼容护栏）────────────────────────────────────────────────
def test_undeclared_domain_is_unrestricted() -> None:
    scope = CapabilityScope()
    assert scope.unrestricted("filesystem") is True
    assert scope.allows("filesystem", "D:/随便什么/文件.txt") is True
    assert scope.allows("process", "cmd.exe") is True
    assert scope.check_tool("file_write", {"path": "D:/x.txt"}) is None


def test_star_means_unrestricted_but_hard_deny_still_applies() -> None:
    scope = CapabilityScope({"filesystem": ["*"]})
    assert scope.allows("filesystem", "D:/项目/a.txt") is True
    # 硬红线：即使 "*" 也拒绝
    assert scope.allows("filesystem", "C:/Windows/System32/cmd.exe") is False
    assert scope.allows("filesystem", "/etc/passwd") is False
    assert scope.allows("filesystem", "/usr/bin/python3") is False


# ── 白名单与穿越 ──────────────────────────────────────────────────────────
def test_filesystem_whitelist_glob() -> None:
    scope = CapabilityScope({"filesystem": ["~/Downloads/**"]})
    assert scope.allows("filesystem", "~/Downloads/a.txt") is True
    assert scope.allows("filesystem", "~/Downloads/sub/deep/b.txt") is True
    assert scope.allows("filesystem", "~/Desktop/a.txt") is False


def test_path_traversal_is_normalized_before_check() -> None:
    scope = CapabilityScope({"filesystem": ["~/Downloads/**"]})
    # .. 逃逸出白名单 → 归一化后不匹配 → 拒绝
    assert scope.allows("filesystem", "~/Downloads/../../Desktop/secret.txt") is False


def test_windows_and_posix_separators_are_equivalent() -> None:
    scope = CapabilityScope({"filesystem": ["D:/Project/Yuii/**"]})
    assert scope.allows("filesystem", "D:\\Project\\Yuii\\a.txt") is True
    assert scope.allows("filesystem", "D:/Project/Other/a.txt") is False


# ── network / process ────────────────────────────────────────────────────
def test_network_domain_matching() -> None:
    scope = CapabilityScope({"network": ["music.163.com", "*.siliconflow.cn"]})
    assert scope.allows("network", "music.163.com") is True
    assert scope.allows("network", "163.com") is False  # 精确域名不放宽到父域
    assert scope.allows("network", "api.siliconflow.cn") is True
    assert scope.allows("network", "evil.com") is False


def test_process_keyword_matching() -> None:
    scope = CapabilityScope({"process": ["记事本", "网易云音乐"]})
    assert scope.allows("process", "记事本") is True
    assert scope.allows("process", "网易云音乐") is True
    assert scope.allows("process", "cmd.exe") is False


# ── 工具 → 域映射 ─────────────────────────────────────────────────────────
def test_tool_domain_mapping() -> None:
    assert arg_key_for("file_write") == "path"
    assert arg_key_for("app_open") == "name"
    assert arg_key_for("media_control") is None  # 无资源参数 → 不校验

    scope = CapabilityScope({"filesystem": ["~/Downloads/**"], "process": ["记事本"]})
    assert scope.check_tool("file_write", {"path": "~/Downloads/x.txt"}) is None
    assert scope.check_tool("file_write", {"path": "D:/其它.txt"}) is not None
    assert scope.check_tool("app_open", {"name": "记事本"}) is None
    assert scope.check_tool("app_open", {"name": "不知名程序"}) is not None
    # 未登记工具完全不受影响
    assert scope.check_tool("netease_play", {"keyword": "任意歌名"}) is None


# ── Policy 集成 ───────────────────────────────────────────────────────────
def test_policy_denies_out_of_scope_before_risk_check() -> None:
    policy = Policy(profile="trusted", scope={"filesystem": ["~/Downloads/**"]})
    # 越界：即使 trusted（LOW/MEDIUM 直通）也必须 deny
    d = policy.decide("file_write", {"path": "C:/Windows/evil.txt"})
    assert d.denied is True
    assert "filesystem" in d.reason
    # 域内：按风险档位正常放行
    assert policy.decide("file_write", {"path": "~/Downloads/ok.txt"}).action == "allow"


def test_policy_scope_deny_is_not_approval() -> None:
    """越界是硬边界，不进入审批流（ask 才算审批）。"""
    policy = Policy(profile="normal", scope={"process": ["记事本"]})
    d = policy.decide("app_open", {"name": "powershell"})
    assert d.denied is True
    assert d.requires_approval is False


def test_policy_without_scope_keeps_s11_risk_behavior() -> None:
    """向后兼容护栏：不传 scope 时，**风险档位行为**与 S11 完全一致。"""
    policy = Policy(profile="normal")
    assert policy.decide("file_write", {"path": "D:/项目/a.txt"}).action == "ask"
    assert policy.decide("file_read", {"path": "D:/项目/a.txt"}).action == "allow"
    assert policy.risk_of("file_delete") is RiskLevel.HIGH


def test_hard_deny_is_default_on() -> None:
    """S19 的新默认：即使没配 scope，系统目录也拒绝（安全默认，有意收紧）。

    这与 S11 的差异是**有意的**：`file_write` 到系统目录此前是 `ask`（用户可能点同意），
    现在是 `deny`（配置层直接不允许）。普通路径的档位行为不变（见上一个用例）。
    """
    policy = Policy(profile="normal")
    assert policy.decide("file_write", {"path": "C:/Windows/x.txt"}).denied is True
    # 即使 trusted（写操作直通）也拒绝系统目录
    assert Policy(profile="trusted").decide(
        "file_write", {"path": "C:/Program Files/x.txt"}
    ).denied is True


# ── 视图 ──────────────────────────────────────────────────────────────────
def test_to_dict_view() -> None:
    scope = CapabilityScope({"filesystem": ["~/Downloads/**"]})
    view = scope.to_dict()
    assert view["declared"] == {"filesystem": ["~/Downloads/**"]}
    assert "network" in view["unrestricted_domains"]  # 未声明 → 不限
    assert "c:/windows" in view["hard_deny"]
    assert view["tool_domains"]["file_write"] == {
        "domain": ResourceDomain.FILESYSTEM.value,
        "arg": "path",
    }


# ── 真实拦截链路（ToolDispatcher）────────────────────────────────────────
@pytest.mark.asyncio
async def test_dispatcher_blocks_out_of_scope_tool() -> None:
    """端到端：越界调用在 ToolDispatcher 被拦下，工具根本没被执行。"""
    executed: list[str] = []

    class _Tool:
        async def execute(self, args, session_id, approval_callback=None):
            executed.append(session_id)
            return json.dumps({"status": "ok"})

    class _Registry:
        def execute(self, name, args, session_id, approval_callback=None):
            return _Tool().execute(args, session_id, approval_callback)

    policy = Policy(profile="normal", scope={"filesystem": ["~/Downloads/**"]})
    dispatcher = ToolDispatcher(_Registry(), policy=policy)

    blocked = await dispatcher.execute_one(
        "file_write", {"path": "C:/Windows/evil.txt"}, "sess1"
    )
    payload = json.loads(blocked)
    assert payload["status"] == "denied"
    assert "filesystem" in payload["note"]
    assert executed == []  # 未执行

    ok = await dispatcher.execute_one(
        "file_write", {"path": "~/Downloads/ok.txt"}, "sess1"
    )
    assert json.loads(ok)["status"] == "ok"
    assert executed == ["sess1"]  # 域内正常执行
