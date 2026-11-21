"""Context 基础设施（S06 起）：Hot Context 的组装与预算管理。

- ``ContextItem``：带元数据（source/scope/priority/token_cost/mandatory）的上下文片段；
- ``ContextBudget``：Hot Context 总预算（估算 token）；
- ``ContextEngine``：收集 → 排序 → 预算裁剪 → LLM messages。

规范：``docs/spec/architecture-goal.md`` §3.3、``docs/plan/S06-context-engine.md``。
"""
from yuiro.context.engine import ContextEngine, fit_budget
from yuiro.context.item import ContextBudget, ContextItem, estimate_tokens

__all__ = ["ContextBudget", "ContextEngine", "ContextItem", "estimate_tokens", "fit_budget"]
