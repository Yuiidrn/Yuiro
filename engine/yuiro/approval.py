"""审批门：引擎侧系统操作审批，路由到前端 WS 并等待用户裁决。

流程：
1. AgentLoop 工具执行前调 ``approval_gate(tool, args, task_id)``
2. 向对应 session 的 WS 推送 ``{type:'approval:required', request_id, tool, summary, args}``
3. 前端（原生对话框）裁决后回 ``{type:'approval:resolve', request_id, approved}``
4. ``resolve_approval`` 完成 future；超时/断开视为拒绝
"""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from yuiro.logger import vlog

# session_id -> WebSocket（由 main.py 在连接建立/关闭时注册）
_audio_conns: dict = {}
_control_conns: dict = {}
# request_id -> asyncio.Future[bool]
_pending_approvals: dict[str, asyncio.Future] = {}

APPROVAL_TIMEOUT_S = 120.0  # 审批等待：给用户足够决策时间（原生对话框）

# 审批模式开关：
# - "auto"（默认）：完全开放权限，所有需审批的工具直接通过，不弹窗。
# - "manual"：人工审批，每次需审批的工具都推送弹窗等待用户裁决。
# 由 main.py 启动时按配置（cfg.systemd.approval_mode）设置。
_APPROVAL_MODE: str = "auto"


def set_approval_mode(mode: str) -> None:
    """设置审批模式：auto（自动通过）/ manual（人工审批）。"""
    global _APPROVAL_MODE
    _APPROVAL_MODE = mode


def get_approval_mode() -> str:
    """当前审批模式。"""
    return _APPROVAL_MODE


def register_audio_conn(session_id: str, ws) -> None:
    _audio_conns[session_id] = ws


def get_audio_conn(session_id: str):
    """查询 audio 会话连接（音频回传/事件转发用）。"""
    return _audio_conns.get(session_id)


def unregister_audio_conn(session_id: str) -> None:
    _audio_conns.pop(session_id, None)


async def broadcast_audio_event(event: dict) -> None:
    """向所有已连接的 audio WS 广播事件（如冷启动加载进度）。"""
    dead = []
    for sid, ws in list(_audio_conns.items()):
        try:
            await ws.send_json(event)
        except Exception:  # noqa: BLE001
            dead.append(sid)
    for sid in dead:
        _audio_conns.pop(sid, None)


def register_control_conn(session_id: str, ws) -> None:
    _control_conns[session_id] = ws


def unregister_control_conn(session_id: str) -> None:
    _control_conns.pop(session_id, None)


async def approval_gate(tool: str, args: dict, task_id: str) -> bool:
    """审批门：推送审批请求到对应 session WS，等待前端裁决。

    只有 manual（人工审批）才弹窗；其余所有模式（auto / 历史遗留的 native 等）
    一律直接通过，避免旧配置残留导致"自动审批失效仍弹窗"。
    """
    if _APPROVAL_MODE != "manual":
        return True
    ws = _audio_conns.get(task_id) or _control_conns.get(task_id)
    if ws is None:
        vlog("agent", f"审批被拒：找不到会话 {task_id[:8]} 的连接")
        return False
    request_id = uuid4().hex
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    _pending_approvals[request_id] = future
    vlog(
        "agent",
        f"[{task_id[:8]}] 请求审批: {tool} "
        f"{json.dumps(args, ensure_ascii=False)[:120]}",
    )
    try:
        await ws.send_json({
            "type": "approval:required",
            "request_id": request_id,
            "tool": tool,
            "summary": f"桌宠想执行系统操作：{tool}",
            "args": args,
        })
        return await asyncio.wait_for(future, timeout=APPROVAL_TIMEOUT_S)
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001 — 超时/断开视为拒绝
        vlog("agent", f"[{task_id[:8]}] 审批超时或连接断开，拒绝 {tool}")
        return False
    finally:
        _pending_approvals.pop(request_id, None)


def resolve_approval(request_id: str, approved: bool) -> None:
    """前端裁决回传：完成对应审批 future。"""
    future = _pending_approvals.get(request_id)
    if future is not None and not future.done():
        future.set_result(approved)
        vlog("agent", f"审批结果: request={request_id[:8]} approved={approved}")
    else:
        vlog("agent", f"审批回传未匹配: request={request_id[:8]}")


async def broadcast_control(payload: dict) -> int:
    """向所有 /ws/control 连接广播消息（如 emotion:set）；返回送达连接数。"""
    sent = 0
    for ws in list(_control_conns.values()):
        try:
            await ws.send_json(payload)
            sent += 1
        except Exception:  # noqa: BLE001 — 断开连接静默跳过
            continue
    return sent
