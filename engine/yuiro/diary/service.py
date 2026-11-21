"""日记编排（S51）：解构润色 + 隐私三档 + 记忆联动 + 总评。

设计：`docs/features/diary-feature-design.md`
（§2.3 解构 / §3.2 写入协议 / §8.2 总评 / §9.1.4 档位联动）。

三条必须守住的行为（每条都有对应测试）：

1. **解构失败绝不丢日记**：LLM 出错时原文照存、结构化留空 ——
   用户的记录比系统的花活重要得多。
2. **隐私写入只有一处**：``shared`` 才写记忆；``local_only`` **绝不碰记忆库** ——
   "检索搜不到"由"不写入"保证，而不是靠检索侧过滤（不写入即不可见，最小权限）。
3. **改档位必须联动**（§9.1.4）：``shared → local_only`` 要**删除已写记忆**，
   否则就是谎报隐私（S50 同胞问题：用户可见的操作必须与实际存储一致）。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from yuiro.diary import PRIVACY_ALL, PRIVACY_DISCARD, PRIVACY_LOCAL_ONLY, PRIVACY_SHARED
from yuiro.logger import vlog

# ---- 解构 prompt（§2.3：辅助而非篡改）--------------------------------------
_DECONSTRUCT_PROMPT = """你是日记整理助手。把用户的生活片段整理成结构化结果。

只输出一个 JSON 对象（不要解释、不要代码块围栏），字段：
{
  "polished_text": "润色稿：修正错别字、理顺语序，保留原意与口语感。★只改表达，不加任何新事实",
  "summary": "一句话摘要（≤50字，供记忆注入用）",
  "mood_tags": ["情绪词，2-4 个，如 疲惫/期待"],
  "topics": ["主题词，1-3 个，如 毕设/跑步"],
  "entities": [{"type": "person|place|thing", "name": "出现的具体对象"}],
  "followup_question": "下次可以自然问起的一句话；没有就填空字符串",
  "narrative_type": "short 或 long（短期事件 / 持续状态，如'这学期在准备考研'）"
}

用户原文：
---
{raw_text}
---"""

# ---- 总评 prompt（§8.2 的质量红线）-----------------------------------------
_REVIEW_PROMPT = """你刚读完用户今天的日记。用 2-4 句说出你的感受与观察。

硬要求（违反任何一条都算失败）：
- **必须锚定日记里的具体内容**（提到具体的人/事/细节）—— 泛泛而谈、换一篇日记
  也成立的话，就是失败的回应；
- 先回应情绪，再谈你注意到的；
- 若内容是低落/焦虑的：**共情优先**，绝不说教、绝不出现"你应该…"；
- 不给评价、不打分、不建议；
- 只输出你要说的话本身，不要任何解释、前缀或引号。

