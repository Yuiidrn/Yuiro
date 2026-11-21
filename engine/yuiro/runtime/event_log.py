"""EventLog（S12）：AgentEvent 的追加式落盘与回放。

spec 要求 Event 是"可持久化、可回放"的一等实体（``docs/spec/README.md`` §3）。

设计：
- 追加式 JSONL（``<store_dir>/<session_id>.jsonl``，每行一个事件）；
- 写入失败静默（事件日志永远不能影响主链路）；
- 回放：``load`` 按时间序返回事件列表（``replay`` 为语义别名）；
- 上限：单会话文件超过 ``max_lines`` 时保留最近一半（避免无限增长）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from yuiro.logger import vlog
from yuiro.runtime.events import AgentEvent


class EventLog:
    """事件日志：追加落盘 + 按会话回放。"""

    def __init__(self, *, store_dir: str | Path = "data/events", max_lines: int = 5000) -> None:
        self._dir = Path(store_dir)
        self._max_lines = max(100, int(max_lines))
        self._counts: dict[str, int] = {}

    async def sink(self, event: AgentEvent) -> None:
        """EventBus 的 async 订阅者入口（S12：``subscribe_all(sink)``）。"""
        self.append(event)

    def _path(self, session_id: str) -> Path:
        safe = (session_id or "global").replace("/", "_").replace("\\", "_")[:64]
        return self._dir / f"{safe}.jsonl"

    # ---- 写入 ---------------------------------------------------------------
    def append(self, event: AgentEvent) -> None:
        """追加一条事件（失败静默：日志绝不能影响主链路）。"""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._path(event.session_id)
            line = json.dumps(
                {
                    "ts": event.timestamp,
                    "type": event.type,
                    "source": event.source,
                    "session_id": event.session_id,
                    "generation": event.generation,
                    "trace_id": event.trace_id,
                    "event_id": event.event_id,
                    "payload": event.payload,
                },
                ensure_ascii=False,
            )
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            n = self._counts.get(event.session_id, 0) + 1
            self._counts[event.session_id] = n
            # 每 max_lines/2 条检查一次（留出超限余量，确保能真正触发轮转）
            if n % max(1, self._max_lines // 2) == 0:
                self._trim(path)
        except Exception:  # noqa: BLE001, S110 — 落盘失败静默（不影响主链路）
            pass

    def _trim(self, path: Path) -> None:
        """超过上限时保留最近一半（行级轮转）。"""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= self._max_lines:
                return
            keep = lines[len(lines) // 2 :]
            path.write_text("\n".join(keep) + "\n", encoding="utf-8")
            vlog("event", f"[日志轮转] {path.name}: {len(lines)} → {len(keep)} 行")
        except Exception:  # noqa: BLE001, S110 — 轮转失败忽略
            pass

    # ---- 读取 / 回放 ---------------------------------------------------------
    def load(
        self, session_id: str, *, limit: int = 200, event_type: str | None = None
    ) -> list[dict]:
        """回放某会话的事件（时间升序，取最近 limit 条；损坏行跳过）。"""
        try:
            path = self._path(session_id)
            if not path.exists():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            return []
        events: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue  # 损坏行跳过（截断写入等场景）
            if not isinstance(data, dict):
                continue
            if event_type and data.get("type") != event_type:
                continue
            events.append(data)
        return events[-max(1, int(limit)) :]

    def replay(self, session_id: str, *, limit: int = 200) -> list[dict]:
        """Replay 语义别名：按时间序返回最近事件（供调试台/分析）。"""
        return self.load(session_id, limit=limit)

    def sessions(self) -> list[str]:
        """已有事件日志的会话列表（按文件修改时间倒序）。"""
        try:
            if not self._dir.exists():
                return []
            files = sorted(
                self._dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            return [f.stem for f in files]
        except Exception:  # noqa: BLE001
            return []

    def stats(self) -> dict:
        """轻量统计（文件数 / 总行数 / 目录）。"""
        try:
            files = list(self._dir.glob("*.jsonl")) if self._dir.exists() else []
            total = 0
            for f in files:
                try:
                    total += sum(1 for _ in f.open(encoding="utf-8"))
                except Exception:  # noqa: BLE001, S112
                    continue
            return {"dir": str(self._dir), "sessions": len(files), "lines": total}
        except Exception:  # noqa: BLE001
            return {"dir": str(self._dir), "sessions": 0, "lines": 0}


def log_now() -> float:
    """当前时间戳（供测试与外部复用）。"""
    return time.time()
