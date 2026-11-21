"""Capability Policy（S11）：工具级风险分级与权限档位。

设计要点：
- 工具级决策（风险 × 档位）+ **参数级域校验**（S19：CapabilityScope，路径/域名/进程）；
- ``ask`` 的最终效果由既有 ``[systemd].approval_mode`` 决定（auto → 放行 / manual → 弹窗）；
- ``deny`` 是**硬边界**：无论审批模式如何都拒绝（S11）；参数越界同样直接 deny（S19）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from yuiro.capability.scope import CapabilityScope


class RiskLevel(IntEnum):
    """工具风险级（数字越大越危险）。"""

    LOW = 1  # 只读 / 无副作用
    MEDIUM = 2  # 可逆写 / 影响可见状态
    HIGH = 3  # 破坏性 / 系统级（含未来能力，先登记以便拦截）


class ProfileName(str):
    """权限档位名（spec §3.7 的 PermissionProfile 收敛为四档语义）。"""

    READ_ONLY = "read_only"  # 只读：MEDIUM 及以上一律拒绝
    PRIVACY = "privacy"  # 隐私：同只读（预留：网络外发类工具另加拦截）
    NORMAL = "normal"  # 常规（默认）：低风险直通、中/高按审批模式
    TRUSTED = "trusted"  # 信任：低/中直通、高风险按审批模式


@dataclass(frozen=True)
class Decision:
    """一次工具级权限判定。"""

    action: str  # allow | ask | deny
    reason: str = ""

    @property
    def denied(self) -> bool:
        return self.action == "deny"

    @property
    def requires_approval(self) -> bool:
        return self.action == "ask"


# ---- 工具风险登记表（未登记者按 MEDIUM 保守处理）-----------------------------
_TOOL_RISK: dict[str, RiskLevel] = {
    # LOW：只读 / 无副作用 / 纯本地状态
    "file_read": RiskLevel.LOW,
    "file_list": RiskLevel.LOW,
    "artifact_read": RiskLevel.LOW,
    "media_control": RiskLevel.LOW,
    "app_focus": RiskLevel.LOW,
    "task_list": RiskLevel.LOW,
    "task_create": RiskLevel.LOW,
    "task_advance": RiskLevel.LOW,
    "task_complete": RiskLevel.LOW,
    "netease_search": RiskLevel.LOW,
    # S51：联网检索是**只读**能力（不写本地、不改系统状态），且失败只影响本轮回答。
    # 若不登记会落到 MEDIUM → normal 档位下变 ask（每次搜索都弹审批），
    # 与"闲聊式提问"的使用场景严重冲突。
    "web_search": RiskLevel.LOW,
    "netease_lyric": RiskLevel.LOW,
    "netease_playlist": RiskLevel.LOW,
    "netease_recommend": RiskLevel.LOW,
    "netease_control": RiskLevel.LOW,
    "transaction_list": RiskLevel.LOW,
    # MEDIUM：可逆写 / 影响可见状态
    "app_open": RiskLevel.MEDIUM,
    "file_create": RiskLevel.MEDIUM,
    "file_write": RiskLevel.MEDIUM,
    "file_move": RiskLevel.MEDIUM,
    "transaction_rollback": RiskLevel.MEDIUM,
    "netease_play": RiskLevel.MEDIUM,
    "netease_login": RiskLevel.MEDIUM,
    # HIGH：破坏性 / 系统级（能力未实现，先登记以便未来默认拦截）
    "process_kill": RiskLevel.HIGH,
    "terminal_exec": RiskLevel.HIGH,
    "mouse_inject": RiskLevel.HIGH,
    "keyboard_inject": RiskLevel.HIGH,
    "file_delete": RiskLevel.HIGH,
}

_DEFAULT_RISK = RiskLevel.MEDIUM  # 未登记工具：保守（需要审批；档位过低则拒绝）


@dataclass(frozen=True)
class Profile:
    name: str
    max_risk: RiskLevel  # 超过则 DENY
    approval_min_risk: RiskLevel  # 达到则 ASK


_PROFILES: dict[str, Profile] = {
    ProfileName.READ_ONLY: Profile(ProfileName.READ_ONLY, RiskLevel.LOW, RiskLevel.HIGH),
    ProfileName.PRIVACY: Profile(ProfileName.PRIVACY, RiskLevel.LOW, RiskLevel.HIGH),
    ProfileName.NORMAL: Profile(ProfileName.NORMAL, RiskLevel.HIGH, RiskLevel.MEDIUM),
    ProfileName.TRUSTED: Profile(ProfileName.TRUSTED, RiskLevel.HIGH, RiskLevel.HIGH),
}

DEFAULT_PROFILE = ProfileName.NORMAL


class Policy:
    """工具级权限判定器（无状态、可测）。"""

    def __init__(self, *, profile: str | None = None, scope=None) -> None:
        name = (profile or DEFAULT_PROFILE).strip().lower()
        self._profile = _PROFILES.get(name, _PROFILES[DEFAULT_PROFILE])
        self._requested = name
        # S19：参数级边界。可传 CapabilityScope 实例 / dict（域 → 模式列表）/ None
        self._scope = scope if isinstance(scope, CapabilityScope) else CapabilityScope(scope)

    @property
    def profile_name(self) -> str:
        return self._profile.name

    @property
    def profile_missing(self) -> bool:
        """配置了未知档位（已回落默认）时为 True（供启动日志提示）。"""
        return self._requested not in _PROFILES

    @property
    def scope(self) -> CapabilityScope:
        """参数级资源域（S19）。"""
        return self._scope

    def risk_of(self, tool: str) -> RiskLevel:
        return _TOOL_RISK.get(tool, _DEFAULT_RISK)

    def decide(self, tool: str, args: dict | None = None) -> Decision:
        """判定顺序（S19）：**参数级域校验** → 工具级风险档位。

        越界（配置不允许）直接 deny，不进入审批流——审批是"人可以决定"，
        越界是"配置不允许"，语义不同。
        """
        reason = self._scope.check_tool(tool, args or {})
        if reason is not None:
            return Decision("deny", reason)
        risk = self.risk_of(tool)
        if risk > self._profile.max_risk:
            return Decision(
                "deny",
                f"工具 {tool}（风险 {risk.name}）超出当前权限档位 {self._profile.name}",
            )
        if risk >= self._profile.approval_min_risk:
            return Decision("ask")
        return Decision("allow")
