"""TxnStore（S33）：文件操作的事务化 —— 备份、落盘、回滚。

磁盘布局（``backup_root`` 默认 ``<cwd>/.yuiro/txn``）::

    .yuiro/txn/
    ├── records/<txn_id>.json      # 事务记录（回滚后原地更新 status）
    └── blobs/<txn_id>/<seq>.bak   # 被覆盖 / 删除文件的原始内容

设计取舍：

1. **一次工具调用 = 一个事务**：边界清晰、可测；批量 ``file_move(paths=[...])``
   天然是一个事务（"整理下载夹"一次调用 → 一次全撤销，对应 spec 的 ``move_files``）；
2. **只在必要时备份**：``create``（目标是新文件）不需要备份，回滚即删除；
   ``move`` 不需要备份，回滚是把文件移回去 —— 少写一份数据就少一处失败点；
3. **保留策略**：只保留最近 ``keep`` 个事务（默认 20），否则备份目录会无限增长；
4. **回滚逆序**：后做的先撤，与人的直觉一致（"恢复刚才的操作"）。
"""
from __future__ import annotations

import json
import os
import shutil
import time

from yuiro.logger import vlog
from yuiro.transaction.models import STATUS_CN, TxnOp, TxnRecord, new_txn_id

#: 默认保留的事务数
DEFAULT_KEEP = 20

#: "last" 的各种写法（LLM 可能传中文）
_LAST_ALIASES = frozenset({"", "last", "latest", "最近", "上一次", "刚才", "上一个"})


def default_root(cwd: str | None = None) -> str:
    """默认备份根目录：``<工作目录>/.yuiro/txn``（与 Task Journal 同属引擎自有目录）。"""
    return os.path.join(cwd or os.getcwd(), ".yuiro", "txn")


