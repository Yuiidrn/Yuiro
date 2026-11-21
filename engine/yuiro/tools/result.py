"""工具返回值的统一规约（S42 / P1）—— 把「有没有产出」变成结构，而不是各写各的。

**为什么需要规约**：长期以来每个工具自己拼 JSON，字段名各不一致
（playlists / options / items / tracks / songs / list…）。引擎想把结果变成用户
看得见的东西，就只能靠一张**硬编码的字段名映射表**：:

    _RESULT_CARD_KEYS = {"playlists": ..., "options": ..., "tracks": ..., "items": ...}

前端也只能按那张表猜。后果：
- 新工具用了新字段名 → 界面上什么都不显示，用户侧表现为「给了个壳、没有反馈」；
- 想加一种反馈形式（比如把产物列成可点条目）得回去改引擎的映射表。

统一到下面这组字段后，**引擎与壳层只认规约、不认具体工具**：新增工具只要按规约
返回，反馈（卡片/待选/产物）就是自动的 —— 这正是"泛化"在工具层的体现。

约定结构::

    {
      "status": "ok" | "error" | "pending" | "need_choice",
      "message": "给人看的一句话（引擎用它做兜底话术与卡片备注）",
      "options":   [ {...} ],   # 可选：让用户挑（引擎渲染成可点条目）
      "artifacts": [ {...} ],   # 可选：产出物（文件路径、链接等）
      "data":      { ... }      # 其它结构化数据（保持向后兼容）
    }

``options`` / ``artifacts`` 元素推荐用 ``{"name": ..., "id": ..., "note": ...}``。
"""
from __future__ import annotations

import json

#: 引擎认得的四个状态。``ok``/``error`` 是终态；``pending``/``need_choice`` 表示
#: "还在等"，会被登记为待回应事项（见 agent/tool_events.py 的 PendingInteraction）。
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_PENDING = "pending"
STATUS_NEED_CHOICE = "need_choice"


def _dump(payload: dict) -> str:
    """统一序列化（工具层一律返回 JSON 字符串）。"""
    return json.dumps(payload, ensure_ascii=False)


def ok(message: str, *, options: list[dict] | None = None,
       artifacts: list[dict] | None = None, **data: object) -> str:
    """成功。``options``/``artifacts`` 会被引擎自动转成界面元素。"""
    return _dump(_payload(STATUS_OK, message, options, artifacts, data))


def err(message: str, *, options: list[dict] | None = None, **data: object) -> str:
    """失败。message 必须**如实**说明原因（提示词原则二：不许假装完成）。"""
    return _dump(_payload(STATUS_ERROR, message, options, None, data))


def pending(message: str, *, options: list[dict] | None = None, **data: object) -> str:
    """还在进行中（如"已交给播放器，但还没出声"）。"""
    return _dump(_payload(STATUS_PENDING, message, options, None, data))


def need_choice(message: str, options: list[dict], **data: object) -> str:
    """需要用户选一个。

    **不确定就不要猜**：猜错一张歌单等于整列放错歌（S41 的实测教训）。
    把候选给出来，让用户点选或让模型接着挑。
    """
    return _dump(_payload(STATUS_NEED_CHOICE, message, options, None, data))


def _payload(status: str, message: str, options: list[dict] | None,
             artifacts: list[dict] | None, data: dict) -> dict:
    payload: dict = {"status": status, "message": message}
    if options:
        payload["options"] = list(options)
    if artifacts:
        payload["artifacts"] = list(artifacts)
    # 其它字段平铺在顶层：保持与历史工具的返回兼容（模型读起来也更直接）
    payload.update(data)
    return payload
