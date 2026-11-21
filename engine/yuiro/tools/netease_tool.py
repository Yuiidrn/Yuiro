"""网易云音乐工具组（LLM 可见）——引擎自管播放链路。

架构（2026-09-12 定稿，替换掉 ncm-cli 的播放链路）：
    工具层 → yuiro.netease.api    自签名调开放平台接口（搜索/详情/推荐/歌单/歌词）
           → yuiro.netease.player 引擎自管 mpv（播放 + IPC 控制 + 原生播放列表）

为什么不再用 ncm-cli 播放：
    ncm-cli 0.1.7 在登录态下，daemon 收到 play 后能取到 playUrl、能上报播放记录，
    却**始终不启动播放器进程**（实测 mpv 进程恒为 0、IPC 管道从未出现），无任何
    错误日志，用户表现是"说放歌却毫无反应、没声音没窗口"。改用自签名 API + 自管
    mpv 后链路完全可控；个性化能力（搜索/歌单/推荐/收藏）一个不少——同源接口。

登录：仍交给 ncm-cli（扫码流程成熟，见 netease_login）；登录后本模块通过 Node
      钩子自动取回 accessToken 与设备信息，后续接口调用全由引擎自己完成。

能力划分（与系统工具风格一致）：
  netease_login     扫码登录（弹二维码图片）
  netease_search    搜索歌曲/歌单
  netease_play      点歌（关键词 / song_id / 歌单）——直接出声
  netease_control   暂停/继续/切歌/停止/音量/查看当前播放
  netease_playlist  我的歌单 / 歌单内歌曲
  netease_recommend 每日推荐——直接播放整列
  netease_lyric     歌词
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path

from yuiro.config import NeteaseConfig
from yuiro.netease import api, check_login, fetch_login_qr, player, render_qr_png
from yuiro.netease.availability import song_availability, unavailable_note
from yuiro.tools import BaseTool

log = logging.getLogger(__name__)

_MAX_CANDIDATES = 5

# 当前播放的歌曲（播放时记住）：
# mpv 的 media-title 只是音频文件名（形如 xxx.mp3），拿不到歌曲 ID，
# 因此"收藏这首歌""这首歌叫什么"这类指令需要靠这里记录的元数据。
_current_song: dict | None = None


def _remember_current(song: dict | None) -> None:
    global _current_song
    if song:
        _current_song = song

# 非原版/翻唱标记（点歌时用于避免把翻版当原唱自动播放）
_RE_NON_ORIGINAL = re.compile(
    r"remix|bootleg|beat|trap|remake|电音|electronic|dubstep|"
    r"伴奏|live|演唱会|纯音乐|instrumental|DJ版|铃声|"
    r"翻唱|cover|钢琴版|吉他版|鼓点|清唱|弹唱|串烧|现场|翻跳",
    re.IGNORECASE,
)
_RE_COVER_MARK = re.compile(r"原唱|翻唱|cover", re.IGNORECASE)


def _compact(s: str) -> str:
    return re.sub(r"[\s\-_/()（）【】\[\]]", "", (s or "")).lower()


def _brief_song(r: dict) -> dict:
    artists = r.get("artists") or []
    return {
        "name": r.get("name", ""),
        "artist": "、".join(a.get("name", "") for a in artists if isinstance(a, dict)),
        "album": (r.get("album") or {}).get("name", "") if isinstance(r.get("album"), dict) else "",
        "duration_s": round((r.get("duration") or 0) / 1000),
        "song_id": r.get("originalId"),
        "encrypted_id": r.get("id"),
        **song_availability(r),
    }


def _brief_playlist(r: dict) -> dict:
    return {
        "name": r.get("name", ""),
        "track_count": r.get("trackCount"),
        "play_count": r.get("playCount"),
        "playlist_id": r.get("originalId"),
        "encrypted_id": r.get("id"),
    }


# ── S41：把"某某歌单"匹配到账号里的具体歌单 ──────────────────────────────
#: 语义命中的相似度下限（BGE-M3 余弦；低于它宁可让用户选）
_SEMANTIC_HIT = 0.62
#: top1 要领先 top2 这么多才算"确定"（否则列表里有俩差不多的，猜一个不如问一句）
_SEMANTIC_GAP = 0.04

_embedder_singleton: object | None = None
_embedder_failed = False


def _get_embedder():
    """惰性获取嵌入器（BGE-M3 子进程）。

    只在**字面匹配不够**时才调用 —— 歌单名通常很短，精确/包含匹配已覆盖多数说法，
    没必要为每次点歌拉起一个模型子进程。不可用时返回 None（纯字面模式）。
    """
    global _embedder_singleton, _embedder_failed
    if _embedder_singleton is not None or _embedder_failed:
        return _embedder_singleton
    try:
        from yuiro.config import load_config
        from yuiro.logger import vlog
        from yuiro.memory import Embedder

        # 跟随 [memory].embedder —— 工具层与记忆系统必须用**同一个**嵌入模型：
        # 否则用户明确配成 md5（接受降级）时，这里还会偷偷去加载真模型。
        model = str(getattr(load_config().memory, "embedder", "") or "")
        if not model or model == "md5":
            _embedder_failed = True
            vlog("netease", "[歌单匹配] 配置为 md5（无语义），只做字面匹配")
            return None
        _embedder_singleton = Embedder(model)
    except Exception as exc:  # noqa: BLE001 — 装不上就纯字面匹配
        _embedder_failed = True
        from yuiro.logger import vlog

        vlog("netease", f"[歌单匹配] 嵌入器不可用，按字面匹配：{exc}")
    return _embedder_singleton


def _norm_name(s: str) -> str:
    """歌单名归一：去空白/括号/书名号等装饰，便于比较。"""
    return re.sub(r"[\s\-_/()（）【】\[\]《》\"'·、，,]+", "", (s or "")).lower()


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def _match_playlist(
    query: str, lists: list[dict], *, top: int = 30
) -> tuple[dict | None, list[dict], str]:
    """把自然语言歌单名匹配到账号里的具体歌单 → ``(命中, 候选, 依据)``。

    **两级匹配**（这是"播放我账号里的某某歌单"能work的关键）：

    1. **字面**（便宜且准）：完全相等 → 包含 → 反向包含；
    2. **语义向量**（BGE-M3）：覆盖"那个学习的歌单""晚上跑步听的"这类**描述性说法**；
       只有字面完全没着落时才启用，避免为每次点歌拉起模型子进程。

    仍不够确定（top1/top2 接近、或相似度低于阈值）→ 返回候选让用户选。
    **猜错一张歌单 = 整列放错歌**，这种代价不值得赌。
    """
    q = _norm_name(query)
    if not q or not lists:
        return None, [], ""

    named = [(r, _norm_name(str(r.get("name") or ""))) for r in lists]
    # 1) 字面
    for predicate in (
        lambda n: n == q,                     # 完全相等
        lambda n: n and (q in n or n in q),   # 双向包含
    ):
        hit = [r for r, n in named if predicate(n)]
        if len(hit) == 1:
            return hit[0], [], "字面"

    # 2) 语义（仅当"字面毫无着落"= 用户是在描述而非念名字）
    if not any(q and (q in n or n in q) for _, n in named):
        emb = _get_embedder()
        if emb is not None:
            try:
                # 等子进程就绪：未就绪时 embed 会**静默降级成 md5 向量**（无语义，
                # 相似度≈随机）—— 那样"语义匹配"会假装跑过却全错。宁可等几秒。
                waiter = getattr(emb, "wait_ready", None)
                if waiter is not None and not await waiter(8.0):
                    raise RuntimeError("嵌入器未就绪（避免用无语义的 md5 向量匹配）")
                # 一次算完（query + 全部候选名）：逐条 embed 在 50+ 歌单时要 50+ 次
                # 子进程往返，实测慢到语义这条路等于没做（"学习"匹配不到"自习室"）。
                targets = [r for r, n in named if n]
                names = [str(r.get("name") or "") for r in targets]
                many = getattr(emb, "embed_many", None)
                scored: list[tuple[float, dict]] = []
                if many is not None:
                    vecs = await many([query, *names])
                    qv, rest = vecs[0], vecs[1:]
                    scored = [(_cos(qv, v), r) for r, v in zip(targets, rest)]
                else:
                    qv = await emb.embed(query)
                    for r, n in zip(targets, names):
                        scored.append((_cos(qv, await emb.embed(n)), r))
                scored.sort(key=lambda x: -x[0])
                if scored and scored[0][0] >= _SEMANTIC_HIT:
                    lead = scored[0][0] - scored[1][0] if len(scored) > 1 else 1.0
                    if lead >= _SEMANTIC_GAP:
                        return scored[0][1], [], f"语义 {scored[0][0]:.2f}"
                    return None, [r for _, r in scored[:top]], "语义接近，需用户选"
            except Exception as exc:  # noqa: BLE001 — 向量不可用则退回候选
                from yuiro.logger import vlog

                vlog("netease", f"[歌单匹配] 语义计算失败，退回字面候选：{exc}")

    # 3) 都不确定 → 给候选让用户选（配合结果卡展示）
    pool = [r for r, n in named if q and (q in n or n in q)] or lists
    return None, pool[:top], "无确定命中"


async def _account_playlists(limit: int = 50) -> list[dict]:
    """账号里的全部歌单：我创建的 + 我订阅/收藏的，按名字去重。

    此前只查 ``playlist_created``（我创建的）—— 实测用户说"我的歌单"时
    多半指的是订阅的那批，只列创建的会显得"少了几个"。
    """
    merged: dict[str, dict] = {}

    # 红心歌单（"我喜欢的音乐"）单独取：它是 specialType=5 的特殊歌单，
    # subed/created 两个入口都不返回它 —— 实测用户说"放我喜欢的音乐"却找不到。
    try:
        fav = await api.favorite_playlist()
        if fav:
            merged[_norm_name(str(fav.get("name") or "")) or "favorite"] = fav
    except Exception as exc:  # noqa: BLE001 — 拿不到红心歌单不影响其余
        from yuiro.logger import vlog

        vlog("netease", f"[歌单] 红心歌单读取失败（忽略）：{exc}")

    for fetcher in (api.playlist_subed, api.playlist_created, api.playlist_collected):
        try:
            for r in await fetcher(limit):
                key = _norm_name(str(r.get("name") or "")) or str(r.get("id") or "")
                merged.setdefault(key, r)
        except Exception as exc:  # noqa: BLE001 — 单个入口失败不影响其余
            from yuiro.logger import vlog

            vlog("netease", f"[歌单] 入口 {fetcher.__name__} 读取失败（忽略）：{exc}")
            continue
    return list(merged.values())


async def _resolve_playlist_encrypted(pid: str) -> str:
    """把"歌单 ID"解析成播放接口需要的**加密 id**。

    账号歌单接口给的是 ``originalId``（明文），而取歌曲列表的接口要 ``id``（加密）——
    此前直接把明文塞进去，是"歌单播放不好用"的一个来源。两种 ID 现在都能喂进来。
    """
    if not pid:
        return ""
    pid = str(pid).strip()
    from yuiro.logger import vlog

    try:
        for r in await _account_playlists():
            if pid in (str(r.get("id") or ""), str(r.get("originalId") or "")):
                return str(r.get("id") or pid)
    except Exception as exc:  # noqa: BLE001 — 解析失败退回原值
        vlog("netease", f"[歌单] 账号歌单里没解析到 {pid}（{exc}），改用详情接口")
    try:
        detail = await api.playlist_detail(pid)
        return str(detail.get("id") or pid)
    except Exception as exc:  # noqa: BLE001
        vlog("netease", f"[歌单] 详情接口也没解析到 {pid}（{exc}），按原值尝试")
        return pid


# ---------------------------------------------------------------------------
# 系统媒体会话（SMTC）转发：桌宠的 mpv 空闲时，"暂停/下一首"这类命令多半是在说
# 用户自己开着的那个播放器（网易云客户端等）。
#
# 背景（2026-09-16 实测厘清）：网易云客户端在设置里勾选「开启 SMTC」后会注册
# 系统媒体会话（实测 aumid = ``cloudmusic.exe``），因此可被系统级读取与控制。
# 同批还纠了一个乌龙：native 后端的 SMTC 查询桥用了只有 pwsh 7 才有的
# ``IAsyncOperation.GetAwaiter()``，在 Windows PowerShell 5.1 下**从未成功过**，
# 失败被误读成"网易云不注册会话"，还写进了设计文档（已更正）。
# ---------------------------------------------------------------------------
#: 可转投 SMTC 的控制动作（SMTC 无 stop 接口，以 pause 等价）
_SMTC_FORWARD_ACTIONS: dict[str, str] = {
    "pause": "pause",
    "resume": "play",
    "next": "next",
    "prev": "prev",
    "stop": "stop",
}


async def _system_session() -> dict | None:
    """显式客户端桥接辅助：只读取唯一 cloudmusic.exe 会话，不猜其他播放器。

    返回 ``{'aumid','status','title','artist'}``；无会话或桥不可用时 None。
    """
    try:
        from yuiro.native.backend import NativeBackend

        result = await NativeBackend(txn_enabled=False).call("media_control", {"action": "list_sessions"})
        status, out = result.status, result.stdout
    except Exception as exc:  # noqa: BLE001 — 转发是锦上添花，失败不该影响主流程
        log.debug("SMTC 会话探测失败: %s", exc)
        return None
    if status != "ok":
        return None
    try:
        sessions = json.loads(out)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(sessions, list):
        return None

    matched = [s for s in sessions if isinstance(s, dict)
               and str(s.get("aumid") or "").casefold() == "cloudmusic.exe"]
    return matched[0] if len(matched) == 1 else None


async def _forward_to_system(action: str) -> dict | None:
    """把控制动作转投系统媒体会话。返回 None 表示无目标可投（调用方照常报错）。"""
    mapped = _SMTC_FORWARD_ACTIONS.get(action)
    if not mapped:
        return None
    sess = await _system_session()
    if sess is None:
        return None
    try:
        from yuiro.native.backend import NativeBackend

        result = await NativeBackend(txn_enabled=False).call(
            "media_control", {"action": mapped, "target": str(sess["aumid"])}
        )
        status, out = result.status, result.stdout
    except Exception as exc:  # noqa: BLE001
        log.debug("SMTC 转发失败: %s", exc)
        return None
    if status != "ok":
        return None
    return {
        "status": "ok",
        "forwarded": True,
        "target": sess.get("aumid"),
        "note": (
            "已按明确指定的客户端目标执行控制"
            f"（{sess.get('aumid')}）。向用户说明时请讲清是控制了他的播放器，"
            "不要声称是桌宠在播。"
        ),
        "external": {"title": sess.get("title"), "artist": sess.get("artist")},
        "result": out,
    }


def _err(exc: Exception, *, cfg: NeteaseConfig | None = None) -> str:
    """统一错误出口：登录类问题自动弹二维码（不依赖 LLM 是否想起调 netease_login）。"""
    msg = str(exc)
    low = msg.lower()
    need_login = getattr(exc, "code", None) in (301, 401, 1002) or any(
        k in low for k in ("未登录", "登录已失效", "登录过期", "token expired", "invalid token",
                           "token失效", "令牌过期", "请重新登录")
    )
    if need_login:
        return json.dumps(
            {
                "status": "need_login",
                "message": "网易云登录已失效。请让用户用手机网易云 App 扫码登录"
                           "（桌宠会弹出二维码），登录后即可继续。",
            },
            ensure_ascii=False,
        )
    return json.dumps({"status": "error", "message": msg[:200]}, ensure_ascii=False)


async def _play_songs(songs: list[dict], limit: int) -> tuple[bool, list[dict], list[dict]]:
    """把一组歌曲（含加密 ID）解析成直链并交给 mpv 播放。"""
    urls: list[str] = []
    titles: list[str] = []
    briefs: list[dict] = []
    playable_briefs: list[dict] = []
    for s in songs[:limit]:
        eid = str(s.get("id") or "")
        if not eid:
            continue
        briefs.append(_brief_song(s))
        try:
            detail = await api.song_detail(eid)
        except Exception as exc:  # noqa: BLE001 — 单曲失败不影响整列
            log.warning("取播放地址失败 %s: %s", s.get("name"), exc)
            continue
        if (song_availability(detail, detail=True)["availability"] == "api_available"
                and str(detail.get("originalId") or "") == str(s.get("originalId") or "")):
            urls.append(detail["playUrl"])
            titles.append(detail.get("name") or "")
            playable_briefs.append(_brief_song(detail))
    if not urls:
        return False, briefs, []
    ok = await player.play_urls(urls, titles)
    if ok:
        _remember_current(playable_briefs[0] if playable_briefs else None)
    return ok, briefs, titles


async def _pick_best(keyword: str) -> tuple[dict | None, list[dict] | None]:
    """关键词选歌：只自动播「可播且强匹配原版」；否则给候选让用户确认。"""
    records = await api.search_song(keyword, 40)
    if not records:
        return None, None
    tokens = [t for t in keyword.split() if t]
    song_tok = _compact(tokens[-1]) if tokens else ""
    artist_tok = _compact(" ".join(tokens[:-1])) if len(tokens) > 1 else ""

    def strong(r: dict) -> bool:
        name = r.get("name") or ""
        name_c = _compact(name)
        if not song_tok or song_tok not in name_c:
            return False
        if _RE_COVER_MARK.search(name) or _RE_NON_ORIGINAL.search(name):
            return False
        if not artist_tok:
            return True
        prim = (r.get("artists") or r.get("fullArtists")) or []
        prim_c = _compact(" ".join(a.get("name", "") or "" for a in prim if isinstance(a, dict)))
        return artist_tok in prim_c if prim_c else artist_tok in name_c

    matched = [r for r in records if strong(r)]
    if matched:
        # S45：这里曾静默过滤通道不可播的原版，再返回第一个同名曲，
        # 就会播"同名的另一首歌"（实测：点/说《LIFE》(Neuro-sama)
        # 播成了 Life(Tobu)），而调用方与用户**都无从知晓**。
        # 现在：同名多候选就交给用户选，不替他决定 —— 与 S41 歌单匹配同一条原则：
        # **不确定时给候选，而不是猜一个再当成功。**
        if len(matched) > 1 or song_availability(matched[0])["availability"] != "api_available":
            return None, [_brief_song(r) for r in matched[:5]]
        return matched[0], None
    opts, seen = [], set()
    for r in records:
        if song_tok and song_tok not in _compact(r.get("name") or ""):
            continue
        oid = r.get("originalId")
        if oid in seen:
            continue
        seen.add(oid)
        opts.append(_brief_song(r))
    return None, (opts[:5] or None)


class NeteaseLoginTool(BaseTool):
    """扫码登录（登录仍交给 ncm-cli：其扫码流程成熟，登录后引擎自取 token 与设备信息）。"""

    name = "netease_login"
    description = (
        "登录/重新授权网易云账号：会把一张二维码图片弹到屏幕上，"
        "让用户用手机网易云 App 扫码即可完成授权。"
        "当其他网易云工具返回“登录失效/需要登录”时调用本工具，"
        "不要重复调用原工具，也不要让用户自己去敲命令行。"
    )
    approval_required = False
    requires_env = "ncm-cli"

    def __init__(self, daemon=None, config: NeteaseConfig | None = None) -> None:
        del daemon
        self._cfg = config or NeteaseConfig()

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del args, task_id
        if await check_login(self._cfg.bin):
            return json.dumps(
                {"status": "ok", "message": "网易云已经登录着，不用重新扫码，直接继续就行"},
                ensure_ascii=False,
            )
        url, err = await fetch_login_qr(self._cfg.bin)
        if err:
            return json.dumps({"status": "error", "message": err}, ensure_ascii=False)
        path = Path(os.environ.get("YUIRO_DATA_DIR") or tempfile.gettempdir()) / "netease_login_qr.png"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        shown = False
        if render_qr_png(url, str(path)):
            try:
                os.startfile(str(path))
                shown = True
            except Exception as exc:  # noqa: BLE001
                log.warning("打开二维码失败: %s", exc)
        if not shown:
            return json.dumps(
                {"status": "error", "message": f"二维码没能弹出，可让用户用手机打开：{url}"},
                ensure_ascii=False,
            )
        for _ in range(5):
            await asyncio.sleep(5)
            if await check_login(self._cfg.bin):
                await api.ensure_token(force=True)  # 刷新引擎侧 token
                return json.dumps(
                    {"status": "ok", "message": "登录成功！已经可以继续放歌了"},
                    ensure_ascii=False,
                )
        return json.dumps(
            {"status": "pending",
             "message": "二维码已经弹在屏幕上了，请用手机网易云 App 扫码授权；扫完跟我说一声。"},
            ensure_ascii=False,
        )


class NeteaseSearchTool(BaseTool):
    name = "netease_search"
    description = (
        "搜索网易云音乐：按歌名、歌手、专辑或歌单名找资源。"
        "用户想听某首歌/某位歌手的歌时先调用它拿候选，再用 netease_play 播放。"
    )
    approval_required = False
    requires_env = "ncm-cli"

    def __init__(self, daemon=None, config: NeteaseConfig | None = None) -> None:
        del daemon
        self._cfg = config or NeteaseConfig()

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string",
                                    "description": "搜索关键词，如 '周杰伦 晴天'、'林俊杰'"},
                        "limit": {"type": "integer",
                                  "description": f"返回条数，默认 {_MAX_CANDIDATES}"},
                    },
                    "required": ["keyword"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        keyword = str(args.get("keyword", "")).strip()
        if not keyword:
            return json.dumps({"status": "error", "message": "缺少搜索关键词"}, ensure_ascii=False)
        limit = min(int(args.get("limit") or _MAX_CANDIDATES), _MAX_CANDIDATES * 2)
        try:
            records = await api.search_song(keyword, max(limit, 10))
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
        items = [_brief_song(r) for r in records[:limit]]
        if not items:
            return json.dumps(
                {"status": "ok", "count": 0, "message": f"没找到与「{keyword}」相关的内容"},
                ensure_ascii=False,
            )
        # 保留服务端检索顺序；不能把不可播原版挤走、优先推荐可播 Remix。
        return json.dumps(
            {"status": "ok", "count": len(items), "keyword": keyword, "items": items},
            ensure_ascii=False,
        )


class NeteasePlayTool(BaseTool):
    """点歌：关键词/ID/歌单 → 取直链 → 引擎自管 mpv 播放（有窗口、可手动操作）。"""

    name = "netease_play"
    description = (
        "播放网易云音乐的歌曲或歌单（会真正出声，并弹出播放窗口）。"
        "点歌可给 keyword，只有唯一强匹配原版且当前通道可播才自动播放；否则返回候选，不替换版本。"
        "也可给 song_id/encrypted_id，指定的歌曲 ID 不得改变。"
        "**播放我账号里的歌单**时用 playlist_name：可以说歌单名（\"我喜欢的音乐\"），"
        "也可以只说个描述（\"那个学习的歌单\"）—— 内部按字面 + 语义在你的账号歌单里匹配；"
        "匹配不确定会返回候选，请把候选列给用户选，不要猜。"
    )
    approval_required = False
    requires_env = "ncm-cli"

    def __init__(self, daemon=None, config: NeteaseConfig | None = None) -> None:
        del daemon
        self._cfg = config or NeteaseConfig()

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string",
                                    "description": "歌曲/歌手关键词，如 '周杰伦 晴天'。与 song_id、playlist_id 三选一"},
                        "song_id": {"type": "string",
                                    "description": "歌曲明文 ID（netease_search 返回的 song_id）"},
                        "encrypted_id": {"type": "string",
                                         "description": "歌曲加密 ID（netease_search 返回的 encrypted_id，配合 song_id 可直接播放）"},
                        "playlist_id": {"type": "string",
                                        "description": "歌单 ID（明文 originalId 或加密 id 均可）"},
                        "playlist_name": {"type": "string",
                                          "description": "歌单名或其描述（如 '我喜欢的音乐'、"
                                                         "'那个晚上跑步听的'）。用户让我放"
                                                         "'他账号里的某个歌单'却没给 ID 时用它"},
                        "artist": {"type": "string", "description": "可选，歌手名，用于缩小搜索范围"},
                    },
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        keyword = str(args.get("keyword", "")).strip()
        song_id = str(args.get("song_id") or "").strip()
        if args.get("backend", "builtin") != "builtin":
            return json.dumps({"status": "error", "message": "该播放工具仅绑定自管 mpv，未切换播放器"}, ensure_ascii=False)
        encrypted = str(args.get("encrypted_id") or "").strip()
        playlist_id = str(args.get("playlist_id") or "").strip()
        playlist_name = str(args.get("playlist_name") or "").strip()
        if artist := str(args.get("artist", "")).strip():
            keyword = f"{artist} {keyword}".strip()

        picked: dict | None = None

        # 0) 按**名字/描述**播歌单（S41）：用户说"放我账号里的某个歌单"时走这条。
        #    字面 → 语义两级匹配；**不确定就返回候选让用户选，绝不猜** ——
        #    猜错一张歌单等于整列放错歌，这个代价不值得赌。
        if playlist_name and not (playlist_id or song_id or encrypted):
            try:
                lists = await _account_playlists()
            except Exception as exc:  # noqa: BLE001
                return _err(exc)
            if not lists:
                return json.dumps(
                    {"status": "pending", "played": False,
                     "message": "没读到你账号里的歌单（可能是登录失效）"},
                    ensure_ascii=False,
                )
            matched, options, why = await _match_playlist(playlist_name, lists)
            if matched is None:
                briefs = [_brief_playlist(r) for r in options]
                return json.dumps(
                    {
                        "status": "need_choice",
                        "message": (
                            f"「{playlist_name}」没能唯一定位到你的歌单（{why}）。"
                            "下面是候选清单：**如果其中有明显对应的，请你直接挑一个**"
                            "（用它的 encrypted_id 再调一次 netease_play 即可播放）；"
                            "拿不准就把清单念给用户、让他选。"
                        ),
                        "playlists": briefs,
                        "options": briefs,
                    },
                    ensure_ascii=False,
                )
            playlist_id = str(matched.get("id") or "")
            from yuiro.logger import vlog

            vlog(
                "netease",
                f"[歌单匹配] {playlist_name!r} → 《{matched.get('name')}》（{why}）",
            )

        # 1) 歌单播放（playlist_id 可能是明文 originalId，统一解析成加密 id ——
        #    取歌曲列表的接口要的是加密 id，此前直接塞明文是"歌单播放不好用"的来源之一）
        if playlist_id and not (song_id or encrypted):
            enc = await _resolve_playlist_encrypted(playlist_id)
            try:
                tracks = await api.playlist_tracks(enc or playlist_id, 50)
            except Exception as exc:  # noqa: BLE001
                return _err(exc)
            if not tracks:
                return json.dumps({"status": "pending", "played": False,
                                   "message": "这个歌单里没读到歌"}, ensure_ascii=False)
            ok, briefs, _ = await _play_songs(tracks, 30)
            return json.dumps(
                {"status": "ok" if ok else "pending", "played": ok,
                 "playlist_id": playlist_id, "count": len(briefs),
                 "tracks": briefs[:10], "state": await player.get_state()},
                ensure_ascii=False,
            )

        # 2) 指定歌曲（**有加密 ID 最省事**；只有明文 ID 时得先解析）
        if not encrypted and song_id:
            # S45：明文 ID **不能**直接查详情（实测接口返回 400「参数错误：28830410」），
            # 只能靠搜索解析成加密 ID；而搜索接口匹配的是**歌名/歌手** ——
            # 把 ID 当关键词必然搜不到。原实现正是拿 ID 去搜（等于白搜一次），
            # 最终落到下面的兜底分支报「请给 …song_id…」——而用户明明给了 song_id，
            # 错误信息**完全误导**（实测日志）。
            query = keyword.strip()
            try:
                records = await api.search_song(query, 20) if query else []
            except Exception as exc:  # noqa: BLE001
                return _err(exc)
            for r in records:
                if str(r.get("originalId")) == song_id:
                    encrypted = str(r.get("id") or "")
                    picked = r
                    break
        elif encrypted and song_id:
            picked = {"originalId": song_id, "id": encrypted}

        # 3) 关键词点歌：强匹配优先，否则给候选让用户挑
        if not encrypted:
            if not keyword:
                # S45：原提示是「请给歌曲关键词、song_id 或 playlist_id 之一」——
                # 但调用方**明明给了 song_id**，只是它（明文 ID）解析不成加密 ID。
                # 误导性提示会把排查引到错方向（实测日志里就是这条在误导），
                # 改成如实说明：缺的是什么、该怎么办。
                return json.dumps(
                    {
                        "status": "error",
                        "message": (
                            "这条请求只给了明文 song_id，而**明文 ID 无法直接播放**"
                            "（接口只接受 encrypted_id，实测返回 400）。"
                            "请改传 encrypted_id，或补上歌名（keyword）让我重新定位。"
                        ),
                    },
                    ensure_ascii=False,
                )
            try:
                best, options = await _pick_best(keyword)
            except Exception as exc:  # noqa: BLE001
                return _err(exc)
            if options:
                return json.dumps(
                    {"status": "need_choice",
                     "message": f"「{keyword}」需要确认具体版本及当前 API 可播性。"
                                "不可播不等于无版权或未开会员；不得自行换为 Remix/翻唱。"
                                "请让用户选择，确认后传 song_id + encrypted_id。",
                     "options": options},
                    ensure_ascii=False,
                )
            if not best:
                return json.dumps(
                    {"status": "pending", "played": False,
                     "message": f"没找到可播放的「{keyword}」，换个说法试试？"},
                    ensure_ascii=False,
                )
            picked = best
            encrypted = str(best.get("id") or "")

        # 4) 取直链并播放（mpv 原生播放列表：单曲 1 首，也可扩展成整列）
        try:
            detail = await api.song_detail(encrypted)
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
        play_url = detail.get("playUrl")
        if song_id and str(detail.get("originalId") or "") != str(song_id):
            return json.dumps({"status": "error", "message": "歌曲 ID 缺失或版本不一致，未播放"}, ensure_ascii=False)
        if not play_url or song_availability(detail, detail=True)["availability"] != "api_available":
            return json.dumps(
                {"status": "error",
                 "message": unavailable_note(detail.get("name") or keyword),
                 "song": {**song_availability(detail, detail=True), "song_id": song_id,
                          "encrypted_id": encrypted}},
                ensure_ascii=False,
            )
        played = await player.play_urls([play_url], [detail.get("name") or ""])
        state = await player.get_state() if played else {}
        song = _brief_song(picked) if picked else {
            "name": detail.get("name"), "artist": detail.get("artistName"),
            "song_id": song_id, "encrypted_id": encrypted,
        }
        # play-by-id 路径的 picked 只有裸 ID（无歌名/歌手/playFlag），_brief_song 会
        # 产出 name=""、playable=false 的矛盾结果——收尾模型据此误判"没播成"
        # （实测"播放成功但回复说还在等确认"）。用 song_detail 的真实元数据补齐，
        # 且既然已实际交给播放器，playable 如实置 True。
        if not song.get("name"):
            song["name"] = detail.get("name") or ""
        if not song.get("artist"):
            song["artist"] = detail.get("artistName") or ""
        if not song.get("album") and detail.get("albumName"):
            song["album"] = detail.get("albumName")
        if played:
            song["playable"] = True
        payload: dict = {
            "status": "ok" if played else "pending",
            "played": played,
            "song": song,
            "state": state,
        }
        if not played:
            payload["note"] = "已经交给播放器了，但还没出声——稍等片刻或再让我放一次"
        return json.dumps(payload, ensure_ascii=False)


class NeteaseControlTool(BaseTool):
    """播放控制：直接操作引擎自管的 mpv（暂停/切歌/音量/进度/状态）。"""

    name = "netease_control"
    description = (
        "控制音乐播放：暂停、继续、下一首、上一首、停止、调音量、快进快退、"
        "跳到指定时间点、切换播放模式（顺序/单曲循环/列表循环/随机）、"
        "把想听的歌加到待播队列、查看当前正在播放的歌曲。"
        "用户说'暂停''下一首''现在放的什么''声音小点''跳到 1 分 30 秒''单曲循环'"
        "'等这首放完再放那首'时用。"
        "只控制桌宠自管 mpv，不因空闲或错误而转控外部播放器。"
        "官方客户端桥接需明确选择与单独验证，不能擅自切换控制目标。"
    )
    approval_required = False
    requires_env = "ncm-cli"

    def __init__(self, daemon=None, config: NeteaseConfig | None = None) -> None:
        del daemon
        self._cfg = config or NeteaseConfig()

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
                            "enum": ["pause", "resume", "next", "prev", "stop", "state",
                                     "volume", "seek", "forward", "back", "mode", "queue"],
                            "description": (
                                "pause 暂停 / resume 继续 / next 下一首 / prev 上一首 / "
                                "stop 停止 / state 查看当前播放（曲目+进度）/ "
                                "volume 调音量 / seek 跳到第 N 秒 / forward 快进 N 秒 / "
                                "back 快退 N 秒 / mode 切换播放模式 / queue 把某首歌加入待播队列"
                            ),
                        },
                        "level": {"type": "integer",
                                  "description": "action=volume 时的音量（0-100），默认 70"},
                        "seconds": {"type": "number",
                                    "description": "action=seek/forward/back 时的秒数，如 90 表示 1 分 30 秒"},
                        "mode": {"type": "string",
                                 "enum": ["sequential", "repeat_all", "repeat_one", "shuffle"],
                                 "description": "action=mode 时：sequential 顺序 / repeat_all 列表循环 / repeat_one 单曲循环 / shuffle 随机"},
                        "keyword": {"type": "string",
                                    "description": "action=queue 时要追加的歌曲关键词（如 '周杰伦 晴天'）"},
                    },
                    "required": ["action"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        action = str(args.get("action", "")).strip()
        if args.get("backend", "builtin") != "builtin":
            return json.dumps({"status": "error", "message": "该控制工具仅绑定自管 mpv，未操作其他播放器"}, ensure_ascii=False)

        if action == "state":
            st = await player.get_state()
            if _current_song:
                st["song"] = _current_song
            return json.dumps({"status": "ok", "backend": "builtin", "state": st}, ensure_ascii=False)

        if action == "mode":
            mode = str(args.get("mode") or "sequential")
            return json.dumps(await player.set_mode(mode), ensure_ascii=False)

        if action in ("seek", "forward", "back"):
            secs = float(args.get("seconds") or 0)
            if action == "back":
                secs = -abs(secs)
            return json.dumps(
                await player.seek(secs, relative=(action != "seek")), ensure_ascii=False
            )

        if action == "queue":
            kw = str(args.get("keyword") or "").strip()
            if not kw:
                return json.dumps(
                    {"status": "error", "message": "要把哪首歌加入队列？给个歌名或歌手"},
                    ensure_ascii=False,
                )
            try:
                best, options = await _pick_best(kw)
            except Exception as exc:  # noqa: BLE001
                return _err(exc)
            if options:
                return json.dumps({"status": "need_choice", "options": options,
                                   "message": "入队前需确认具体版本，未自行选择其他歌曲"}, ensure_ascii=False)
            target = best
            if not target:
                return json.dumps(
                    {"status": "error", "message": f"没找到可播放的「{kw}」"},
                    ensure_ascii=False,
                )
            eid = str(target.get("encrypted_id") or target.get("id") or "")
            try:
                detail = await api.song_detail(eid)
            except Exception as exc:  # noqa: BLE001
                return _err(exc)
            if (song_availability(detail, detail=True)["availability"] != "api_available"
                    or str(detail.get("originalId") or "") != str(target.get("originalId") or "")):
                return json.dumps(
                    {"status": "error", "message": unavailable_note(str(target.get("name") or ""))},
                    ensure_ascii=False,
                )
            n = await player.enqueue([detail["playUrl"]])
            return json.dumps(
                {"status": "ok" if n else "error",
                 "message": f"已把《{target.get('name')}》排进待播队列",
                 "queued": n, "state": await player.get_state()},
                ensure_ascii=False,
            )

        if action not in {"pause", "resume", "next", "prev", "stop", "volume"}:
            return json.dumps(
                {"status": "error", "message": f"不支持的控制动作: {action}"},
                ensure_ascii=False,
            )
        # 归属固定为 builtin，空闲/未知均不得触发外部控制。
        if action in _SMTC_FORWARD_ACTIONS:
            mpv_state = await player.get_state()
            if mpv_state.get("status") == "unknown":
                return json.dumps(
                    {"status": "error", "message": "内置播放器状态暂时读不到，未操作外部播放器，请稍后重试",
                     "state": mpv_state}, ensure_ascii=False,
                )
            if mpv_state.get("status") == "stopped":
                return json.dumps(
                    {"status": "ok", "backend": "builtin", "state": mpv_state,
                     "message": "自管播放器当前空闲，未操作任何外部播放器"}, ensure_ascii=False,
                )
        level = max(0, min(100, int(args.get("level", 70)))) if action == "volume" else None
        result = await player.control(action, level)
        result["backend"] = "builtin"
        if result.get("status") == "ok" and _current_song and action in ("next", "prev"):
            _remember_current(None)  # 切歌后旧记录失效，等新的播放再记录
        return json.dumps(result, ensure_ascii=False)


class NeteasePlaylistTool(BaseTool):
    name = "netease_playlist"
    description = (
        "查看网易云歌单：列出我创建的歌单，或查看某个歌单里有哪些歌。"
        "用户说'我的歌单''歌单里有什么'时调用。"
    )
    approval_required = False
    requires_env = "ncm-cli"

    def __init__(self, daemon=None, config: NeteaseConfig | None = None) -> None:
        del daemon
        self._cfg = config or NeteaseConfig()

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list", "tracks"],
                                   "description": "list 列出我的歌单；tracks 查看某歌单的歌曲，默认 list"},
                        "playlist_id": {"type": "string",
                                        "description": "action=tracks 时必填：歌单 ID"},
                        "limit": {"type": "integer", "description": "返回条数，默认 10"},
                    },
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        action = str(args.get("action") or "list")
        limit = int(args.get("limit") or 10)
        try:
            if action == "tracks":
                pid = str(args.get("playlist_id", "")).strip()
                if not pid:
                    return json.dumps({"status": "error", "message": "查看歌单歌曲需要 playlist_id"},
                                      ensure_ascii=False)
                tracks = await api.playlist_tracks(pid, limit)
                return json.dumps(
                    {"status": "ok", "count": len(tracks),
                     "tracks": [_brief_song(r) for r in tracks[:limit]]},
                    ensure_ascii=False,
                )
            # S41：我创建 + 我订阅/收藏的全部歌单。
            # 此前只列"我创建的" —— 而用户说"我的歌单"时多半也指订阅的那批，
            # 只列创建的会显得"少了几个"，也就没法用名字点播。
            lists = await _account_playlists(limit)
            return json.dumps(
                {"status": "ok", "count": len(lists),
                 "playlists": [_brief_playlist(r) for r in lists[:limit]]},
                ensure_ascii=False,
            )
        except Exception as exc:  # noqa: BLE001
            return _err(exc)


class NeteaseRecommendTool(BaseTool):
    """每日推荐——**直接播放**（用户说"想听歌"是要听到，不是看列表）。"""

    name = "netease_recommend"
    description = (
        "播放网易云个性化推荐：每日推荐（按账号听歌习惯）或心动模式。"
        "用户说'随便放点''推荐几首''每日推荐''想听歌'时调用——会直接把推荐列表放出来。"
    )
    approval_required = False
    requires_env = "ncm-cli"

    def __init__(self, daemon=None, config: NeteaseConfig | None = None) -> None:
        del daemon
        self._cfg = config or NeteaseConfig()

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["daily", "heartbeat"],
                                 "description": "daily 每日推荐（默认）；heartbeat 心动模式"},
                        "limit": {"type": "integer",
                                  "description": "播放首数，默认 5，每日推荐最多 40"},
                    },
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        kind = str(args.get("kind") or "daily")
        limit = min(int(args.get("limit") or _MAX_CANDIDATES), 40)
        try:
            songs = await api.recommend_daily(limit)
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
        if not songs:
            return json.dumps({"status": "pending", "played": False,
                               "message": "这次没拿到推荐，稍后再试一次吧"}, ensure_ascii=False)
        played, briefs, titles = await _play_songs(songs, limit)
        return json.dumps(
            {
                "status": "ok" if played else "pending",
                "played": played,
                "kind": kind,
                "count": len(briefs),
                "items": briefs,
                "now": titles[0] if titles else "",
                "state": await player.get_state() if played else {},
            },
            ensure_ascii=False,
        )


class NeteaseLyricTool(BaseTool):
    name = "netease_lyric"
    description = "获取网易云歌曲的歌词。用户问'这首歌的歌词''唱的什么'时调用。"
    approval_required = False
    requires_env = "ncm-cli"

    def __init__(self, daemon=None, config: NeteaseConfig | None = None) -> None:
        del daemon
        self._cfg = config or NeteaseConfig()

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "歌曲关键词（与 song_id 二选一）"},
                        "song_id": {"type": "string", "description": "歌曲明文 ID"},
                    },
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        keyword = str(args.get("keyword", "")).strip()
        encrypted = str(args.get("encrypted_id") or "").strip()
        title = ""
        try:
            if not encrypted:
                if not keyword:
                    return json.dumps({"status": "error", "message": "请给歌曲关键词或 song_id"},
                                      ensure_ascii=False)
                records = await api.search_song(keyword, 1)
                if not records:
                    return json.dumps({"status": "ok", "message": f"没找到「{keyword}」的歌词"},
                                      ensure_ascii=False)
                encrypted = str(records[0].get("id") or "")
                title = str(records[0].get("name") or "")
            data = await api.song_lyric(encrypted)
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
        text = data.get("lyric") or ""
        if not text:
            return json.dumps(
                {"status": "ok", "song": title, "lyric": "", "message": "这首是纯音乐或暂无歌词"},
                ensure_ascii=False,
            )
        payload: dict = {"status": "ok", "song": title, "lyric": text}
        if data.get("transLyric"):
            payload["translation"] = data["transLyric"]
        return json.dumps(payload, ensure_ascii=False)


class NeteaseLibraryTool(BaseTool):
    """个人音乐库与探索：收藏/取消收藏、我的歌单、收藏的歌单、最近播放、歌单雷达、账号信息。"""

    name = "netease_library"
    description = (
        "个人音乐库与探索：把歌曲加入/移出红心收藏、查看我的歌单、我收藏的歌单、"
        "我最近听过的歌、我的账号信息、歌单雷达（按口味推荐一批歌单）。"
        "用户说'收藏这首歌''取消收藏''我的歌单''我最近听的什么''换个口味''我是谁'时调用。"
    )
    approval_required = False
    requires_env = "ncm-cli"

    def __init__(self, daemon=None, config: NeteaseConfig | None = None) -> None:
        del daemon
        self._cfg = config or NeteaseConfig()

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
                            "enum": ["like", "unlike", "recent", "my_playlists",
                                     "collected_playlists", "radar", "profile", "play_recent"],
                            "description": (
                                "like 收藏（红心）/ unlike 取消收藏 / recent 最近播放过的歌 / "
                                "my_playlists 我创建或订阅的歌单 / collected_playlists 我收藏的歌单 / "
                                "radar 歌单雷达（按口味推荐歌单）/ profile 我的账号信息 / "
                                "play_recent 直接播放最近听过的歌"
                            ),
                        },
                        "encrypted_id": {
                            "type": "string",
                            "description": "action=like/unlike 时的歌曲加密 ID；"
                                           "不填则默认对**当前正在播放**的歌操作",
                        },
                        "keyword": {
                            "type": "string",
                            "description": "action=like/unlike 时也可给歌名（自动搜索匹配）",
                        },
                        "limit": {"type": "integer", "description": "返回/播放条数，默认 10"},
                    },
                    "required": ["action"],
                },
            },
        }

    async def _resolve_song(self, args: dict) -> tuple[str, str]:
        """定位要操作的歌曲：(encrypted_id, name)。"""
        eid = str(args.get("encrypted_id") or "").strip()
        if eid:
            return eid, ""
        kw = str(args.get("keyword") or "").strip()
        if kw:
            records = await api.search_song(kw, 5)
            for r in records:
                if r.get("playFlag") and r.get("id"):
                    return str(r["id"]), str(r.get("name") or "")
            if records:
                return str(records[0].get("id") or ""), str(records[0].get("name") or "")
            return "", ""
        # 默认作用于当前播放的歌曲
        if _current_song and _current_song.get("encrypted_id"):
            return str(_current_song["encrypted_id"]), str(_current_song.get("name") or "")
        return "", ""

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        action = str(args.get("action") or "").strip()
        limit = min(int(args.get("limit") or 10), 50)

        try:
            if action in ("like", "unlike"):
                eid, name = await self._resolve_song(args)
                if not eid:
                    return json.dumps(
                        {"status": "error",
                         "message": "要收藏哪首歌？可以点名歌名，或先放一首再让我收藏"},
                        ensure_ascii=False,
                    )
                name = name or (_current_song or {}).get("name") or ""
                await api.song_like(eid, action == "like")
                return json.dumps(
                    {"status": "ok",
                     "message": f"已{'收藏' if action == 'like' else '取消收藏'}《{name}》"
                                if name else "已更新收藏",
                     "song": name, "liked": action == "like"},
                    ensure_ascii=False,
                )

            if action == "recent":
                songs = await api.play_history(limit)
                return json.dumps(
                    {"status": "ok", "count": len(songs),
                     "items": [_brief_song(s) for s in songs[:limit]]},
                    ensure_ascii=False,
                )

            if action == "play_recent":
                songs = await api.play_history(max(limit, 5))
                if not songs:
                    return json.dumps({"status": "pending", "played": False,
                                       "message": "最近没有播放记录"}, ensure_ascii=False)
                played, briefs, titles = await _play_songs(songs, limit)
                return json.dumps(
                    {"status": "ok" if played else "pending", "played": played,
                     "count": len(briefs), "items": briefs[:limit],
                     "now": titles[0] if titles else "",
                     "state": await player.get_state() if played else {}},
                    ensure_ascii=False,
                )

            if action == "my_playlists":
                lists = await api.playlist_subed(limit)
                return json.dumps(
                    {"status": "ok", "count": len(lists),
                     "playlists": [_brief_playlist(r) for r in lists[:limit]]},
                    ensure_ascii=False,
                )

            if action == "collected_playlists":
                lists = await api.playlist_collected(limit)
                return json.dumps(
                    {"status": "ok", "count": len(lists),
                     "playlists": [_brief_playlist(r) for r in lists[:limit]]},
                    ensure_ascii=False,
                )

            if action == "radar":
                lists = await api.playlist_radar()
                return json.dumps(
                    {"status": "ok", "count": len(lists),
                     "playlists": [_brief_playlist(r) for r in lists[:limit]]},
                    ensure_ascii=False,
                )

            if action == "profile":
                p = await api.user_profile()
                return json.dumps(
                    {"status": "ok",
                     "nickname": p.get("nickname"), "signature": p.get("signature"),
                     "vip": bool(p.get("vipDetail")),
                     # S50：防止 NCM 账号昵称覆盖用户身份（实测：人设里用户是
                     # "Yui"，模型据 profile 的 nickname 回答"你是 I_drcen"，
                     # 造成身份冲突且经 history 反复强化）。
                     "note": "以上只是网易云音乐账号信息（音乐服务身份），"
                             "不要把它当作用户的真实称呼——用户是谁以人设与"
                             "既有对话为准。"},
                    ensure_ascii=False,
                )
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

        return json.dumps({"status": "error", "message": f"不支持的操作: {action}"},
                          ensure_ascii=False)


# 装配顺序即 LLM 看到的顺序。登录工具放最前——它是所有能力的前置依赖。
NETEASE_TOOLS: list[type] = [
    NeteaseLoginTool,
    NeteaseSearchTool,
    NeteasePlayTool,
    NeteaseControlTool,
    NeteaseLibraryTool,
    NeteasePlaylistTool,
    NeteaseRecommendTool,
    NeteaseLyricTool,
]

__all__ = [
    "NETEASE_TOOLS",
    "NeteaseControlTool",
    "NeteaseLibraryTool",
    "NeteaseLoginTool",
    "NeteaseLyricTool",
    "NeteasePlayTool",
    "NeteasePlaylistTool",
    "NeteaseRecommendTool",
    "NeteaseSearchTool",
]
