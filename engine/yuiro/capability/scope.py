"""CapabilityScope（S19）：声明式资源域 + 参数级越界拦截。

规范依据（``docs/spec/architecture-goal.md`` §3.7 Security）：

```
Agent → Capability → Permission → Sandbox → Approval → Execution → SystemDaemon
```

- **Policy**（S11）："这个工具该不该做"（工具级风险 × 权限档位）；
- **CapabilityScope**（本模块）："这个工具**碰的这个东西**允不允许"（参数级边界）；
- **Sandbox**：OS 层隔离（SystemDaemon 侧，后续 Wave）。

域声明借鉴手机权限模型：

```
filesystem: ~/Documents/Yuiro/**, ~/Downloads/**
network:    api.siliconflow.cn, *.163.com
process:    记事本, 网易云音乐
media:      *              （未声明的域 = 不限）
```

设计原则：

1. **默认宽松，红线收紧**：未声明的域一律不限（向后兼容，不打断现有工作流）；
   但**系统关键目录是硬红线**——即使写 ``*`` 也不放行（防止"全权"误伤 OS）；
2. **单点校验**：只在 ``ToolDispatcher`` 执行前校验（与执行后端解耦，Sandbox 可再兜一层）；
3. **越界即 deny**：不进入审批流（审批是"人可以决定"，越界是"配置不允许"）。
"""
from __future__ import annotations

import fnmatch
import os
from enum import Enum
from pathlib import PurePosixPath


class ResourceDomain(str, Enum):
    """资源域（spec §3.7 的五个域 + clipboard/screen 预留）。"""

    FILESYSTEM = "filesystem"
    NETWORK = "network"
    PROCESS = "process"
    MEDIA = "media"
    CLIPBOARD = "clipboard"
    SCREEN = "screen"


# 工具 → (域, 取哪个参数作为资源值)；未登记的工具不做参数级校验
_TOOL_DOMAIN: dict[str, tuple[str, str]] = {
    "file_read": (ResourceDomain.FILESYSTEM.value, "path"),
    "file_create": (ResourceDomain.FILESYSTEM.value, "path"),
    "file_write": (ResourceDomain.FILESYSTEM.value, "path"),
    "file_delete": (ResourceDomain.FILESYSTEM.value, "path"),
    "file_list": (ResourceDomain.FILESYSTEM.value, "path"),
    "file_move": (ResourceDomain.FILESYSTEM.value, "path"),
    "file_copy": (ResourceDomain.FILESYSTEM.value, "path"),
    "app_open": (ResourceDomain.PROCESS.value, "name"),
    "app_focus": (ResourceDomain.PROCESS.value, "name"),
    "process_kill": (ResourceDomain.PROCESS.value, "name"),
}

# 硬红线：系统关键目录（即使域配置为 "*" 也拒绝）
_HARD_DENY_PREFIXES: tuple[str, ...] = (
    "c:/windows",
    "c:/program files",
    "c:/program files (x86)",
    "c:/programdata",
    "c:/$recycle.bin",
    "/etc",
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/usr/lib",
    "/sys",
    "/proc",
    "/boot",
    "/dev",
    "/system",
)


def _normalize_path(value: str) -> str:
    """归一化路径用于判定：展开 ~ → 绝对化 → normpath（消解 ``..``）→ 正斜杠小写。

    特例：POSIX 绝对路径（``/etc/passwd``）在 Windows 上 ``abspath`` 会被补上盘符
    （``d:/etc/passwd``），从而绕过硬红线判定——此时保留 POSIX 形态，
    使跨平台配置的红线在任一平台都成立。
    """
    raw = value.strip().strip('"').strip("'")
    if not raw:
        return ""
    posix_abs = raw.startswith("/") and not raw.startswith("//")
    try:
        expanded = os.path.expanduser(raw)
        # normpath 消解 ..（越界尝试在归一化后会被硬红线/白名单自然拦下）
        normalized = os.path.normpath(os.path.abspath(expanded))
    except Exception:  # noqa: BLE001 — 路径异常按原串处理
        normalized = raw
    result = normalized.replace("\\", "/").lower()
    if posix_abs and not result.startswith("/"):
        # "/etc/passwd" → "d:/etc/passwd"：回补为 POSIX 形态以命中硬红线
        return "/" + os.path.normpath(raw).replace("\\", "/").lstrip("/").lower()
    return result


