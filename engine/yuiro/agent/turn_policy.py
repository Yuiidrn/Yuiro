"""回合策略（S25：从 ``AgentLoop.send`` 逐字抽离）。

只管三件事——"本轮工具调用该不该执行"，以及与执行结果的记账：

- **成功去重**（``done``）：同一 ``(tool, name)`` 已成功执行过 → 再请求直接回 ``done``，
  避免对已打开的应用反复 ``app_open`` / 反复 ``app_focus``（实测"打开网易云疑云"）；
- **失败限流**（``skipped``）：同一 ``(tool, name)`` 连续失败达阈值 → 回 ``skipped``，
  避免无意义重试把工具轮耗尽；
- **询问去重**（``asked``）：同一调用已向用户抛出 need_choice/pending → 再请求直接回
  ``asked``，避免"用户还没回答，模型又拿旧参数重调"空转（实测"确认点歌死循环"：
  同一个 netease_play(keyword) 连打 3 轮全是 need_choice）；
- **无进展早停**（``progress_made``）：整轮全是重复/限流（无任何实质推进）→ 提前结束工具轮。

**不做**（各归其位）：

- 权限判定 / 并发执行 / 结果归一 → ``ToolDispatcher``（S16）；
- 状态摘要 → ``StateNotes``（S16）；
- 工具本身的成败语义 → 由调用方按结果 JSON 的 ``status`` 传入。

状态是**每轮对话级**（每次 ``send`` 新建一个实例），与 AgentLoop 的会话状态无关。
"""
from __future__ import annotations

import json

# 连续失败阈值（同一 (tool, name)）
FAIL_LIMIT = 2

# 视为"成功"的状态（登记去重；其中 done 是去重占位，不算新成功）
_SUCCESS_STATUS = ("ok", "done", "success", "opened", "text")


class TurnPolicy:
    """一轮对话内的工具调用策略（无 IO、可独立测试）。"""

    FAIL_LIMIT = FAIL_LIMIT

    def __init__(self) -> None:
        self._fail: dict[str, int] = {}
        self._done: set[str] = set()
        # 已向用户抛出 need_choice/pending 的调用键：用户尚未回答前重调同键无意义。
        self._asked: set[str] = set()
        self._progress = False
        self.rounds_skipped = 0  # 统计：被跳过的调用数（可观测）

    # ---- 键 ---------------------------------------------------------------
    @staticmethod
    def key_for(tool_name: str, args: dict | None) -> str:
        """去重/限流键：``tool:主参数`` + 其余参数的规范化签名。

        主参数沿用 name/app（可读）；其余参数（keyword/path/action 等）**必须进键**——
        否则不同关键词的 netease_play、不同路径的 file_write 会互相误去重/误限流
        （旧版只取 name/app，实测"确认点歌"时不同 keyword 被当成同一次调用）。
        """
        a = dict(args or {})
        head = a.pop("name", None) or a.pop("app", None) or ""
        rest = json.dumps(a, sort_keys=True, ensure_ascii=False) if a else ""
        return f"{tool_name}:{head}|{rest}" if rest else f"{tool_name}:{head}"

    # ---- 判定 -------------------------------------------------------------
    def skip_reason(self, key: str) -> str | None:
        """应跳过时返回 ``"done"`` / ``"skipped"`` / ``"asked"``；可执行时返回 ``None``。"""
        if key in self._done:
            return "done"
        if key in self._asked:
            return "asked"
        if self._fail.get(key, 0) >= self.FAIL_LIMIT:
            return "skipped"
        return None

    @staticmethod
    def skip_result(reason: str) -> str:
        """跳过时返回给 LLM 的结构化结果。

        ⚠ note 文案刻意强调「回看真实结果、不要臆造成功」：此前 ``done`` 的
        "该操作已完成"会被收尾总结误解成"已成功"，于是"没找到歌"被汇报成
        "已经放起来了"（实测撒谎）。去重占位绝不能诱导模型把"跳过"当"成功"。
        """
        if reason == "done":
            return json.dumps(
                {"status": "done",
                 "note": "该调用与之前已成功执行过的完全相同（同参数重复），已跳过。"
                         "请回看【本轮工具结果】里该工具的**真实返回**并据此向用户汇报，"
                         "不要因为本次被跳过就臆造成功。"},
                ensure_ascii=False,
            )
        if reason == "asked":
            return json.dumps(
                {"status": "skipped",
                 "note": "该调用与之前完全相同（同参数重复），已拒绝重调。"
                         "请回看【本轮工具结果】里该工具的**真实返回**并据此向用户汇报，"
                         "不要臆造成功（之前是没找到 / 等待确认，现在依然是）。"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"status": "skipped", "note": "已连续失败，跳过重复调用"}, ensure_ascii=False
        )

    @staticmethod
    def skip_trace(reason: str) -> str:
        """工具轨迹里的跳过标注（沿用抽离前的中文文案）。"""
        return {"done": "已去重", "asked": "已询问待确认"}.get(reason, "限流")

    # ---- 记账 -------------------------------------------------------------
    def begin_round(self) -> None:
        """每轮工具调用前重置"本轮是否有实质进展"。"""
        self._progress = False

    def note_result(self, key: str, status: str) -> bool:
        """按结果状态记账；返回是否需要**更新状态摘要**。

        原逻辑（逐字保留）：

        - ``error`` → 失败计数 +1，且视为"有进展"（真实尝试过）；
        - 既非 ``skipped`` 也非 ``done`` → 清除失败计数，视为有进展；
          其中 ``need_choice`` / ``pending`` 额外登记询问（同键重调将被 skip）；
        - 成功类状态 → 登记去重；其中 ``done`` 是去重占位，不更新状态摘要。
        """
        if status == "error":
            self._fail[key] = self._fail.get(key, 0) + 1
            self._progress = True
        elif status not in ("skipped", "done"):
            self._fail.pop(key, None)
            self._progress = True
            if status in ("need_choice", "pending"):
                self._asked.add(key)
        if status in _SUCCESS_STATUS:
            self._done.add(key)
            return status != "done"
        return False

    # ---- 查询 -------------------------------------------------------------
    @property
    def progress_made(self) -> bool:
        """本轮是否有实质推进（``ok`` / ``error`` / ``text`` 均算推进）。"""
        return self._progress

    @property
    def done_count(self) -> int:
        return len(self._done)

    def state(self) -> dict:
        return {
            "done": len(self._done),
            "failed": sum(1 for v in self._fail.values() if v >= self.FAIL_LIMIT),
            "progress": self._progress,
        }
