"""系统操作的原生实现（S10）：与 system-daemon/src/capability/*.cpp 行为对齐。

实现手段：Windows API（ctypes） + 标准库 + PowerShell 桥（仅 SMTC 查询用）。
所有函数返回 ``(status, stdout)``，status ∈ ``ok | denied | error``（dry-run 由上层处理）。

对齐要点（见 docs/plan/S10-native-system-backend.md 行为契约）：
- 中文应用别名表、三级窗口查找、文案（`已打开 "X"` / `未找到标题含 …`）；
- 文件路径必须位于允许根目录内（穿越防护按归一化前缀比较）；
- 音量/mute 走系统媒体键；now_playing/list_sessions 走 PowerShell + WinRT SMTC。
"""
from __future__ import annotations

import base64
import ctypes
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

from yuiro.logger import vlog

_IS_WINDOWS = os.name == "nt"
# POSIX 上 Popen(creationflags=...) 非 0 会直接 ValueError，故按平台取 0。
_NO_WINDOW = 0x08000000 if _IS_WINDOWS else 0

# ---- 应用别名（与 C++ resolve_target 的 kAliases 对齐）------------------------
_APP_ALIASES: dict[str, str] = {
    "记事本": "notepad",
    "计算器": "calc",
    "画图": "mspaint",
    "命令提示符": "cmd",
    "cmd": "cmd",
    "控制面板": "control",
    "资源管理器": "explorer",
    "文件管理器": "explorer",
    "我的电脑": "explorer",
    "此电脑": "explorer",
    "浏览器": "msedge",
    "Edge": "msedge",
    "网易云音乐": "cloudmusic",
    "网易云": "cloudmusic",
    "微信": "wechat",
    "QQ": "qq",
}

# ---- 媒体键（与 C++ kMediaKeys 对齐）----------------------------------------
_VK: dict[str, int] = {
    "VK_MEDIA_PLAY_PAUSE": 0xB3,
    "VK_MEDIA_NEXT_TRACK": 0xB0,
    "VK_MEDIA_PREV_TRACK": 0xB1,
    "VK_VOLUME_UP": 0xAF,
    "VK_VOLUME_DOWN": 0xAE,
    "VK_VOLUME_MUTE": 0xAD,
}
_MEDIA_KEYS: dict[str, str] = {
    "play": "VK_MEDIA_PLAY_PAUSE",
    "pause": "VK_MEDIA_PLAY_PAUSE",
    "play_pause": "VK_MEDIA_PLAY_PAUSE",
    "next": "VK_MEDIA_NEXT_TRACK",
    "prev": "VK_MEDIA_PREV_TRACK",
    "volume_up": "VK_VOLUME_UP",
    "volume_down": "VK_VOLUME_DOWN",
    "mute": "VK_VOLUME_MUTE",
}
_VOLUME_ACTIONS = frozenset({"volume_up", "volume_down", "mute"})
#: SMTC（Windows 媒体会话）类 action —— 走 PowerShell 桥查询
SMTC_ACTIONS = frozenset({"now_playing", "list_sessions"})
#: 可由 SMTC **精确控制**的 action（按 AUMID 锁定会话，只作用于目标应用）。
#: 音量类不在此列 —— SMTC 不提供音量接口，仍走系统媒体键。
_SMTC_CONTROL_ACTIONS = frozenset({"play", "pause", "play_pause", "next", "prev", "stop"})
#: 全部合法 action（供参数校验与错误文案）
MEDIA_ACTIONS = tuple(sorted(_MEDIA_KEYS.keys() | SMTC_ACTIONS | _SMTC_CONTROL_ACTIONS | {"open_song", "client_state", "client_launch", "client_search", "client_favorite", "client_recommend"}))

_KEYEVENTF_KEYUP = 0x0002
_SW_RESTORE = 9
_CREATE_NO_WINDOW = 0x08000000


def new_trace_id() -> str:
    """与 C++ make_trace_id 同形（时间戳-随机）。"""
    return f"{int(time.time() * 10_000_000):016x}-{uuid.uuid4().hex[:16]}"


def resolve_app(name: str) -> str:
    """中文应用名 → 可执行名（未命中原样返回）。"""
    return _APP_ALIASES.get(name, name)


