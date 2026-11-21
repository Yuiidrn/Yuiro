"""Relationship Memory（S26）：**我们之间发生过什么**。

规范依据（``docs/spec/README.md`` 的配套区分，不得混用）：

```
Conversation Memory = 用户和我聊了什么     ← 已由 L2/L3 承担
Relationship Memory = 我们之间发生过什么   ← 本模块
Task State          = 我正在做什么         ← Task Journal
Model Personality   = 我说话做事像谁       ← LoRA
```

与 Conversation Memory 的**本质区别**（决定了实现方式）：

| | Conversation Memory | Relationship Memory |
|---|---|---|
| 内容 | 对话与事实 | **关系事实**（认识多久 / 聊过多少次 / 一起做成过什么） |
| 规模 | 大（持续增长） | 极小（几十字节，稳定） |
| 检索 | 语义检索（RRF） | **不检索**：always-on 的背景知识 |
| 注入 | 命中的片段 | 每次都在（独立分段【我们的关系】） |

因此本模块**不写 sqlite、不做 embedding**，只是一份 JSON + 派生文本。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from yuiro.logger import vlog

# 天数里程碑（跨过即记一笔"值得记住的时刻"）
_DAY_MILESTONES = (3, 7, 30, 100, 365)

# 注入时最多回看的里程碑条数（保持人话、不啰嗦）
_MILESTONE_TAIL = 3


@dataclass
class RelationshipState:
    """关系的全部事实（刻意保持极小）。"""

    first_seen: float = 0.0  # 首次互动时间戳
    last_seen: float = 0.0
    interactions: int = 0  # 互动轮数（用户说话次数）
    tasks_completed: int = 0  # 一起完成的事
    explicit_memories: int = 0  # 用户要求记住的事数
    milestones: list[str] = field(default_factory=list)
    last_milestone_day: int = 0  # 已记过的最大天数里程碑


class RelationshipMemory:
    """关系事实的轻量存储（JSON 落盘；量小、稳定、不参与语义检索）。"""

    def __init__(self, path: str | Path = "data/relationship.json") -> None:
        self._path = Path(path)
        self.state = RelationshipState()
        self._load()

    # ---- 记录（写入点极简，避免到处埋钩子）----------------------------------
    def note_interaction(self) -> list[str]:
        """一次用户互动。返回本次新增的里程碑（供可观测/日志）。"""
        now = time.time()
        if self.state.first_seen <= 0:
            self.state.first_seen = now
            vlog("relationship", "第一次见面（关系记忆开始）")
        self.state.last_seen = now
        self.state.interactions += 1
        new = self._check_day_milestones()
        self._save()
        return new

    def note_task_completed(self, goal: str = "") -> None:
        self.state.tasks_completed += 1
        if self.state.tasks_completed == 1:
            suffix = f"（{goal}）" if goal.strip() else ""
            self._add_milestone(f"第一次一起完成一件事{suffix}")
        self._save()

    def note_explicit_memory(self) -> None:
        self.state.explicit_memories += 1
        self._save()

    def reset(self) -> None:
        """清零关系记忆并落盘（"清空全部记忆"时调用，S50）。

        关系记忆是**独立 JSON 文件、不在 SQLite 里** —— 此前全清清不到它，
        导致 db 全空后回复仍出现"认识六天、聊过一百三十九次"（用户实测）。
        reset 后 ``interactions=0`` → ``summary()`` 返回空串 = 不再注入；
        下次互动由 ``note_interaction`` 自动补 ``first_seen`` 重新计数。
        """
        self.state = RelationshipState()
        self._save()
        vlog("relationship", "关系记忆已重置")

    # ---- 派生 ---------------------------------------------------------------
    @property
    def days_known(self) -> int:
        if self.state.first_seen <= 0:
            return 0
        return int((time.time() - self.state.first_seen) // 86400) + 1

    def summary(self) -> str:
        """注入文本（自然语言；无互动记录时返回空串 = 不注入）。"""
        if self.state.interactions <= 0:
            return ""
        parts = [f"你和用户已经认识 {self.days_known} 天，聊过 {self.state.interactions} 次"]
        if self.state.tasks_completed:
            parts.append(f"一起完成过 {self.state.tasks_completed} 件事")
        if self.state.explicit_memories:
            parts.append(f"用户让你记住 {self.state.explicit_memories} 件事")
        text = "，".join(parts) + "。"
        if self.state.milestones:
            text += "值得记住的时刻：" + "；".join(self.state.milestones[-_MILESTONE_TAIL:]) + "。"
        return text

    def _check_day_milestones(self) -> list[str]:
        new: list[str] = []
        days = self.days_known
        for mark in _DAY_MILESTONES:
            if days >= mark > self.state.last_milestone_day:
                self.state.last_milestone_day = mark
                label = f"认识第 {mark} 天"
                self._add_milestone(label)
                new.append(label)
        return new

    def _add_milestone(self, text: str) -> None:
        if text and text not in self.state.milestones:
            self.state.milestones.append(text)

    # ---- 持久化（失败静默：关系记忆不值得影响主链路）------------------------
    def _load(self) -> None:
        try:
            if not self._path.is_file():
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self.state = RelationshipState(
                first_seen=float(data.get("first_seen", 0.0)),
                last_seen=float(data.get("last_seen", 0.0)),
                interactions=int(data.get("interactions", 0)),
                tasks_completed=int(data.get("tasks_completed", 0)),
                explicit_memories=int(data.get("explicit_memories", 0)),
                milestones=[str(m) for m in data.get("milestones", [])],
                last_milestone_day=int(data.get("last_milestone_day", 0)),
            )
        except Exception as exc:  # noqa: BLE001 — 损坏文件按全新关系处理
            vlog("relationship", f"关系记忆读取失败（按新关系处理）：{exc}")
            self.state = RelationshipState()

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(asdict(self.state), ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 — 落盘失败不影响对话
            vlog("relationship", f"关系记忆落盘失败（忽略）：{exc}")

    # ---- 视图 ---------------------------------------------------------------
    def to_dict(self) -> dict:
        data = asdict(self.state)
        data["days_known"] = self.days_known
        data["summary"] = self.summary()
        return data
