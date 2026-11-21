"""Yuiro engine — tools package (registry + builtin tools + gating)."""
from __future__ import annotations

import inspect
import json
from abc import ABC, abstractmethod
from collections.abc import Callable


def function_to_tool_schema(fn) -> dict:
    """Auto-generate an OpenAI tool schema from a Python function signature +
    Google-style docstring (Agentic-Desktop-Pet).

    Zero-friction tool authoring: just write a docstring with an ``Args:``
    section and parameters get captured automatically.
    """
    sig = inspect.signature(fn)
    doc = inspect.getdoc(fn) or ""

    properties: dict[str, dict] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
        properties[name] = {"type": _python_to_json_type(annotation)}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    description = doc.split("\n", 1)[0].strip() if doc else fn.__name__
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _python_to_json_type(annotation) -> str:
    """Map a Python type annotation to a JSON schema type."""
    name = getattr(annotation, "__name__", str(annotation)).lower()
    if "int" in name:
        return "integer"
    if "float" in name:
        return "number"
    if "bool" in name:
        return "boolean"
    if any(k in name for k in ("list", "dict", "tuple", "set")):
        return "object"
    return "string"


#: 副作用等级（S48 / 方案 D）—— 决定**崩溃恢复时该步骤能否安全重放**：
#: - ``read``     只读，无副作用 → 总是可重放；
#: - ``local``    本地写入（文件 / 记忆 / 任务）→ 重复执行通常收敛（覆盖写）→ 可重放；
#: - ``external`` 对外产生影响（放歌 / 开应用 / 发消息 / 登录）→ **不可重放**。
EFFECT_READ = "read"
EFFECT_LOCAL = "local"
EFFECT_EXTERNAL = "external"
EFFECT_ALL = (EFFECT_READ, EFFECT_LOCAL, EFFECT_EXTERNAL)

#: 按名字推断副作用等级时的线索词。**顺序即优先级**：先判"危险"，再判只读。
#: 保守原则：**认不出来就当 external** —— 宁可多问一句，也不要静默地重复放歌。
_EFFECT_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        EFFECT_EXTERNAL,
        (
            "netease_play", "netease_login", "netease_control", "netease_library",
            "app_open", "app_focus", "media_control", "avatar_perform", "subagent",
        ),
    ),
    (
        EFFECT_LOCAL,
        (
            "file_create", "file_write", "file_move", "file_delete",
            "memory", "task_", "txn", "transaction",
        ),
    ),
    (
        EFFECT_READ,
        (
            "read", "list", "search", "query", "state", "get", "probe", "inspect",
            "lyric", "recommend", "profile", "recent", "detail", "help", "capabilit",
        ),
    ),
)


def infer_effect(tool_name: str) -> str:
    """按工具名保守推断副作用等级（**只在未显式声明时**使用）。

    为什么需要它：``BaseTool.effect`` 默认是保守的 ``external``；若没有这一步，
    恢复时会把"读个文件"也当成危险操作去问用户 —— **唠叨到没人看，等于没有防护**。
    推断只覆盖**一眼能确定**的名字，其余一律落到 ``external``。
    """
    name = (tool_name or "").lower()
    if not name:
        return EFFECT_EXTERNAL
    for effect, hints in _EFFECT_HINTS:
        if any(h in name for h in hints):
            return effect
    return EFFECT_EXTERNAL


#: 环境可用性探测表（S51）：``BaseTool.requires_env`` 的**消费者**。
#:
#: 背景：``requires_env`` 长期是"只声明、无消费"的死字段 —— 工具声明了
#: "缺某环境就隐藏"，却没有任何代码读它。这里补上消费入口。
#:
#: 保守原则：**未登记的环境一律视为可用（不隐藏）** —— 避免给既有工具
#: （如 netease 的 ``ncm-cli``）引入未经确认的行为变更。要启用某个探测，
#: 由对应工具模块在导入时 ``register_env_probe`` 自注册。
_ENV_PROBES: dict[str, Callable[[], bool]] = {}


def register_env_probe(env: str, probe: Callable[[], bool]) -> None:
    """登记某个 ``requires_env`` 的可用性探测（工具模块导入时调用）。"""
    if env:
        _ENV_PROBES[env] = probe


