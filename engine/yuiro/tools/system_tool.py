"""Builtin system tools — flat proxies to the system execution backend.

M0/M4: 每个真实工具暴露为一个独立顶层工具，参数 schema 完整，
LLM 直接调用（如 app_open(name="网易云音乐")），无需嵌套转发。
S10: 执行后端可切换（native 默认 / C++ daemon 可选），工具层不感知差异。
S33: 文件写操作（create / write / move / delete）**自动事务化**，并补齐
     `transaction_list` / `transaction_rollback` 两个"撤销"工具 —— 对应 spec
     的 `Approval + Checkpoint + Rollback`。
"""
from __future__ import annotations

import json

from yuiro.tools import BaseTool

# 内部命令行依赖：LLM 偶发把它们当 GUI 应用打开（幻觉，实测出现过把 "ncm-cli"
# 传给 app_open 的情况），在 app_open 层拦截并引导改走网易云工具。
_INTERNAL_TOOL_NAMES = frozenset({
    "ncm-cli", "ncm", "mpv", "node", "npm", "yarn",
})


class SystemActionTool(BaseTool):
    """抽象基类：所有系统操作工具共用 daemon 调用与结果格式化。"""

    # 子类覆盖：daemon 的 tools/call 真实工具名
    daemon_tool: str = ""
    # 子类覆盖：是否需审批（默认需审批，安全红线）
    approval_required: bool = True

    def __init__(self, daemon=None, backend=None) -> None:
        # S10：backend 优先（native / daemon 均可，二者同签名）；daemon= 保留兼容旧装配路径
        self._backend = backend if backend is not None else daemon

    async def _invoke(self, args: dict, task_id: str) -> str:
        if self._backend is None:
            return json.dumps(
                {"status": "pending", "note": "系统执行后端未注入"},
                ensure_ascii=False,
            )
        try:
            result = await self._backend.call(self.daemon_tool, args)
            raw = result.stdout or ""
            payload: dict = {"status": result.status}
            # S38：**结构化结果解包**，不再塞进 stdout 字符串。
            # 此前 file_list / media_control(state) 等返回的 JSON 被 json.dumps 二次转义：
            # 长度翻倍（近一半是 \" 转义符）→ 更容易撞上 tool_result_max_chars → 被截断 →
            # LLM 看不到内容 → 反复重试或编造（实测"列目录"连续两轮都读不到清单，
            # 最终只能含糊收场）。解包后 count/dirs/files 直接可见，长度也减半。
            parsed: object = None
            if raw.lstrip()[:1] in ("{", "["):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = None
            if isinstance(parsed, dict):
                payload.update(parsed)
            elif isinstance(parsed, list):
                payload["items"] = parsed
            elif raw:
                payload["stdout"] = raw
                payload["trace_id"] = result.trace_id  # 仅非结构化结果保留（结构化时是噪音）
            # S33：回传事务 id —— 让 LLM 知道"这次改动可撤销"，之后能响应"恢复刚才的操作"
            txn_id = getattr(result, "txn_id", "")
            if txn_id:
                payload["txn_id"] = txn_id
                payload["rollback_hint"] = "如用户要求撤销，调用 transaction_rollback(txn_id=…)"
            return json.dumps(payload, ensure_ascii=False)
        except NotImplementedError:
            return json.dumps(
                {"status": "pending", "note": "SystemDaemon MCP transport 未接线"},
                ensure_ascii=False,
            )
        except Exception as e:  # noqa: BLE001 — 守护进程异常透出
            return json.dumps({"status": "error", "note": str(e)}, ensure_ascii=False)


class OpenAppTool(SystemActionTool):
    name = "app_open"
    daemon_tool = "app_open"
    approval_required = True
    description = (
        "打开/启动一个软件或应用。只要用户的话语中出现软件名或应用名——"
        "无论是明确命令（\"打开网易云音乐\"、\"帮我开记事本\"）还是单独说出名词"
        "（\"记事本。\"、\"网易云音乐。\"、\"来点音乐\"）——都必须调用本工具，"
        "name 填应用名/可执行名/窗口标题关键词（如 \"网易云音乐\"、\"notepad\"）。"
        "禁止只在文字里说\"帮你打开\"而不调用。"
    )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "要打开的应用名/可执行名/窗口标题关键词，如 '网易云音乐'、'notepad'",
                        },
                    },
                    "required": ["name"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        name = str(args.get("name", "")).strip()
        # 防御 LLM 幻觉：把内部命令行依赖当成应用打开（实测会把 "ncm-cli"
        # 传给 ShellExecute，导致弹出无用控制台窗口）。这类工具没有界面，
        # 也不该被打开——直接引导改走网易云工具。
        if name.lower() in _INTERNAL_TOOL_NAMES:
            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        f"{name} 是幕后的命令行工具，没有界面也不需要打开。"
                        "想听歌请直接说歌名（比如「放首周杰伦的晴天」），"
                        "想要推荐就说「随便放点」「来点音乐」，"
                        "这些我会用音乐能力帮你完成。"
                    ),
                },
                ensure_ascii=False,
            )
        return await self._invoke({"name": name}, task_id)


