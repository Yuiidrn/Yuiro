"""表演工具（S18）：让 LLM 用**语义**触发一次 Live2D 表演。

规范依据（``docs/spec/roadmap.md`` Era 1 Perform）：

- **不要把 LLM 输出绑到具体 Live2D motion**：LLM 只说"该庆祝了"（语义名），
  由 ``PerformanceResolver`` 决定用哪个表情/动作 —— 换模型只改配置；
- **不要在 Agent 里写 ``if success: celebrate``**：语义判断交给 LLM，
  表演由本工具触发（``docs/spec/阶段性总评和后续方向.md`` §32）。

免审批（不触碰系统资源，只影响自身形象）。
"""
from __future__ import annotations

import json

# 可选表演名：直接由表演库派生（S53 起不再手抄一份 —— 手抄必然与
# `_BUILTIN_PERFORMANCES` 漂移，之前 sing/shy 就只能靠档案才会出现在 enum 里）。
from yuiro.avatar.performance import BUILTIN_PERFORMANCE_NAMES
from yuiro.tools import BaseTool

PERFORMANCES = BUILTIN_PERFORMANCE_NAMES


class AvatarPerformTool(BaseTool):
    name = "avatar_perform"
    approval_required = False
    description = (
        "让自己的形象做一次表演（表情 + 动作），用于表达明显的情绪反应。"
        "当你判断此刻需要额外情绪反馈时调用："
        "用户报喜或一件事全部办成 → celebrate；"
        "用户受挫、需要安慰 → comfort；"
        "用户回来/打招呼 → greet；听到意外消息 → surprise。"
        "普通情绪波动不需要调用（系统会自动跟随情绪变化），"
        "一次只选一个表演名，不要连续多次调用。"
        "工具成功表示已发送演出请求，不代表动画已结束；skipped表示已有表演或被占用，请继续对话，不要重试刷动作。"
    )

    def __init__(self, avatar_getter=None) -> None:
        self._get_avatar = avatar_getter

    def schema(self) -> dict:
        # 可选表演名 = 内置 + [persona.performance_map] 里用户自定的（DIY 出来也要能被 LLM 点播）。
        # 工具 schema 每回合重新生成，所以调试台改完搭配立刻生效，不需要重启引擎。
        names = list(PERFORMANCES)
        avatar = self._get_avatar() if callable(self._get_avatar) else None
        if avatar is not None:
            try:
                extra = [
                    str(p.get("name", ""))
                    for p in avatar.performances()
                    if p.get("name") and not p.get("builtin", False)
                ]
                names = sorted(set(names) | set(extra))
            except Exception:  # noqa: BLE001 — 拿不到表演库不影响工具本身可用
                names = list(PERFORMANCES)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "performance": {
                            "type": "string",
                            "enum": names,
                            "description": "表演名（语义名，非具体动画文件）",
                        },
                    },
                    "required": ["performance"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        avatar = self._get_avatar() if callable(self._get_avatar) else None
        if avatar is None:
            return json.dumps(
                {"status": "pending", "note": "AvatarRuntime 未注入"}, ensure_ascii=False
            )
        name = str(args.get("performance", "")).strip().lower()
        if not name:
            return json.dumps(
                {"status": "error", "note": "performance 不能为空"}, ensure_ascii=False
            )
        try:
            # task_id 实参由 AgentLoop 传入 session_id（与 task_tool 同约定）
            ok = await avatar.perform(task_id, name, source="agent")
        except Exception as exc:  # noqa: BLE001 — 表演失败不影响对话
            return json.dumps({"status": "error", "note": str(exc)}, ensure_ascii=False)
        return json.dumps(
            {"status": "ok" if ok else "skipped", "performance": name},
            ensure_ascii=False,
        )
