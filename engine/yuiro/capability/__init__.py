"""Capability 层（S11 起）：工具的权限分级与可见性。

安全链中的位置：

```
Agent → Capability(本包) → Permission → Sandbox(执行后端) → Approval → Execution
```

- ``Policy``：工具级风险分级 × 权限档位 → ALLOW / ASK / DENY（S11）；
- ``CapabilityScope``：参数级资源域（filesystem / network / process / media / clipboard / screen）
  + 越界拦截（S19；系统目录为硬红线）；
- ``CapabilityView``：按 Policy 过滤暴露给 LLM 的工具表（Tool Context Explosion 的正解）；
- OS 层隔离由执行后端承担（Sandbox 角色，见 ``yuiro/native``）。

规范：``docs/spec/architecture-goal.md`` §3.7、``docs/plan/S11-capability-policy.md``、
``docs/plan/S19-capability-scope.md``。
"""
from yuiro.capability.policy import Decision, Policy, ProfileName, RiskLevel
from yuiro.capability.scope import CapabilityScope, ResourceDomain
from yuiro.capability.view import CapabilityView

__all__ = [
    "CapabilityScope",
    "CapabilityView",
    "Decision",
    "Policy",
    "ProfileName",
    "ResourceDomain",
    "RiskLevel",
]