class TxnStore:
    """事务存储与回滚执行器（无外部依赖，可离线测）。"""

    def __init__(
        self, root: str | os.PathLike | None = None, *, keep: int = DEFAULT_KEEP
    ) -> None:
        self._root = os.path.abspath(str(root)) if root else os.path.abspath(default_root())
        self._records_dir = os.path.join(self._root, "records")
        self._blobs_dir = os.path.join(self._root, "blobs")
        self._keep = max(1, int(keep))

    # ---- 查询 ---------------------------------------------------------------
    @property
    def root(self) -> str:
        return self._root

    @property
    def keep(self) -> int:
        return self._keep

    def _ensure_dirs(self) -> bool:
        try:
            os.makedirs(self._records_dir, exist_ok=True)
            os.makedirs(self._blobs_dir, exist_ok=True)
            return True
        except OSError as exc:
            vlog("txn", f"事务目录不可用: {exc}")
            return False

    # ---- 写入侧（被 NativeBackend 调用）--------------------------------------
    def begin(self, tool: str) -> TxnRecord:
        """开启一个事务（尚未落盘；失败即丢弃）。"""
        return TxnRecord(id=new_txn_id(), tool=str(tool), ts=time.time())

    def backup(self, txn: TxnRecord, path: str) -> str:
        """备份 ``path`` 当前内容 → 返回相对 blobs 的路径（文件不存在返回 ``""``）。"""
        if not path or not os.path.isfile(path) or not self._ensure_dirs():
            return ""
        rel = f"{txn.id}/{len(txn.ops)}.bak"
        dst = os.path.join(self._blobs_dir, txn.id, f"{len(txn.ops)}.bak")
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(path, dst)
        except OSError as exc:
            vlog("txn", f"备份失败（该操作将不记录备份）: {path} → {exc}")
            return ""
        return rel

    def commit(self, txn: TxnRecord) -> TxnRecord:
        """落盘并触发保留策略。"""
        txn.status = "committed"
        self._save(txn)
        self._prune()
        return txn

    def discard(self, txn: TxnRecord) -> None:
        """执行失败：丢弃备份，不落盘（避免留下无法对应的事务）。"""
        shutil.rmtree(os.path.join(self._blobs_dir, txn.id), ignore_errors=True)

    # ---- 读取侧 -------------------------------------------------------------
    def _all(self) -> list[TxnRecord]:
        """全部事务，按时间**升序**。"""
        try:
            names = [n for n in os.listdir(self._records_dir) if n.endswith(".json")]
        except OSError:
            return []
        records: list[TxnRecord] = []
        for name in names:
            rec = self._load(name[:-5])
            if rec is not None:
                records.append(rec)
        records.sort(key=lambda r: r.ts)
        return records

    def _load(self, txn_id: str) -> TxnRecord | None:
        path = os.path.join(self._records_dir, f"{txn_id}.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return TxnRecord.from_dict(data) if isinstance(data, dict) else None

    def _save(self, txn: TxnRecord) -> None:
        if not self._ensure_dirs():
            return
        path = os.path.join(self._records_dir, f"{txn.id}.json")
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(txn.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)  # 原子替换：避免半截 JSON
        except OSError as exc:
            vlog("txn", f"事务落盘失败: {exc}")

    def get(self, txn_id: str = "last") -> TxnRecord | None:
        """按 id 取；``last`` / 空 / 中文"最近" → 最近一个事务。"""
        tid = str(txn_id or "").strip()
        if tid.lower() in _LAST_ALIASES:
            records = self._all()
            return records[-1] if records else None
        return self._load(tid)

    def history(self, *, limit: int = 10) -> list[TxnRecord]:
        """最近的事务（时间**降序**）。"""
        records = self._all()
        records.reverse()
        return records[: max(1, int(limit))]

    def to_dict(self, *, limit: int = 10) -> dict:
        """调试视图（``GET /transaction/list`` 用）。"""
        all_records = self._all()
        return {
            "root": self._root,
            "keep": self._keep,
            "total": len(all_records),
            "reversible": len([r for r in all_records if r.reversible]),
            "recent": [r.to_dict() for r in self.history(limit=limit)],
        }

    # ---- 回滚 ---------------------------------------------------------------
    def rollback(self, txn_id: str = "last") -> tuple[bool, str]:
        """撤销一个已提交事务（逆序执行）。返回 ``(是否全部成功, 说明)``。"""
        rec = self.get(txn_id)
        if rec is None:
            return False, f"未找到事务 {txn_id}（还没有文件操作记录，或已被清理）"
        if rec.status == "rolled_back":
            return False, f"事务 {rec.id} 已经回滚过了，无需重复"
        if rec.status != "committed":
            state = STATUS_CN.get(rec.status, rec.status)
            return False, f"事务 {rec.id} 当前状态为「{state}」，不可回滚"

        undone: list[str] = []
        failures: list[str] = []
        for op in reversed(rec.ops):
            ok, msg = self._undo(op)
            (undone if ok else failures).append(f"{op.describe()}：{msg}")

        rec.status = "rolled_back" if not failures else "partial"
        rec.note = f"已撤销 {len(undone)} 步" if not failures else "；".join(failures)
        rec.rolled_back_ts = time.time()
        self._save(rec)

        done_n = len(undone)
        head = (
            f"已回滚事务 {rec.id}（{done_n}/{len(rec.ops)} 步）"
            if failures
            else f"已回滚事务 {rec.id}（{done_n} 步全部撤销）"
        )
        detail = "；".join(undone + [f"⚠ {f}" for f in failures])
        return (not failures), f"{head}：{detail}" if detail else head

    def _undo(self, op: TxnOp) -> tuple[bool, str]:
        try:
            if op.kind == "mkdir":
                # 目录是本次操作新建的 → 回滚时若已空则一并删除。
                # （否则"整理完再撤销"会在磁盘上留下一个空文件夹 —— S33 冒烟实测发现）
                if not os.path.isdir(op.path):
                    return True, "目录已不存在（无需处理）"
                if os.listdir(op.path):
                    return True, "目录非空，已保留"
                os.rmdir(op.path)
                return True, "已删除本次新建的空目录"

            if op.kind == "create":
                # 新建的文件：回滚 = 删除（无备份可还原）
                if os.path.exists(op.path):
                    os.remove(op.path)
                    return True, "已删除新建的文件"
                return True, "文件已不存在（无需处理）"

            if op.kind in ("overwrite", "delete"):
                if not op.backup:
                    return False, "无备份（写入时备份失败），无法还原"
                src = os.path.join(self._blobs_dir, *op.backup.split("/"))
                if not os.path.isfile(src):
                    return False, "备份文件已丢失，无法还原"
                parent = os.path.dirname(os.path.abspath(op.path))
                if parent:
                    os.makedirs(parent, exist_ok=True)
                shutil.copy2(src, op.path)
                return True, "已还原原内容"

            if op.kind == "move":
                if not os.path.exists(op.path):
                    return False, "文件已不在移动后的位置（可能被外部改动）"
                if os.path.exists(op.src):
                    return False, "原位置已有同名文件，未覆盖（保留现状）"
                parent = os.path.dirname(os.path.abspath(op.src))
                if parent:
                    os.makedirs(parent, exist_ok=True)
                shutil.move(op.path, op.src)
                return True, "已移回原位"
        except OSError as exc:
            return False, f"撤销失败: {exc}"
        return False, f"未知操作类型 {op.kind}"

    # ---- 保留策略 -----------------------------------------------------------
    def _prune(self) -> None:
        records = self._all()
        if len(records) <= self._keep:
            return
        for stale in records[: len(records) - self._keep]:
            try:
                os.remove(os.path.join(self._records_dir, f"{stale.id}.json"))
            except OSError:
                pass
            shutil.rmtree(os.path.join(self._blobs_dir, stale.id), ignore_errors=True)
