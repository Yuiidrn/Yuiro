"""Tool Transaction 数据模型（S33）。

规范依据 ``docs/spec/architecture-goal.md`` §3.15：

    ToolExecution { dry_run() → execute() → verify() → rollback() }
    move_files: dry_run → record original paths → execute → rollback token
    用户："恢复刚才的操作。" → rollback(transaction_id)

安全三件套：``Approval + Checkpoint + Rollback``。

与 spec 的 C++ ``transaction.hpp`` 同形（``RollbackToken`` ↔ 本模块的 ``TxnOp``），
但落在 **Python 侧**：系统工具自 S10 起由 ``native`` 后端执行，事务必须贴着执行点，
否则备份与真实写入之间存在窗口（daemon 只是可选后端）。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field

#: 操作类型 → 中文（供 LLM / 调试台读，避免它去猜 kind 的含义）
KIND_CN: dict[str, str] = {
    "create": "新建",
    "overwrite": "覆盖",
    "move": "移动",
    "delete": "删除",
    "mkdir": "新建目录",
}

#: 事务状态 → 中文
STATUS_CN: dict[str, str] = {
    "pending": "进行中",
    "committed": "已提交",
    "rolled_back": "已回滚",
    "partial": "部分回滚",
}


def new_txn_id() -> str:
    """事务 id：时间前缀（天然可排序）+ 短随机（可读、可口头引用）。"""
    return f"txn-{int(time.time()):x}-{uuid.uuid4().hex[:6]}"


@dataclass
class TxnOp:
    """一次可撤销的原子操作（spec ``RollbackToken`` 的等价物）。"""

    #: create | overwrite | move | delete
    kind: str
    #: 主路径：create/overwrite/delete 的目标；move 的目标（dst）
    path: str
    #: 备份文件（相对 blobs 根）；仅 overwrite / delete 需要
    backup: str = ""
    #: move 的源路径
    src: str = ""
    #: 执行结果说明
    detail: str = ""

    def describe(self) -> str:
        cn = KIND_CN.get(self.kind, self.kind)
        if self.kind == "move":
            return f"{cn} {self.src} → {self.path}"
        return f"{cn} {self.path}"


@dataclass
class TxnRecord:
    """一次工具调用产生的事务（**一次工具调用 = 一个事务**）。"""

    id: str
    tool: str
    ts: float
    ops: list[TxnOp] = field(default_factory=list)
    #: pending | committed | rolled_back | partial
    status: str = "pending"
    note: str = ""
    rolled_back_ts: float = 0.0

    @property
    def reversible(self) -> bool:
        """仅「已提交」的事务可回滚（进行中 / 已回滚 / 部分回滚的不再受理）。"""
        return self.status == "committed"

    def summary(self) -> str:
        """一行摘要（调试台与 LLM 工具返回共用）。"""
        head = (
            f"{self.id}｜{self.tool}｜{len(self.ops)} 步｜"
            f"{STATUS_CN.get(self.status, self.status)}"
        )
        if not self.ops:
            return head
        shown = "；".join(op.describe() for op in self.ops[:4])
        tail = "…" if len(self.ops) > 4 else ""
        return f"{head}｜{shown}{tail}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["summary"] = self.summary()
        data["reversible"] = self.reversible
        return data

    @classmethod
    def from_dict(cls, data: dict) -> TxnRecord:
        ops = [
            TxnOp(
                kind=str(o.get("kind", "")),
                path=str(o.get("path", "")),
                backup=str(o.get("backup", "")),
                src=str(o.get("src", "")),
                detail=str(o.get("detail", "")),
            )
            for o in data.get("ops", [])
            if isinstance(o, dict)
        ]
        return cls(
            id=str(data.get("id", "")),
            tool=str(data.get("tool", "")),
            ts=float(data.get("ts", 0.0) or 0.0),
            ops=ops,
            status=str(data.get("status", "pending")),
            note=str(data.get("note", "")),
            rolled_back_ts=float(data.get("rolled_back_ts", 0.0) or 0.0),
        )
