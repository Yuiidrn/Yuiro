"""日记回顾工具（S51）：``diary_recall``。

设计：`docs/features/diary-feature-design.md` §9.2.1 / §9.2.4。

两条关键设计（都不直观，所以写在这里）：

1. **只给摘要与元信息，绝不朗读全文** —— 回顾是"浏览"，不是播报；
   全文由 UI 呈现（用户自己看），模型拿全文只会把它当谈资。
2. ★ **`local_only`（仅保存）只返回元信息**：它的语义是"她检索不到"。
   但用户**主动问**"我写过什么"是用户的权利 —— 所以给"9-12 有一篇（未共享）"
   这样的存在性信息，**不把内容交给模型**（既尊重隐私，又不像"当没写过"那样撒谎）。
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from yuiro.logger import vlog
from yuiro.tools import EFFECT_READ, BaseTool


class DiaryRecallTool(BaseTool):
    name = "diary_recall"
    description = (
        "回顾用户**自己写过**的日记（按关键词或情绪查找）。"
        "当用户问「我上周写的日记呢」「我最近写了什么」「上次那篇关于 X 的」时调用。"
        "返回摘要与日期；**未共享的日记只会说明它存在、不返回内容**。"
    )
    approval_required = False
    effect = EFFECT_READ

    def __init__(self, store_getter: Callable[[], object] | None = None) -> None:
        # 延迟绑定（与 avatar_getter 同款）：日记在 lifespan 里装配，晚于工具注册，
        # 传 getter 可让顺序无关、且重建 AgentLoop 时不会拿到过期引用。
        self._get_store = store_getter or (lambda: None)

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "关键词（如「比赛」「火锅」）；留空则按时间倒序列出最近的",
                        },
                        "mood": {
                            "type": "string",
                            "description": "按情绪筛选（如「疲惫」「开心」），可选",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回条数（默认 5，上限 20）",
                        },
                    },
                    "required": [],
                },
            },
        }

    @staticmethod
    def _brief(row: dict) -> dict:
        """列表项：shared 给摘要，其余**只给存在性**（§9.2.4）。"""
        date = str(row.get("created_at") or "")[:10]
        from yuiro.diary import PRIVACY_SHARED

        if str(row.get("privacy") or "") == PRIVACY_SHARED:
            return {
                "date": date,
                "summary": str(row.get("summary") or "").strip() or "（无摘要）",
                "mood": list(row.get("mood_tags") or []),
                "shared": True,
            }
        return {"date": date, "shared": False, "note": "有一篇未共享的日记（内容仅用户可见）"}

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        store = self._get_store()
        if store is None:
            return json.dumps(
                {"status": "pending", "note": "日记功能未启用"}, ensure_ascii=False
            )
        a = args or {}
        query = str(a.get("query") or "").strip()
        mood = str(a.get("mood") or "").strip()
        try:
            limit = max(1, min(int(a.get("limit") or 5), 20))
        except (TypeError, ValueError):
            limit = 5

        def _fetch() -> list[dict]:
            if query:
                return store.search(query, limit=limit)  # type: ignore[attr-defined]
            return store.list_recent(limit=limit, mood=mood)  # type: ignore[attr-defined]

        try:
            rows = await asyncio.to_thread(_fetch)
        except Exception as exc:  # noqa: BLE001 — 检索失败要如实说，不编造"你写过…"
            vlog("diary", f"回顾检索失败：{type(exc).__name__}: {exc}")
            return json.dumps(
                {"status": "error", "note": "翻日记时出错了，可以稍后再试"},
                ensure_ascii=False,
            )
        if not rows:
            return json.dumps(
                {"status": "ok", "count": 0, "note": "没找到相关日记"},
                ensure_ascii=False,
            )
        items = [self._brief(r) for r in rows]
        return json.dumps(
            {"status": "ok", "count": len(items), "items": items}, ensure_ascii=False
        )


DIARY_TOOLS: list[type] = [DiaryRecallTool]
