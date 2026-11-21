"""NativeBackend（S10/S33）：系统操作的原生执行后端 + 文件事务。

与 ``SystemDaemonClient`` 同签名（``call(tool, args, dry_run) -> SystemActionResult``），
可被 ``SystemActionTool`` 无差别使用；dry-run 与错误文案与 C++ 实现对齐。

S33（Tool Transaction）：
- 四个文件写操作（``file_create`` / ``file_write`` / ``file_move`` / ``file_delete``）
  **自动事务化** —— 执行前备份原内容、记录可撤销操作、成功后落盘；
- 结果里回传 ``txn_id``，供 LLM 之后说"恢复刚才的操作"时定位（``transaction_rollback``）；
- 读操作、app / media 工具**不产生事务**（无副作用，进事务只是噪音）；
- 事务失败不影响工具本身：备份写不下去时，操作照常执行（只是不可回滚）。
"""
from __future__ import annotations

import asyncio
import json
import os

from yuiro.logger import vlog
from yuiro.native import ops
from yuiro.systemd.client import SystemActionResult
from yuiro.transaction import TxnOp, TxnRecord, TxnStore


def _plan_moves(paths: list[str], dest: str) -> tuple[list[tuple[str, str]], bool]:
    """规划移动的 ``(src, dst)``；返回 ``(moves, dest_is_dir)``。

    ``dest`` 何时视为**目录**（而不是"重命名目标"）：

    - 移动多个文件（一对多必然进目录）；
    - ``dest`` 已是目录，或以分隔符结尾；
    - ``dest`` **没有扩展名**（``D:\\x\\图片`` 显然是想进/建目录）。

    最后一条是 S38 补的：实测 LLM 说"把退宿申请表.xls 移到『表格文件』"时被解释成**重命名**，
    于是一个 .xls 变成了叫「表格文件」的无扩展名文件；模型随后看到"两个没扩展名的文件"
    直接卡住（它没做错，是这里的语义太窄）。判据用"有无扩展名"，简单且符合直觉。
    """
    as_dir = (
        len(paths) > 1
        or os.path.isdir(dest)
        or dest.endswith(("/", "\\"))
        or not os.path.splitext(os.path.basename(dest.rstrip("/\\")))[1]
    )
    moves: list[tuple[str, str]] = []
    for p in paths:
        name = os.path.basename(p.rstrip("/\\"))
        moves.append((p, os.path.join(dest, name) if as_dir else dest))
    return moves, as_dir