# ---------------- 应用启动 / 聚焦 ---------------------------------------------
def open_app(name: str) -> tuple[str, str]:
    target = resolve_app(name)
    if not _IS_WINDOWS:
        # macOS 用 open（-a 语义由 open 自己处理裸应用名），Linux 用 xdg-open
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen(
                [opener, target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return "ok", f'已打开 "{target}"'
        except Exception as exc:  # noqa: BLE001 — 透出失败原因
            return "error", f'打开失败: {exc}（目标 "{target}"）'
    try:
        os.startfile(target)  # 等价 ShellExecute("open")：按默认关联/PATH 解析
        return "ok", f'已打开 "{target}"'
    except OSError:
        # 二段降级：cmd start（覆盖 startfile 对裸可执行名解析失败的环境）
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", target],
                creationflags=_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return "ok", f'已打开 "{target}"'
        except Exception as exc:  # noqa: BLE001 — 透出失败原因
            return "error", f'打开失败: {exc}（目标 "{target}"）'


def _netease_executable() -> str:
    """只读取官方协议注册，不修改注册表、不执行其中的任意参数。"""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"orpheus\shell\open\command") as key:
        command = winreg.QueryValue(key, None)
    match = re.match(r'^"([^"]+)"', command)
    executable = match.group(1) if match else ""
    if os.path.basename(executable).casefold() != "cloudmusic.exe" or not os.path.isfile(executable):
        raise ValueError("未找到明确的网易云官方客户端程序")
    return executable


def open_netease_song(song_id: str) -> tuple[str, str]:
    """受限的原版定位请求；投递成功不等于客户端已定位或起播。"""
    if not _IS_WINDOWS or not re.fullmatch(r"[1-9][0-9]{0,19}", song_id):
        return "denied", "需要 Windows 与纯数字网易云歌曲 ID，未执行"
    try:
        executable = _netease_executable()
        command = {"type": "song", "id": song_id, "cmd": "play"}
        uri = "orpheus://" + base64.b64encode(json.dumps(command, separators=(",", ":")).encode()).decode('ascii')
        # 参数分开传，不复用可能缺少分隔空格的协议注册模板，也不经过 shell。
        subprocess.Popen([executable, f"--webcmd={uri}"], cwd=os.path.dirname(executable), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception as exc:  # noqa: BLE001
        return "error", f"官方客户端定位请求失败：{type(exc).__name__}"
    return "ok", json.dumps({"backend": "netease_client", "target": "cloudmusic.exe",
                             "song_id": song_id, "requested": True, "playback_confirmed": False,
                             "note": "仅完成客户端请求投递，尚未确认定位或播放"}, ensure_ascii=False)


def _enum_windows() -> list[tuple[int, str, int]]:
    """枚举所有顶层窗口 → [(hwnd, title, pid)]。"""
    user32 = ctypes.windll.user32
    results: list[tuple[int, str, int]] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            results.append((int(hwnd), buf.value, int(pid.value)))
        return True

    user32.EnumWindows(enum_proc(_cb), 0)
    return results


def _iter_process_names() -> dict[int, str]:
    """Toolhelp32 快照：pid → 进程名（去 .exe）。"""
    kernel32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260
    INVALID = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * MAX_PATH),
        ]

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID:
        return {}
    names: dict[int, str] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            exe = str(entry.szExeFile)
            if exe.lower().endswith(".exe"):
                exe = exe[:-4]
            names[int(entry.th32ProcessID)] = exe
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return names


def _find_window(name: str) -> int | None:
    """三级查找（L1 可见标题 → L2 任意标题 → L3 进程名反查），返回 hwnd。"""
    user32 = ctypes.windll.user32
    windows = _enum_windows()
    # L1：可见窗口标题含关键词
    for hwnd, title, _pid in windows:
        if name in title and user32.IsWindowVisible(hwnd):
            return hwnd
    # L2：任意窗口（含最小化）
    for hwnd, title, _pid in windows:
        if name in title:
            return hwnd
    # L3：进程名反查
    raw_candidates = {name, resolve_app(name)}
    candidates = {
        c[:-4] if c.lower().endswith(".exe") else c for c in raw_candidates
    }
    candidates.discard("")
    pid_map = _iter_process_names()
    target_pids = {
        pid for pid, exe in pid_map.items() if exe.lower() in {c.lower() for c in candidates}
    }
    if target_pids:
        for hwnd, _title, pid in windows:
            if pid in target_pids:
                return hwnd
    return None


