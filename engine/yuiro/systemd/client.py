"""SystemDaemon MCP client — stdio newline-JSON transport (M4).

传输层用 ``subprocess.Popen`` + 线程内同步读写（经 asyncio.to_thread 桥接），
**不依赖 asyncio 子进程 API**——任何事件循环（含 Selector/ComfyUI 环境）
都能 spawn C++ daemon，规避 Windows 上 create_subprocess_exec 的
NotImplementedError（Proactor 策略问题）。
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from dataclasses import dataclass, field

from yuiro.config import SystemDaemonConfig
from yuiro.logger import vlog


@dataclass
class SystemActionResult:
    trace_id: str
    status: str  # ok | denied | error | dry-run
    approval_required: bool = False
    approval_request_id: str | None = None
    stdout: str = ""
    artifacts: list[str] = field(default_factory=list)
    #: S33：文件写操作产生的事务 id（可回滚；读操作与 app/media 工具为空）
    txn_id: str = ""


@dataclass
class ToolDef:
    name: str
    description: str
    approval_required: bool
    dry_run: bool


class SystemDaemonClient:
    """stdio newline-JSON MCP 客户端：spawn C++ daemon，逐行读写请求/响应。

    传输契约与 ``system-daemon/src/mcp/server_stdio.cpp`` 对齐：
    请求 {jsonrpc, id, method, params}，响应回显 id 并带 result/error。
    """

    _CALL_TIMEOUT_S = 60.0

    def __init__(self, cfg: SystemDaemonConfig) -> None:
        self._cfg = cfg
        self._tools: list[ToolDef] = []
        self._proc: subprocess.Popen | None = None
        self._io_lock = threading.Lock()  # 保护 stdin/stdout 读写（单请求串行）
        self._id = 0

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def connect(self) -> None:
        """spawn daemon 进程并拉取工具清单；失败仅记日志不抛（上层可降级）。"""
        if self.is_running:
            return
        vlog("systemd", f"启动 SystemDaemon: {' '.join(self._cfg.command)}")
        try:
            # 同步 Popen：与事件循环无关，任何 Python 环境都可用。
            self._proc = subprocess.Popen(
                self._cfg.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=False,
            )
        except FileNotFoundError:
            vlog("systemd", f"SystemDaemon 可执行文件不存在: {self._cfg.command[0]}（M4 需先构建）")
            self._proc = None
            return
        except Exception as exc:  # noqa: BLE001 — daemon 启动失败不阻断引擎
            vlog("systemd", f"SystemDaemon 启动失败: {exc}")
            self._proc = None
            return
        try:
            tools = await self.list_tools()
            self._tools = tools
            vlog(
                "systemd",
                f"SystemDaemon 已连接，暴露 {len(tools)} 个工具: {[t.name for t in tools]}",
            )
        except Exception as exc:  # noqa: BLE001 — 连接失败不阻断引擎
            vlog("systemd", f"SystemDaemon tools/list 失败: {exc}")

    async def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                await asyncio.to_thread(proc.wait, 3)
            except Exception:  # noqa: BLE001 — 超时则强杀
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass

    def _roundtrip(self, req: dict) -> dict:
        """同步往返：写一行请求、读一行响应（在 to_thread 中执行）。"""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            raise ConnectionError("SystemDaemon 未运行")
        data = (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8")
        with self._io_lock:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(data)
            proc.stdin.flush()
            line = proc.stdout.readline()
        if not line:
            raise ConnectionError("SystemDaemon 输出已关闭")
        resp = json.loads(line.decode("utf-8"))
        if "error" in resp:
            raise RuntimeError(f"SystemDaemon error: {resp['error']}")
        return resp.get("result", {})

    async def _request(self, method: str, params: dict) -> dict:
        if not self.is_running:
            raise ConnectionError("SystemDaemon 未运行")
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        return await asyncio.wait_for(
            asyncio.to_thread(self._roundtrip, req), timeout=self._CALL_TIMEOUT_S
        )

    async def list_tools(self) -> list[ToolDef]:
        result = await self._request("tools/list", {})
        return [
            ToolDef(
                name=str(t.get("name", "")),
                description=str(t.get("description", "")),
                approval_required=bool(t.get("approval_required", False)),
                dry_run=bool(t.get("dry_run", False)),
            )
            for t in result.get("tools", [])
        ]

    async def call(self, tool: str, args: dict, dry_run: bool = False) -> SystemActionResult:
        # 懒连接：daemon 未运行（lifespan connect 失败/进程退出/--reload 重载后）
        # 时，工具调用前自动尝试拉起，避免"SystemDaemon 未运行"。
        if not self.is_running:
            await self.connect()
        if not self.is_running:
            raise ConnectionError("SystemDaemon 未运行")
        result = await self._request(
            "tools/call", {"name": tool, "arguments": args, "dry_run": dry_run}
        )
        return SystemActionResult(
            trace_id=str(result.get("trace_id", "")),
            status=str(result.get("status", "error")),
            approval_required=bool(result.get("approval_required", False)),
            approval_request_id=result.get("approval_request_id"),
            stdout=str(result.get("stdout", "")),
            artifacts=[str(a) for a in result.get("artifacts", [])],
        )
