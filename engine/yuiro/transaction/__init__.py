"""Tool Transaction（S33）：桌面 Agent 的 Checkpoint —— 文件操作可回滚。

规范依据 ``docs/spec/architecture-goal.md`` §3.15（**不是 Git checkpoint**）：

```
ToolExecution { dry_run() → execute() → verify() → rollback() }
用户："恢复刚才的操作。" → rollback(transaction_id)
安全三件套：Approval + Checkpoint + Rollback
```

本包提供：

- ``TxnRecord`` / ``TxnOp``：一次工具调用（= 一个事务）及其可撤销的原子操作；
- ``TxnStore``：写入前备份 → 落盘 → **逆序回滚** → 保留策略。

分工（与既有三层一致，不重叠）：

| 层 | 回答的问题 | 归属 |
|---|---|---|
| Policy | 这个工具该不该做 | S11 |
| CapabilityScope | 它碰的这个东西允不允许 | S19 |
| **Tool Transaction** | **做错了能不能撤回** | **S33（本包）** |
| Sandbox | OS 层拒绝越界 | 未做（daemon 侧） |

S29 的 Checkpoint 是**摘要级**（"卡在哪、试过几次、为什么失败"，给 LLM 读），
本包是**资源级**（真实文件在哪、原内容是什么，给文件系统用）——两者互补，
合起来才是 spec 说的 `Approval + Checkpoint + Rollback`。
"""
from yuiro.transaction.models import KIND_CN, STATUS_CN, TxnOp, TxnRecord, new_txn_id
from yuiro.transaction.store import DEFAULT_KEEP, TxnStore, default_root

__all__ = [
    "DEFAULT_KEEP",
    "KIND_CN",
    "STATUS_CN",
    "TxnOp",
    "TxnRecord",
    "TxnStore",
    "default_root",
    "new_txn_id",
]
