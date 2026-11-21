"""工具活动文案（S39）：把"调用了什么工具"翻译成"它正在做什么"。

用途：

- **前端状态行**：桌宠在干活时显示「正在读取目录…」，而不是静默几秒；
- **长任务进度**：配合 ``TaskRuntime`` 显示「3/7 步 · 正在移动文件」。

设计原则：

1. **克制**：只描述事实，不加情绪、不加 emoji；一条不超过一行；
2. **进行时**：都是「正在…」，让用户知道"还在进行"，而不是"做完了"；
3. **可降级**：未登记的工具回退为「正在处理…」，不抛错、不泄漏工具内部名。
"""
from __future__ import annotations

import json

#: 工具 → 进行时文案（前端状态行展示）
_ACTIVITY: dict[str, str] = {
    # 文件
    "file_list": "正在查看目录…",
    "file_read": "正在读文件…",
    "file_write": "正在写入文件…",
    "file_create": "正在创建文件…",
    "file_move": "正在移动文件…",
    "file_delete": "正在删除文件…",
    # 事务
    "transaction_list": "正在查看操作记录…",
    "transaction_rollback": "正在撤销刚才的操作…",
    # 系统
    "app_open": "正在打开应用…",
    "app_focus": "正在切换窗口…",
    "media_control": "正在调整播放…",
    # 网易云
    "netease_search": "正在搜歌…",
    "netease_play": "正在准备播放…",
    "netease_control": "正在控制播放…",
    "netease_playlist": "正在读歌单…",
    "netease_recommend": "正在挑歌…",
    "netease_lyric": "正在找歌词…",
    "netease_login": "正在准备登录…",
    # 联网检索（S51）：检索要 1–3s，**必须有进行中反馈**（设计文档 §9.2）——
    # 没有它用户会以为"卡住了/没听见"。
    "web_search": "正在联网查询…",
    # 日记（S51）：回顾要扫库，同样需要反馈。
    "diary_recall": "正在翻你的日记…",
    # 任务
    "task_create": "正在登记任务…",
    "task_advance": "正在推进任务…",
    "task_complete": "正在完成任务…",
    "task_plan": "正在拟定计划…",
    "task_retry": "正在换思路重试…",
    "task_list": "正在查看任务…",
    # 其他
    "artifact_read": "正在调取大段结果…",
    "avatar_perform": "正在表演…",
}

#: 未登记工具的回退文案
_FALLBACK = "正在处理…"

#: 工具 → **语义动作槽位**（G5 动作联动；S53 起不再写死数值索引）。
#:
#: 为什么改：数值索引是模型私有的（对应 TapBody 第 N 个动作）。换到只有单一
#: `Motion` 组的模型（Hotaru）后，原来的 5/7/9 会播到完全无关的动作。
#: 现在只表达"它在看 / 它在回应"，具体播哪个由当前模型清单解析。
_ACTIVITY_MOTION_SLOT: dict[str, str] = {
    "web_search": "thinking",
    "netease_search": "thinking",
    "netease_recommend": "thinking",
    "diary_recall": "thinking",
    "task_plan": "thinking",
    "file_list": "look",
    "file_read": "look",
    "file_write": "look",
    "file_create": "look",
    "file_move": "look",
    "file_delete": "look",
    "app_open": "greet",
    "netease_play": "greet",
}


def activity_outcome(results: list[str]) -> str:
    """只根据已执行工具的明确状态反馈；未知/待选择不伪装成功。"""
    states = []
    for result in results:
        try:
            states.append(str(json.loads(result).get("status", "unknown")))
        except (ValueError, AttributeError, TypeError):
            states.append("unknown")
    if any(s in {"error", "failed", "denied", "blocked"} for s in states):
        return "error"
    if any(s in {"pending", "need_choice", "approval_required", "asked"} for s in states):
        return "waiting"
    if states and all(s in {"ok", "success", "opened", "text"} for s in states):
        return "success"
    return "unknown"


def activity_text(tool: str, args: dict | None = None) -> str:
    """工具 → 进行时文案（未登记回退为「正在处理…」）。

    ``args`` 目前不参与文案（保持简单），保留参数是为了将来能带上"在读哪个文件"。
    """
    del args
    name = str(tool or "").strip()
    if not name:
        return ""
    return _ACTIVITY.get(name, _FALLBACK)


def activity_motion_slot(tool: str) -> str | None:
    """工具 → 语义动作槽位（无建议返回 None，前端按频率决定是否播放）。"""
    return _ACTIVITY_MOTION_SLOT.get(str(tool or "").strip())


def is_long_task_tool(tool: str) -> bool:
    """是否为"需要时间的活"（决定要不要显示状态行，避免一闪而过的提示）。"""
    return str(tool or "").strip() in _ACTIVITY_MOTION_SLOT
