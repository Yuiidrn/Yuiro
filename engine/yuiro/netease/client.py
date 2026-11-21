"""ncm-cli 子进程封装。

设计约束（均来自实测，改动前请先读 docs/features/netease-music-design.md）：

1. **必须用 asyncio.to_thread + subprocess.run**
   Windows 下 asyncio 子进程 API 会抛 NotImplementedError（Proactor 限制），
   与 yuiro/systemd/client.py 的既有处理保持一致。切勿改用 create_subprocess_exec。

2. **命令集依赖登录态**
   ncm-cli 的 search / playlist / recommend / song 等命令在**登录成功后才动态加载**；
   未登录时不仅在 `ncm-cli commands` 里看不到，调用也会报 unknown command。
   因此 command_missing 的提示必须引导用户先登录，而不是报"未知命令"。

3. **返回结构有两种形态**，必须都兼容：
   - {"code":200,"data":{"recordCount":N,"records":[...]}}   （search / playlist）
   - {"code":200,"data":[...]}                               （recommend daily）

4. **资源自带 jumpUrl**（orpheus://song/<originalId>、orpheus://playlist/<originalId>），
   投递给桌面客户端播放时优先用它，不要自己拼 URI。

5. **脱敏**：凭证由 ncm-cli 自己托管，本模块不接触 privateKey；
   日志只记子命令名与参数个数，不记录关键词等用户隐私内容。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# ncm-cli 输出偶尔混入 ANSI 颜色码，解析前需剥离。
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# 命令缺失 / 未授权 的特征串（来自实测输出）。
# ★ 只用于「响应无法解析为成功 JSON」时的错误分类；成功的 code=200 响应
#   会先返回，绝不做文本匹配——否则歌曲数据里碰巧出现的 "401"（如跳转链接）
#   会把成功误判成未授权（2026-08-31 实测踩坑：keyword=test 命中了这问题）。
_RE_COMMAND_MISSING = re.compile(r"unknown command|unknown option", re.I)
_RE_NOT_AUTHORIZED = re.compile(r"未登录|登录已失效|not login|unauthorized|(?:^|\D)401(?:\D|$)", re.I)

NOT_INSTALLED = "not_installed"
NOT_AUTHORIZED = "not_authorized"
COMMAND_MISSING = "command_missing"
TIMEOUT = "timeout"
API_ERROR = "api_error"
UNKNOWN = "unknown"

# 面向桌宠用户的中文提示：给出可执行的操作，而不是暴露技术细节。
#
# ★ 登录失效场景（2026-09-05 实测确认）：ncm-cli 的命令集是登录后动态加载的——
#   未登录时连 search 都报 "unknown command"，桌宠整块音乐能力瘫痪，却只拿到一句
#   "请执行 ncm-cli login"。而桌宠是 GUI 场景，用户看不到终端二维码，直接死锁。
#   因此提示必须给出「用户亲手可做的恢复动作」，且说明桌宠无法代办的原因，
#   避免 LLM 只会复读命令却让用户无从下手。
_ERROR_HINTS: dict[str, str] = {
    NOT_INSTALLED: "网易云命令行工具还没装，请先执行 npm install -g @music163/ncm-cli",
    # ★ 登录失效不再要求用户手动敲命令：改为引导 LLM 调用 netease_login 工具，
    #   由桌宠自己弹出二维码（见 fetch_login_qr）。这是"登录内置化"的关键一环。
    NOT_AUTHORIZED: (
        "网易云登录已失效。请立刻调用 netease_login 工具：它会弹出一张二维码图片，"
        "让用户用手机网易云 App 扫码就行，扫完登录立即生效。"
    ),
    COMMAND_MISSING: (
        "这个功能要登录网易云账号才能用，而现在登录失效了（整个音乐库都读不到）。"
        "请立刻调用 netease_login 工具给用户弹出登录二维码，让用户用手机网易云 App 扫码，"
        "不要重复调用本工具。"
    ),
    TIMEOUT: "网易云响应有点慢，稍后再试一次吧",
}


@dataclass
class NcmResult:
    """ncm-cli 调用的结构化结果。"""

    ok: bool
    data: Any = None
    records: list[dict] = field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None

    @property
    def hint(self) -> str:
        """给桌宠口播用的中文提示。"""
        return _ERROR_HINTS.get(self.error_kind or "", self.error or "未知错误")


def is_available(bin_name: str = "ncm-cli") -> bool:
    """探测 ncm-cli 是否可执行（供 BaseTool.requires_env 显隐工具）。"""
    return shutil.which(bin_name) is not None


# ---------------------------------------------------------------------------
# 后台播放守护进程（ncm daemon）
#
# 关键机制（2026-08-31 实测确定）：ncm-cli 的 index.js 里有
#     if (process.env.NCM_DAEMON === '1') { runDaemon() }
# 也就是说**只有 NCM_DAEMON=1 时才启动后台播放服务**。
# 普通 `ncm-cli play` 只是把歌曲加进共享队列就返回（提示"歌曲已发送到播放服务"），
# 若此时没有 daemon 消费队列，state 会永远是 stopped、mpv 也拉不起来。
#
# 因此播放前必须先确保 daemon 常驻。daemon 是阻塞式常驻进程，
# 这里用 Popen 后台拉起并保留句柄，进程内的播放类命令共用它。
# ---------------------------------------------------------------------------
_daemon_proc: subprocess.Popen | None = None
# daemon 首次被探测到就绪的时刻（用于"播放服务预热"计时，见 ensure_daemon_ready）
_daemon_ready_at: float | None = None
# UnifiedPlayService（真正处理 play/queue 的服务）比 daemon 就绪晚约 10~19s 启动。
# 这里只做**首段**盲等（6s），剩下的交给 netease_play 的"投递后校验队列、未入队即
# 重投"机制兜底——盲等固定值既慢又不可靠（实测耗时在 10~19s 间波动）。
_PLAY_SERVICE_WARMUP_S = 6.0


_PIPE_PATH = r"\\.\pipe\ncm-daemon"


def daemon_alive() -> bool:
    """守护进程是否可用（本进程启动的存活，或系统里已有一个）。

    ★ 判定方式于 2026-09-12 改为「命名管道是否存在」：
      旧实现 spawn PowerShell + WMI 查 node 进程命令行，单次耗时 0.5~2s，
      且在被密集调用时**恒返回 False**（实测 45 秒内 daemon 明明活着、
      state 一直通，它却全程报 False）。这个误报会让 netease_play 的看门狗
      以为"daemon 死了"而去重启它，把正在处理播放的 daemon 打断，
      直接导致"点歌毫无反应、无声音无窗口"。

      管道探测是同步、毫秒级、零副作用的：daemon 常驻时必持有
      \\\\.\\pipe\\ncm-daemon，进程退出后管道随之消失。
    """
    if _daemon_proc is not None and _daemon_proc.poll() is None:
        return True
    try:
        return os.path.exists(_PIPE_PATH)
    except OSError:
        return False


def _system_daemon_running() -> bool:
    """系统里是否已有 daemon（单实例判定用）：同样走管道探测。"""
    return daemon_alive()


def ensure_daemon(bin_name: str = "ncm-cli", settle_s: float = 5.0) -> bool:
    """确保 ncm 播放守护进程已启动；返回是否可用。

    已存活时直接返回 True；否则以 NCM_DAEMON=1 后台拉起。
    ``settle_s`` 为启动后等待就绪的时间（过短会导致首条 play 被丢弃）。
    """
    global _daemon_proc
    if daemon_alive():
        return True

    exe = shutil.which(bin_name)
    if not exe:
        return False

    env = os.environ.copy()
    env["NCM_DAEMON"] = "1"
    # mpv 所在目录需在 PATH 内（ncm-cli 的 player 只接受 "mpv" 字面量）
    mpv_dir = os.environ.get("YUIRO_MPV_DIR", "")
    if mpv_dir and os.path.isdir(mpv_dir) and mpv_dir.lower() not in env.get("PATH", "").lower():
        env["PATH"] = mpv_dir + os.pathsep + env.get("PATH", "")

    kwargs: dict[str, Any] = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    # 只加 CREATE_NO_WINDOW 隐藏窗口即可。
    # ★ 不要再加 DETACHED_PROCESS：实测两者叠加时 daemon 会启动即退出
    #   （现象：ensure_daemon 返回 True，但随后 list 进程已空、play 不出声），
    #   仅用 CREATE_NO_WINDOW 时进程稳定常驻。
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        _daemon_proc = subprocess.Popen([exe], **kwargs)
    except Exception as exc:  # noqa: BLE001 — 启动失败需降级为不可用而非崩溃
        log.warning("ncm 播放守护进程启动失败: %s", exc)
        _daemon_proc = None
        return False

    time.sleep(settle_s)
    if daemon_alive():
        log.info("ncm 播放守护进程已启动 (pid=%s)", _daemon_proc.pid)
        return True

    # 拉起的进程已退出：绝大多数情况是"系统里已有一个 daemon"——
    # ncm daemon 是单实例的，重复启动会立即以 0 退出。
    # 而系统级探测走 WMI 查询进程命令行，可能慢于进程退出，
    # 故再等一拍重试，避免把"复用已有 daemon"误判成启动失败。
    time.sleep(1.5)
    if _system_daemon_running():
        log.info("复用系统里已存在的 ncm 播放守护进程")
        return True

    log.warning("ncm 播放守护进程启动后立即退出，且未探测到已有实例")
    _daemon_proc = None
    return False


def _parse_json(text: str) -> dict | None:
    """从可能带前缀/ANSI 的输出中稳健提取 JSON 对象。"""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj = json.loads(text[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _extract_records(payload: dict) -> list[dict]:
    """统一抽取资源列表，兼容 data 为数组与 {recordCount, records} 两种形态。"""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        records = data.get("records")
        if isinstance(records, list):
            return [r for r in records if isinstance(r, dict)]
    return []


async def run_ncm(
    args: list[str],
    timeout_s: float = 20.0,
    bin_name: str = "ncm-cli",
) -> NcmResult:
    """执行 ncm-cli 命令并返回结构化结果。

    ``args`` 不含程序名与 --output，例如 ["search", "song", "--keyword", "晴天"]。
    """
    exe = shutil.which(bin_name)
    if not exe:
        return NcmResult(False, error="未找到 ncm-cli", error_kind=NOT_INSTALLED)

    cmd = [exe, *args, "--output", "json"]
    # 脱敏：只记子命令与参数个数，不记关键词等隐私内容
    log.debug("ncm-cli 调用: %s (参数 %d 个)", " ".join(args[:2]), len(args))

    kwargs: dict[str, Any] = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        shell=False,
    )
    # 避免每次调用弹出控制台窗口（仅 Windows 支持该标志）
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        proc = await asyncio.to_thread(subprocess.run, cmd, **kwargs)
    except subprocess.TimeoutExpired:
        return NcmResult(False, error=f"调用超时（{timeout_s}s）", error_kind=TIMEOUT)
    except FileNotFoundError:
        return NcmResult(False, error="未找到 ncm-cli", error_kind=NOT_INSTALLED)
    except Exception as exc:  # noqa: BLE001 — 子进程异常统一收敛为结果对象
        return NcmResult(False, error=str(exc), error_kind=UNKNOWN)

    stdout = _ANSI_RE.sub("", proc.stdout or "").strip()
    stderr = _ANSI_RE.sub("", proc.stderr or "").strip()
    blob = f"{stderr}\n{stdout}"

    def _fail(kind: str, detail: str) -> NcmResult:
        # 失败原因落日志（截断 + 只留前后片段，输出里不含凭证明文，可安全记录），
        # 供真实对话场景定位引擎环境下的异常。
        log.warning("ncm-cli %s 失败(kind=%s): %r", " ".join(args[:2]), kind, blob[:240])
        return NcmResult(False, error=detail, error_kind=kind)

    payload = _parse_json(stdout)

    # 1) 成功响应优先返回，绝不参与文本特征匹配。
    #    成功判定兼容两种协议：
    #      搜索/歌单等：{"code": 200, ...}
    #      播放状态等：{"success": true, "state": {...}}  ← 没有 code 字段！
    #    ★ 因此「code 缺失且无 success」也按成功放行（保守），
    #      只有明确的 code!=200 或 success==false 才算业务失败。
    #    （回归教训：此前把 code=None 判成失败，导致 state 恒为 api_error，
    #      ensure_daemon_ready 探测不到 daemon，播放全部报"服务没启动"。）
    if payload is not None:
        code = payload.get("code")
        success = payload.get("success")
        is_ok = (code == 200) or (success is True) or (code is None and success is None)
        if is_ok:
            return NcmResult(True, data=payload, records=_extract_records(payload))
        msg = payload.get("message") or payload.get("msg") or f"接口返回 code={code}"
        return _fail(API_ERROR, str(msg))

    # 2) 无法解析为 JSON → 用文本特征分类（命令缺失 / 未授权 / 未知）
    if _RE_COMMAND_MISSING.search(blob):
        return _fail(COMMAND_MISSING, stderr[:200])
    if _RE_NOT_AUTHORIZED.search(blob):
        return _fail(NOT_AUTHORIZED, stderr[:200] or stdout[:200])
    return _fail(API_ERROR, stdout[:200] or stderr[:200] or "无输出")


# ---------------------------------------------------------------------------
# 扫码登录（登录内置化）
#
# 实测机制（2026-09-12）：
#   `ncm-cli login --output json` 输出
#       {"success":true,"qrCodeUrl":"https://163cn.tv/xxxx",
#        "clickableUrl":"...","message":"后台轮询已启动，请点击链接登录"}
#   随后主进程约 10s 内自行退出，"登录轮询"转入 CLI 后台；用户扫码授权后
#   凭证自动落盘（tokens.enc.json），无需重启任何进程即刻生效。
#
#   因此桌宠可以完全代办登录流程：取链接 → 自己画二维码 → 弹给用户扫。
#   不再需要用户手动开 PowerShell 敲命令（那是此前"鉴权不弹出指引"的痛点）。
# ---------------------------------------------------------------------------
async def check_login(bin_name: str = "ncm-cli") -> bool:
    """账号当前是否已登录（login --check）。"""
    result = await run_ncm(["login", "--check"], timeout_s=25.0, bin_name=bin_name)
    return result.ok


async def fetch_login_qr(bin_name: str = "ncm-cli") -> tuple[str, str]:
    """发起扫码登录并取回二维码链接。

    返回 (qr_url, 错误信息)；成功时错误信息为空串。调用不会阻塞等待扫码
    （CLI 的登录轮询在后台进行，授权成功后凭证自动写入）。
    """
    result = await run_ncm(["login"], timeout_s=30.0, bin_name=bin_name)
    if not result.ok:
        return "", result.hint
    data = result.data or {}
    url = str(data.get("qrCodeUrl") or data.get("clickableUrl") or "")
    if not url:
        return "", "登录接口没有返回二维码，稍后再试一次吧"
    return url, ""


def render_qr_png(url: str, out_path: str) -> bool:
    """把链接渲染成二维码 PNG；成功返回 True（失败由调用方降级处理）。"""
    try:
        import qrcode  # 轻量纯 Python，依赖已有的 Pillow

        img = qrcode.make(url)
        img.save(out_path)
        return True
    except Exception as exc:  # noqa: BLE001 — 渲染失败不致命，可降级为打开链接
        log.warning("二维码渲染失败: %s", exc)
        return False


async def ensure_daemon_ready(
    bin_name: str = "ncm-cli",
    settle_s: float = 5.0,
    ready_timeout_s: float = 20.0,
) -> bool:
    """确保播放守护进程**已启动、且播放服务已就绪**。

    ★ 两层就绪（2026-09-12 实测厘清，此前一直混淆）：
      1) PlayerDaemon 就绪 —— 监听 \\\\.\\pipe\\ncm-daemon，**state 命令由它直接响应**；
      2) UnifiedPlayService 就绪 —— 真正处理 play/queue 的播放服务，
         实测比 daemon 就绪**晚约 10 秒**才打印"已启动，等待命令..."。

    只用 state 探测会过早返回，此时投递的 play 被**静默丢弃**（队列为空、
    无 mpv、无声音），用户表现就是"说放歌却毫无反应"。
    因此 daemon 就绪后再等一个预热窗口（默认 12s），仅对"本轮新启动的
    daemon"生效；daemon 常驻后（保活生效）后续点歌零额外等待。
    """
    global _daemon_ready_at
    if not daemon_alive():
        _daemon_ready_at = None  # daemon 已不在（或换了实例）→ 需重新预热

    # ensure_daemon 内部含阻塞 sleep，放线程里避免卡住事件循环
    if not await asyncio.to_thread(ensure_daemon, bin_name, settle_s):
        return False

    deadline = time.monotonic() + ready_timeout_s
    while time.monotonic() < deadline:
        probe = await run_ncm(["state"], timeout_s=5.0, bin_name=bin_name)
        if probe.ok:
            start_keepalive()  # 高频心跳，别让 daemon 因 8s 无命令而自杀
            if _daemon_ready_at is None:
                _daemon_ready_at = time.monotonic()
            waited = time.monotonic() - _daemon_ready_at
            if waited < _PLAY_SERVICE_WARMUP_S:
                warmup = _PLAY_SERVICE_WARMUP_S - waited
                log.info("等待 ncm 播放服务预热 %.0fs（daemon 就绪后其启动约需 10s）", warmup)
                await asyncio.sleep(warmup)
            return True
        await asyncio.sleep(1.0)
    log.warning("ncm 播放守护进程在 %.0fs 内未就绪", ready_timeout_s)
    return False


# ---------------------------------------------------------------------------
# daemon 保活（关键！）
#
# app.log 揭示的机制（2026-09-05 复测更新）：
#   [PlayerDaemon] 就绪，监听 \\.\pipe\ncm-daemon
#   [PlayerDaemon] 开始播放: "xxx"
#   [PlayerDaemon] 无活跃连接，daemon 自动退出        ← 播放开始 3s 后就退！
#
# ★ daemon 的退出判定是「无客户端管道连接 ~3s」，且**播放中也不豁免**——
#   play 命令的连接 3s 超时断开后，daemon 立即自杀，连带杀死它 spawn 的 mpv。
#   用户表现："播放界面闪一下就没了 / 根本没界面 / 歌放到一半停"。
#   （2026-08-31 时观察到的"30s 空闲退出"是当时的次要路径；3s 无连接退出
#    才是主因，20s queue 心跳的间隔远大于 3s，来不及救。）
#
# 解法（2026-09-05 实测 40s+ 播放稳定、mpv 窗口常驻）：
#   主保活 = **持久打开命名管道连接**（daemon 始终有活跃连接，永不自杀）；
#   副保活 = 周期 queue 命令（顺带刷新内部状态 + 探测断线，断了就重连）。
# ---------------------------------------------------------------------------
_keepalive_task: asyncio.Task | None = None
# 心跳间隔必须 < daemon 的退出阈值（实测 ~8s 无命令活动即退出）。
# 取 4s：既有充足余量，又不会太频繁地 spawn Node 进程。
_KEEPALIVE_INTERVAL_S = 4.0


async def _keepalive_loop(interval_s: float = _KEEPALIVE_INTERVAL_S) -> None:
    """高频轻量命令心跳，使 daemon 常驻。

    ★ 重要纠错（2026-09-12）：daemon 的存活判定是「近期有**命令活动**」，
      而不是「管道有连接」——它打印的是
          [PlayerDaemon] 无活跃连接，daemon 自动退出
      但只要没有命令进来，哪怕我们持着管道连接它照样退出（阈值约 8s）。

      9/5 那次我误把"持久管道连接"当作保活手段（当时实验里恰好每 8s 调了
      一次 state，真正续命的是那些命令）；改成 20s 间隔后 daemon 频繁自杀，
      连带引发"play 命令冷启动新 daemon → 命令在就绪前被丢弃 → 队列为空、
      无声音、无 mpv 窗口"的一连串现象。

      故保活只用一种手段：**每 4s 一次 state**（最便宜的只读命令）。
    """
    while True:
        await asyncio.sleep(interval_s)
        try:
            await run_ncm(["state"], timeout_s=6)
        except Exception:  # noqa: BLE001 — daemon 不在时静默，由 ensure_daemon 重拉
            pass


def start_keepalive() -> None:
    """启动 daemon 保活循环（幂等）。须在事件循环内调用。"""
    global _keepalive_task
    if _keepalive_task is None or _keepalive_task.done():
        _keepalive_task = asyncio.create_task(_keepalive_loop())


# 进程内短缓存：Node 冷启动约 200-500ms，连续提问同一命令时避免重复 spawn。
_CACHE: dict[tuple, tuple[float, NcmResult]] = {}


async def run_ncm_cached(
    args: list[str],
    timeout_s: float = 20.0,
    ttl_s: float = 30.0,
    bin_name: str = "ncm-cli",
) -> NcmResult:
    """带 TTL 缓存的读取（仅用于幂等的查询类命令）。"""
    key = (bin_name, tuple(args))
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit is not None and now - hit[0] < ttl_s:
        return hit[1]
    result = await run_ncm(args, timeout_s, bin_name)
    if result.ok:
        _CACHE[key] = (now, result)
    return result


def cache_clear() -> None:
    """清空缓存（写操作后调用，避免读到过期列表）。"""
    _CACHE.clear()
