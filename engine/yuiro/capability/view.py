"""CapabilityView（S11）：Agent 此刻能看到哪些工具。

解决 Tool Context Explosion：被 Policy 拒绝（deny）的工具不进入 LLM 的工具表——
"看不见"比"看得见但会被拒绝"更省 context，也更不容易诱发幻觉调用。
被隐藏工具若仍被调用（幻觉），AgentLoop 执行前的 Policy 判定会二次拦截（双保险）。
"""
from __future__ import annotations

from yuiro.capability.policy import Policy


class CapabilityView:
    def __init__(self, registry, policy: Policy | None = None) -> None:
        self._registry = registry
        self._policy = policy

    def visible_schemas(self, disabled: set[str] | None = None) -> list[dict]:
        """按 Policy 过滤后的工具 schema 列表（无 policy 时全量）。

        ``disabled``（S51）：**会话级临时禁用集** —— 用于"本轮不联网"这类
        每轮变化的意图。它与 Policy（长期权限档位）**语义不同、必须分开**：
        - Policy：配置级，决定"这个能力**能不能**用"（权限）；
        - disabled：会话级，决定"这一轮**要不要**给它"（意图）。
        合在一起会让"临时关一下"变成改配置，既慢又危险。

        禁用即"不放进 schema" —— 模型看不到它，自然不会调用
        （对齐 airi 的 ``filterToolsByAllowedTools``：调用前过滤而非事后拒）。
        """
        schemas = self._registry.schemas() if self._registry is not None else []
        if disabled:
            schemas = [
                s
                for s in schemas
                if str(s.get("function", {}).get("name", "")) not in disabled
            ]
        if self._policy is None:
            return schemas
        visible: list[dict] = []
        for schema in schemas:
            name = str(schema.get("function", {}).get("name", ""))
            if not self._policy.decide(name).denied:
                visible.append(schema)
        return visible

    def hidden_tools(self) -> list[str]:
        """被权限档位隐藏的工具名（供启动日志/调试）。"""
        if self._policy is None or self._registry is None:
            return []
        return [
            name
            for name in (
                str(s.get("function", {}).get("name", "")) for s in self._registry.schemas()
            )
            if self._policy.decide(name).denied
        ]
