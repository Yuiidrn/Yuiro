"""工具执行编排（S16：从 AgentLoop.send 抽离）。

职责边界：
- **权限判定**（Policy）→ deny 直接返回结构化结果，不执行、不走审批；
- **并发执行**（工具之间无依赖，并行显著降低总耗时）；
- **异常与结果归一**（非 JSON 纯文本归一为 ``{"status":"text"}``）。

**不负责**（仍由 AgentLoop 维护，因为与回合策略强耦合）：
去重 / 限流计数 / 早停判定 / 状态摘要 / 记忆写入。
"""
from __future__ import annotations

import asyncio
import json

from yuiro.logger import vlog


class ToolDispatcher:
    def __init__(self, registry, *, policy=None, approval_gate=None) -> None:
        self._registry = registry
        self._policy = policy
        self._approval_gate = approval_gate

    # ---- 判定 ---------------------------------------------------------------
    def decide(self, name: str, args: dict):
        """策略判定（未注入 Policy 时返回 None = 不做分级）。"""
        if self._policy is None:
            return None
        return self._policy.decide(name, args)

    @staticmethod
    def denied_result(name: str, reason: str) -> str:
        return json.dumps(
            {"status": "denied", "tool": name, "note": reason}, ensure_ascii=False
        )

    # ---- 执行 ---------------------------------------------------------------
    async def execute_one(self, name: str, args: dict, session_id: str) -> str:
        """执行单个工具：Policy → 审批门 → registry.execute；异常归一。"""
        decision = self.decide(name, args)
        if decision is not None and decision.denied:
            vlog("capability", f"[{session_id[:8]}] 拒绝 {name}：{decision.reason}")
            return self.denied_result(name, decision.reason)
        # 仅当策略要求审批时才挂审批门（allow 类型直接执行）
        cb = (
            self._approval_gate
            if (decision is None or decision.requires_approval)
            else None
        )
        try:
            return await self._registry.execute(
                name, args, session_id, approval_callback=cb
            )
        except Exception as exc:  # noqa: BLE001 — 工具异常不阻断回合
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    async def run_batch(self, pending, session_id: str) -> list[tuple[int, str]]:
        """并发执行本轮的待执行工具。

        ``pending``：``[(idx, tool_call, key, args)]``（tool_call 需具备
        ``tool_name`` / ``tool_args`` 属性）。返回 ``[(idx, result_json)]``。
        """

        async def _one(idx: int, tc: object, key: str, args: dict) -> tuple[int, str]:
            del key, args  # 去重键与已解析参数仅用于上层策略；此处直接用 tool_call 自带参数
            name = getattr(tc, "tool_name", "") or ""
            tool_args = getattr(tc, "tool_args", {}) or {}
            return idx, await self.execute_one(name, tool_args, session_id)

        return list(
            await asyncio.gather(*(_one(i, tc, k, a) for i, tc, k, a in pending))
        )

    # ---- 归一 ---------------------------------------------------------------
    @staticmethod
    def normalize(raw: str) -> str:
        """结果归一：合法 JSON 原样返回；非 JSON 纯文本 → ``{"status":"text"}``。

        工具返回非 JSON 纯文本（如 "[todo] 无待办"）时，旧逻辑一律记为 "?"，
        导致限流与去重双双失效、空转耗尽轮数。归一为 ``text`` 状态即视为
        已执行并登记去重，杜绝同一无意义调用反复触发。
        注意：必须用真实 JSON 解析判定，不能用 ``startswith(("[", "{"))``
        —— "[todo] 无待办" 以 '[' 开头但并非合法 JSON。
        """
        try:
            json.loads(raw)
            return raw
        except Exception:  # noqa: BLE001 — 非 JSON 纯文本，归一为 text
            return json.dumps({"status": "text", "output": raw}, ensure_ascii=False)