def env_available(env: str | None) -> bool:
    """``requires_env`` 是否满足。未登记 / 探测异常 → True（绝不因探测而隐藏能力）。"""
    if not env:
        return True
    probe = _ENV_PROBES.get(env)
    if probe is None:
        return True
    try:
        return bool(probe())
    except Exception:  # noqa: BLE001 — 探测失败按"可用"处理，避免误伤
        return True


class BaseTool(ABC):
    name: str
    description: str = ""
    approval_required: bool = False
    requires_env: str | None = None  # e.g. missing API key hides tool
    #: 副作用等级（S48）：``""`` = 未声明，由 :func:`resolve_effect` 按名字推断。
    #: 决定崩溃恢复时该步骤能否**安全重放** —— 算是"能力自描述"的一部分：
    #: 新工具顺手就得想清楚自己的副作用语义，而不是让恢复逻辑去猜。
    effect: str = ""

    @abstractmethod
    def schema(self) -> dict:
        """OpenAI function schema: {type,function:{name,description,parameters}}."""
        ...

    @abstractmethod
    async def run(self, args: dict, task_id: str) -> str:
        """Execute; MUST return a JSON string."""
        ...

    def approval_needed(self, args: dict) -> bool:
        """是否需审批。默认按静态 approval_required；复合工具（如 SystemTool）
        可按具体子操作细化（如 media_control 免审批）。"""
        del args
        return self.approval_required


def resolve_effect(tool: BaseTool | None) -> str:
    """工具的实际副作用等级：**显式声明优先，否则按名字保守推断**。"""
    if tool is None:
        return EFFECT_EXTERNAL
    declared = str(getattr(tool, "effect", "") or "").strip().lower()
    if declared in EFFECT_ALL:
        return declared
    return infer_effect(str(getattr(tool, "name", "")))


class ToolRegistry:
    """Auto-discovers *_tool.py modules; registers on import via register().

    Supports toolset gating (hide task-irrelevant tools) and runtime check_fn.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """按名字取工具（S48：恢复建议要据此查副作用等级）。"""
        return self._tools.get(str(name or ""))

    def effect_of(self, name: str) -> str:
        """工具名的副作用等级。

        - **已注册**：以工具自描述为准（未声明则按名字推断）；
        - **未注册**（历史工具名 / 已下线）：**按名字保守推断**。

        ⚠ 未注册时不能直接返回 ``external`` —— 那会让"读个文件"也被当成危险
        操作去问用户，防护退化成唠叨。判太严和判太松**同样是 bug**。
        """
        tool = self.get(name)
        if tool is None:
            return infer_effect(name)
        return resolve_effect(tool)

    def schemas(self, toolset: list[str] | None = None) -> list[dict]:
        tools = self._tools.values()
        if toolset:
            tools = [t for t in tools if t.name in toolset]
        # S51：``requires_env`` 的消费者 —— 环境不满足的工具**不暴露**给 LLM。
        # 此前该字段"只声明、无消费"（全仓无人读），是能力自描述与实际行为脱节的坑；
        # 例如未配置搜索 key 时 ``web_search`` 仍会出现在 schema 里，模型可能去调一个
        # 根本用不了的工具。现在按需隐藏，模型看不到不存在的能力。
        tools = [t for t in tools if env_available(getattr(t, "requires_env", None))]
        return [t.schema() for t in tools]

    async def execute(
        self,
        name: str,
        args: dict,
        task_id: str,
        approval_callback=None,
    ) -> str:
        """Look up tool, run, return JSON result string.

        ``approval_callback``：可选审批门 ``async (tool_name, args, task_id) -> bool``。
        工具 ``approval_needed(args)`` 为真且传入回调时，先过审批门；
        拒绝时返回 ``{"status":"denied"}`` 而不执行。
        """
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False)
        if approval_callback is not None and tool.approval_needed(args or {}):
            ok = await approval_callback(name, args or {}, task_id)
            if not ok:
                return json.dumps(
                    {"status": "denied", "tool": name, "note": "用户拒绝了该操作"},
                    ensure_ascii=False,
                )
        return await tool.run(args or {}, task_id)


# 注：原 TodoTool 已移除。实测 LLM 将其误用为「记忆库」来存用户画像
# （如 todo update id="user_like_hotpot"），而项目已有独立的 L3 事实系统
# （MemorySystem._extract_facts + FactsStore）承载用户画像，两套存储并存
# 只会造成语义混乱与无意义空转。用户画像统一走 L3 facts。

