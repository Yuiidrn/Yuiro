"""网易云播放器：引擎自管 mpv + IPC 控制（2026-09-12 定稿）。

为什么自己管播放器（而不是用 ncm-cli 的 daemon）：
    ncm-cli 0.1.7 在登录状态下，daemon 收到 play 后能取到 playUrl、能上报播放
    记录，却**始终不启动播放器进程**（实测 mpv 进程恒为 0、IPC 管道从未出现），
    且无任何错误日志。故播放这一段改由引擎完全接管：
        api.py（自签名取播放地址） → player.py（mpv 播放 + 控制）
    个性化能力不受影响——数据仍走同一套官方开放平台接口。

实现要点：
- mpv 常驻（--idle），控制通道为命名管道 \\\\.\\pipe\\yuiro-mpv（JSON 行协议）；
  Windows 上用 ctypes 直接读写管道（已验证可用，无需第三方依赖）。
- 播放列表交给 **mpv 原生 playlist**（loadfile ... append）：顺序播放、上一首/
  下一首、播放结束自动续播都由 mpv 负责，引擎不再自己维护队列。
- 窗口沿用项目自带的 mpv.conf（force-window=yes，右下角小窗 + 底部控制条），
  因此"能听到 + 能看到界面"两个诉求同时满足，且可手动拖进度。
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from itertools import count
from pathlib import Path

log = logging.getLogger(__name__)

# 控制通道按平台选型：Windows 命名管道 / POSIX（macOS、Linux）Unix domain socket。
# mpv 的 --input-ipc-server= 两端都支持，只是客户端连接方式不同。
_IS_WINDOWS = os.name == "nt"
_PIPE = r"\\.\pipe\yuiro-mpv" if _IS_WINDOWS else "/tmp/yuiro-mpv.sock"
_mpv_proc: subprocess.Popen | None = None

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_kernel32 = ctypes.windll.kernel32 if _IS_WINDOWS else None
if _kernel32 is not None:  # Windows 专属：wintypes 在非 Windows 上 import 即报错
    from ctypes import wintypes

    _kernel32.CreateFileW.restype = wintypes.HANDLE


def mpv_exe() -> str:
    """定位 mpv 可执行文件（优先 YUIRO_MPV_DIR，其次 PATH）。"""
    d = os.environ.get("YUIRO_MPV_DIR", "").strip()
    if d:
        p = Path(d) / ("mpv.exe" if _IS_WINDOWS else "mpv")
        if p.exists():
            return str(p)
    found = shutil.which("mpv")
    return found or ""


# 常驻 IPC 连接句柄。
# ★ 必须复用同一条连接：实测每次新建/关闭连接时约有一半的命令收不到响应
#   （mpv 侧 accept 与客户端写入存在竞争），表现为"暂停后状态读回旧值"。
# Windows 存 ctypes HANDLE（int），POSIX 存已连接的 socket 对象。
_ipc_handle = None
_ipc_lock = threading.RLock()
_ipc_ids = count(1)
_ipc_buffer = b""


def _open_ipc_handle():
    global _ipc_handle
    with _ipc_lock:
        if _ipc_handle is not None:
            return _ipc_handle
        if _IS_WINDOWS:
            handle = _kernel32.CreateFileW(
                _PIPE, _GENERIC_READ | _GENERIC_WRITE, 0, None, _OPEN_EXISTING, 0, None
            )
            invalid = wintypes.HANDLE(-1).value
            if not handle or handle == invalid:
                return None
            _ipc_handle = handle
            return handle
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(_PIPE)
        except OSError:
            return None
        sock.settimeout(None)
        _ipc_handle = sock
        return sock


def _close_ipc_handle() -> None:
    global _ipc_handle, _ipc_buffer
    with _ipc_lock:
        if _ipc_handle is not None:
            try:
                if _IS_WINDOWS:
                    _kernel32.CloseHandle(_ipc_handle)
                else:
                    _ipc_handle.close()
            except Exception as exc:  # noqa: BLE001
                log.debug("关闭 mpv IPC 句柄失败：%s", type(exc).__name__)
            _ipc_handle = None
        _ipc_buffer = b""


def pipe_alive() -> bool:
    """mpv 的控制管道是否可用（等价于"播放器在运行"）。

    ★ 用「实际打开/复用管道句柄」判定，而不是 os.path.exists：后者对 Windows
      命名管道不可靠（实测 mpv 已就绪却返回 False，导致重复拉起多个 mpv）。
    """
    return _open_ipc_handle() is not None


def ensure_mpv(volume: int = 70) -> bool:
    """确保 mpv 常驻（幂等）。"""
    global _mpv_proc
    if pipe_alive():
        return True
    _close_ipc_handle()  # 旧句柄可能指向已退出的实例
    exe = mpv_exe()
    if not exe:
        log.warning("找不到 mpv.exe（YUIRO_MPV_DIR=%s）", os.environ.get("YUIRO_MPV_DIR"))
        return False
    args = [
        exe,
        "--no-video",                      # 纯音频（窗口由 portable_config 的 force-window 提供）
        f"--input-ipc-server={_PIPE}",
        "--idle=yes",
        "--keep-open=no",
        f"--volume={volume}",
        "--title=Yuiro 音乐播放",
    ]
    kw: dict = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
    # ★ 不能加 CREATE_NO_WINDOW：mpv 需要创建可见窗口（实测加了会导致无窗口）
    try:
        _mpv_proc = subprocess.Popen(args, **kw)
    except Exception as exc:  # noqa: BLE001
        log.warning("mpv 启动失败: %s", exc)
        return False
    # 等管道就绪（mpv 初始化 + 绑定 IPC 约 1~3 秒）
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if pipe_alive():
            log.info("mpv 已就绪（pid=%s）", _mpv_proc.pid)
            return True
        time.sleep(0.25)
    log.warning("mpv 启动后 IPC 管道未就绪")
    return False


async def ensure_mpv_async(volume: int = 70) -> bool:
    return await asyncio.to_thread(ensure_mpv, volume)


# ---------------------------------------------------------------------------
# IPC（JSON 行协议；Windows 命名管道 / POSIX Unix socket）
# ---------------------------------------------------------------------------
def _send_ipc_sync(commands: list[list], timeout_s: float = 3.0) -> list[dict]:
    """连一次控制通道，发送若干命令并收集响应。

    ★ Windows 下读响应前必须先用 PeekNamedPipe 探测是否有数据：管道以阻塞模式
      打开时 ReadFile 会一直挂住，导致响应丢失/错位（实测"暂停成功却仍报
      playing"、"音量设 35 却读回 70"都源于此）；POSIX 侧用 socket 超时等效实现。
    """
    # to_thread 调用共用常驻连接，必须串行化整次读写，不能只锁写入。
    with _ipc_lock:
        return _send_ipc_locked(commands, timeout_s)


def _consume_reply_lines(
    chunk: bytes, expected: dict[int, int], results: list[dict]
) -> None:
    """把收到的字节追加进缓冲区，按行解析并回填批内编号。"""
    global _ipc_buffer
    _ipc_buffer += chunk
    while b"\n" in _ipc_buffer:
        line, _ipc_buffer = _ipc_buffer.split(b"\n", 1)
        try:
            reply = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(reply, dict):
            continue
        request_id = reply.get("request_id")
        if type(request_id) is not int or request_id not in expected:
            continue  # 事件、重复和迟到响应不算本次指令确认
        # 保留 get_state 使用的批内编号，不把传输层递增编号泄露给调用方。
        results.append({**reply, "request_id": expected.pop(request_id)})
    if len(_ipc_buffer) > 1024 * 1024:
        raise OSError("mpv IPC line exceeded limit")


def _pump_windows(handle: int, payloads: list[bytes],
                  expected: dict[int, int], results: list[dict], timeout_s: float) -> None:
    for payload in payloads:
        written = wintypes.DWORD(0)
        ok = _kernel32.WriteFile(handle, payload, len(payload),
                                 ctypes.byref(written), None)
        if not ok or written.value != len(payload):
            raise OSError("WriteFile failed")
    deadline = time.monotonic() + timeout_s
    buf = ctypes.create_string_buffer(65536)
    while expected and time.monotonic() < deadline:
        avail = wintypes.DWORD(0)
        peeked = _kernel32.PeekNamedPipe(
            handle, None, 0, None, ctypes.byref(avail), None
        )
        if not peeked:
            raise OSError("PeekNamedPipe failed")
        if avail.value == 0:
            time.sleep(0.02)
            continue
        read = wintypes.DWORD(0)
        ok = _kernel32.ReadFile(handle, buf, 65536, ctypes.byref(read), None)
        if not ok or read.value == 0:
            raise OSError("ReadFile failed")
        _consume_reply_lines(buf.raw[:read.value], expected, results)


def _pump_posix(sock, payloads: list[bytes],
                expected: dict[int, int], results: list[dict], timeout_s: float) -> None:
    for payload in payloads:
        sock.sendall(payload)
    deadline = time.monotonic() + timeout_s
    while expected and time.monotonic() < deadline:
        # 短超时轮询：既能让出 GIL，也能在 deadline 到点后干净退出
        sock.settimeout(max(0.02, min(0.2, deadline - time.monotonic())))
        try:
            chunk = sock.recv(65536)
        except TimeoutError:
            continue
        if not chunk:
            raise OSError("mpv IPC 连接已关闭")
        _consume_reply_lines(chunk, expected, results)
    sock.settimeout(None)


def _send_ipc_locked(commands: list[list], timeout_s: float) -> list[dict]:
    handle = _open_ipc_handle()
    if handle is None:
        return []
    results: list[dict] = []
    expected: dict[int, int] = {}
    payloads: list[bytes] = []
    for idx, cmd in enumerate(commands):
        request_id = next(_ipc_ids)
        expected[request_id] = idx
        payloads.append(
            (json.dumps({"command": cmd, "request_id": request_id}) + "\n").encode("utf-8")
        )
    try:
        if _IS_WINDOWS:
            _pump_windows(handle, payloads, expected, results, timeout_s)
        else:
            _pump_posix(handle, payloads, expected, results, timeout_s)
        if expected:
            log.warning("mpv IPC 响应不完整（缺少 %d 条），不将其视为已停止", len(expected))
        return results
    except OSError:
        # 连接失效（mpv 重启/关闭）→ 丢弃句柄，下次调用自动重连
        _close_ipc_handle()
        return []


async def _ipc(commands: list[list], timeout_s: float = 3.0) -> list[dict]:
    return await asyncio.to_thread(_send_ipc_sync, commands, timeout_s)


# ---------------------------------------------------------------------------
# 播放与控制
# ---------------------------------------------------------------------------
async def play_urls(urls: list[str], titles: list[str] | None = None) -> bool:
    """把一组直链交给 mpv 播放（第一首立即播，其余进 mpv 原生播放列表顺序续播）。

    S36：把歌名作为 ``force-media-title`` 传给 mpv —— 否则 ``media-title`` 会退化成
    直链的文件名（形如 ``3ac3424e….mp3``），**用户和 LLM 都不知道在放什么**
    （实测日志：``"title": "3ac3424e4c7fd1948e8bb2a01025cb12.mp3"``）。
    """
    if not urls:
        return False
    if not await ensure_mpv_async():
        return False
    # ★ 不要先发 stop：第一条 loadfile 的 replace 模式本身就会替换整个播放列表，
    #   而额外 stop 会让 mpv 进入 idle 并可能吞掉紧接着的 loadfile（实测播放列表始终为 0）。
    #
    # ★★ 但**必须清掉可能残留的 pause**（S45）：`pause` 是 mpv 的**全局属性**，
    #   `loadfile` **不会**重置它。于是只要此前暂停过（用户说过"暂停"、或系统媒体键
    #   暂停过），之后每次 loadfile 完都停在 paused ——
    #   症状恰好是"日志里 played / 曲目信息都完整，播放器却没声音"，极难归因。
    #   顺带一个好处：清掉后通常 1 秒内就变成 playing，下面的等待可以提前返回。
    cmds: list[list] = [["set_property", "pause", False]]
    for i, u in enumerate(urls):
        flags = "replace" if i == 0 else "append"
        title = (titles[i] if titles and i < len(titles) else "") or ""
        if title:
            # loadfile <url> <flags> <index> <options>：第 4 个参数是 per-file options
            cmds.append(["loadfile", u, flags, "-1", f"force-media-title={title}"])
        else:
            cmds.append(["loadfile", u, flags])
    res = await _ipc(cmds, timeout_s=6.0)
    # 老版本 mpv 不认 per-file options → 退回不带标题重发（至少保证能播）
    if titles and any(
        isinstance(r, dict) and r.get("error") not in (None, "success") for r in res
    ):
        from yuiro.logger import vlog

        vlog("netease", "mpv 不接受 force-media-title，退回不带歌名播放（media-title 将是文件名）")
        await _ipc(
            [
                ["loadfile", u, "replace" if i == 0 else "append"]
                for i, u in enumerate(urls)
            ],
            timeout_s=6.0,
        )
    # 等它真正出声（ffmpeg 拉流需要一点时间）
    for _ in range(10):
        await asyncio.sleep(1.0)
        st = await get_state()
        if st.get("status") == "playing":
            return True
    return False


async def control(action: str, level: int | None = None) -> dict:
    """播放控制。action: pause/resume/next/prev/stop/volume/seek/state。"""
    if action == "state":
        # S36：主状态查询精简掉了 volume（见 _STATE_KEYS 的注释），这里单独补一次
        st = await get_state()
        res = await _ipc([["get_property", "volume"]])
        if res and isinstance(res[0], dict) and res[0].get("error") == "success":
            st["volume"] = res[0].get("data")
        return st
    if not await ensure_mpv_async():
        return {"status": "error", "message": "播放器没能启动"}

    if action == "pause":
        command = ["set_property", "pause", True]
    elif action == "resume":
        command = ["set_property", "pause", False]
    elif action == "next":
        command = ["playlist-next", "weak"]
    elif action == "prev":
        command = ["playlist-prev", "weak"]
    elif action == "stop":
        command = ["stop"]
    elif action == "volume":
        command = ["set_property", "volume", max(0, min(100, int(level or 70)))]
    elif action == "seek":
        command = ["seek", int(level or 0), "absolute"]
    else:
        return {"status": "error", "message": f"不支持的动作: {action}"}
    replies = await _ipc([command])
    if not any(r.get("request_id") == 0 and r.get("error") == "success" for r in replies):
        return {"status": "error", "message": "播放器未确认控制指令，请稍后重试",
                "state": await get_state()}
    await asyncio.sleep(0.6)
    st = await get_state()
    if st.get("status") == "unknown" or (action == "stop" and st.get("status") != "stopped"):
        return {"status": "error", "message": "播放器控制结果未确认，请稍后重试", "state": st}
    if action == "volume":  # 音量单独回读（主状态查询已精简掉该字段）
        res = await _ipc([["get_property", "volume"]])
        if res and res[0].get("error") == "success":
            st["volume"] = res[0].get("data")
    return {"status": "ok", "action": action, "state": st}


async def set_mode(mode: str) -> dict:
    """设置播放模式。

    mode: sequential 顺序 / repeat_all 列表循环 / repeat_one 单曲循环 / shuffle 随机
    （底层用 mpv 的 loop-file / loop-playlist / playlist-shuffle 实现）
    """
    if not await ensure_mpv_async():
        return {"status": "error", "message": "播放器没能启动"}
    seq = [["set_property", "loop-file", "no"], ["set_property", "loop-playlist", "no"]]
    if mode == "repeat_one":
        cmds = [["set_property", "loop-file", "inf"], ["set_property", "loop-playlist", "no"]]
    elif mode == "repeat_all":
        cmds = [["set_property", "loop-file", "no"], ["set_property", "loop-playlist", "inf"]]
    elif mode == "shuffle":
        cmds = seq + [["playlist-shuffle"]]
    elif mode == "sequential":
        cmds = seq + [["set_property", "playlist-shuffle", "no"]]
    else:
        return {"status": "error", "message": f"不支持的播放模式: {mode}"}
    await _ipc(cmds, timeout_s=3.0)
    return {"status": "ok", "mode": mode, "state": await get_state()}


async def seek(seconds: float, relative: bool = False) -> dict:
    """跳转播放进度（relative=True 表示快进/快退若干秒）。

    ★ 必须先校验"确实有歌在播"（2026-09-15）：歌放完后 mpv 会进入 idle
      （playlist-pos=-1），此时 seek 无对象、静默无效；若不拦截，LLM 拿到
      空洞的 ok 就会谎报"已跳到 X 分 Y 秒"，用户端体感是"没跳转"。
      同时按 duration 钳制目标位置，免得跳到超出时长被 mpv 拒绝。
    """
    if not await ensure_mpv_async():
        return {"status": "error", "message": "播放器没能启动"}
    st = await get_state()
    if st.get("status") == "stopped":
        return {
            "status": "error",
            "message": "现在没有在播放歌曲，没法跳转进度（可以让用户先点一首）",
            "state": st,
        }
    if st.get("duration", 0) <= 0:
        return {
            "status": "error",
            "message": "歌曲还在加载中，稍等一两秒再跳进度",
            "state": st,
        }
    if relative:
        target = max(0.0, min(float(seconds) + st.get("position", 0.0), st["duration"]))
        mode = "absolute"
    else:
        target = max(0.0, min(float(seconds), st["duration"]))
        mode = "absolute"
    await _ipc([["seek", target, mode]])
    await asyncio.sleep(0.4)
    after = await get_state()
    return {"status": "ok", "state": after, "seeked_to": target}


async def enqueue(urls: list[str], next_up: bool = False) -> int:
    """把歌曲追加进播放列表（不影响当前播放）。next_up=True 插到下一首位置。"""
    if not urls or not await ensure_mpv_async():
        return 0
    mode_flag = "insert-next" if next_up else "append"
    await _ipc([["loadfile", u, mode_flag] for u in urls], timeout_s=5.0)
    return len(urls)


async def clear_queue() -> None:
    """清空播放列表（停止播放）。"""
    if await asyncio.to_thread(pipe_alive):
        await _ipc([["playlist-clear"], ["stop"]])


# 精简到 6 个（实测查太多属性时个别响应会在超时内收不齐，
# 导致 media-title 缺失被误判成 stopped）
_STATE_KEYS = ("pause", "media-title", "time-pos", "duration",
               "playlist-count", "playlist-pos")


async def get_state() -> dict:
    """读取当前播放状态（供桌宠口播与工具回传）。

    ★ 一次连接批量发命令（避免频繁连管道触发 mpv 连接竞态），按 request_id
      回填；并对"部分响应缺失"做容错——只要有曲目名或播放列表非空，
      就不能判 stopped（否则会把正在缓冲/加载的歌曲误报为已停止）。
    """
    # 等待共用管道锁不能阻塞引擎事件循环。
    if not await asyncio.to_thread(pipe_alive):
        return {"status": "stopped", "title": "", "position": 0, "duration": 0, "volume": None}
    keys = list(_STATE_KEYS)
    res = await _ipc([["get_property", k] for k in keys], timeout_s=4.5)
    vals: dict = {}
    for item in res:
        rid = item.get("request_id")
        if isinstance(rid, int) and 0 <= rid < len(keys) and item.get("error") == "success":
            vals[keys[rid]] = item.get("data")
    title = vals.get("media-title") or ""
    count = vals.get("playlist-count") or 0
    pos = vals.get("playlist-pos")
    # ★ 判定核心是 playlist-pos —— 它等于 -1 表示"列表里有歌但没有一首在播"
    #   （歌已放完 / 从未起播），此时 mpv 处于 idle。
    #   血的教训（2026-09-15）：旧逻辑只看 title/count，把这种空转误报成
    #   "playing"，于是 seek 对着空气执行、LLM 照报"已跳到1分30秒"，
    #   用户端表现为"没跳转"甚至错觉"切了下一首"。
    playing_index = isinstance(pos, int) and pos >= 0
    # 缺失 playlist-pos 是传输状态未知，不能据此推断播放器空闲。
    confirmed = type(pos) is int and (pos < 0 or type(vals.get("pause")) is bool)
    if not confirmed:
        status = "unknown"
    elif not playing_index:
        status = "stopped"
    elif vals.get("pause") is True:
        status = "paused"
    else:
        status = "playing"
    duration = float(vals.get("duration") or 0)
    return {
        "status": status,
        "title": title,
        "position": round(float(vals.get("time-pos") or 0), 1),
        "duration": round(duration, 1),
        # 元数据是否就绪 —— 刚切歌时 duration 为 0，别让 LLM 说成"这首 0 秒的歌"
        "ready": confirmed and playing_index and bool(title) and duration > 0,
        "state_confirmed": confirmed,
        "volume": None,
        "queueLength": count,
        "currentIndex": pos if isinstance(pos, int) else -1,
    }


def stop_mpv() -> None:
    """关闭 mpv（仅用于测试清理）。"""
    global _mpv_proc
    _close_ipc_handle()
    if _mpv_proc is not None and _mpv_proc.poll() is None:
        try:
            _mpv_proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    _mpv_proc = None