日记：
---
{content}
---"""


class DiaryService:
    """日记用例编排（不直接依赖 FastAPI；供 debug_api / 工具层复用）。"""

    def __init__(self, store, *, memory=None, llm=None, forget_memory=None) -> None:
        self._edit_lock = asyncio.Lock()
        self._store = store
        self._memory = memory  # MemorySystem | None（None 时 shared 仅落库、不写记忆）
        self._llm = llm        # LLMProvider | None（None 时跳过解构/总评，降级但可用）
        self._forget_memory = forget_memory  # 可选跨角色撤销入口；默认保持单 memory 契约

    # ---- LLM 调用 -----------------------------------------------------------
    async def _call_llm(self, prompt: str) -> str:
        """一次性调用 LLM 并聚合流式 token；失败返回空串（**绝不抛给上层**）。"""
        if self._llm is None:
            return ""
        parts: list[str] = []
        try:
            async for chunk in self._llm.stream_text(
                [{"role": "user", "content": prompt}]
            ):
                if getattr(chunk, "kind", "") == "token":
                    parts.append(str(getattr(chunk, "content", "")))
        except Exception as exc:  # noqa: BLE001 — 解构失败不阻断日记落库
            vlog("diary", f"LLM 调用失败（降级继续）：{type(exc).__name__}: {exc}")
            return ""
        return "".join(parts).strip()

    @staticmethod
    def _parse_json(text: str) -> dict:
        """从模型输出里抠出 JSON（容忍代码块围栏与前后废话）。"""
        s = (text or "").strip()
        if not s:
            return {}
        if "```" in s:
            # 取第一个围栏内的内容
            start = s.find("```")
            body = s[start + 3 :]
            body = body.removeprefix("json")
            end = body.find("```")
            s = body[:end] if end >= 0 else body
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            return {}
        try:
            data = json.loads(s[i : j + 1])
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    async def deconstruct(self, raw_text: str) -> dict:
        """解构润色。**失败返回空 dict**（调用方据此退回"只用原文"）。"""
        # 用 replace 而不是 str.format：prompt 里的 JSON 示例含 `{`/`}`，
        # format 会把它们当占位符直接抛 KeyError（已在测试里被抓住）。
        out = await self._call_llm(_DECONSTRUCT_PROMPT.replace("{raw_text}", raw_text))
        data = self._parse_json(out)
        if not data:
            vlog("diary", "解构未产出可用 JSON —— 原文照存，结构化留空")
        return data

    # ---- 提交（解构 → 落库 → 隐私写入）-------------------------------------
    async def submit(
        self,
        raw_text: str,
        *,
        privacy: str = PRIVACY_LOCAL_ONLY,
        quip_mode: bool = False,
        data: dict | None = None,
    ) -> dict:
        """用户确认后提交一篇日记。

        顺序刻意是**先解构、再落库**：日记里存的是定稿与结构化结果。
        但解构失败**不影响落库** —— 原文照存（§2.3 的"记忆绝不丢失"同理）。
        """
        if privacy not in PRIVACY_ALL:
            raise ValueError(f"未知隐私档位：{privacy!r}")
        text = (raw_text or "").strip()
        if not text and not (data and (data.get("title") or data.get("attachment_ids"))):
            return {"ok": False, "note": "日记内容为空"}

        if privacy == PRIVACY_DISCARD:
            # 阅后即焚：不落库、不写记忆。这里直接返回，不进入任何持久化路径。
            vlog("diary", "阅后即焚：不落库、不写记忆")
            return {"ok": True, "diary_id": 0, "privacy": privacy, "discard": True}

        # ``data`` 可选：审阅态已解构过就**不重复调 LLM**（§2.1 审阅编辑态）。
        if data is None:
            data = await self.deconstruct(text)
        diary_id = self._store.save(
            raw_text=text,
            polished_text=str(data.get("polished_text") or text),
            summary=str(data.get("summary") or " ".join(text.split())[:120]),
            mood_tags=list(data.get("mood_tags") or []),
            topics=list(data.get("topics") or []),
            entities=list(data.get("entities") or []),
            followup_question=str(data.get("followup_question") or ""),
            narrative_type=str(data.get("narrative_type") or "short"),
            privacy=privacy,
            quip_mode=quip_mode,
            title=str(data.get("title") or ""),
            attachment_ids=data.get("attachment_ids") or [],
        )
        row = self._store.get(diary_id) or {}
        written = 0
        if privacy == PRIVACY_SHARED:
            written = await self._write_to_memory(row)
        vlog(
            "diary",
            f"日记已落库 id={diary_id} privacy={privacy}"
            f"（解构={'有' if data else '无'}，记忆{'已写' if written else '未写'}）",
        )
        return {
            "ok": True,
            "diary_id": diary_id,
            "privacy": privacy,
            "memory_written": bool(written),
            "deconstructed": bool(data),
        }

    async def edit(self, diary_id, *, revision, title, text, attachment_ids):
        from yuiro.diary.media import validate_assets, revise
        async with self._edit_lock:
            row = self._store.get(diary_id)
            if not row or row["revision"] != revision:
                raise ValueError("记录已被更新，请重新打开；本地修改仍保留")
            if not (title.strip() or text.strip() or attachment_ids):
                raise ValueError("标题、正文或附件至少保留一项")
            validate_assets(self._store, attachment_ids, diary_id)
            if row.get("memory_written") or row["source_meta"].get("memory_text"):
                await self._remove_from_memory(row)
                fresh = self._store.get(diary_id)
                if fresh["source_meta"].get("memory_text"):
                    raise ValueError("旧记忆暂未撤回，未修改正文，请稍后重试")
            updated = revise(self._store, diary_id, revision=revision, title=title,
                             text=text, ids=attachment_ids)
            written = await self._write_to_memory(updated) if updated["privacy"] == PRIVACY_SHARED else 0
            return {"ok":True,"diary_id":diary_id,"revision":updated["revision"],
                    "memory_written":bool(written)}

    # ---- 隐私联动（§9.1.4 红线）--------------------------------------------
    async def change_privacy(self, diary_id: int, new_privacy: str) -> dict:
        """改档位并**同步记忆**。

        ``shared → local_only``：删掉已写入的记忆（否则"改成私密"是假的）；
        ``local_only → shared``：补写记忆（此时才首次写入）。
        """
        if new_privacy not in PRIVACY_ALL:
            raise ValueError(f"未知隐私档位：{new_privacy!r}")
        ok, old = self._store.set_privacy(diary_id, new_privacy)
        if not ok:
            return {"ok": False, "note": f"找不到日记 id={diary_id}"}
        row = self._store.get(diary_id) or {}
        removed = 0
        written = 0
        if old == PRIVACY_SHARED and new_privacy != PRIVACY_SHARED:
            removed = await self._remove_from_memory(row)
        elif old != PRIVACY_SHARED and new_privacy == PRIVACY_SHARED:
            written = await self._write_to_memory(row)
        vlog(
            "diary",
            f"隐私档位 {old} → {new_privacy}（id={diary_id}，"
            f"删记忆 {removed} 条 / 写记忆 {written} 条）",
        )
        return {
            "ok": True,
            "diary_id": diary_id,
            "from": old,
            "to": new_privacy,
            "memory_removed": removed,
            "memory_written": written,
        }

    async def delete(self, diary_id: int) -> dict:
        """删日记 —— 同时清掉它写入的记忆（默认同删，符合直觉，§9.6）。"""
        row = self._store.get(diary_id)
        if row is None:
            return {"ok": False, "note": f"找不到日记 id={diary_id}"}
        removed = await self._remove_from_memory(row)
        done = self._store.delete(diary_id)
        return {"ok": bool(done), "diary_id": diary_id, "memory_removed": removed}

    # ---- 总评（§8.2）-------------------------------------------------------
    async def closing_review(self, diary_id: int) -> dict:
        """确认录入后的总评（一次性；失败**不阻塞**，退回既有简短回应）。

        ``review_enabled`` 由配置控制；这里只管"有内容/没内容"。
        """
        row = self._store.get(diary_id)
        if row is None:
            return {"ok": False, "note": f"找不到日记 id={diary_id}"}
        content = str(row.get("polished_text") or row.get("raw_text") or "")
        text = await self._call_llm(_REVIEW_PROMPT.replace("{content}", content[:1500]))
        if not text:
            return {"ok": False, "note": "总评暂不可用"}
        self._store.set_closing_review(diary_id, text)
        return {"ok": True, "diary_id": diary_id, "review": text}

    # ---- 记忆写入/删除 ------------------------------------------------------
    @staticmethod
    def _memory_text(row: dict) -> str:
        """写入记忆时的文本。

        ★ 带**来源标注**（§3.3）：让模型知道这是日记内容、有"能不能提"的边界，
        避免她张口就是"我看了你的日记"。
        """
        stamp = str(row.get("created_at") or "")[:10]
        summary = str(row.get("summary") or "").strip()
        body = summary or str(row.get("polished_text") or row.get("raw_text") or "")
        title = str(row.get("title") or "").strip()
        content = "\n".join(part for part in (title, body) if part)
        return f"[来自用户的日记 {stamp}] {content}"[:400]

    async def _write_to_memory(self, row: dict) -> int:
        """``shared`` → 写 L2 情景记忆；写入文本记进 ``source_meta`` 供日后删除。

        用 ``retriever.add`` 直接写 L2（而不是 ``remember``）：日记的入库**不经过
        对话语义**（没有"用户说/我回复"的轮次结构），且写入是用户显式授权的。
        """
        if self._memory is None:
            return 0
        text = self._memory_text(row)
        try:
            await self._memory.retriever.add(text, salience=2.0)
        except Exception as exc:  # noqa: BLE001 — 记忆写入失败不影响日记落库
            vlog("diary", f"写入记忆失败：{type(exc).__name__}: {exc}")
            return 0
        # 回链：把写入文本存进 source_meta（**不动记忆库 schema** 的轻量方案），
        # 供改档位时精确删除 —— 否则"改成私密"删不掉已写的记忆。
        meta = dict(row.get("source_meta") or {})
        meta["memory_text"] = text
        diary_id = int(row.get("id") or 0)
        if diary_id:
            self._store.conn.execute(
                "UPDATE diaries SET source_meta = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), diary_id),
            )
            self._store.conn.commit()
            self._store.mark_memory_written(diary_id, True)
        return 1

    async def _remove_from_memory(self, row: dict) -> int:
        """删除该日记写入的记忆条目（改档位 / 删日记时调用）。"""
        if self._memory is None and self._forget_memory is None:
            return 0
        meta: dict[str, Any] = dict(row.get("source_meta") or {})
        text = str(meta.get("memory_text") or "")
        if not text:
            return 0
        try:
            removed = (await self._forget_memory(text) if self._forget_memory is not None
                       else await self._memory.forget_text(text))
        except Exception as exc:  # noqa: BLE001
            vlog("diary", f"删除记忆失败：{type(exc).__name__}: {exc}")
            return 0
        diary_id = int(row.get("id") or 0)
        if diary_id:
            meta.pop("memory_text", None)
            self._store.conn.execute(
                "UPDATE diaries SET source_meta = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), diary_id),
            )
            self._store.conn.commit()
            self._store.mark_memory_written(diary_id, False)
        return removed