class FocusAppTool(SystemActionTool):
    name = "app_focus"
    daemon_tool = "app_focus"
    approval_required = True
    description = (
        "把某个已运行的窗口聚焦到前台（如切到网易云音乐窗口）。"
        "name 用可执行文件名或窗口标题关键词。"
    )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "要聚焦的窗口名/标题关键词，如 '网易云音乐'",
                        },
                    },
                    "required": ["name"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        return await self._invoke({"name": str(args.get("name", ""))}, task_id)


class MediaControlTool(SystemActionTool):
    name = "media_control"
    daemon_tool = "media_control"
    approval_required = False  # 切歌/音量属高频无风险动作，免审批
    description = (
        "通过系统媒体会话（SMTC）控制第三方应用的播放：播放/暂停、上一首/下一首、"
        "读取当前播放曲目。适用于**用户自己开着**的播放器（网易云客户端、浏览器等）。"
        "action 取值：play / pause / play_pause / next / prev / now_playing / list_sessions /"
        "volume_up / volume_down / mute。"
        "now_playing 回答'现在放的什么歌'；list_sessions 查看有哪些应用在播放。"
        "注意：① 桌宠自己点播的歌走 netease_control，不要用本工具去控；"
        "② 网易云客户端需在其「设置」里勾选「开启 SMTC」才会注册会话（实测可正常控制）；"
        "③ 音量动作是系统全局音量（系统接口不提供按应用调音量）。"
        "target 缺省时自动匹配网易云音乐；其他播放器请先用 list_sessions 查 AUMID 再指定。"
    )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["play", "pause", "play_pause", "next", "prev",
                                     "now_playing", "list_sessions",
                                     "volume_up", "volume_down", "mute"],
                            "description": (
                                "play 播放 / pause 暂停 / play_pause 播放暂停切换 / "
                                "next 下一首 / prev 上一首 / "
                                "now_playing 读取当前曲目 / list_sessions 列出正在播放的应用"
                            ),
                        },
                        "target": {
                            "type": "string",
                            "description": "目标应用的精确 AUMID（如 cloudmusic.exe），不接受名称片段，"
                                           "缺省自动匹配网易云音乐；"
                                           "其他应用可先 list_sessions 查看 AUMID 再填",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        payload: dict = {"action": str(args.get("action", ""))}
        if target := str(args.get("target", "")).strip():
            payload["target"] = target
        return await self._invoke(payload, task_id)


class FileCreateTool(SystemActionTool):
    name = "file_create"
    daemon_tool = "file_create"
    approval_required = True
    description = "创建一个文件（可写内容）。path 为目标路径，content 为内容。"

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件完整路径"},
                        "content": {"type": "string", "description": "文件内容"},
                    },
                    "required": ["path", "content"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        return await self._invoke(
            {"path": str(args.get("path", "")), "content": str(args.get("content", ""))},
            task_id,
        )


class FileReadTool(SystemActionTool):
    name = "file_read"
    daemon_tool = "file_read"
    approval_required = True
    description = "读取一个文本文件的内容。path 为目标路径。"

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件完整路径"},
                    },
                    "required": ["path"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        return await self._invoke({"path": str(args.get("path", ""))}, task_id)


class FileListTool(SystemActionTool):
    name = "file_list"
    daemon_tool = "file_list"
    approval_required = False  # 只读
    description = (
        "列出一个目录里有什么（子目录 + 每个文件的类型/大小/修改时间）。"
        "**整理文件夹的第一步就是它** —— 先看清有什么，再决定怎么分类。"
        "path 传目录；pattern 可按扩展名过滤（如 '*.pdf'）；recursive=true 递归列出子目录内容。"
        "结果按大小降序（大文件优先看到）。"
    )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "要列出的目录路径"},
                        "pattern": {
                            "type": "string",
                            "description": "文件名过滤（glob，如 '*.pdf'）；默认全部",
                        },
                        "recursive": {
                            "type": "boolean",
                            "description": "是否递归列出子目录里的文件（默认 false）",
                        },
                    },
                    "required": ["path"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        payload: dict = {"path": str(args.get("path", ""))}
        if pattern := str(args.get("pattern") or "").strip():
            payload["pattern"] = pattern
        if args.get("recursive"):
            payload["recursive"] = True
        return await self._invoke(payload, task_id)


class FileWriteTool(SystemActionTool):
    name = "file_write"
    daemon_tool = "file_write"
    approval_required = True
    description = "向已有文件写入内容（覆盖）。path 为目标路径，content 为内容。"

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件完整路径"},
                        "content": {"type": "string", "description": "要写入的内容"},
                    },
                    "required": ["path", "content"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        return await self._invoke(
            {"path": str(args.get("path", "")), "content": str(args.get("content", ""))},
            task_id,
        )


class FileMoveTool(SystemActionTool):
    name = "file_move"
    daemon_tool = "file_move"
    approval_required = True
    description = (
        "移动文件（支持批量）。整理文件夹就用它：paths 一次列出要移动的文件，"
        "dest 填目标目录（移动多个文件时必须是目录）。"
        "一次调用是一个可撤销的事务——用户说\"恢复刚才的操作\"时能整体撤回。"
        "目标已存在时**不覆盖**（安全优先，会报错让你改名）。"
    )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要移动的源文件路径列表（批量整理时一次列全）",
                        },
                        "dest": {
                            "type": "string",
                            "description": "目标目录（移动多个文件时），或完整目标路径（单文件重命名）",
                        },
                    },
                    "required": ["paths", "dest"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        payload: dict = {"dest": str(args.get("dest") or args.get("destination") or "")}
        paths = args.get("paths")
        if paths:
            payload["paths"] = paths if isinstance(paths, list) else [str(paths)]
        elif args.get("path"):
            payload["paths"] = [str(args["path"])]
        return await self._invoke(payload, task_id)


class FileDeleteTool(SystemActionTool):
    name = "file_delete"
    daemon_tool = "file_delete"
    approval_required = True
    description = (
        "删除一个文件（仅文件，不删目录）。删除前会自动备份，"
        "用户说\"恢复刚才的操作\"时可以还原。"
    )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "要删除的文件完整路径"},
                    },
                    "required": ["path"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        return await self._invoke({"path": str(args.get("path", ""))}, task_id)


class TransactionListTool(SystemActionTool):
    name = "transaction_list"
    daemon_tool = ""
    approval_required = False  # 只读
    description = (
        "查看最近的文件操作事务（哪些文件被改/移/删、是否还能撤销）。"
        "用户问\"你刚才改了什么\"\"能撤销吗\"时用它。"
    )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "查看最近几条事务（默认 10）",
                        },
                    },
                    "required": [],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        backend = self._backend
        if backend is None or not hasattr(backend, "list_transactions"):
            return json.dumps(
                {"status": "warn", "note": "当前执行后端不支持文件事务"},
                ensure_ascii=False,
            )
        try:
            limit = int(args.get("limit") or 10)
        except (TypeError, ValueError):
            limit = 10
        view = await backend.list_transactions(limit)
        return json.dumps(view, ensure_ascii=False)