def _glob_match(pattern: str, path: str) -> bool:
    """glob 匹配（支持 ``**`` 递归：``~/Downloads/**`` 命中其下任意深度）。"""
    pat = _normalize_path(pattern)
    if not pat:
        return False
    if pat.endswith("/**"):
        return path == pat[:-3] or path.startswith(pat[:-2])
    # fnmatch 的 * 不跨目录，按段拆分后用 ** 语义匹配
    try:
        return PurePosixPath(path).match(pat) or fnmatch.fnmatch(path, pat)
    except Exception:  # noqa: BLE001
        return fnmatch.fnmatch(path, pat)


def _host_match(pattern: str, host: str) -> bool:
    """域名匹配：``*.163.com`` 命中 ``music.163.com``；精确域名需完全相同。"""
    pat = pattern.strip().lower()
    h = host.strip().lower()
    if not pat or not h:
        return False
    if pat.startswith("*."):
        return h == pat[2:] or h.endswith(pat[1:])
    return h == pat


def arg_key_for(tool: str) -> str | None:
    """该工具的资源值参数名（None = 不做参数级校验）；供调试试算复用。"""
    spec = _TOOL_DOMAIN.get(str(tool).strip())
    return spec[1] if spec else None


class CapabilityScope:
    """声明式资源域（可热重载：重建实例即可）。"""

    def __init__(self, rules: dict | None = None) -> None:
        self._rules: dict[str, list[str]] = {}
        for key, values in (rules or {}).items():
            domain = str(key).strip().lower()
            if not domain:
                continue
            items = [str(v).strip() for v in (values or []) if str(v).strip()]
            self._rules[domain] = items

    # ---- 查询 ---------------------------------------------------------------
    @property
    def rules(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._rules.items()}

    def unrestricted(self, domain: str) -> bool:
        """未声明该域，或显式写了 ``*`` → 不限。"""
        items = self._rules.get(str(domain).strip().lower())
        if not items:
            return True
        return "*" in items

    def allows(self, domain: str, value: str) -> bool:
        """域内放行判定（含硬红线）。"""
        dom = str(domain).strip().lower()
        raw = (value or "").strip()
        if not raw:
            return True  # 无值可校验

        if dom == ResourceDomain.FILESYSTEM.value:
            path = _normalize_path(raw)
            if not path:
                return True
            # 硬红线优先：越界尝试（.. 逃逸）归一化后同样命中
            if any(path == p or path.startswith(p + "/") for p in _HARD_DENY_PREFIXES):
                return False
            if self.unrestricted(dom):
                return True
            return any(_glob_match(pat, path) for pat in self._rules[dom])

        if dom == ResourceDomain.NETWORK.value:
            if self.unrestricted(dom):
                return True
            return any(_host_match(pat, raw) for pat in self._rules[dom])

        # process / media / clipboard / screen：关键词（不区分大小写）包含匹配
        if self.unrestricted(dom):
            return True
        low = raw.lower()
        return any(pat.lower() in low or pat.lower() == "*" for pat in self._rules[dom])

    # ---- 工具级校验 ---------------------------------------------------------
    def check_tool(self, tool: str, args: dict | None = None) -> str | None:
        """越界时返回原因（供 Policy 组装 DENY）；None = 放行。"""
        spec = _TOOL_DOMAIN.get(str(tool).strip())
        if spec is None:
            return None
        domain, arg_key = spec
        value = (args or {}).get(arg_key)
        if value is None:
            return None
        if self.allows(domain, str(value)):
            return None
        return f"参数越出 {domain} 授权范围：{value}（当前 {domain} = {self._rules.get(domain) or '*'})"

    def to_dict(self) -> dict:
        """调试视图（未声明的域标注为 "不限"）。"""
        return {
            "declared": self.rules,
            "unrestricted_domains": [
                d.value for d in ResourceDomain if self.unrestricted(d.value)
            ],
            "hard_deny": list(_HARD_DENY_PREFIXES),
            "tool_domains": {
                tool: {"domain": dom, "arg": arg} for tool, (dom, arg) in _TOOL_DOMAIN.items()
            },
        }
