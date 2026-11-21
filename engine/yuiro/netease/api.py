"""网易云开放平台 API 直连（引擎自签名，2026-09-12 实测打通）。

背景（为什么不再依赖 ncm-cli 的播放链路）：
    ncm-cli 0.1.7 在**登录状态**下，daemon 收到 play 后会取到 playUrl、上报播放
    记录，却**始终不启动播放器**（实测 16s 内 mpv 进程数恒为 0、IPC 管道从未出现），
    且无任何错误日志——用户表现就是"说放歌却毫无反应、没声音没窗口"。
    （未登录时它能正常拉起 mpv，故问题锁定在它自身登录后的播放路径。）

    因此改为：**引擎自己签名调开放平台 API 拿播放地址，自己管理 mpv 播放**。
    个性化能力（搜索/歌单/推荐/收藏）全部保留——走的还是同一套官方接口。

认证机制（抓包 + 逆向 ncm-cli 混淆代码后实测确认）：
    GET https://openncm.music.163.com<path>?<params>
    参数：
      appId        应用 ID
      signType     "RSA_SHA256"
      timestamp    毫秒时间戳
      device       设备信息 JSON
      bizContent   业务参数 JSON
      accessToken  登录令牌（登录后才有）
      sign         签名
    签名算法：
      待签名串 = 除 sign 外的全部参数，**按参数名升序**拼成 "k=v&k=v&..."
                （值用原始字符串，不做 URL 编码）
      签名 = RSA-SHA256(PKCS#1 v1.5) → Base64
      ★ 已用真实请求 + 用户私钥逐字节复现验证通过。

凭证：
    AppID 与 PrivateKey 由用户提供，存放于本地（不进仓库）：
      .env-local/npm-cache/netease_private_key.pem   —— 私钥（PKCS#8，可带/不带 PEM 头）
    accessToken 由 ncm-cli 登录产生，本模块通过 Node 钩子自动获取并缓存
    （登录仍交给 ncm-cli，成本最低；播放则完全不经过它）。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BASE_URL = "https://openncm.music.163.com"
# AppID 是公开标识（会出现在请求 URL 中），允许用环境变量覆盖。
DEFAULT_APP_ID = "b3010d00000000003fd2b9cb136658ad"

# 各接口路径（与 ncm-cli 实际调用一致）
PATH_SEARCH_SONG = "/openapi/music/basic/search/song/get/v3"
PATH_SONG_DETAIL = "/openapi/music/basic/song/detail/get/v2"
PATH_SONG_LYRIC = "/openapi/music/basic/song/lyric/get/v2"
PATH_RECOMMEND_DAILY = "/openapi/music/basic/recommend/songlist/get/v2"
PATH_PLAYLIST_CREATED = "/openapi/music/basic/playlist/created/get/v2"
PATH_PLAYLIST_TRACKS = "/openapi/music/basic/playlist/song/list/get/v3"
PATH_SONG_LIKE = "/openapi/music/basic/playlist/song/like/v2"

_http_timeout_s = 15.0
# accessToken 内存缓存（长时间有效；失效时重新从 ncm-cli 取）
_token_cache: str = ""
_token_fetched_at: float = 0.0
_TOKEN_TTL_S = 6 * 3600.0
# ncm-cli 的 device 原文：accessToken 与设备绑定，必须沿用同一 device
_ncm_device: str = ""


class MusicApiError(RuntimeError):
    """保留通道错误码，不把所有拒绝都解释成用户未登录或未买会员。"""

    def __init__(self, code, message):
        self.code = code
        super().__init__(f"接口返回 code={code} message={message}")


# ---------------------------------------------------------------------------
# 路径与凭证
# ---------------------------------------------------------------------------
def _project_root() -> Path:
    """定位仓库根（engine/yuiro/netease/api.py → 上溯 4 层）。"""
    return Path(__file__).resolve().parents[3]


def _private_key_path() -> Path:
    env = os.environ.get("YUIRO_NCM_PRIVATE_KEY", "").strip()
    if env:
        return Path(env)
    return _project_root() / ".env-local" / "npm-cache" / "netease_private_key.pem"


def _app_id() -> str:
    return os.environ.get("YUIRO_NCM_APPID", "").strip() or DEFAULT_APP_ID


def _load_private_key():
    """加载 RSA 私钥（支持带/不带 PEM 头尾的裸 Base64）。"""
    from cryptography.hazmat.primitives import serialization

    path = _private_key_path()
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise RuntimeError(f"私钥文件为空: {path}")
    if "BEGIN" not in raw:
        # 裸 Base64 → 补 PEM 头尾（PKCS#8）
        body = "\n".join(raw[i : i + 64] for i in range(0, len(raw), 64))
        raw = f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----\n"
    return serialization.load_pem_private_key(raw.encode("utf-8"), password=None)


_device_cache: dict[str, str] = {}
_IP_CACHE_TTL_S = 3600.0


def _data_dir() -> Path:
    d = os.environ.get("YUIRO_DATA_DIR") or str(_project_root() / ".env-local" / "data")
    p = Path(d)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 — 建不了就用临时目录
        p = Path(tempfile.gettempdir())
    return p


def _device_id() -> str:
    """稳定的设备 ID：首次生成后持久化（服务端会校验其一致性）。"""
    if _device_cache.get("deviceId"):
        return _device_cache["deviceId"]
    f = _data_dir() / "netease_device_id.txt"
    if f.exists():
        v = f.read_text(encoding="utf-8").strip()
        if v:
            _device_cache["deviceId"] = v
            return v
    v = "ncmcli_" + os.urandom(12).hex()
    try:
        f.write_text(v, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    _device_cache["deviceId"] = v
    return v


def _client_ip() -> str:
    """公网 IP——服务端强制要求（缺失会返回 code=2511 缺少clientIp参数）。

    ★ 必须是**公网** IP（实测 ncm-cli 传的是 183.x.x.x）。本机无法自省，
      故向公共回显服务查询，并缓存 1 小时（IP 不会频繁变化）。
      查询失败时回退到上次缓存值，避免拖垮整个调用链。
    """
    now = time.monotonic()
    ip, ts = _device_cache.get("clientIp", ""), float(_device_cache.get("ipAt") or 0)
    if ip and now - ts < _IP_CACHE_TTL_S:
        return ip
    f = _data_dir() / "netease_ip_cache.txt"
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://ipinfo.io/ip"):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                got = resp.read().decode("utf-8").strip()
            if got and len(got) <= 45 and "." in got:
                _device_cache["clientIp"] = got
                _device_cache["ipAt"] = str(now)
                try:
                    f.write_text(got, encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass
                return got
        except Exception:  # noqa: BLE001 — 换下一个服务
            continue
    if f.exists():  # 全失败：用上次结果兜底
        old = f.read_text(encoding="utf-8").strip()
        if old:
            _device_cache["clientIp"] = old
            _device_cache["ipAt"] = str(now)
            return old
    return ip


def _device_json() -> str:
    """设备信息。

    ★ 优先复用 ncm-cli 的 device 原文：accessToken 绑定设备，换 deviceId 会被
      服务端判为"当前设备未授权，请重新登录"(code=1406)。仅在没有捕获到时
      才自行构造（此时需登录后重新取 token 才可用）。
    """
    if _ncm_device:
        return _ncm_device
    import platform

    return json.dumps(
        {
            "deviceType": "openapi",
            "os": "ncmcli",
            "appVer": "0.1.7",
            "channel": "ncmcli",
            "model": f"{platform.system()}_{platform.machine()}_cli",
            "brand": "ncmcli",
            "osVer": platform.version(),
            "clientIp": _client_ip(),
            "deviceId": _device_id(),
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 签名与请求
# ---------------------------------------------------------------------------
def sign_params(params: dict[str, str]) -> str:
    """按 ncm-cli 实测算法签名：字典序拼接 k=v 后用私钥 RSA-SHA256 签名。"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    payload = "&".join(f"{k}={params[k]}" for k in sorted(params))
    key = _load_private_key()
    sig = key.sign(payload.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode("ascii")


def _build_params(biz: dict[str, Any], token: str) -> dict[str, str]:
    params: dict[str, str] = {
        "appId": _app_id(),
        "signType": "RSA_SHA256",
        "timestamp": str(int(time.time() * 1000)),
        "device": _device_json(),
        "bizContent": json.dumps(biz, separators=(",", ":"), ensure_ascii=False),
    }
    if token:
        params["accessToken"] = token
    params["sign"] = sign_params(params)
    return params


def _build_url(path: str, biz: dict[str, Any], token: str) -> str:
    return f"{BASE_URL}{path}?{urllib.parse.urlencode(_build_params(biz, token))}"


_HEADERS = {"User-Agent": "ncm-0.1.7", "Referer": "https://music.163.com/"}


def _http_get(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_http_timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post(path: str, biz: dict[str, Any], token: str) -> dict[str, Any]:
    """少数接口（如私人漫游 FM）用 POST，参数集直接作为 JSON body（实测 ncm-cli 即如此）。"""
    body = json.dumps(_build_params(biz, token), ensure_ascii=False).encode("utf-8")
    headers = dict(_HEADERS)
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=_http_timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def call_api(
    path: str, biz: dict[str, Any], *, retry_on_auth: bool = True, method: str = "GET"
) -> dict[str, Any]:
    """调用开放平台接口，返回解析后的 JSON（异步封装）。"""

    async def _do(token: str) -> dict[str, Any]:
        if method.upper() == "POST":
            return await asyncio.to_thread(_http_post, path, biz, token)
        url = await asyncio.to_thread(_build_url, path, biz, token)
        return await asyncio.to_thread(_http_get, url)

    token = await ensure_token()
    data = await _do(token)
    code = data.get("code")
    if code == 200:
        return data
    # 令牌失效：刷新后重试一次
    if retry_on_auth and code in (301, 401, 1002):
        log.info("accessToken 可能失效(code=%s)，刷新后重试", code)
        fresh = await ensure_token(force=True)
        if fresh and fresh != token:
            data = await _do(fresh)
            if data.get("code") == 200:
                return data
    raise MusicApiError(data.get("code"), data.get("message"))


# ---------------------------------------------------------------------------
# accessToken：从 ncm-cli 的请求中自动获取（登录仍由 ncm-cli 完成）
# ---------------------------------------------------------------------------
_HOOK_JS = r"""
const fs = require("fs");
const OUT = process.env.YUIRO_TOKEN_FILE;
const origFetch = globalThis.fetch;
if (origFetch) {
  globalThis.fetch = async function (input, init) {
    try {
      const u = new URL(String(typeof input === "string" ? input : (input && input.url)));
      if (/openncm/.test(u.host)) {
        const t = u.searchParams.get("accessToken");
        const d = u.searchParams.get("device");
        if (t && OUT) {
          fs.writeFileSync(OUT, JSON.stringify({ accessToken: t, device: d || "" }), "utf8");
        }
      }
    } catch (e) {}
    return origFetch.apply(this, arguments);
  };
}
"""


def _ncm_cli_paths() -> tuple[str, str] | None:
    """返回 (node.exe, ncm-cli 的 index.js)；找不到则 None。"""
    import shutil

    node = shutil.which("node")
    if not node:
        return None
    # ncm-cli.cmd 里写明的入口：<node_global>/node_modules/@music163/ncm-cli/dist/index.js
    cand = []
    npm = shutil.which("npm")
    if npm:
        cand.append(Path(npm).parent / "node_modules" / "@music163" / "ncm-cli" / "dist" / "index.js")
    cand.append(
        Path(node).parent / "node_global" / "node_modules" / "@music163" / "ncm-cli" / "dist" / "index.js"
    )
    for p in cand:
        if p.exists():
            return node, str(p)
    return None


def _fetch_token_blocking() -> str:
    """跑一次带钩子的 ncm-cli 命令，拦截请求里的 accessToken。"""
    paths = _ncm_cli_paths()
    if not paths:
        return ""
    node, js = paths
    hook = Path(tempfile.gettempdir()) / "yuiro_ncm_token_hook.js"
    hook.write_text(_HOOK_JS, encoding="utf-8")
    out = Path(tempfile.gettempdir()) / "yuiro_ncm_token.txt"
    out.unlink(missing_ok=True)

    env = os.environ.copy()
    env["YUIRO_TOKEN_FILE"] = str(out)
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # 必须跑**会真正发出 API 请求**的命令才能拦到 accessToken：
    # state 由本地 daemon 响应、login --check 也可能走本地校验，都不发请求。
    # search 一定会打接口（哪怕因参数报错，请求头里的 token 也已被捕获）。
    for cmd in (
        ["search", "song", "--keyword", "token-probe", "--limit", "1"],
        ["login", "--check"],
        ["state"],
    ):
        try:
            subprocess.run(
                [node, "--require", str(hook), js, *cmd],
                env=env,
                capture_output=True,
                timeout=30,
                creationflags=creation,
            )
        except Exception:  # noqa: BLE001 — 取不到就试下一条命令
            continue
        if out.exists():
            try:
                data = json.loads(out.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — 解析失败则试下一条命令
                continue
            if data.get("accessToken"):
                return data
    return {}


async def ensure_token(force: bool = False) -> str:
    """确保拿得到 accessToken（带内存缓存）。

    ★ 同时缓存 ncm-cli 的 device：accessToken 与**设备绑定**，用随机 deviceId
      调接口会被判"当前设备未授权，请重新登录"(code=1406)。实测确认。
    """
    global _token_cache, _token_fetched_at, _ncm_device
    fresh = _token_cache and (time.monotonic() - _token_fetched_at) < _TOKEN_TTL_S
    if fresh and not force:
        return _token_cache
    got = await asyncio.to_thread(_fetch_token_blocking)
    if got.get("accessToken"):
        _token_cache = got["accessToken"]
        _token_fetched_at = time.monotonic()
        if got.get("device"):
            _ncm_device = got["device"]
        log.info("已从 ncm-cli 获取 accessToken（len=%d）与设备信息", len(_token_cache))
    return _token_cache


# ---------------------------------------------------------------------------
# 业务接口
# ---------------------------------------------------------------------------
async def search_song(keyword: str, limit: int = 20) -> list[dict]:
    data = await call_api(
        PATH_SEARCH_SONG,
        {"keyword": keyword, "limit": str(limit), "offset": 0,
         "qualityFlag": False, "trialScene": "cli"},
    )
    inner = data.get("data") or {}
    return [r for r in (inner.get("records") or []) if isinstance(r, dict)]


async def song_detail(encrypted_id: str, *, with_url: bool = True, bitrate: int = 128) -> dict:
    """歌曲详情；with_url=True 时返回 playUrl（可直接交给 mpv 播放）。"""
    data = await call_api(
        PATH_SONG_DETAIL,
        {"songId": encrypted_id, "withUrl": with_url, "bitrate": bitrate, "trialScene": "cli"},
    )
    return data.get("data") or {}


async def recommend_daily(limit: int = 10) -> list[dict]:
    """每日推荐。返回结构为 data: [...]（实测）。"""
    data = await call_api(
        PATH_RECOMMEND_DAILY,
        {"limit": str(limit), "qualityFlag": False, "trialScene": "cli"},
    )
    inner = data.get("data")
    if isinstance(inner, list):
        return [r for r in inner if isinstance(r, dict)]
    if isinstance(inner, dict):
        return [r for r in (inner.get("records") or []) if isinstance(r, dict)]
    return []


async def playlist_created(limit: int = 50) -> list[dict]:
    data = await call_api(PATH_PLAYLIST_CREATED, {"limit": str(limit), "offset": 0})
    inner = data.get("data") or {}
    return [r for r in (inner.get("records") or []) if isinstance(r, dict)]


async def playlist_tracks(encrypted_id: str, limit: int = 50) -> list[dict]:
    data = await call_api(
        PATH_PLAYLIST_TRACKS,
        {"playlistId": encrypted_id, "limit": str(limit), "offset": 0},
    )
    inner = data.get("data") or {}
    return [r for r in (inner.get("records") or []) if isinstance(r, dict)]


async def song_lyric(encrypted_id: str) -> dict:
    data = await call_api(
        PATH_SONG_LYRIC, {"songId": encrypted_id, "lv": -1, "kv": -1, "tv": -1}
    )
    return data.get("data") or {}


async def song_like(encrypted_id: str, like: bool = True) -> dict:
    """红心 / 取消红心（收藏歌曲）。

    ★ 该接口必须用 POST（实测 GET 报 400；ncm-cli 亦为 POST + JSON body）。
    """
    data = await call_api(
        PATH_SONG_LIKE,
        {"songId": encrypted_id, "isLike": like},  # ★ 参数名是 isLike，写错会 400
        method="POST",
    )
    return data.get("data") or {}


# ---------------------------------------------------------------------------
# 个人音乐库 / 发现（2026-09-14 扩展：参数均来自对 ncm-cli 实际请求的抓取）
# ---------------------------------------------------------------------------
PATH_PLAY_HISTORY = "/openapi/music/basic/song/play/record/list"
PATH_PLAYLIST_COLLECTED = "/openapi/music/basic/playlist/star/get/v2"
PATH_PLAYLIST_SUBED = "/openapi/music/basic/playlist/subed/get/v2"
PATH_ALBUM_COLLECTED = "/openapi/music/basic/album/subed/get/v2"
PATH_PLAYLIST_DETAIL = "/openapi/music/basic/playlist/detail/get/v2"
PATH_ROAMING_FM = "/openapi/music/basic/private/fm/roaming/song/list"
PATH_ARTIST_SONGS = "/openapi/music/basic/song/artist/bypubtime/get/v2"
PATH_USER_PROFILE = "/openapi/music/basic/user/profile/get/v2"
PATH_PLAYLIST_RADAR = "/openapi/music/basic/playlist/radar/get"


def _records_of(data: dict) -> list[dict]:
    inner = data.get("data")
    if isinstance(inner, list):
        return [r for r in inner if isinstance(r, dict)]
    if isinstance(inner, dict):
        # 各接口字段名不一：search/playlist → records；history → songListVo；
        # 推荐/FM 偶用 songs/list。逐个兜住，避免"明明有数据却解析成 0 条"。
        for key in ("records", "songListVo", "songs", "list"):
            v = inner.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


async def play_history(limit: int = 30) -> list[dict]:
    """最近播放的歌曲。"""
    data = await call_api(PATH_PLAY_HISTORY, {"limit": str(limit), "qualityFlag": False})
    return _records_of(data)


async def playlist_collected(limit: int = 30) -> list[dict]:
    """我收藏的歌单。"""
    data = await call_api(PATH_PLAYLIST_COLLECTED, {"limit": str(limit), "offset": 0})
    return _records_of(data)


async def playlist_subed(limit: int = 30) -> list[dict]:
    """我收藏/订阅的歌单（另一入口，部分账号以此为准）。"""
    data = await call_api(PATH_PLAYLIST_SUBED, {"limit": str(limit), "offset": 0})
    return _records_of(data)


async def favorite_playlist() -> dict:
    """我的红心歌单（"我喜欢的音乐"）。"""
    data = await call_api(PATH_PLAYLIST_SUBED, {"limit": "100", "offset": 0})
    for r in _records_of(data):
        name = str(r.get("name") or "")
        if "喜欢" in name or r.get("specialType") == 5:
            return r
    return {}


async def album_collected(limit: int = 20) -> list[dict]:
    """我收藏的专辑。

    ⚠ 2026-09-14 实测：该接口服务端返回 HTTP 400（ncm-cli 自身同样失败），
      疑为接口未开放或账号无权限，故暂未暴露给工具。保留实现待其恢复。
    """
    data = await call_api(PATH_ALBUM_COLLECTED, {"limit": str(limit)})
    return _records_of(data)


async def playlist_detail(playlist_id: str) -> dict:
    """歌单详情。"""
    data = await call_api(
        PATH_PLAYLIST_DETAIL, {"playlistId": playlist_id, "originalCoverFlag": False}
    )
    inner = data.get("data")
    return inner if isinstance(inner, dict) else {}


async def roaming_fm() -> list[dict]:
    """私人漫游（FM）：返回一批推荐歌曲。

    ★ 必须用 POST（实测 GET 报 400；ncm-cli 亦为 POST + JSON body）。
    ⚠ 但即便用 POST，服务端当前仍返回 400（ncm-cli 自身同样失败），
      故暂未暴露给工具；用「每日推荐 / 歌单雷达」替代"发现新歌"的场景。
    """
    data = await call_api(PATH_ROAMING_FM, {}, method="POST")
    return _records_of(data)


async def playlist_radar() -> list[dict]:
    """歌单雷达：按口味生成的一组歌单。"""
    data = await call_api(PATH_PLAYLIST_RADAR, {})
    return _records_of(data)


async def artist_songs(artist_id: str, limit: int = 20) -> list[dict]:
    """某位艺人的歌曲（artist_id 为加密 ID，取自搜索结果的 artists[].id）。"""
    data = await call_api(PATH_ARTIST_SONGS, {"artistId": artist_id, "limit": str(limit)})
    return _records_of(data)


async def user_profile() -> dict:
    """当前账号信息（昵称/头像/VIP 等）。"""
    data = await call_api(PATH_USER_PROFILE, {})
    inner = data.get("data")
    return inner if isinstance(inner, dict) else {}