class TransactionRollbackTool(SystemActionTool):
    name = "transaction_rollback"
    daemon_tool = ""
    approval_required = True  # 会改动真实文件，属可逆写
    description = (
        "撤销一次文件操作，把文件恢复到操作前的状态。"
        "用户说\"恢复刚才的操作\"\"把它改回去\"\"撤销\"\"算了别弄了\"时调用。"
        "txn_id 可省略（默认撤销最近一次）；重复撤销会被拒绝。"
        "想先确认有哪些可撤销的事务，可用 transaction_list。"
    )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "txn_id": {
                            "type": "string",
                            "description": "要撤销的事务 id（如 txn-68c1a2-3f9e1b）；省略则撤销最近一次",
                        },
                    },
                    "required": [],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        backend = self._backend
        if backend is None or not hasattr(backend, "rollback_transaction"):
            return json.dumps(
                {"status": "warn", "note": "当前执行后端不支持文件事务"},
                ensure_ascii=False,
            )
        ok, msg = await backend.rollback_transaction(str(args.get("txn_id", "") or "last"))
        return json.dumps(
            {"status": "ok" if ok else "error", "note": msg}, ensure_ascii=False
        )


# 保持旧名兼容：build_agent_loop 仍可 import SystemTool 列表
SYSTEM_TOOLS = [
    OpenAppTool, FocusAppTool, MediaControlTool,
    FileCreateTool, FileReadTool, FileListTool, FileWriteTool,
    FileMoveTool, FileDeleteTool,
    TransactionListTool, TransactionRollbackTool,
]
