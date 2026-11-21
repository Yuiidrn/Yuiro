"""ArtifactStore（S09）：工具大结果的落盘与按需回读。

- ``put`` 存入完整内容并返回带 id 的 Artifact；
- ``read_slice`` 支持分片读取（LLM 用 artifact_read 工具按需取片段）；
- 内存 + 磁盘双写（``<store_dir>/<artifact_id>.json``），LRU 上限自动清理；
- 任何 IO 失败都不得影响主链路（静默降级为内存态）。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from yuiro.logger import vlog


@dataclass
class Artifact:
    """一份大对象（当前仅文本）：内容 + 来源 + 元数据。"""

    id: str
    name: str
    content: str
    created_at: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.content)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "created_at": self.created_at,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Artifact:
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            content=str(d.get("content", "")),
            created_at=float(d.get("created_at", time.time())),
            meta=dict(d.get("meta", {})),
        )


class ArtifactStore:
    def __init__(
        self, *, store_dir: str | Path = "data/artifacts", max_items: int = 50
    ) -> None:
        self._dir = Path(store_dir)
        self._max_items = max(1, int(max_items))
        self._items: dict[str, Artifact] = {}
        self._load()

    # ---- 持久化 -------------------------------------------------------------
    def _path(self, artifact_id: str) -> Path:
        return self._dir / f"{artifact_id}.json"

    def _load(self) -> None:
        try:
            if not self._dir.exists():
                return
            files = sorted(
                self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )[: self._max_items]
            for f in files:
                try:
                    art = Artifact.from_dict(json.loads(f.read_text(encoding="utf-8")))
                    if art.id:
                        self._items[art.id] = art
                except Exception:  # noqa: BLE001, S112 — 单个损坏文件不影响其余
                    continue
        except Exception as exc:  # noqa: BLE001 — 恢复失败不阻断启动
            vlog("artifact", f"[恢复] 失败（忽略）：{exc}")

    def _persist(self, art: Artifact) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path(art.id).write_text(
                json.dumps(art.to_dict(), ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 — 落盘失败不阻断（内存态仍可用）
            vlog("artifact", f"[落盘] 失败（忽略）：{exc}")

    # ---- 读写 ---------------------------------------------------------------
    def put(self, name: str, content: str, meta: dict | None = None) -> Artifact:
        """存入一份内容，返回带 id 的 Artifact（自动 LRU 清理）。"""
        art = Artifact(
            id=f"art_{uuid.uuid4().hex[:8]}",
            name=(name or "artifact")[:60],
            content=content,
            meta=dict(meta or {}),
        )
        self._items[art.id] = art
        self._persist(art)
        self.prune()
        vlog("artifact", f"[存入] {art.id} {art.name}（{art.size} 字符）")
        return art

    def get(self, artifact_id: str) -> Artifact | None:
        return self._items.get(artifact_id)

    def read_slice(self, artifact_id: str, start: int = 0, length: int = 2000) -> str:
        """读取片段（start 越界返回空串）。"""
        art = self.get(artifact_id)
        if art is None:
            return ""
        start = max(0, int(start))
        length = max(1, int(length))
        return art.content[start : start + length]

    def list(self) -> list[Artifact]:
        items = sorted(self._items.values(), key=lambda a: a.created_at, reverse=True)
        return items

    # ---- 维护 ---------------------------------------------------------------
    def prune(self) -> int:
        """超出上限时按创建时间删除最旧的（返回删除数）。"""
        removed = 0
        while len(self._items) > self._max_items:
            oldest = min(self._items.values(), key=lambda a: a.created_at)
            self._items.pop(oldest.id, None)
            try:
                self._path(oldest.id).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001, S110 — 删除失败不影响内存态
                pass
            removed += 1
        if removed:
            vlog("artifact", f"[清理] 移除 {removed} 个过期 artifact（上限 {self._max_items}）")
        return removed