def focus_app(name: str) -> tuple[str, str]:
    if not _IS_WINDOWS:
        return "error", "app_focus 目前仅支持 Windows"
    hwnd = _find_window(name)
    if not hwnd:
        return "error", f'未找到标题含 "{name}" 的窗口（且进程 {resolve_app(name)} 未运行）'
    user32 = ctypes.windll.user32
    try:
        if not user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, _SW_RESTORE)
        # 前台抢占场景：AttachThreadInput + BringWindowToTop 再聚焦
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None)
        cur_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        if fg_thread and fg_thread != cur_thread:
            user32.AttachThreadInput(cur_thread, fg_thread, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(cur_thread, fg_thread, False)
        else:
            user32.SetForegroundWindow(hwnd)
    except Exception as exc:  # noqa: BLE001 — 透出失败原因
        return "error", f"聚焦失败: {exc}"
    return "ok", f"已聚焦窗口: {name}"


# ---------------- 媒体控制 -----------------------------------------------------
def _send_key(vk: int) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


# PowerShell + WinRT SMTC 查询（now_playing / list_sessions）。
#
# ★ 2026-09-16 修复：原脚本用 `IAsyncOperation.GetAwaiter().GetResult()`，
#   那是 pwsh 7 / .NET Core 的写法；**Windows PowerShell 5.1 里该方法不存在**
#   （实测报 "[System.__ComObject] 不包含名为 GetAwaiter 的方法"），
#   导致本桥自诞生起**从未成功过一次**，而错误被上层解读为"没有媒体会话"，
#   进而写成"网易云不注册 SMTC"的错误结论（实测：网易云注册 cloudmusic.exe 会话）。
#   5.1 的正确姿势是用 System.Runtime.WindowsRuntime 的 AsTask 扩展 + 等待 Task。
# 另注：PowerShell 投影下 WinRT 的**方法会变属性**（SourceAppUserModelId、
#   PlaybackStatus、Title/Artist），写成 `X()` 会报"不包含名为 X 的方法"。
_SMTC_PRELUDE = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($task, $type) {
    $asTask = $asTaskGeneric.MakeGenericMethod($type)
    $netTask = $asTask.Invoke($null, @($task))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[void][Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType=WindowsRuntime]
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
function Find-Session($target) {
    $pickedSessions = @()
    foreach ($s in $mgr.GetSessions()) {
        $a = $s.SourceAppUserModelId
        if ([string]::IsNullOrEmpty($target)) {
            if ($a -match 'cloudmusic|netease|orpheus') { $pickedSessions += $s }
        } elseif ($a -ieq $target) { $pickedSessions += $s }
    }
    if ($pickedSessions.Count -eq 1) { return $pickedSessions[0] }
    return $null
}
"""

_SMTC_PS = _SMTC_PRELUDE + r"""
$out = @()
foreach ($s in $mgr.GetSessions()) {
  $info = $s.GetPlaybackInfo()
  try { $media = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties]) } catch { $media = $null }
  try { $timeline = $s.GetTimelineProperties() } catch { $timeline = $null }
  $out += [pscustomobject]@{
    aumid  = $s.SourceAppUserModelId
    status = $info.PlaybackStatus.ToString()
    title  = if ($media) { $media.Title } else { '' }
    artist = if ($media) { $media.Artist } else { '' }
    position = if ($timeline) { $timeline.Position.TotalSeconds } else { $null }
    can_play = $info.Controls.IsPlayEnabled
    can_pause = $info.Controls.IsPauseEnabled
    can_stop = $info.Controls.IsStopEnabled
  }
}
ConvertTo-Json -InputObject @($out) -Depth 4 -Compress
"""

# SMTC **精确控制**（按 AUMID 锁定会话）。
# 为什么不继续只用全局媒体键：媒体键是系统级的，系统里同时有多个播放器
# （我们的 mpv / 用户的网易云客户端 / 浏览器）时会打错目标 —— 这正是历史上
# "误控"的根因。SMTC 定位到具体会话再下发命令，只作用于目标应用。
# 参数经环境变量传入（避免 PowerShell 引号转义地狱）。
_SMTC_CTRL_PS = _SMTC_PRELUDE + r"""
$s = Find-Session $env:YUIRO_SMTC_TARGET
if ($null -eq $s) { Write-Output 'NOSESSION'; exit 0 }
if ($env:YUIRO_SMTC_TITLE) {
  $media = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
  if ($media.Title -ine $env:YUIRO_SMTC_TITLE) { Write-Output 'TRACK_CHANGED'; exit 0 }
}
if ($env:YUIRO_SMTC_ACTION -eq 'stop' -and -not $s.GetPlaybackInfo().Controls.IsStopEnabled) {
  Write-Output 'UNSUPPORTED'; exit 0
}
$ok = $false
switch ($env:YUIRO_SMTC_ACTION) {
  'play'       { $ok = Await ($s.TryPlayAsync()) ([System.Boolean]) }
  'pause'      { $ok = Await ($s.TryPauseAsync()) ([System.Boolean]) }
  'stop'       { $ok = Await ($s.TryStopAsync()) ([System.Boolean]) }
  'play_pause' { $ok = Await ($s.TryTogglePlayPauseAsync()) ([System.Boolean]) }
  'next'       { $ok = Await ($s.TrySkipNextAsync()) ([System.Boolean]) }
  'prev'       { $ok = Await ($s.TrySkipPreviousAsync()) ([System.Boolean]) }
}
$expected = @{play='Playing';pause='Paused';stop='Stopped'}[$env:YUIRO_SMTC_ACTION]
if ($ok -and $expected) {
  $confirmed = $false
  for ($attempt=0; $attempt -lt 10; $attempt++) {
    if ($s.GetPlaybackInfo().PlaybackStatus.ToString() -eq $expected) { $confirmed=$true; break }
    Start-Sleep -Milliseconds 100
  }
  if (-not $confirmed) { Write-Output 'UNCONFIRMED'; exit 0 }
}
Write-Output ("OK=" + $ok + ";" + $s.SourceAppUserModelId)
"""


def _smtc_control(action: str, target: str, expected_title: str = "") -> tuple[bool, str]:
    """用 SMTC 精确控制目标会话。返回 ``(是否已处理, 说明)``。

    未处理（无会话/桥不可用）时返回 ``(False, 原因)``，禁止转发全局媒体键。
    """
    if not _IS_WINDOWS:
        return False, "非 Windows"
    env = dict(os.environ)
    env["YUIRO_SMTC_TARGET"] = target or ""
    env["YUIRO_SMTC_TITLE"] = expected_title
    env["YUIRO_SMTC_ACTION"] = action
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SMTC_CTRL_PS],
            capture_output=True,
            text=True,
            encoding='utf-8', errors='replace',
            timeout=20,
            check=False,
            creationflags=_NO_WINDOW,
            env=env,
        )
    except Exception as exc:  # noqa: BLE001
        vlog("native", f"SMTC 控制桥失败: {exc}")
        return False, f"SMTC 桥异常: {exc}"
    raw = (proc.stdout or "").strip()
    if "TRACK_CHANGED" in raw:
        return True, "目标曲目已变化，拒绝执行本次控制"
    if "UNSUPPORTED" in raw:
        return True, f"目标会话不支持 {action}，未执行，也未改成其他动作"
    if "UNCONFIRMED" in raw:
        return True, f"目标会话未确认 {action} 的最终状态，不能报告已完成"
    if "NOSESSION" in raw:
        return False, "未找到匹配的媒体会话"
    if not raw.startswith("OK="):
        vlog("native", f"SMTC 控制未识别输出: {raw[:160]} / {proc.stderr[:160]}")
        return False, "SMTC 桥无有效输出"
    body = raw[3:]
    ok_str, _, aumid = body.partition(";")
    if ok_str.strip().lower() != "true":
        # 会话存在但拒绝了该操作（应用未实现/状态不允许）
        return True, f"目标会话拒绝执行 {action}（{aumid}）"
    labels = {"play": "播放", "pause": "暂停", "play_pause": "播放/暂停切换",
              "next": "下一首", "prev": "上一首", "stop": "停止"}
    return True, f"已通过 SMTC 对 {aumid} 执行：{labels.get(action, action)}"


def _smtc_sessions() -> list[dict] | None:
    """返回 [{'aumid','status','title','artist'}]；失败返回 None。"""
    if not _IS_WINDOWS:
        return None
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SMTC_PS],
            capture_output=True,
            text=True,
            encoding='utf-8', errors='replace',
            timeout=20,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except Exception as exc:  # noqa: BLE001 — 桥不可用时返回 None（上层给说明）
        vlog("native", f"SMTC PowerShell 桥失败: {exc}")
        return None
    if proc.returncode != 0:
        vlog("native", f"SMTC PowerShell 退出码 {proc.returncode}: {proc.stderr[:200]}")
        return None
    raw = (proc.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data = [data]
    return [d for d in data if isinstance(d, dict)]


def media_control(action: str, target: str = "", expected_title: str = "") -> tuple[str, str]:
    if action in _MEDIA_KEYS or action == "stop":
        # ★ 优先 SMTC 精确控制（2026-09-16）：按 AUMID 锁定目标会话再下发命令，
        #   只作用于目标应用。旧实现无条件发全局媒体键，系统里同时有多个播放器
        #   （我们的 mpv / 网易云客户端 / 浏览器）时会打错目标 —— 历史"误控"根因。
        #   找不到匹配会话时直接拒绝，不能再用全局媒体键猜测目标。
        if action in _SMTC_CONTROL_ACTIONS:
            handled, note = (_smtc_control(action, target, expected_title) if expected_title
                             else _smtc_control(action, target))
            if handled:
                return ("error" if any(x in note for x in ("拒绝", "不支持", "未确认")) else "ok"), note
            return "error", f"SMTC 未处理 {action}（{note}），未发送全局媒体键"
        if target:
            return "error", "指定应用的音量不能用系统全局音量键代替，未执行"
        try:
            _send_key(_VK[_MEDIA_KEYS[action]])
        except Exception as exc:  # noqa: BLE001
            return "error", f"发送媒体键失败: {exc}"
        if action in _VOLUME_ACTIONS:
            return "ok", f"已发送系统音量键: {action}（SMTC 无音量接口，作用范围为系统全局）"
        return "ok", f"已发送全局媒体键: {action}"
    if action in SMTC_ACTIONS:
        sessions = _smtc_sessions()
        if sessions is None:
            return "error", (
                "SMTC 查询失败（需要 Windows PowerShell + Windows 10+）；"
                "未猜测其他播放器，也未发送全局播放控制键"
            )
        if action == "list_sessions":
            return "ok", json.dumps(sessions, ensure_ascii=False, indent=2)
        # now_playing：显式 target 必须唯一精确命中；无 target 才读取默认候选。
        picked: dict | None = None
        if target:
            matched = [s for s in sessions if target.casefold() == str(s.get("aumid", "")).casefold()]
            if len(matched) == 1:
                picked = matched[0]
        if picked is None and not target:
            for s in sessions:
                if str(s.get("title", "")).strip():
                    picked = s
                    break
        if picked is None:
            payload: dict = {"status": "无媒体会话在使用", "sessions": []}
            if target and not any(
                target.lower() in str(s.get("aumid", "")).lower() for s in sessions
            ):
                payload["hint"] = "请用 action=list_sessions 查看当前所有媒体会话的 AUMID"
                payload["sessions"] = [s.get("aumid", "") for s in sessions]
            return ("error" if target else "ok"), json.dumps(payload, ensure_ascii=False, indent=2)
        return "ok", json.dumps(picked, ensure_ascii=False, indent=2)
    return "error", f'未知 action: {action}（可用: {"|".join(MEDIA_ACTIONS)}）'


# ---------------- 文件操作 -----------------------------------------------------
def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def path_allowed(path: str, roots: list[str]) -> bool:
    """路径穿越防护：归一化后必须位于某个允许根目录内（对齐 C++ Policy::path_allowed）。"""
    try:
        p = _norm(path)
    except Exception:  # noqa: BLE001 — 无效路径 → 拒绝
        return False
    for root in roots:
        try:
            base = _norm(root)
        except Exception:  # noqa: BLE001, S112 — 无效根目录跳过
            continue
        if p == base or p.startswith(base.rstrip("\\/") + os.sep):
            return True
    return False


def file_create(path: str, content: str, roots: list[str]) -> tuple[str, str]:
    if not path_allowed(path, roots):
        return "denied", f"路径不在允许目录内，已拒绝: {path}"
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        data = content.encode("utf-8")
        with open(path, "wb") as f:
            f.write(data)
    except Exception as exc:  # noqa: BLE001
        return "error", f"创建失败: {exc}"
    return "ok", f"已创建文件: {path}（{len(data)} 字节）"


def file_read(path: str, roots: list[str]) -> tuple[str, str]:
    if not path_allowed(path, roots):
        return "denied", f"路径不在允许目录内，已拒绝: {path}"
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return "error", f"无法读取文件: {path}"
    except Exception as exc:  # noqa: BLE001
        return "error", f"读取失败: {exc}"
    return "ok", raw.decode("utf-8", errors="replace")


def file_write(path: str, content: str, roots: list[str]) -> tuple[str, str]:
    if not path_allowed(path, roots):
        return "denied", f"路径不在允许目录内，已拒绝: {path}"
    try:
        data = content.encode("utf-8")
        with open(path, "wb") as f:
            f.write(data)
    except FileNotFoundError:
        return "error", f"无法写入文件: {path}"
    except Exception as exc:  # noqa: BLE001
        return "error", f"写入失败: {exc}"
    return "ok", f"已写入文件: {path}（{len(data)} 字节）"


def file_delete(path: str, roots: list[str]) -> tuple[str, str]:
    """删除单个文件（S33）。目录不删（避免误伤整棵树）。"""
    if not path_allowed(path, roots):
        return "denied", f"路径不在允许目录内，已拒绝: {path}"
    if os.path.isdir(path):
        return "error", f"目标是目录，本工具只删除文件: {path}"
    if not os.path.isfile(path):
        return "error", f"文件不存在: {path}"
    try:
        size = os.path.getsize(path)
        os.remove(path)
    except Exception as exc:  # noqa: BLE001
        return "error", f"删除失败: {exc}"
    return "ok", f"已删除文件: {path}（{size} 字节）"


def file_list(
    path: str,
    roots: list[str],
    *,
    pattern: str = "*",
    recursive: bool = False,
    max_items: int = 80,
) -> tuple[str, str]:
    """列出目录内容（S38）→ JSON（名称/扩展名/大小/修改时间 + 子目录）。

    "帮我整理文件夹"的**第一步是看清有什么** —— 但此前只有 ``file_read``（读单个文件），
    没有任何"列目录"能力，于是整理类请求实际上无从起步（S34 诊断出的空壳之一）。
    返回按**大小降序**（整理时先看大件是常见需求），超出 ``max_items`` 截断并标记。
    """
    if not path_allowed(path, roots):
        return "denied", f"路径不在允许目录内，已拒绝: {path}"
    if not os.path.isdir(path):
        return "error", f"不是目录（file_list 只用于列目录）: {path}"

    dirs: list[str] = []
    picked: list[tuple[str, os.stat_result]] = []
    truncated = False
    try:
        if recursive:
            for root_dir, dnames, fnames in os.walk(path):
                for d in dnames:
                    dirs.append(os.path.relpath(os.path.join(root_dir, d), path))
                for f in fnames:
                    picked.append((os.path.join(root_dir, f), None))  # type: ignore[arg-type]
        else:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_dir():
                            dirs.append(entry.name)
                        elif entry.is_file():
                            picked.append((entry.path, entry.stat()))
                    except OSError:  # noqa: PERF203 — 单个条目失败不影响其余
                        continue
    except OSError as exc:
        return "error", f"读取目录失败: {exc}"

    files: list[dict] = []
    for full, st in picked:
        name = os.path.relpath(full, path)
        base = os.path.basename(full)
        if not fnmatch.fnmatch(base, pattern):
            continue
        if len(files) >= max_items:
            truncated = True
            break
        if st is None:
            try:
                st = os.stat(full)
            except OSError:
                continue
        files.append({
            "name": name,
            "ext": os.path.splitext(base)[1].lower(),
            "size": int(st.st_size),
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
        })
    files.sort(key=lambda f: f["size"], reverse=True)
    payload = {
        "status": "ok",
        "path": path,
        "count": len(files),
        "dirs": dirs[:50],
        "files": files,
        "truncated": truncated,
    }
    return "ok", json.dumps(payload, ensure_ascii=False)


def file_move(src: str, dst: str, roots: list[str]) -> tuple[str, str]:
    """移动单个文件（S33）。**已存在的目标不覆盖**（否则回滚语义会变模糊）。"""
    if not path_allowed(src, roots) or not path_allowed(dst, roots):
        return "denied", f"路径不在允许目录内，已拒绝: {src} → {dst}"
    if not os.path.isfile(src):
        return "error", f"源文件不存在: {src}"
    if os.path.exists(dst):
        return "error", f"目标已存在（不覆盖）: {dst}"
    try:
        parent = os.path.dirname(os.path.abspath(dst))
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.move(src, dst)
    except Exception as exc:  # noqa: BLE001
        return "error", f"移动失败: {exc}"
    return "ok", f"已移动: {src} → {dst}"