class NativeBackend:
    """Python 原生执行后端（不依赖 C++ daemon 与构建工具链）。"""

    name = "native"

    #: 支持的工具（S10 与 C++ ``g_capabilities`` 对齐；S33 增 file_move / file_delete）
    SUPPORTED = frozenset(
        {
            "app_open",
            "app_focus",
            "media_control",
            "file_create",
            "file_read",
            "file_write",
            "file_list",
            "file_move",
            "file_delete",
        }
    )

    def __init__(
        self,
        *,
        file_roots: list[str] | None = None,
        txn_store: TxnStore | None = None,
        txn_enabled: bool = True,
    ) -> None:
        # 文件操作允许根目录（默认仅当前工作目录 = engine/，与 daemon 的 allowed_base 一致）
        self._roots = list(file_roots) if file_roots else ["."]
        # S33：事务存储（默认 <cwd>/.yuiro/txn；构造无副作用，目录懒创建）
        if txn_store is not None:
            self._txn: TxnStore | None = txn_store
        else:
            self._txn = TxnStore() if txn_enabled else None

    @property
    def file_roots(self) -> list[str]:
        return list(self._roots)

    @property
    def is_running(self) -> bool:
        """兼容 SystemDaemonClient 的探活接口（native 无进程，恒可用）。"""
        return True

    @property
    def txn_store(self) -> TxnStore | None:
        """事务存储（供调试台 / 测试直接检查）。"""
        return self._txn

    async def connect(self) -> None:
        """兼容接口：native 无需连接。"""

    async def close(self) -> None:
        """兼容接口：native 无需关闭。"""

    # ---- 事务 API（供 transaction_list / transaction_rollback 工具）-------------
    async def rollback_transaction(self, txn_id: str = "last") -> tuple[bool, str]:
        """撤销一个已提交的文件事务（``last`` = 最近一次）。"""
        if self._txn is None:
            return False, "文件事务未启用（[transaction].enabled = false）"
        ok, msg = await asyncio.to_thread(self._txn.rollback, txn_id)
        vlog("txn", f"[回滚] {msg}")
        return ok, msg

    async def list_transactions(self, limit: int = 10) -> dict:
        """事务视图（调试台 / 工具返回）。"""
        if self._txn is None:
            return {"status": "warn", "note": "文件事务未启用", "total": 0, "recent": []}
        return await asyncio.to_thread(self._txn.to_dict, limit=max(1, int(limit)))

    # ---- 主入口 -------------------------------------------------------------
    async def call(self, tool: str, args: dict, dry_run: bool = False) -> SystemActionResult:
        trace_id = ops.new_trace_id()
        args = args or {}

        def _r(status: str, stdout: str, txn: TxnRecord | None = None) -> SystemActionResult:
            return SystemActionResult(
                trace_id=trace_id,
                status=status,
                stdout=stdout,
                txn_id=txn.id if txn is not None else "",
            )

        if tool not in self.SUPPORTED:
            return _r("error", f"原生后端不支持的工具: {tool}")

        # ---- 应用 -----------------------------------------------------------
        if tool == "app_open":
            name = str(args.get("name") or args.get("app") or "").strip()
            if not name:
                return _r("error", '参数错误：需要 {"name": "<应用或路径>"}')
            if dry_run:
                return _r("dry-run", f'dry-run：将打开 "{ops.resolve_app(name)}"')
            status, out = await asyncio.to_thread(ops.open_app, name)
            return _r(status, out)

        if tool == "app_focus":
            name = str(args.get("name", "")).strip()
            if not name:
                return _r("error", '参数错误：需要 {"name": "<窗口标题关键词>"}')
            if dry_run:
                return _r("dry-run", f'dry-run：将聚焦窗口 "{name}"')
            status, out = await asyncio.to_thread(ops.focus_app, name)
            return _r(status, out)

        # ---- 媒体（不产生事务：无文件副作用）----------------------------------
        if tool == "media_control":
            action = str(args.get("action", "")).strip()
            target = str(args.get("target", "")).strip()
            if not action:
                return _r(
                    "error",
                    '参数错误：需要 {"action": '
                    '"play|pause|play_pause|next|prev|now_playing|list_sessions|'
                    'stop|open_song|volume_up|volume_down|mute"}',
                )
            if action not in ops.MEDIA_ACTIONS:
                return _r("error", f'未知 action: {action}（可用: {"|".join(ops.MEDIA_ACTIONS)}）')
            if action in ('client_state', 'client_launch', 'client_search', 'client_favorite', 'client_recommend'):
                if target.casefold() != 'cloudmusic.exe':
                    return _r('denied', '客户端连接需要明确 cloudmusic.exe 目标')
                if dry_run:
                    return _r('dry-run', '仅本机网易云连接，不读取账号或其他播放器')
                from . import netease_client
                try:
                    if action == 'client_favorite':
                        return _r('ok', json.dumps(await netease_client.favorite(str(args.get('song_id') or ''), args.get('desired')), ensure_ascii=False))
                    if action == 'client_recommend':
                        return _r('ok', json.dumps(await netease_client.recommend(int(args.get('limit',6))), ensure_ascii=False))
                    if action == 'client_search':
                        return _r('ok', json.dumps(await netease_client.search(str(args.get('keyword') or ''), int(args.get('limit',8))), ensure_ascii=False))
                    if action == 'client_launch':
                        await asyncio.to_thread(netease_client.launch_if_closed)
                        return _r('ok', '已启动本机网易云连接，尚未确认播放')
                    return _r('ok', json.dumps(await netease_client.state(), ensure_ascii=False))
                except Exception as exc:
                    return _r('error', str(exc))
            if action == "open_song":
                if target.casefold() != "cloudmusic.exe":
                    return _r("denied", "原版定位仅允许显式 cloudmusic.exe 目标，未执行")
                song_id = str(args.get("song_id") or "")
                if dry_run:
                    return _r("dry-run", f"dry-run：向网易云官方客户端请求定位 {song_id}，不保证起播")
                status, out = await asyncio.to_thread(ops.open_netease_song, song_id)
                return _r(status, out)
            if dry_run:
                if action in ops.SMTC_ACTIONS:
                    return _r("dry-run", f"dry-run：将通过 SMTC 对目标会话执行 {action}")
                return _r("dry-run", f"dry-run：将按目标 {target or '默认候选'} 请求 {action}，不使用全局播放键回退")
            expected = str(args.get("expected_title") or "")
            status, out = (await asyncio.to_thread(ops.media_control, action, target, expected)
                           if expected else await asyncio.to_thread(ops.media_control, action, target))
            return _r(status, out)

        # ---- 文件：移动（批量语义 → 一个事务）---------------------------------
        if tool == "file_move":
            return await self._file_move(args, dry_run, _r)

        # ---- 文件：其余（read 无事务 / create·write·delete 事务化）------------
        path = str(args.get("path", "")).strip()
        if not path:
            if dry_run:
                return _r("dry-run", "dry-run：将操作文件（缺少 path 参数）")
            return _r("error", '参数错误：需要 {"path": "<路径>"}')
        content = str(args.get("content", ""))

        if tool == "file_read":
            if dry_run:
                if not ops.path_allowed(path, self._roots):
                    return _r("denied", f"路径不在允许目录内，已拒绝: {path}")
                return _r("dry-run", f'dry-run：将读取文件 "{path}"')
            status, out = await asyncio.to_thread(ops.file_read, path, self._roots)
            return _r(status, out)

        # S38：列目录 —— 整理类请求的第一步（此前没有该能力，"帮我整理文件夹"无从起步）
        if tool == "file_list":
            pattern = str(args.get("pattern") or "*").strip() or "*"
            recursive = bool(args.get("recursive"))
            if dry_run:
                if not ops.path_allowed(path, self._roots):
                    return _r("denied", f"路径不在允许目录内，已拒绝: {path}")
                return _r("dry-run", f'dry-run：将列出目录 "{path}"（pattern={pattern}）')
            status, out = await asyncio.to_thread(
                ops.file_list, path, self._roots, pattern=pattern, recursive=recursive
            )
            return _r(status, out)

        verb = {"file_create": "创建", "file_write": "写入", "file_delete": "删除"}.get(
            tool, "操作"
        )
        if dry_run:
            if not ops.path_allowed(path, self._roots):
                return _r("denied", f"路径不在允许目录内，已拒绝: {path}")
            return _r("dry-run", f'dry-run：将{verb}文件 "{path}"')

        return await self._write_with_txn(tool, path, content, _r)

    # ---- 事务化执行 ---------------------------------------------------------
    async def _write_with_txn(self, tool: str, path: str, content: str, _r) -> SystemActionResult:
        """create / write / delete 共用：备份 → 执行 → 提交（失败则丢弃备份）。"""
        txn = self._txn.begin(tool) if self._txn is not None else None
        # 删除也需要备份（回滚要还原内容）；create 的目标若已存在则等价于覆盖
        existed = os.path.isfile(path)
        backup = ""
        if txn is not None and existed:
            backup = await asyncio.to_thread(self._txn.backup, txn, path)

        if tool == "file_create":
            status, out = await asyncio.to_thread(ops.file_create, path, content, self._roots)
        elif tool == "file_write":
            status, out = await asyncio.to_thread(ops.file_write, path, content, self._roots)
        else:
            status, out = await asyncio.to_thread(ops.file_delete, path, self._roots)

        if tool == "file_delete":
            kind = "delete"
        else:
            kind = "overwrite" if existed else "create"
        txn = self._finish_txn(txn, status, TxnOp(kind=kind, path=path, backup=backup, detail=out))
        return _r(status, out, txn)

    async def _file_move(self, args: dict, dry_run: bool, _r) -> SystemActionResult:
        """批量移动：**一次调用 = 一个事务**（"整理下载夹"可一次全撤销）。"""
        raw = args.get("paths") or args.get("path") or []
        if isinstance(raw, str):
            raw = [raw]
        paths = [str(p).strip() for p in raw if str(p or "").strip()]
        dest = str(
            args.get("dest") or args.get("destination") or args.get("target") or ""
        ).strip()
        if not paths or not dest:
            return _r(
                "error",
                '参数错误：需要 {"paths": ["<源路径>", …], "dest": "<目标目录或路径>"}',
            )
        # 多个文件时 dest 是目录（不存在则创建 —— "整理下载夹 → 新建图片目录"是主场景）；
        # 只有把文件当目录用（dest 已是一个文件）才拒绝
        if len(paths) > 1 and os.path.isfile(dest):
            return _r("error", f'移动多个文件时 dest 必须是目录，但 "{dest}" 是一个文件')

        moves, dest_is_dir = _plan_moves(paths, dest)
        # 预检（越界 / 源缺失 / 目标冲突）：事务语义是"要么成批，要么不动手"
        for src, dst in moves:
            if not ops.path_allowed(src, self._roots) or not ops.path_allowed(dst, self._roots):
                return _r("denied", f"路径不在允许目录内，已拒绝: {src} → {dst}")
            if not os.path.isfile(src):
                return _r("error", f"源文件不存在: {src}")
            if os.path.exists(dst):
                return _r("error", f"目标已存在（不覆盖）: {dst}")

        if dry_run:
            preview = "；".join(f"{s} → {d}" for s, d in moves)
            return _r("dry-run", f"dry-run：将移动 {len(moves)} 项：{preview}")

        txn = self._txn.begin("file_move") if self._txn is not None else None
        # 目标目录若由本次操作创建 → 记一条 mkdir（放在 ops 首位），回滚时逆序最后撤销它，
        # 若已空则删除 —— 否则"整理完再撤销"会在磁盘上留下一个空文件夹（冒烟实测）。
        if txn is not None and dest_is_dir and not os.path.isdir(dest):
            txn.ops.append(TxnOp(kind="mkdir", path=dest, detail="新建目标目录"))
        done: list[str] = []
        failed = ""
        for src, dst in moves:
            status, out = await asyncio.to_thread(ops.file_move, src, dst, self._roots)
            if status != "ok":
                failed = out
                break
            done.append(out)
            if txn is not None:
                txn.ops.append(TxnOp(kind="move", path=dst, src=src, detail=out))

        if failed:
            # 部分成功：已移动的如实记录（仍可回滚），并说明中止原因
            note = f"已移动 {len(done)}/{len(moves)} 项后中止：{failed}"
            if txn is not None and txn.ops:
                self._txn.commit(txn)
                return _r("error", note, txn)
            if txn is not None:
                self._txn.discard(txn)
            return _r("error", note)

        if txn is not None:
            self._txn.commit(txn)
            vlog("txn", f"[事务] {txn.summary()}")
        return _r("ok", f"已移动 {len(done)} 项：" + "；".join(done), txn)

    def _finish_txn(self, txn: TxnRecord | None, status: str, op: TxnOp) -> TxnRecord | None:
        """成功 → 记录操作并落盘；失败 → 丢弃备份（不留下无法对应的事务）。"""
        if txn is None or self._txn is None:
            return None
        if status != "ok":
            self._txn.discard(txn)
            return None
        txn.ops.append(op)
        self._txn.commit(txn)
        vlog("txn", f"[事务] {txn.summary()}")
        return txn
