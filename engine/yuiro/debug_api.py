"""Developer/debug API for the Yuiro engine.

Backs the shell's developer window (opened from the pet's island):
  - config read / partial update + hot reload (config.toml is the source of truth)
  - per-provider 联调 / readiness tests (llm / asr / tts / vad / memory / systemd)
  - engine + daemon status
  - in-memory structured log tail

M1-level: tests are lightweight readiness/connectivity probes — real where cheap
(LLM ping, edge-tts voice lookup), labelled clearly where a key/model is needed.
They deepen as each milestone lands. All endpoints are localhost-only.
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from collections import deque
from dataclasses import asdict, dataclass

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from yuiro.agent.chat_service import build_responder
from yuiro.approval import get_approval_mode, set_approval_mode
from yuiro.config import (
    FIELD_META,
    AppConfig,
    config_apply,
    config_to_dict,
    effective_motion_slots,
    effective_persona_maps,
    load_config,
    save_config,
)
from yuiro.keychain import (
    clear_llm_key,
    clear_search_key,
    load_llm_key,
    load_search_key,
    save_llm_key,
    save_search_key,
)

router = APIRouter(prefix="/api", tags=["debug"])


@router.get("/netease/probe")
async def netease_probe() -> dict:
    """诊断引擎进程内的网易云 ncm-cli 环境。

    用于排查「真实对话中网易云工具报错、但 shell 手动测正常」的环境差异：
    返回 which 解析、PATH 中 node 相关条目、USERPROFILE，并实跑 state/search。
    """
    import shutil

    from yuiro.netease import is_available, run_ncm

    bin_name = "ncm-cli"
    state = await run_ncm(["state"], timeout_s=8)
    search = await run_ncm(["search", "song", "--keyword", "test", "--limit", "1"], timeout_s=12)
    node_paths = [
        p for p in os.environ.get("PATH", "").split(os.pathsep)
        if "node" in p.lower() or "npm" in p.lower()
    ]
    return {
        "which": shutil.which(bin_name),
        "available": is_available(bin_name),
        "userprofile": os.environ.get("USERPROFILE", ""),
        "node_path_entries": node_paths,
        "state": {"ok": state.ok, "kind": state.error_kind, "error": (state.error or "")[:200]},
        "search": {
            "ok": search.ok,
            "kind": search.error_kind,
            "count": len(search.records),
            "error": (search.error or "")[:200],
        },
    }


# ---------------------------------------------------------------------------
# 内存日志环形缓冲
# ---------------------------------------------------------------------------
@dataclass
class LogEntry:
    ts: float
    level: str
    source: str
    message: str


class LogRing:
    def __init__(self, maxlen: int = 2000) -> None:
        self._buf: deque[LogEntry] = deque(maxlen=maxlen)

    def emit(self, level: str = "INFO", source: str = "engine", message: str = "") -> None:
        self._buf.append(LogEntry(time.time(), level.upper(), source, message))

    def tail(self, n: int = 200) -> list[LogEntry]:
        items = list(self._buf)
        return items[-n:]

    def clear(self) -> None:
        self._buf.clear()


log_ring = LogRing()


def _emit(level: str, source: str, message: str) -> None:
    log_ring.emit(level, source, message)
    print(f"[yuiro][{source}][{level}] {message}", flush=True)


#: 看着像"仓库开发文档"的路径特征（S51 知识库导入防线）。
#: 实测：把 docs/init/milestones.md 导进知识库后，内容**每轮注入对话**，
#: 她会冒出"我们在 M4→M5 阶段""记得写 ARCHITECTURE 变更日志"这类项目术语。
_DEV_DOC_MARKERS = (
    "docs/init", "docs/spec", "docs/plan", "docs/features",
    "milestones", "roadmap", "architecture", "changelog",
    "里程碑", "路线图", "变更日志",
)


def _looks_like_dev_doc(path: str) -> bool:
    """路径是否像"仓库里的开发过程文档"（导入知识库容易让她说话带项目术语）。"""
    p = str(path or "").replace("\\", "/").lower()
    return any(m in p for m in _DEV_DOC_MARKERS)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def _state_config(app) -> AppConfig:
    return app.state.app_config


def _rebuild_responder(app) -> None:
    """用当前配置 + 运行中的 API key 重建聊天响应器、AgentLoop 与人设组件。

    人设（persona）热重载：
    - AgentLoop：注入新的 system_prompt（并复用已缓存的 MemorySystem，避免重复 spawn
      嵌入 worker / 丢失记忆检索，修复旧逻辑未传 memory 的 bug）。
    - EmotionEngine：注入新的 emotion_hints / expression_map。
    - TTSProvider：注入新的 voice（voice_pipeline 内若有则替换）。
    - memory_subject：涉及 L3 事实归属，仅启动时生效，热更新时仅记录提示。
    """
    cfg = _state_config(app)
    key = getattr(app.state, "llm_api_key", "") or ""
    # 单轮 responder 同样注入系统+人设提示词（agent_loop 未装配时的 fallback 路径）。
    app.state.chat_responder = build_responder(
        cfg.llm, key or None,
        cfg.persona.system_prompt + "\n\n" + cfg.persona.persona_prompt
    )
    # 同步重建 AgentLoop（工具循环/记忆检索/审批门）
    memory = getattr(app.state, "memory", None)
    # 保留运行中的 SystemDaemon 客户端：热重载重建 AgentLoop 时若丢失，SystemTool
    # 将退化为无真实系统操作能力（与 main.py 的 _build_agent 行为对齐）。
    system_daemon = getattr(app.state, "system_daemon", None)
    # S10：优先复用运行中的执行后端（native 或 daemon），缺省退回旧 daemon 引用
    system_backend = getattr(app.state, "system_backend", system_daemon)
    factory = getattr(app.state, "build_character_agent", None)
    if key and callable(factory):
        previous = getattr(app.state, "agent_loop", None)
        app.state.agent_loop = factory()
        if previous is not None and app.state.agent_loop is not None:
            app.state.agent_loop._history = previous._history
            app.state.agent_loop._state = previous._state
    elif key:
        from yuiro.agent import build_agent_loop
        from yuiro.approval import approval_gate, set_approval_mode

        set_approval_mode(getattr(cfg.systemd, "approval_mode", "auto"))
        app.state.agent_loop = build_agent_loop(
            base_url=cfg.llm.base_url,
            model=cfg.llm.model,
            api_key=key,
            temperature=cfg.llm.temperature,
            approval_gate=approval_gate,
            memory_system=memory,
            system_daemon=system_daemon,
            system_backend=system_backend,
            persona=cfg.persona,
            memory_config=cfg.memory,
            netease_config=cfg.netease,
            context_config=cfg.context,
            task_runtime=getattr(app.state, "tasks", None),
            capability_config=cfg.capability,
            avatar_getter=lambda: getattr(app.state, "avatar", None),
            relationship=getattr(app.state, "relationship", None),
        )
    else:
        app.state.agent_loop = None

    registry = getattr(app.state, "runtimes", None)
    if registry is not None:
        from yuiro.runtime.adapters import AgentRuntimeAdapter

        registry.register(AgentRuntimeAdapter(app.state.agent_loop))

    # S49：按当前 model_path 选出该模型的表现档案 —— 三张映射表都以"生效值"为准，
    # 否则换模型 / 改档案后，情感引擎与头像运行时还会各算各的（表现半新半旧）。
    eff_expr, eff_motion, eff_perf = effective_persona_maps(cfg.persona)
    eff_slots = effective_motion_slots(cfg.persona)
    # 人设热重载：情感引擎（情绪文案/表情映射）
    emotion_engine = getattr(app.state, "emotion_engine", None)
    if emotion_engine is not None:
        emotion_engine._hints = dict(cfg.persona.emotion_hints)
        emotion_engine._expression_map = dict(eff_expr)
    # S05：同步头像运行时的表情映射（否则热重载后表情不跟着变）
    avatar = getattr(app.state, "avatar", None)
    if avatar is not None:
        avatar.update_expression_map(eff_expr)
        # S18：动作映射（表演包的动作组覆盖）
        avatar.update_motion_map(eff_motion)
        # S48：自由搭配（表演名 → 表情 + 动作），不热重载的话改完看不到效果
        avatar.update_performance_map(eff_perf)
        # S53：语义动作槽位（槽位 → 组#索引）
        avatar.update_motion_slots(eff_slots)

    # 人设热重载：音色（voice_pipeline 内的 TTS provider，私有属性 _tts）
    # 按 cfg.tts.provider 分支装配，与 main.py 的 _build_voice_pipeline 对齐；
    # 修复旧逻辑硬编码 edge-tts 导致切换 cosyvoice 后热重载被覆盖回 edge-tts 的问题。
    voice_pipeline = getattr(app.state, "voice_pipeline", None)
    if voice_pipeline is not None:
        # ★ 打断开关：**运行时同步**（在调试台一改就生效，不必重启引擎）
        voice_pipeline._barge_in_enabled = bool(cfg.vad.barge_in_enabled)
        # S52：朗读语种（[language].speak_language）—— 与 main.py 的装配口径一致
        _speak_lang = (getattr(cfg.language, "speak_language", "auto") or "auto").lower()
        if cfg.tts.provider == "cosyvoice":
            from yuiro.audio import CosyVoiceProvider

            voice_pipeline._tts = CosyVoiceProvider(
                base_url=cfg.tts.tts_url,
                reference_wav=cfg.tts.reference_wav,
                reference_text=cfg.tts.reference_text,
                instruct_zh=cfg.tts.instruct_zh,
                instruct_en=cfg.tts.instruct_en,
                instruct_ja=getattr(cfg.tts, "instruct_ja", ""),
                default_language=cfg.tts.default_language,
                backend=cfg.tts.backend,
                segment_streaming=cfg.tts.segment_streaming,
                language=_speak_lang,
            )
        elif cfg.tts.provider == "gptsovits":
            from yuiro.audio import GPTSoVITSProvider

            voice_pipeline._tts = GPTSoVITSProvider(
                base_url=cfg.tts.tts_url,
                text_language=(
                    _speak_lang if _speak_lang != "auto"
                    else (cfg.tts.tts_text_language or cfg.tts.default_language)
                ),
                segment_streaming=cfg.tts.segment_streaming,
            )
        elif cfg.tts.provider == "fish":
            from yuiro.audio.fish import build_fish_provider

            voice_pipeline._tts = build_fish_provider(cfg.tts)
        elif cfg.tts.provider == "siliconflow":
            from yuiro.audio import SiliconFlowProvider
            from yuiro.keychain import load_siliconflow_key

            sf_key = cfg.tts.siliconflow_key or load_siliconflow_key() or ""
            voice_pipeline._tts = SiliconFlowProvider(
                api_key=sf_key,
                voice=cfg.tts.siliconflow_voice,
                reference_wav=cfg.tts.siliconflow_reference_wav,
                reference_text=cfg.tts.siliconflow_reference_text,
                model=cfg.tts.siliconflow_model,
                segment_streaming=cfg.tts.segment_streaming,
            )
        else:
            from yuiro.audio import TTSProvider

            voice_pipeline._tts = TTSProvider(
                voice=cfg.persona.voice,
                segment_streaming=cfg.tts.segment_streaming,
                language=_speak_lang,
            )

        # S52：语言设置热重载 —— 刷新出口渲染器（展示/朗读语言 + 转换模式 + 超时）
        # 必须与 provider 一起刷新：否则用户在调试台改完「语言」却发现没反应，
        # 只能以为功能坏了（本会话在音色上踩过同样的坑）。
        renderer = getattr(app.state, "output_renderer", None)
        if renderer is not None:
            if key:
                try:
                    from yuiro.agent import OpenAIProvider

                    renderer.set_llm(OpenAIProvider(cfg.llm.base_url, cfg.llm.model, key))
                except Exception as exc:  # noqa: BLE001 — 渲染器热重载失败不影响对话
                    _emit("WARN", "language", f"渲染器 LLM 热重载失败：{exc}")
            renderer.set_languages(
                display_language=getattr(cfg.language, "display_language", "zh"),
                speak_language=getattr(cfg.language, "speak_language", "auto"),
                mode=getattr(cfg.language, "translate_mode", "sentence"),
                timeout_s=getattr(cfg.language, "translate_timeout_s", 6.0),
            )
            voice_pipeline.set_renderer(renderer)
            # 热重载必须**可观测**：否则"改完没反应"时无从判断是没生效还是没说话
            _emit("INFO", "language", f"语言设置已热重载：{renderer.describe()}")

    # memory_subject 仅启动时生效，热更新时提示需重启。
    _emit(
        "INFO",
        "persona",
        f"人设已热重载（voice={cfg.persona.voice}；"
        f"memory_subject={cfg.persona.memory_subject} 需重启生效）",
    )
    invalidate = getattr(app.state, "invalidate_inactive_characters", None)
    if callable(invalidate):
        invalidate()


def _text_defaults() -> dict:
    """**留空即回退引擎内置**的文本字段 → 内置默认文案。

    为什么需要：这类字段（提示词）留空时引擎会用自己的内置文案，但调试台只拿到配置里
    的空串 —— 界面上是一片空白，看起来像"没加载出来"（用户实测反馈："系统提示词默认
    加载内容是空的"）。把内置文案一并回传，调试台就能显示**当前实际生效的内容**，
    并直接以它为起点修改。

    真相源仍然是 agent 模块里的常量：这里只做转手，**不在 config.py 再抄一份**
    （抄一份的下场见 config.py 里 prompts 字段的注释）。
    """
    try:
        from yuiro.agent import _DEFAULT_PERSONA_PROMPT, _DEFAULT_SYSTEM_PROMPT
    except Exception:  # noqa: BLE001 — 拿不到就不提供，界面退回"留空 = 内置默认"的说明
        return {}
    return {
        "persona": {
            "system_prompt": _DEFAULT_SYSTEM_PROMPT,
            "persona_prompt": _DEFAULT_PERSONA_PROMPT,
        },
    }


def _character_view(app) -> dict | None:
    service = getattr(app.state, "characters", None)
    return service.view() if service else None


def _character_conflict(app, body, patch):
    from yuiro.characters import ROLE_SECTIONS

    service = getattr(app.state, "characters", None)
    if not service:
        return None
    if service.lock.locked():
        return JSONResponse({"detail": "正在切换角色，请稍后再保存"}, status_code=409)
    if set(patch) & set(ROLE_SECTIONS):
        if (body.get("character_id") != service.store.active()
                or body.get("character_revision") != service.revision):
            return JSONResponse({"detail": "角色已变化，请刷新后重新编辑；旧草稿未保存"}, status_code=409)
    # memory 文件归属不可在热更新中改变，避免设置写到卡上却仍使用旧 store。
    cfg = _state_config(app)
    for field in ("db_path", "embedder"):
        if field in patch.get("memory", {}) and patch["memory"][field] != getattr(cfg.memory, field):
            return JSONResponse({"detail": "记忆存储与嵌入配置变更需重启，不支持角色内热迁移"}, status_code=409)
    return None


@router.get("/characters")
async def characters(request: Request) -> dict:
    return _character_view(request.app) or {"active_id": "", "items": []}


@router.post("/characters/switch")
async def switch_character(request: Request):
    import secrets

    secret = _state_config(request.app).server.shared_secret
    if secret and secret != "dev-only-change-me" and not secrets.compare_digest(
        secret, request.headers.get("x-yuiro-secret", "")
    ):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    service = getattr(request.app.state, "characters", None)
    if not service:
        return JSONResponse({"detail": "角色服务未装配"}, status_code=503)
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("id"), str):
        return JSONResponse({"detail": "id must be a string"}, status_code=400)
    try:
        return await service.switch(body["id"])
    except (ValueError, FileNotFoundError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001 — 切换失败已恢复旧角色，向 UI 返回明确终态
        _emit("ERROR", "character", f"角色切换失败：{type(exc).__name__}")
        return JSONResponse({"detail": "切换失败，已保留原角色；请查看 character 日志"}, status_code=409)


@router.get("/config")
async def get_config(request: Request) -> dict:
    cfg = _state_config(request.app)
    return {
        "character": _character_view(request.app),
        "sections": config_to_dict(cfg),
        "schema": FIELD_META,
        # 双层 getattr：responder 尚未装配时（引擎刚起 / 最小化测试 app）不该整个 500
        "backend": getattr(getattr(request.app.state, "chat_responder", None), "backend_name", "unknown"),
        # 留空即回退内置的文本字段（提示词）：给调试台显示"实际生效内容"用
        "text_defaults": _text_defaults(),
    }


@router.put("/config")
async def put_config(request: Request) -> dict:
    """Body: {"patch": {"<section>": {"<field>": value, ...}, ...}}.

    Applies to the live config object, persists to config.toml, and hot-reloads
    the chat responder. Returns the full updated config.
    """
    body = await request.json()
    patch = body.get("patch", {}) if isinstance(body, dict) else {}
    if not isinstance(patch, dict):
        return JSONResponse({"detail": "patch must be an object"}, status_code=400)

    cfg = _state_config(request.app)
    conflict = _character_conflict(request.app, body, patch)
    if conflict is not None:
        return conflict
    if "tts" in patch:
        import copy

        candidate = copy.deepcopy(cfg)
        try:
            config_apply(candidate, patch)
            if candidate.tts.provider == "fish":
                from yuiro.audio.fish import build_fish_provider

                build_fish_provider(candidate.tts)
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({"detail": "TTS 配置无效，未保存"}, status_code=400)
    config_apply(cfg, patch)
    save_config(cfg)

    # ★ 打断开关：**在这里**同步到运行中的语音管线（聊天坞的图标开关、调试台卡片
    #   都走这个端点）—— 只写配置文件的话，改了要重启引擎才生效，用户会以为"点了没用"。
    _vp = getattr(request.app.state, "voice_pipeline", None)
    if _vp is not None:
        _vp._barge_in_enabled = bool(cfg.vad.barge_in_enabled)

    _rebuild_responder(request.app)
    _emit("INFO", "config", f"配置已更新并热重载: {sorted(patch.keys())}")
    return {
        "character": _character_view(request.app),
        "sections": config_to_dict(cfg),
        "backend": getattr(getattr(request.app.state, "chat_responder", None), "backend_name", "unknown"),
    }


@router.post("/config/reload")
async def reload_config(request: Request) -> dict:
    """从磁盘重读 config.toml（覆盖内存态），并重建聊天响应器。"""
    characters = getattr(request.app.state, "characters", None)
    if characters and characters.lock.locked():
        return JSONResponse({"detail": "正在切换角色，请稍后再试"}, status_code=409)
    fresh = load_config(getattr(_state_config(request.app), "_config_path", None))
    cfg = _state_config(request.app)
    config_apply(cfg, config_to_dict(fresh))
    _rebuild_responder(request.app)
    _emit("INFO", "config", "配置已从磁盘重载")
    return {
        "character": _character_view(request.app),
        "sections": config_to_dict(cfg),
        "backend": getattr(getattr(request.app.state, "chat_responder", None), "backend_name", "unknown"),
    }


# ---------------------------------------------------------------------------
# 审批模式（运行时实时开关，不落盘）
# ---------------------------------------------------------------------------
@router.get("/systemd/approval-mode")
async def get_systemd_approval_mode() -> dict:
    """读取当前审批模式：auto（自动通过，不弹窗）/ manual（人工审批弹窗）。"""
    return {"approval_mode": get_approval_mode()}


@router.put("/systemd/approval-mode")
async def put_systemd_approval_mode(request: Request) -> dict:
    """实时切换审批模式（纯内存，不写 config.toml，立即生效）。
    Body: {"approval_mode": "auto" | "manual"}
    """
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"detail": "body must be an object"}, status_code=400)
    mode = (body.get("approval_mode") or "").strip().lower()
    if mode not in ("auto", "manual"):
        return JSONResponse(
            {"detail": "approval_mode 必须是 'auto' 或 'manual'"},
            status_code=400,
        )
    set_approval_mode(mode)
    _emit("INFO", "systemd", f"审批模式已切换为: {mode}")
    return {"approval_mode": mode}


# ---------------------------------------------------------------------------
# LLM API key 管理（OS keychain 持久化，一次配置重启长期可用；不回显明文）
# ---------------------------------------------------------------------------
@router.put("/providers/llm/key")
async def put_llm_key(request: Request) -> dict:
    """把 LLM API key 存入 OS keychain + 运行时内存并热重载聊天响应器。

    Body: {"key": "sk-xxx"}。key 为空返回 400；不回显明文。
    持久化到 keychain 后重启引擎仍可用（keychain 故障时仅内存态，返回
    ``persisted: false`` 提示）。
    """
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"detail": "body must be an object"}, status_code=400)
    key = body.get("key", "")
    if not key or not isinstance(key, str):
        return JSONResponse({"detail": "key 不能为空"}, status_code=400)

    persisted = save_llm_key(key)
    request.app.state.llm_api_key = key
    _rebuild_responder(request.app)
    _emit(
        "INFO",
        "llm-key",
        f"API key 已更新并热重载（keychain 持久化: {'是' if persisted else '否，仅内存'}）",
    )
    return {"status": "set", "persisted": persisted}


def _key_auth(request: Request):
    """key 相关端点（搜索 / Fish）的共享鉴权：**dev 占位密钥视为未配置**。

    与 WS（``main._authorized``）、角色接口的口径保持一致：``shared_secret``
    为空或仍是 ``"dev-only-change-me"`` 时不做强校验。

    ★ 这里原来漏了这层豁免，导致一个很难归因的故障：壳若从**未加载 env.ps1**
    的终端启动，就拿不到 ``YUIRO_SHARED_SECRET``（请求头为空），而引擎侧仍拿
    占位值做严格比较 → 调试台读取/保存 DeepSeek 搜索 key 永远 401，界面表现
    正是「读取中…」卡住 + 红字 ``unauthorized``（用户实测反馈）。
    """
    import secrets

    secret = _state_config(request.app).server.shared_secret
    if not secret or secret == "dev-only-change-me":
        return None
    if not secrets.compare_digest(secret, request.headers.get("x-yuiro-secret", "")):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return None


@router.api_route("/providers/fish/key", methods=["GET", "PUT", "DELETE"])
async def fish_key(request: Request):
    """仅返回配置状态；凭证不进入 AppConfig/角色卡/日志。"""
    from yuiro.keychain import clear_fish_key, load_fish_key, save_fish_key

    denied = _key_auth(request)
    if denied is not None:
        return denied
    if request.method == "PUT":
        body = await request.json()
        key = body.get("key") if isinstance(body, dict) else None
        if not isinstance(key, str) or not key.strip():
            return JSONResponse({"detail": "key 不能为空"}, status_code=400)
        if not save_fish_key(key.strip()):
            return JSONResponse({"detail": "OS 安全存储不可用，密钥未保存"}, status_code=503)
    elif request.method == "DELETE" and not clear_fish_key():
        return JSONResponse({"detail": "安全存储删除失败"}, status_code=503)
    configured = bool(load_fish_key())
    return {"status": "set" if configured else "unset", "persisted": configured}


@router.get("/providers/llm/key")
async def get_llm_key(request: Request) -> dict:
    """返回 API key 是否已配置的状态（查 keychain，绝不返回明文）。"""
    key = load_llm_key() or getattr(request.app.state, "llm_api_key", "") or ""
    return {"status": "set" if key else "unset", "persisted": key == load_llm_key()}


@router.delete("/providers/llm/key")
async def delete_llm_key(request: Request) -> dict:
    """清除 LLM API key（keychain + 内存），并回退 responder 到 mock。"""
    cleared = clear_llm_key()
    request.app.state.llm_api_key = ""
    _rebuild_responder(request.app)
    _emit("INFO", "llm-key", "API key 已清除")
    return {"status": "unset", "persisted": not cleared}


# ---------------------------------------------------------------------------
# 联网检索 key 管理（S51）——与 LLM key 同范式：keychain 持久化、不回显明文
#
# 为什么必须有这三个端点（此前的真缺口）：`save_search_key()` 早就有了，但**没有
# 任何配置入口** —— 用户既无法在调试台填 key，也无法用界面开启检索，等于功能不可用
# （"有实现、无入口"）。同时 config.toml 里连 `[search]` 段都没有。
# ---------------------------------------------------------------------------
@router.put("/providers/search/key")
async def put_search_key(request: Request) -> dict:
    """保存联网检索的 API key 到 OS keychain，并**重建 AgentLoop**。

    必须重建的原因：`web_search` 工具是**按"key 是否存在"决定是否注册**的
    （`requires_env="search-key"`）。只存 key 不重建，本次运行里工具依旧不存在，
    模型看不到它 → 用户会以为"配了没用"。
    """
    denied = _key_auth(request)
    if denied is not None:
        return denied
    body = await request.json()
    key = (body or {}).get("key", "") if isinstance(body, dict) else ""
    if not key or not isinstance(key, str):
        return JSONResponse({"detail": "key 不能为空"}, status_code=400)
    persisted = save_search_key(key)
    if not persisted:
        return JSONResponse({"detail": "DeepSeek 密钥未保存：OS 安全存储不可用"}, status_code=503)
    _rebuild_responder(request.app)
    _emit(
        "INFO",
        "search-key",
        f"搜索 key 已更新并重建 AgentLoop（keychain 持久化: {'是' if persisted else '否，仅内存'}）",
    )
    return {"status": "set", "persisted": persisted}


@router.get("/providers/search/key")
async def get_search_key(request: Request) -> dict:
    """返回搜索 key 是否已配置（查 keychain，绝不返回明文）。"""
    denied = _key_auth(request)
    if denied is not None:
        return denied
    key = (load_search_key() or "").strip()
    return {"status": "set" if key else "unset", "persisted": bool(key)}


@router.delete("/providers/search/key")
async def delete_search_key(request: Request) -> dict:
    """清除搜索 key 并重建 AgentLoop（工具随之从 schema 隐藏）。"""
    denied = _key_auth(request)
    if denied is not None:
        return denied
    cleared = clear_search_key()
    _rebuild_responder(request.app)
    _emit("INFO", "search-key", "搜索 key 已清除")
    if not cleared:
        return JSONResponse({"detail": "安全存储删除失败"}, status_code=503)
    return {"status": "unset", "persisted": False}


@router.post("/search/test")
async def test_search(request: Request):
    denied = _key_auth(request)
    if denied is not None:
        return denied
    cfg = _state_config(request.app).search
    if not cfg.enabled:
        return JSONResponse({"detail": "请先保存开启联网检索"}, status_code=409)
    body = await request.json()
    query = body.get("query") if isinstance(body, dict) else None
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 128:
        return JSONResponse({"detail": "搜索词须为 1–128 个字符"}, status_code=400)
    from yuiro.tools.web_tool import WebSearchTool, configure_search_key_provider

    configure_search_key_provider(lambda: load_search_key() or "")
    started = time.perf_counter()
    result = await WebSearchTool(config=cfg).run({"query": query}, "debug-search")
    import json

    return {**json.loads(result), "latency_ms": round((time.perf_counter()-started)*1000, 1)}


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------
def _import_ready(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


@router.get("/runtime")
async def get_runtime_state(request: Request) -> dict:
    """S15：统一 Runtime 状态视图（各 Runtime 的 state 快照）。"""
    registry = getattr(request.app.state, "runtimes", None)
    if registry is None:
        return {"status": "warn", "detail": "RuntimeRegistry 未装配"}
    return {"status": "ok", "runtimes": registry.names(), "state": registry.snapshot()}


@router.get("/events")
async def list_events(request: Request, session_id: str = "", limit: int = 200,
                      event_type: str = "") -> dict:
    """S12：回放某会话的事件日志（时间升序，最近 limit 条）。

    不带 session_id 时返回已有事件日志的会话列表与统计（供调试台浏览）。
    """
    log = getattr(request.app.state, "event_log", None)
    if log is None:
        return {"status": "warn", "detail": "EventLog 未初始化"}
    if not session_id:
        return {"status": "ok", "sessions": log.sessions(), "stats": log.stats()}
    events = log.load(session_id, limit=limit, event_type=event_type or None)
    return {"status": "ok", "session_id": session_id, "count": len(events), "events": events}


@router.get("/turns")
async def list_turns(request: Request, session_id: str = "", limit: int = 50) -> dict:
    """S48：回合级视图 —— "这一轮做到哪"。

    - 不带 ``session_id``：列出有回合记录的会话；
    - 带 ``session_id``：该会话最近的回合（含**未完成的**）。

    为什么值得单独一个端点：``/api/events`` 是**原始事件流**（排障用），
    回合视图是**语义化的"做到哪"**（人和面板看）—— 层级不同。

    未完成的回合还会附上 ``resume_plan``：**按副作用分级的恢复建议**
    （只读/本地写可安全重放；对外产生影响的步骤必须问用户）。
    """
    from dataclasses import asdict

    loop = getattr(request.app.state, "agent_loop", None)
    journal = getattr(loop, "_journal", None) if loop is not None else None
    if journal is None:
        return {
            "status": "warn",
            "detail": "TurnJournal 未装配（AgentLoop 缺省或未注入 events/event_log）",
        }
    if not session_id:
        log = getattr(request.app.state, "event_log", None)
        return {
            "status": "ok",
            "sessions": log.sessions() if log is not None else [],
        }

    turns = journal.recent_turns(session_id, limit=max(1, min(limit, 500)))
    plan = journal.resume_plan(session_id)
    unfinished = None
    if plan is not None:
        unfinished = {
            **asdict(plan.record),
            # replay boundary：这一轮做到哪、哪些能安全重放、哪些要问用户
            "auto_safe": plan.auto_safe,
            "replayable_steps": len(plan.replayable),
            "risky_steps": len(plan.risky),
            "question": plan.question(),
            "summary": plan.describe(),
        }
    return {
        "status": "ok",
        "session_id": session_id,
        "count": len(turns),
        "turns": [asdict(t) for t in turns],
        "unfinished": unfinished,
    }


@router.get("/status")
async def get_status(request: Request) -> dict:
    cfg = _state_config(request.app)
    daemon = getattr(request.app.state, "system_daemon", None)
    daemon_tools = []
    if daemon is not None:
        try:
            daemon_tools = await daemon.list_tools()
        except Exception:  # noqa: BLE001
            daemon_tools = []

    return {
        "engine": {
            "version": "0.1.0",
            "chat_backend": getattr(request.app.state.chat_responder, "backend_name", "unknown"),
        },
        "systemd": {
            "transport": cfg.systemd.transport,
            "http_url": cfg.systemd.http_url,
            "approval_mode": cfg.systemd.approval_mode,
            "tool_count": len(daemon_tools),
        },
        "providers": {
            "llm": {
                "configured": bool(cfg.llm.base_url and cfg.llm.model),
                "backend": getattr(getattr(request.app.state, "chat_responder", None), "backend_name", "unknown"),
            },
            "asr": {
                "ready": _import_ready("faster_whisper") or _import_ready("funasr"),
                "provider": cfg.asr.provider,
                "model": cfg.asr.model,
                "device": cfg.asr.device,
            },
            "tts": {
                "ready": _import_ready("edge_tts") or cfg.tts.provider in ("cosyvoice", "gptsovits", "siliconflow", "fish"),
                "provider": cfg.tts.provider,
                "voice": cfg.persona.voice,
            },
            "vad": {
                "ready": _import_ready("silero_vad") or _import_ready("funasr"),
                "provider": cfg.vad.provider,
                "threshold": cfg.vad.probability_threshold,
            },
            "memory": {
                "ready": _import_ready("sqlite_vec") or _import_ready("sqlite3"),
                "backend": cfg.memory.backend,
            },
        },
        "voice_pipeline": {
            "state": getattr(getattr(request.app.state, "voice_pipeline", None), "_state", "unknown"),
            "loading_stage": getattr(getattr(request.app.state, "voice_pipeline", None), "_loading_stage", ""),
            "loading_progress": getattr(getattr(request.app.state, "voice_pipeline", None), "_loading_progress", 0.0),
        },
    }


# ---------------------------------------------------------------------------
# Provider 联调 / 回调测试
# ---------------------------------------------------------------------------
async def _test_llm(request: Request) -> dict:
    responder = request.app.state.chat_responder
    cfg = _state_config(request.app).llm
    if responder.backend_name == "mock":
        return {
            "status": "warn",
            "backend": "mock",
            "detail": "未配置 API key（当前 mock）",
        }
    t0 = time.perf_counter()
    try:
        reply = await responder.reply("这是一条来自调试面板的连接测试。")
        ms = (time.perf_counter() - t0) * 1000
        return {
            "status": "ok",
            "latency_ms": round(ms, 1),
            "sample": reply,
            "backend": responder.backend_name,
            "model": cfg.model,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "backend": responder.backend_name,
            "model": cfg.model,
            "detail": str(exc),
        }


async def _test_tts(request: Request) -> dict:
    app_cfg = _state_config(request.app)
    voice = app_cfg.persona.voice
    # S52：试听可指定语种（body/query 的 lang），用于对比"同一句话在不同朗读语言下"的听感。
    # 不传则用「语言」设置里的朗读语言（auto 时各后端按文本判定，行为同旧）。
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — 无 body / 非 JSON 时按空处理
        body = {}
    if not isinstance(body, dict):
        body = {}
    lang = str(body.get("lang") or request.query_params.get("lang") or "").strip().lower()
    if lang not in ("zh", "en", "ja"):
        lang = (getattr(app_cfg.language, "speak_language", "auto") or "auto").lower()
    # 试听文本随语种切换：否则"设成日文却念中文句子"看不出语种是否真的生效
    sample = {
        "zh": "你好，我是 Yuiro，这是一条语音测试。",
        "en": "Hi, I'm Yuiro. This is a voice test.",
        "ja": "こんにちは、Yuiroです。これは音声テストです。",
    }.get(lang if lang in ("zh", "en", "ja") else "zh")
    try:
        # 按配置的 provider 分支：cosyvoice 测本地 tts-server，gptsovits 测本地 GPT-SoVITS，
        # 否则 edge-tts。
        if app_cfg.tts.provider == "cosyvoice":
            from yuiro.audio import CosyVoiceProvider

            provider = CosyVoiceProvider(
                base_url=app_cfg.tts.tts_url,
                reference_wav=app_cfg.tts.reference_wav,
                reference_text=app_cfg.tts.reference_text,
                instruct_zh=app_cfg.tts.instruct_zh,
                instruct_en=app_cfg.tts.instruct_en,
                instruct_ja=getattr(app_cfg.tts, "instruct_ja", ""),
                default_language=app_cfg.tts.default_language,
                backend=app_cfg.tts.backend,
                segment_streaming=app_cfg.tts.segment_streaming,
                language=lang or "auto",
            )
            backend_label = f"cosyvoice({app_cfg.tts.backend})"
        elif app_cfg.tts.provider == "gptsovits":
            from yuiro.audio import GPTSoVITSProvider

            provider = GPTSoVITSProvider(
                base_url=app_cfg.tts.tts_url,
                text_language=(
                    lang if lang in ("zh", "en", "ja")
                    else (app_cfg.tts.tts_text_language or app_cfg.tts.default_language)
                ),
                segment_streaming=app_cfg.tts.segment_streaming,
            )
            backend_label = "gptsovits"
        elif app_cfg.tts.provider == "fish":
            from yuiro.audio.fish import build_fish_provider

            provider = build_fish_provider(app_cfg.tts)
            backend_label = "fish"
            voice = app_cfg.tts.fish_reference_id
        elif app_cfg.tts.provider == "siliconflow":
            from yuiro.audio import SiliconFlowProvider
            from yuiro.keychain import load_siliconflow_key

            sf_key = app_cfg.tts.siliconflow_key or load_siliconflow_key() or ""
            if not sf_key:
                return {"status": "error", "voice": voice, "detail": "SiliconFlow key 未配置（config 或 keychain）"}
            provider = SiliconFlowProvider(
                api_key=sf_key,
                voice=app_cfg.tts.siliconflow_voice,
                reference_wav=app_cfg.tts.siliconflow_reference_wav,
                reference_text=app_cfg.tts.siliconflow_reference_text,
                model=app_cfg.tts.siliconflow_model,
                segment_streaming=app_cfg.tts.segment_streaming,
            )
            backend_label = "siliconflow"
        else:
            if not _import_ready("edge_tts"):
                return {"status": "error", "voice": voice, "detail": "edge-tts 未安装"}
            from yuiro.audio import TTSProvider

            provider = TTSProvider(
                voice=voice,
                segment_streaming=app_cfg.tts.segment_streaming,
                language=lang or "auto",
            )
            backend_label = "edge-tts"
        # S52：顺带回传"参考音频转写的语种" —— 朗读语言该设成什么，看它就知道
        #（参考未必是中文：当前 SiliconFlow 用的是英文 Neuro 台词）
        from yuiro.audio.render import detect_language

        _ref_text = str(getattr(provider, "_reference_text", "") or "")
        reference_lang = detect_language(_ref_text) if _ref_text else "unknown"
        t0 = time.perf_counter()
        segment = await provider.synthesize_segment(sample)
        ms = (time.perf_counter() - t0) * 1000
        return {
            "status": "ok",
            "latency_ms": round(ms, 1),
            "voice": voice,
            "backend": backend_label,
            "transport": getattr(provider, 'transport', None),
            # S52：回传本次试听实际用的语种/文本，便于对照（siliconflow 无 language 参数，
            # 语种由模型自动判定 → 这里回传请求语种，实际听感以音频为准）
            "lang": lang or "auto",
            "text": sample,
            # 参考音频转写的语种：朗读语言与它一致时克隆最自然
            "reference_lang": reference_lang,
            "wav_bytes": len(segment.wav),
            "sample_rate": segment.sample_rate,
            "slice_ms": segment.slice_ms,
            "volumes_count": len(segment.volumes),
            "audio_base64": base64.b64encode(segment.wav).decode("ascii"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "voice": voice, "detail": str(exc)}


async def _test_asr(request: Request) -> dict:
    cfg = _state_config(request.app).asr
    if not _import_ready("faster_whisper"):
        return {"status": "error", "detail": "faster-whisper 未安装"}
    try:
        import numpy as np

        from yuiro.audio import ASRProvider

        provider = ASRProvider(
            model=cfg.model,
            device=cfg.device,
            compute_type=cfg.compute_type,
            language=cfg.language,
            beam_size=cfg.beam_size,
            vad_filter=cfg.vad_filter,
            initial_prompt=cfg.initial_prompt,
        )
        # 生成 1 秒 440Hz 正弦波测试音频（16kHz float32）
        sr = 16000
        t = np.arange(sr, dtype=np.float32) / sr
        test_audio = (0.2 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        t0 = time.perf_counter()
        text = provider.transcribe(test_audio)
        ms = (time.perf_counter() - t0) * 1000
        return {
            "status": "ok",
            "latency_ms": round(ms, 1),
            "result": text or "(无识别文本)",
            "model": cfg.model,
            "device": cfg.device,
            "compute_type": cfg.compute_type,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "model": cfg.model,
            "detail": str(exc),
        }


@router.post("/diary/transcribe")
async def diary_transcribe(request: Request) -> dict:
    """日记语音转写（S51）：**只做 ASR，不进对话链路**。

    为什么不复用 ``/ws/audio``：那条链路是 VAD→ASR→LLM→TTS 的**对话链路**，
    日记正文会被当成"用户在说话" —— 触发预路由工具、写 history、出声回复
    （日记里写"记事本"真的会去开记事本）。语音日记只需要「音频 → 文字」，
    因此这里直接调**已加载**的 ASR provider（``voice_pipeline._asr``，模型常驻，
    不重复加载）。

    入参：原始 **16kHz / 单声道 / int16 LE** PCM（application/octet-stream）。
    """
    pipe = getattr(request.app.state, "voice_pipeline", None)
    asr = getattr(pipe, "_asr", None) if pipe is not None else None
    if asr is None:
        return {"ok": False, "note": "语音识别未就绪（引擎语音管线尚未装配）"}
    raw = await request.body()
    if len(raw) < 16000 * 2 * 0.25:  # 不足 0.25s：再快也说不完一个字
        return {"ok": False, "note": "录音太短，按住多说一会儿"}
    try:
        import numpy as np

        from yuiro.audio import is_noise_transcript

        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        t0 = time.perf_counter()
        text = (await asyncio.to_thread(asr.transcribe, audio)).strip()
        ms = int((time.perf_counter() - t0) * 1000)
        if not text:
            return {"ok": False, "note": "没听清，再说一次？"}
        # ★ 噪音防护（与聊天语音链路**同一判定**，见 audio.is_noise_transcript）：
        # 一声咳嗽被转写成"嗯。"不该在日记里蹦出一个字。
        if is_noise_transcript(text):
            return {"ok": False, "note": "没听清，再说一次？"}
        return {"ok": True, "text": text, "duration_ms": ms}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "note": f"识别失败：{exc}"}


async def _test_vad(request: Request) -> dict:
    if not _import_ready("silero_vad"):
        return {"status": "error", "detail": "silero-vad 未安装"}
    cfg = _state_config(request.app).vad
    try:
        import numpy as np

        from yuiro.audio import VADEngine, VADEvent

        vad = VADEngine(
            probability_threshold=cfg.probability_threshold,
            db_threshold=cfg.db_threshold,
            smoothing_window=cfg.smoothing_window,
            required_hits=cfg.required_hits,
            required_misses=cfg.required_misses,
        )
        events: list[str] = []
        rng = np.random.default_rng(42)
        # 语音段：白噪声模拟，喂 required_hits 帧
        for _ in range(max(1, cfg.required_hits)):
            frame = rng.normal(0.0, 0.08, 512).astype(np.float32)
            ev = vad.feed(frame)
            if ev != VADEvent.Silence:
                events.append(ev.value)
        # 静音段：喂 required_misses 帧
        for _ in range(max(1, cfg.required_misses)):
            ev = vad.feed(np.zeros(512, dtype=np.float32))
            if ev != VADEvent.Silence:
                events.append(ev.value)
        return {
            "status": "ok",
            "provider": cfg.provider,
            "threshold": cfg.probability_threshold,
            "events": events,
            "detail": f"状态机事件: {events or '（未触发迁移）'}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


async def _test_memory(request: Request) -> dict:
    cfg = _state_config(request.app).memory
    vec_ok = _import_ready("sqlite_vec")
    return {
        "status": "ok" if vec_ok else "warn",
        "backend": cfg.backend, "embedder": cfg.embedder,
        "detail": "sqlite-vec 可用（M3 接入三层记忆）" if vec_ok else "sqlite-vec 未安装（M3 前仅存接口）",
    }


async def _test_systemd(request: Request) -> dict:
    cfg = _state_config(request.app).systemd
    daemon = getattr(request.app.state, "system_daemon", None)
    if daemon is None:
        return {"status": "warn", "transport": cfg.transport,
                "detail": "守护进程客户端未初始化（lifespan 未运行）"}
    try:
        tools = await daemon.list_tools()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "transport": cfg.transport, "detail": str(exc)}
    return {
        "status": "warn" if not tools else "ok",
        "transport": cfg.transport, "approval_mode": cfg.approval_mode,
        "tool_count": len(tools),
        "detail": "守护进程已连接（M4 前工具列表为空）" if not tools else f"已暴露 {len(tools)} 个工具",
    }


_TESTERS = {
    "llm": _test_llm,
    "tts": _test_tts,
    "asr": _test_asr,
    "vad": _test_vad,
    "memory": _test_memory,
    "systemd": _test_systemd,
}


@router.post("/providers/{name}/test")
async def test_provider(name: str, request: Request) -> dict:
    if name not in _TESTERS:
        return JSONResponse({"detail": f"unknown provider: {name}"}, status_code=404)
    _emit("INFO", "test", f"联调测试开始: {name}")
    result = await _TESTERS[name](request)
    result.setdefault("provider", name)
    _emit(result.get("status", "error").upper(), "test", f"{name} → {result.get('status')}")
    return result


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
@router.get("/logs/tail")
async def logs_tail(n: int = 200, source: str = "", level: str = "") -> dict:
    entries = log_ring.tail(max(1, min(n, 2000)))
    filtered = [
        asdict(e) for e in entries
        if (not source or e.source == source) and (not level or e.level == level.upper())
    ]
    return {"count": len(filtered), "logs": filtered}


@router.delete("/logs")
async def logs_clear() -> dict:
    log_ring.clear()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 记忆查看/清除（M3 RAG：调试台观察三层记忆内容）
# ---------------------------------------------------------------------------
@router.get("/memory")
async def get_memory(request: Request) -> dict:
    """返回记忆快照：L3 用户事实 + L2 最近情景记忆（前 n 条）。"""
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"facts": [], "episodes": [], "note": "记忆系统未装配"}
    facts = []
    try:
        facts = await memory._facts.query(memory.facts_subject)
    except Exception as exc:  # noqa: BLE001
        facts = [{"error": str(exc)}]
    episodes = []
    try:
        rows = memory.store.recent_search(k=20)
        episodes = [
            {"rowid": r.get("rowid"), "text": r.get("text", "")[:200],
             "ts": r.get("ts"), "salience": r.get("salience")}
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        episodes = [{"error": str(exc)}]
    return {"facts": facts, "episodes": episodes}


@router.delete("/memory")
async def clear_memory(request: Request) -> dict:
    """清除**全部**记忆：L2 情景 + L3 事实 + 关系记忆 + 会话内存 history。

    ★ S50：记忆不止 SQLite。漏掉任何一处，用户点"清空全部记忆"后都会在
    回复里看到残留（实测两例：db 全空仍回复"认识六天聊过 139 次"—— 来自
    ``relationship.json``；"I_drcen/VIP 用户" —— 来自会话内存 history 里
    NCM profile 的工具结果）。全部清掉才算"清空"，并逐项返回数量即时反馈。
    """
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"ok": False, "note": "记忆系统未装配"}
    try:
        def _clear() -> dict:
            cur_msg = memory.store.conn.execute("DELETE FROM messages")
            memory.store.conn.execute("DELETE FROM messages_fts")
            memory.store.conn.execute("DELETE FROM messages_vec")
            memory.store.conn.execute("DELETE FROM facts")
            memory.store.conn.commit()
            return {"episodes": cur_msg.rowcount}
        deleted = await asyncio.to_thread(_clear)
        # 关系记忆：独立 JSON 文件（不在 SQLite），同样必须清。
        rel = getattr(request.app.state, "relationship", None)
        if rel is not None:
            await asyncio.to_thread(rel.reset)
        # 会话内存 history / 状态摘要：不在任何持久层，重启前一直存活。
        loop = getattr(request.app.state, "agent_loop", None)
        history_turns = loop.clear_session_memory() if loop is not None else 0
        _emit(
            "INFO",
            "memory",
            f"记忆已全部清除（情景 {deleted['episodes']} 条、关系记忆已重置、"
            f"会话历史 {history_turns} 轮）",
        )
        return {
            "ok": True,
            "deleted": {
                **deleted,
                "history_turns": history_turns,
                "relationship_reset": rel is not None,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "note": str(exc)}


# ---------------------------------------------------------------------------
# 记忆细粒度管理（调试台「记忆管理」页）：事实增删改 + 检索观测 + 单条情景删除
# ---------------------------------------------------------------------------
@router.put("/memory/facts")
async def upsert_fact(request: Request) -> dict:
    """新增或更新一条用户事实：{"key": "籍贯", "value": "广东人"}。

    写入会经过同义 key 归并（如"家乡"→"籍贯"），与自动抽取走同一套口径，
    避免调试台手工写入的事实与 LLM 抽取的事实各占一个 key。
    """
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"ok": False, "note": "记忆系统未装配"}
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"detail": "body must be an object"}, status_code=400)
    key = str(body.get("key", "")).strip()
    value = str(body.get("value", "")).strip()
    if not key or not value:
        return JSONResponse({"detail": "key 与 value 不能为空"}, status_code=400)
    try:
        conf = float(body.get("confidence", 1.0))
    except (TypeError, ValueError):
        conf = 1.0
    # 走 _apply_facts 以复用同义 key 归并 + 冲突消解(ADD/UPDATE/NOOP) + vlog 可观测
    try:
        await memory._apply_facts([(key, value)], source="manual", confidence=conf)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "note": str(exc)}
    _emit("INFO", "memory", f"手动写入事实 {key}: {value}")
    return {"ok": True, "key": memory._normalize_key(key), "value": value}


@router.delete("/memory/facts/{key:path}")
async def delete_fact(key: str, request: Request) -> dict:
    """删除指定事实（按 key）。用于清掉抽取错误或已过期的画像。"""
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"ok": False, "note": "记忆系统未装配"}
    try:
        await asyncio.to_thread(
            lambda: (
                memory.store.conn.execute(
                    "DELETE FROM facts WHERE subject = ? AND key = ?",
                    (memory.facts_subject, key),
                ),
                memory.store.conn.commit(),
            )
        )
        _emit("INFO", "memory", f"删除事实 {key}")
        return {"ok": True, "key": key}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "note": str(exc)}


def _build_eval_responder(request: Request):
    """把 AgentLoop（或降级单轮 responder）包装成基线 responder（S30）。"""
    loop = getattr(request.app.state, "agent_loop", None)
    fallback = getattr(request.app.state, "chat_responder", None)
    if loop is None and fallback is None:
        return None

    async def _respond(text: str):
        if loop is None:
            return await fallback.reply(text)
        parts: list[str] = []
        calls: list[str] = []
        # 固定会话 id：评测不写记忆（memory_writer 在聊天主链路里，不在这里）
        async for chunk in loop.send("eval-baseline", text):
            kind = getattr(chunk, "kind", "")
            if kind == "token":
                parts.append(str(getattr(chunk, "content", "")))
            elif kind == "tool_call":
                calls.append(str(getattr(chunk, "tool_name", "") or ""))
        return "".join(parts), calls

    return _respond


@router.get("/eval/personality/scenarios")
async def eval_personality_scenarios() -> dict:
    """S30：列出人格基线场景集（PB0）。"""
    from yuiro.eval import load_scenarios

    items = load_scenarios()
    by_cat: dict[str, int] = {}
    for s in items:
        by_cat[s.category] = by_cat.get(s.category, 0) + 1
    return {
        "status": "ok",
        "total": len(items),
        "by_category": by_cat,
        "scenarios": [s.to_dict() for s in items],
    }


@router.post("/eval/personality")
async def eval_personality(
    request: Request, limit: int = 0, live: bool = True, include_tools: bool = False
) -> dict:
    """S30：跑一遍人格基线（PB0）。

    - ``live=false``：离线回声（只验证评测链路，不打 LLM）；
    - ``include_tools``：是否包含工具类场景（**默认 false**——工具场景会真实操作系统）；
    - 报告带 ``model`` / ``prompt_hash`` → 换模型或改 Prompt 后可直接对比两份报告。
    """
    from yuiro.eval import prompt_hash, run_baseline

    cfg = getattr(request.app.state, "app_config", None)
    persona = getattr(cfg, "persona", None) if cfg is not None else None
    fingerprint = prompt_hash(
        getattr(persona, "system_prompt", "") or "",
        getattr(persona, "persona_prompt", "") or "",
    )
    model = getattr(getattr(cfg, "llm", None), "model", "") or ""
    skip = () if include_tools else ("tool",)

    if not live:
        async def _echo(text: str) -> str:
            return f"（离线回声）{text}"

        report = await run_baseline(
            _echo,
            model=f"echo:{model}",
            prompt_fingerprint=fingerprint,
            limit=limit,
            skip_categories=skip,
        )
        return {"status": "ok", **report}

    responder = _build_eval_responder(request)
    if responder is None:
        return {"status": "warn", "detail": "无可用 responder（AgentLoop / LLM 均未就绪）"}
    report = await run_baseline(
        responder,
        model=model,
        prompt_fingerprint=fingerprint,
        limit=limit,
        skip_categories=skip,
    )
    return {"status": "ok", **report}


@router.get("/presence/state")
async def presence_state(request: Request) -> dict:
    """S20：Presence 状态（空闲时长 / 冷却剩余 / 是否静默时段 / 裁决计数）。"""
    presence = getattr(request.app.state, "presence", None)
    if presence is None:
        return {"status": "warn", "detail": "PresenceRuntime 未装配"}
    return {"status": "ok", **presence.state()}


@router.post("/presence/nudge")
async def presence_nudge(request: Request, text: str = "在忙吗？") -> dict:
    """S20：手动提交一次主动表达（调试用；同样经 AttentionPolicy 裁决）。"""
    from yuiro.presence import ProactiveIntent, Urgency

    presence = getattr(request.app.state, "presence", None)
    if presence is None:
        return {"status": "warn", "detail": "PresenceRuntime 未装配"}
    decision = await presence.submit(
        ProactiveIntent(text=text, reason="manual", urgency=Urgency.NORMAL), confidence=1.0
    )
    return {
        "status": "ok" if decision.act else "suppressed",
        "reason": decision.reason,
        "text": text,
    }


@router.post("/presence/system-event")
async def presence_system_event(
    request: Request, text: str, kind: str = "system.event", urgency: str = "low"
) -> dict:
    """S22：系统事件通用入口（spec 的「Build completed → 刚编译成功了」类场景）。

    外部集成（终端 / IDE / 脚本）只需提供"要说什么"；是否真说出口由 AttentionPolicy 裁决。
    """
    from yuiro.presence import ProactiveIntent, parse_urgency

    presence = getattr(request.app.state, "presence", None)
    if presence is None:
        return {"status": "warn", "detail": "PresenceRuntime 未装配"}
    decision = await presence.submit(
        ProactiveIntent(text=text, reason=kind, urgency=parse_urgency(urgency)), confidence=0.9
    )
    return {
        "status": "ok" if decision.act else "suppressed",
        "reason": decision.reason,
        "text": text,
    }


@router.get("/sessions")
async def list_sessions(request: Request, limit: int = 50) -> dict:
    """S43：会话一览（内存中的 + 磁盘上有事件日志的）—— 供前端「选择加载页」。

    前端此前只握着自己那一个 session_id，看不到"还有哪些会话"，
    既无法切换、也对历史毫无感知。
    """
    mgr = getattr(request.app.state, "sessions", None)
    if mgr is None or not hasattr(mgr, "list_sessions"):
        return {"status": "warn", "detail": "SessionManager 未初始化"}
    return {"status": "ok", "sessions": mgr.list_sessions(limit=limit)}


@router.post("/sessions/archive")
async def archive_session(request: Request, session_id: str) -> dict:
    """S43：归档会话（从内存移除；**事件日志保留**，之后仍可复活）。

    与自动回收（sweep）的区别：这是"用户主动结束这个会话"。
    """
    mgr = getattr(request.app.state, "sessions", None)
    if mgr is None or not hasattr(mgr, "archive"):
        return {"status": "warn", "detail": "SessionManager 未初始化"}
    ok = mgr.archive(session_id)
    return {
        "status": "ok" if ok else "warn",
        "note": "已归档（事件日志保留，可复活）" if ok else "会话不在内存中（可能已被回收）",
    }


@router.get("/transaction/list")
async def transaction_list(request: Request, limit: int = 10) -> dict:
    """S33：最近的文件操作事务（动了哪些文件、是否还能撤销）。"""
    backend = getattr(request.app.state, "system_backend", None)
    if backend is None or not hasattr(backend, "list_transactions"):
        return {"status": "warn", "detail": "当前执行后端不支持文件事务"}
    view = await backend.list_transactions(limit)
    return {"status": "ok", **view}


@router.post("/transaction/rollback")
async def transaction_rollback(request: Request, txn_id: str = "last") -> dict:
    """S33：撤销一次文件操作（``txn_id=last`` 撤销最近一次）——"恢复刚才的操作"。"""
    backend = getattr(request.app.state, "system_backend", None)
    if backend is None or not hasattr(backend, "rollback_transaction"):
        return {"status": "warn", "detail": "当前执行后端不支持文件事务"}
    ok, msg = await backend.rollback_transaction(txn_id)
    return {"status": "ok" if ok else "error", "note": msg}


# ---------------------------------------------------------------------------
# S51：日记（结构化保存 + 回顾）—— 设计见 docs/features/diary-feature-design.md
# ---------------------------------------------------------------------------
def _diary_pair(request: Request):
    """返回 ``(service, store)``；未装配时均为 None（端点给明确提示而非 500）。"""
    return (
        getattr(request.app.state, "diary", None),
        getattr(request.app.state, "diary_store", None),
    )


def _diary_brief(row: dict) -> dict:
    """列表项（轻量）：回顾页只需要这些就能渲染时间线。"""
    return {
        "id": row.get("id"),
        "created_at": row.get("created_at"),
        "summary": row.get("summary") or "",
        "title": row.get("title") or "",
        "mood_tags": row.get("mood_tags") or [],
        "topics": row.get("topics") or [],
        "privacy": row.get("privacy"),
        "memory_written": bool(row.get("memory_written")),
        "has_review": bool(row.get("closing_review")),
    }


@router.get("/diary/list")
async def diary_list(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    mood: str = "",
    topic: str = "",
    privacy: str = "",
    q: str = "",
) -> dict:
    """时间线（倒序）+ 筛选；``q`` 非空时走全文检索（短词自动回退子串匹配）。"""
    _svc, store = _diary_pair(request)
    if store is None:
        return {"status": "warn", "items": [], "note": "日记未启用"}
    rows = (
        store.search(q, limit=max(1, min(limit, 100)))
        if q.strip()
        else store.list_recent(
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
            mood=mood.strip(),
            topic=topic.strip(),
            privacy=privacy.strip(),
        )
    )
    return {"status": "ok", "count": len(rows), "items": [_diary_brief(r) for r in rows]}


@router.get("/diary/stats")
async def diary_stats(request: Request) -> dict:
    """统计（只呈现事实，不做评价）。"""
    _svc, store = _diary_pair(request)
    if store is None:
        return {"status": "warn", "note": "日记未启用"}
    return {"status": "ok", **store.stats()}


def _diary_media_guard(request):
    import secrets
    from fastapi import HTTPException
    cfg = _state_config(request.app)
    expected = cfg.server.shared_secret
    # 与现有WS/角色接口一致：默认开发占位值不是已配置的凭证。
    # 壳从独立终端启动时可能没有加载env.ps1，不能因此只让新增接口401。
    if expected and expected != "dev-only-change-me" and not secrets.compare_digest(
        expected, request.headers.get("x-yuiro-secret", "")
    ):
        raise HTTPException(401,"引擎与壳的共享密钥不一致，请从同一本地环境启动两者")
    owner = getattr(cfg,"_character_id","")
    if owner and request.headers.get("x-yuiro-character") != owner:
        raise HTTPException(409,"角色已切换，请重新打开记录")


@router.post("/diary/assets")
async def diary_upload(request: Request, name: str = "附件"):
    from fastapi import HTTPException
    from yuiro.diary.media import upload, MAX_BYTES
    _diary_media_guard(request)
    _,store = _diary_pair(request)
    if store is None: raise HTTPException(503,"日记未启用")
    data=bytearray()
    async for chunk in request.stream():
        if len(data)+len(chunk)>MAX_BYTES: raise HTTPException(413,"附件不能超过20MB")
        data.extend(chunk)
    _diary_media_guard(request)
    if store is not _diary_pair(request)[1]: raise HTTPException(409,"角色已切换")
    try: return {"status":"ok","asset":upload(store,name,bytes(data))}
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc


@router.get("/diary/assets/{asset_id}")
async def diary_asset(asset_id: str, request: Request):
    from fastapi import HTTPException
    from fastapi.responses import Response
    _diary_media_guard(request)
    _,store=_diary_pair(request)
    row=store.conn.execute("SELECT mime,data FROM diary_assets WHERE id=?",(asset_id,)).fetchone() if store else None
    if row is None: raise HTTPException(404,"附件不存在")
    return Response(bytes(row["data"]),media_type=row["mime"],headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})


@router.get("/diary/{diary_id}/revisions")
async def diary_revisions(diary_id: int, request: Request):
    import json
    from yuiro.diary.media import assets
    _diary_media_guard(request)
    _,store=_diary_pair(request)
    if not store: return {"status":"error","items":[]}
    rows=store.conn.execute("SELECT snapshot FROM diary_revisions WHERE diary_id=? ORDER BY revision DESC",(diary_id,)).fetchall()
    items=[json.loads(r[0]) for r in rows]
    for row in items: row["attachments"]=assets(store,row.get("source_meta",{}).get("attachment_ids",[]))
    return {"status":"ok","items":items}


@router.put("/diary/{diary_id}")
async def diary_edit(diary_id: int, request: Request):
    from fastapi import HTTPException
    _diary_media_guard(request)
    svc,store=_diary_pair(request)
    body=await request.json()
    _diary_media_guard(request)
    if store is not _diary_pair(request)[1]: raise HTTPException(409,"角色已切换")
    if not svc: raise HTTPException(503,"日记未启用")
    if not isinstance(body,dict): raise HTTPException(400,"无效记录")
    title,text=body.get("title",""),body.get("raw_text","")
    if not isinstance(title,str) or not isinstance(text,str) or len(title)>160 or len(text)>100000:
        raise HTTPException(400,"标题最多160字，正文最多10万字")
    try:
        result=await svc.edit(diary_id,revision=int(body.get("revision",0)),title=title,text=text,attachment_ids=body.get("attachment_ids",[]))
        return {"status":"ok",**result}
    except (ValueError,TypeError) as exc: raise HTTPException(409,str(exc)) from exc


@router.get("/diary/{diary_id}")
async def diary_detail(diary_id: int, request: Request) -> dict:
    """详情：原文 / 定稿 / 总评 / 标签 / 隐私档 / 记忆写入状态（供"她怎么知道的"溯源）。"""
    _svc, store = _diary_pair(request)
    if store is None:
        return {"status": "warn", "note": "日记未启用"}
    row = store.get(diary_id)
    if row is None:
        return {"status": "error", "note": f"找不到日记 id={diary_id}"}
    from yuiro.diary.media import assets
    row["attachments"] = assets(store,row["source_meta"].get("attachment_ids",[]))
    return {"status": "ok", "diary": row, "tags": store.tags_of(diary_id)}


@router.post("/diary")
async def diary_submit(request: Request) -> dict:
    """提交一篇日记：``{"raw_text": "...", "privacy": "local_only|shared|discard", "quip_mode": false}``。"""
    svc, _store = _diary_pair(request)
    if svc is None:
        return {"status": "warn", "note": "日记未启用"}
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"detail": "body must be an object"}, status_code=400)
    raw = str(body.get("raw_text") or "").strip()
    if not raw:
        return {"status": "error", "note": "日记内容为空"}
    from yuiro.diary import PRIVACY_LOCAL_ONLY

    privacy = str(body.get("privacy") or PRIVACY_LOCAL_ONLY)
    try:
        res = await svc.submit(
            raw, privacy=privacy, quip_mode=bool(body.get("quip_mode", False))
        )
    except ValueError as exc:  # 非法档位等
        return {"status": "error", "note": str(exc)}
    if not res.get("ok"):
        return {"status": "error", **res}
    return {"status": "ok", **res}


@router.delete("/diary/{diary_id}")
async def diary_delete(diary_id: int, request: Request) -> dict:
    """删除日记 —— 并**连带删除它写入的记忆**（默认同删，符合直觉）。"""
    svc, _store = _diary_pair(request)
    if svc is None:
        return {"status": "warn", "note": "日记未启用"}
    res = await svc.delete(diary_id)
    if res.get("ok"):
        _emit("INFO", "diary", f"删除日记 id={diary_id}（连带记忆 {res.get('memory_removed', 0)} 条）")
    return {"status": "ok" if res.get("ok") else "error", **res}


@router.post("/diary/{diary_id}/privacy")
async def diary_set_privacy(diary_id: int, request: Request, value: str = "") -> dict:
    """改隐私档位 —— **同步记忆**（改成"仅保存"会删掉已写记忆，否则是谎报隐私）。"""
    svc, _store = _diary_pair(request)
    if svc is None:
        return {"status": "warn", "note": "日记未启用"}
    try:
        res = await svc.change_privacy(diary_id, value.strip())
    except ValueError as exc:
        return {"status": "error", "note": str(exc)}
    if res.get("ok"):
        _emit(
            "INFO",
            "diary",
            f"日记 {diary_id} 档位 {res.get('from')} → {res.get('to')}"
            f"（删记忆 {res.get('memory_removed', 0)} / 写记忆 {res.get('memory_written', 0)}）",
        )
    return {"status": "ok" if res.get("ok") else "error", **res}


@router.post("/diary/{diary_id}/review")
async def diary_review(diary_id: int, request: Request) -> dict:
    """确认录入后的总评（一次性；失败退回既有简短回应，不阻塞）。"""
    svc, _store = _diary_pair(request)
    if svc is None:
        return {"status": "warn", "note": "日记未启用"}
    res = await svc.closing_review(diary_id)
    return {"status": "ok" if res.get("ok") else "error", **res}


@router.get("/search/status")
async def search_status(request: Request) -> dict:
    """S51：联网检索可用性（供聊天坞开关显示禁用态与**理由**）。

    为什么前端需要它：若开关在"引擎根本没配密钥"时仍可点开，用户会以为
    "我开了它却不搜" —— **沉默的失效比禁用更糟**（设计文档 §9.6：禁用态必须说明原因）。
    """
    cfg = getattr(request.app.state, "app_config", None)
    search_cfg = getattr(cfg, "search", None)
    enabled = bool(getattr(search_cfg, "enabled", False))
    from yuiro import keychain

    has_key = bool((keychain.load_search_key() or "").strip())
    if not enabled:
        hint = "联网检索已在设置中关闭"
    elif not has_key:
        hint = "未配置 DeepSeek 搜索密钥，请在联网页安全填写（旧服务商密钥不复用）"
    else:
        hint = ""
    return {
        "status": "ok",
        "enabled": enabled,
        "available": enabled and has_key,
        "hint": hint,
        "provider": str(getattr(search_cfg, "provider", "deepseek")),
    }


@router.get("/capability/scope")
async def capability_scope(request: Request) -> dict:
    """S19：当前 CapabilityScope 视图（域声明 / 未声明域 / 硬红线 / 工具→域映射）。"""
    from yuiro.capability import CapabilityScope

    cfg = getattr(request.app.state, "app_config", None)
    scope_cfg = getattr(getattr(cfg, "capability", None), "scope", None) if cfg else None
    scope = CapabilityScope(scope_cfg)
    profile = getattr(getattr(cfg, "capability", None), "profile", "normal") if cfg else "normal"
    return {"status": "ok", "profile": profile, **scope.to_dict()}


@router.get("/capability/check")
async def capability_check(request: Request, tool: str, value: str = "") -> dict:
    """S19：试算一次判定（不执行）——``?tool=file_write&value=C:/Windows/x.txt``。"""
    from yuiro.capability import Policy

    cfg = getattr(request.app.state, "app_config", None)
    cap = getattr(cfg, "capability", None) if cfg else None
    policy = Policy(
        profile=getattr(cap, "profile", None), scope=getattr(cap, "scope", None)
    )
    # 资源值参数名随工具而定（file_* → path / app_* → name）；试算时按域推断
    from yuiro.capability.scope import arg_key_for

    arg_key = arg_key_for(tool) or "value"
    decision = policy.decide(tool, {arg_key: value} if value else {})
    return {
        "status": "ok",
        "tool": tool,
        "value": value,
        "action": decision.action,
        "reason": decision.reason,
    }


@router.get("/avatar/performances")
async def avatar_performances(request: Request) -> dict:
    """S18 Performance Gallery：列出全部表演包（调试台 / 前端展示用）。"""
    avatar = getattr(request.app.state, "avatar", None)
    if avatar is None:
        return {"status": "warn", "detail": "AvatarRuntime 未装配"}
    return {"status": "ok", "performances": avatar.performances()}


@router.post("/avatar/perform/{name}")
async def avatar_perform(request: Request, name: str, session_id: str = "") -> dict:
    """S18：点击即表演（Performance Gallery 的"现场演出"能力）。"""
    avatar = getattr(request.app.state, "avatar", None)
    if avatar is None:
        return {"status": "warn", "detail": "AvatarRuntime 未装配"}
    ok = await avatar.perform(session_id, name, source="system")
    return {"status": "ok" if ok else "skipped", "performance": name}


def _task_view(task) -> dict:
    cur = task.current_step()
    # S31 修正：字段名用 task_status —— 否则会覆盖外层 {"status": "ok"}（键冲突）
    return {
        "task_id": task.id,
        "goal": task.goal,
        "task_status": task.status.value,
        "progress": task.progress(),
        "current_step": cur.desc if cur is not None else "",
        "attempts": cur.attempts if cur is not None else 0,
        "steps": [s.desc for s in task.steps],
        "summary": task.summary(),
    }


@router.get("/task/list")
async def task_list(request: Request, include_done: bool = False) -> dict:
    """S29：任务列表（默认只看未结束的；待批准计划会带 ``pending_approval`` 状态）。"""
    tasks = getattr(request.app.state, "tasks", None)
    if tasks is None:
        return {"status": "warn", "detail": "TaskRuntime 未装配"}
    items = tasks.list_all() if include_done else tasks.list_active()
    return {"status": "ok", "count": len(items), "tasks": [_task_view(t) for t in items]}


@router.post("/task/{task_id}/approve")
async def task_approve(
    request: Request, task_id: str, steps: str = "", note: str = ""
) -> dict:
    """S29：批准一份待批准的计划（``steps`` 用 ``|`` 分隔可**改写**计划）。"""
    tasks = getattr(request.app.state, "tasks", None)
    if tasks is None:
        return {"status": "warn", "detail": "TaskRuntime 未装配"}
    new_steps = [s.strip() for s in steps.split("|") if s.strip()] if steps else None
    try:
        task = await tasks.approve(task_id, approved=True, steps=new_steps, note=note)
    except (KeyError, ValueError) as exc:
        return {"status": "error", "detail": str(exc)}
    return {"status": "ok", **_task_view(task)}


@router.post("/task/{task_id}/reject")
async def task_reject(request: Request, task_id: str, reason: str = "") -> dict:
    """S29：拒绝一份待批准的计划（任务转为 cancelled）。"""
    tasks = getattr(request.app.state, "tasks", None)
    if tasks is None:
        return {"status": "warn", "detail": "TaskRuntime 未装配"}
    try:
        task = await tasks.approve(task_id, approved=False, note=reason)
    except (KeyError, ValueError) as exc:
        return {"status": "error", "detail": str(exc)}
    return {"status": "ok", **_task_view(task)}


@router.post("/task/{task_id}/retry")
async def task_retry(request: Request, task_id: str, reason: str = "") -> dict:
    """S29：记录一次失败并决定"再试 / 判失败"（失败恢复）。"""
    tasks = getattr(request.app.state, "tasks", None)
    if tasks is None:
        return {"status": "warn", "detail": "TaskRuntime 未注入"}
    try:
        task = await tasks.retry(task_id, reason)
    except (KeyError, ValueError) as exc:
        return {"status": "error", "detail": str(exc)}
    return {"status": "ok", **_task_view(task)}


@router.post("/memory/consolidate")
async def memory_consolidate(
    request: Request, min_support: int = 3, use_llm: bool = True
) -> dict:
    """S28：手动触发一次记忆归纳（Episode → 稳定画像）。

    安全：只写 L3 facts（不改会话/近期记忆）；已有更可信的事实不会被覆盖。
    """
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"status": "warn", "detail": "记忆系统未装配"}
    result = await memory.consolidate(min_support=min_support, use_llm=use_llm)
    return {"status": "ok", **result}


@router.get("/memory/relationship")
async def memory_relationship(request: Request) -> dict:
    """S26：关系记忆视图（认识多久 / 聊过多少次 / 一起做成过什么 / 里程碑）。"""
    rel = getattr(request.app.state, "relationship", None)
    if rel is None:
        return {"status": "warn", "detail": "RelationshipMemory 未装配"}
    return {"status": "ok", **rel.to_dict()}


@router.get("/memory/showcase")
async def memory_showcase(request: Request) -> dict:
    """S17：记忆 Showcase 快照——一次看清"它记得什么"（三通道 + 统计）。

    通道：explicit（用户要求记住的事）/ facts（稳定事实）/ episodes（近期情景）。
    """
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"status": "warn", "detail": "记忆系统未装配"}
    facts: list = []
    episodes: list = []
    try:
        facts = await memory._facts.query(memory.facts_subject)
    except Exception as exc:  # noqa: BLE001
        facts = [{"error": str(exc)}]
    try:
        episodes = memory.store.recent_search(k=10)
    except Exception as exc:  # noqa: BLE001
        episodes = [{"error": str(exc)}]
    explicit = memory.list_explicit()
    return {
        "status": "ok",
        "counts": {
            "explicit": len(explicit),
            "facts": len(facts),
            "episodes": len(episodes),
        },
        "explicit": explicit,
        "facts": facts[:20],
        "episodes": [
            {
                "rowid": e.get("rowid"),
                "text": str(e.get("text", ""))[:160],
                "ts": e.get("ts"),
                "salience": e.get("salience"),
            }
            for e in episodes
        ],
    }


@router.get("/memory/explicit")
async def list_explicit_memory(request: Request) -> dict:
    """S13：列出显式记忆（用户要求记住的事）。"""
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"status": "warn", "items": []}
    items = memory.list_explicit()
    return {"status": "ok", "count": len(items), "items": items}


@router.delete("/memory/explicit/{rowid}")
async def delete_explicit_memory(request: Request, rowid: int) -> dict:
    """S13：删除一条显式记忆（"忘掉这个"）。"""
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"status": "warn", "ok": False}
    ok = memory.delete_explicit(rowid)
    if ok:
        _emit("INFO", "memory", f"显式记忆已删除 rowid={rowid}")
    return {"status": "ok" if ok else "error", "ok": ok, "rowid": rowid}


@router.post("/memory/forget")
async def run_memory_forget(request: Request) -> dict:
    """S13：手动触发记忆遗忘（清理陈旧且已衰减的事实/情景；显式记忆永不删除）。"""
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"status": "warn", "ok": False}
    removed = await memory.forget()
    return {"status": "ok", "removed": removed}


@router.get("/memory/search")
async def search_memory(request: Request, q: str = "", top_k: int = 5) -> dict:
    """按查询实际跑一次检索，返回将被注入上下文的内容。

    用于观测「记忆有没有被召回」——这是排查"记不住/没呼出"最直接的手段：
    输入用户可能说的话，看 L2 情景与 L3 事实分别命中了什么。
    """
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"ok": False, "note": "记忆系统未装配", "results": []}
    if not q.strip():
        return {"ok": True, "results": [], "note": "缺少查询词 q"}
    try:
        mems = await memory.retrieve(q, top_k=max(1, min(top_k, 50)))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "note": str(exc), "results": []}
    return {
        "ok": True,
        "count": len(mems),
        "results": [
            {
                "kind": (m.meta or {}).get("kind", "episode"),
                "text": m.text,
                "score": round(float(m.score), 4),
            }
            for m in mems
        ],
    }


@router.delete("/memory/episodes/{rowid}")
async def delete_episode(rowid: int, request: Request) -> dict:
    """删除单条 L2 情景记忆（按 rowid）。

    ★ S50：主表与附属表（FTS / 向量）**三张一起删**。此前只删 ``messages``，
    FTS 与向量残留孤儿行 —— 直接查库会看到"删了还在"（正是用户反馈
    「删除没落库」的错觉来源），且孤儿向量占着 rowid 污染语义检索。
    返回实际删除数（rowcount），前端据此即时反馈，不再"点了没反应"。
    """
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        return {"ok": False, "note": "记忆系统未装配"}
    try:
        def _delete() -> int:
            cur = memory.store.conn.execute(
                "DELETE FROM messages WHERE rowid = ?", (rowid,)
            )
            memory.store.conn.execute(
                "DELETE FROM messages_fts WHERE rowid = ?", (rowid,)
            )
            memory.store.conn.execute(
                "DELETE FROM messages_vec WHERE rowid = ?", (rowid,)
            )
            memory.store.conn.commit()
            return cur.rowcount
        deleted = await asyncio.to_thread(_delete)
        if deleted:
            _emit("INFO", "memory", f"删除情景记忆 rowid={rowid}")
        return {"ok": deleted > 0, "rowid": rowid, "deleted": deleted}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "note": str(exc)}


# ---------------------------------------------------------------------------
# 知识库 RAG（文档导入/查看/检索/清除）
# ---------------------------------------------------------------------------
@router.post("/knowledge/ingest")
async def ingest_knowledge(request: Request) -> dict:
    """导入知识：{"text": "...", "source": "..."} 或 {"path": "文件/目录路径"}。

    ★ 开发文档防线（S51）：知识库内容会**每轮注入对话**，把里程碑/路线图这类
    开发过程文档导进去，她会冒出"我们在 M4→M5 阶段""记得写 ARCHITECTURE 变更日志"
    之类的话 —— 实测出戏（用户反馈原话："这类东西当知识库有些出戏了"）。
    所以对**明显是仓库开发文档**的路径先拦一下，确需导入时带 ``force: true``。
    """
    memory = getattr(request.app.state, "memory", None)
    knowledge = getattr(memory, "_knowledge", None) if memory else None
    if knowledge is None:
        return {"ok": False, "note": "知识库未装配"}
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"detail": "body must be an object"}, status_code=400)
    try:
        if isinstance(body.get("text"), str) and body["text"].strip():
            n = await knowledge.ingest(
                body["text"], source=str(body.get("source", "manual"))
            )
            _emit("INFO", "knowledge", f"知识导入 {n} 块")
            return {"ok": True, "chunks": n}
        if isinstance(body.get("path"), str) and body["path"].strip():
            path = body["path"]
            if _looks_like_dev_doc(path) and not body.get("force"):
                return {
                    "ok": False,
                    "blocked": True,
                    "note": "这看起来是**开发文档**（里程碑 / 路线图 / 架构 / 计划）。"
                            "知识库的内容会每轮注入对话，容易让她冒出项目术语、显得出戏。"
                            "确实要导入，请带 force=true 再来一次。",
                }
            if os.path.isdir(path):
                n = await knowledge.ingest_dir(path)
            elif os.path.isfile(path):
                n = await knowledge.ingest_file(path)
            else:
                return {"ok": False, "note": f"路径不存在: {path}"}
            _emit("INFO", "knowledge", f"知识导入 {n} 块（{path}）")
            return {"ok": True, "chunks": n}
        return JSONResponse(
            {"detail": "需要 text 或 path 字段"}, status_code=400
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "note": str(exc)}


@router.get("/knowledge")
async def get_knowledge(request: Request) -> dict:
    """知识库统计 + **来源清单** + 按查询检索（可选 ?q=）。

    来源清单是"可见性"的关键：没有它，用户根本不知道知识库里装了什么
    （实测：一份里程碑文档在里面躺了很久，每轮注入 286 tokens 才被发现）。
    """
    memory = getattr(request.app.state, "memory", None)
    knowledge = getattr(memory, "_knowledge", None) if memory else None
    if knowledge is None:
        return {"ok": False, "note": "知识库未装配"}
    stats = knowledge.stats()
    result: dict = {"ok": True, "stats": stats, "sources": knowledge.sources()}
    q = request.query_params.get("q", "")
    if q:
        result["hits"] = await knowledge.retrieve(q, top_k=5)
    return result


@router.delete("/knowledge")
async def clear_knowledge(request: Request) -> dict:
    memory = getattr(request.app.state, "memory", None)
    knowledge = getattr(memory, "_knowledge", None) if memory else None
    if knowledge is None:
        return {"ok": False, "note": "知识库未装配"}
    try:
        await asyncio.to_thread(knowledge.clear)
        _emit("INFO", "knowledge", "知识库已清除")
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "note": str(exc)}


# 供 main.py 启动时回填一些关键事件
def emit_startup_summary(backend_name: str) -> None:
    _emit("INFO", "engine", f"启动完成，聊天后端: {backend_name}")
