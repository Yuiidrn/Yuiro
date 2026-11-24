"""FastAPI entrypoint + WebSocket routes for the Yuiro engine.

M1: WS control channel handles text chat (chat:user -> chat:assistant).
Actual voice pipeline wired in M2.
"""
from __future__ import annotations

import os as _os
import sys as _sys

# 净化 sys.path：本机 venv 基于 ComfyUI 的 Python 3.13 创建，其 python313.zip 标准库
# 压缩包缺部分模块（如 quopri），而同目录的 Lib/ 含完整标准库。这里移除残缺的 zip，
# 仅保留 ComfyUI 的完整 Lib 目录作为 stdlib 来源，避免 import 到错误的 multiprocessing
# 或缺失模块。spawn 子进程继承该 path，故必须在一切 import 之前处理。
_comfy_zip = next((p for p in _sys.path if "ComfyUI" in p and p.endswith(".zip")), None)
if _comfy_zip:
    _comfy_lib = _os.path.join(_os.path.dirname(_comfy_zip), "Lib")
    _sys.path = [p for p in _sys.path if "ComfyUI" not in p]
    if _os.path.isdir(_comfy_lib):
        _sys.path.insert(0, _comfy_lib)
else:
    _sys.path = [p for p in _sys.path if not p or "ComfyUI" not in p]

# 日志编码修正：Windows 下 Python 默认按系统 ANSI（cp936/GBK）写 stdout，
# 而 PowerShell / VSCode / tail 类工具普遍按 UTF-8 读取，导致中文日志整片乱码
# （实测 [yuiro][chat] 处理 chat:user '你好啊' 显示为 "???? chat:user '??'"）。
# 这里在最早时机把 stdout/stderr 切到 UTF-8，并对重定向到文件的场景写入 UTF-8 BOM，
# 使 PowerShell 5.1（按 BOM 识别）与 PowerShell 7（默认 UTF-8）都能正确显示中文。
def _force_utf8_console() -> None:
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(_sys, _stream_name, None)
        if _stream is None:
            continue
        try:
            if hasattr(_stream, "reconfigure"):
                _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — 编码切换失败不阻断启动
            pass
    # 仅在「输出被重定向到文件」且文件为空（刚创建）时写 BOM，避免污染控制台输出。
    _out = getattr(_sys, "stdout", None)
    try:
        if _out is not None and hasattr(_out, "fileno") and not _out.isatty():
            import os as _os2
            _fd = _out.fileno()
            if _os2.fstat(_fd).st_size == 0:
                _out.write("\ufeff")
                _out.flush()
    except Exception:  # noqa: BLE001 — 写 BOM 失败不影响功能
        pass


_force_utf8_console()

from yuiro.logger import quiet_status_poll_logs

quiet_status_poll_logs()

import asyncio
import base64
import json
import sys
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yuiro.memory import MemorySystem

# Windows 子进程（SystemDaemon stdio transport）需要 Proactor 事件循环。
# 必须在 uvicorn 创建事件循环前设置；ComfyUI 等环境可能已改为 Selector 策略。
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:  # noqa: BLE001 — 策略已设置等场景忽略
        pass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from yuiro.agent.chat_service import build_responder
from yuiro.audio import ASRProvider, AudioSegment, TTSProvider, VADEngine, VoicePipeline, split_sentences
from yuiro.config import AppConfig, load_config
from yuiro.debug_api import emit_startup_summary, log_ring
from yuiro.debug_api import router as debug_router
from yuiro.keychain import load_llm_key
from yuiro.logger import vlog
from yuiro.netease import ensure_daemon_ready
from yuiro.runtime import AgentEvent, EventBus, SessionManager, TraceContext
from yuiro.runtime.observation import OrderedObservation
from yuiro.systemd.client import SystemDaemonClient

app_config: AppConfig = load_config()
from yuiro.characters import CharacterStore  # noqa: E402

_character_store = CharacterStore()
_character_id = _character_store.ensure(app_config)
if not getattr(app_config, "_character_id", ""):
    app_config = _character_store.resolve(_character_id, app_config)


def _probe_embedder_files(model: str) -> None:
    """启动时体检嵌入模型文件（**纯文件检查，不 spawn 子进程**）。

    为什么值得单独做这件事：``Embedder`` 在权重缺失/子进程未就绪时会**静默降级到
    md5 向量** —— 那种向量没有语义，记忆召回与语义匹配都退化成近似随机，
    而表面上一切正常。实测 BGE-M3 权重下载中断了数周没人发现，唯一的信号是
    "感觉记忆不太准"这种主观感受，根本无法归因。

    这里只查文件在不在（不加载模型、不 spawn worker，代价近乎为零），
    把"语义能力是否真的在线"变成启动日志里一眼可见的事实。
    """
    try:
        import os

        if os.path.isdir(model):
            names = set(os.listdir(model))
            if {"pytorch_model.bin", "model.safetensors"} & names:
                vlog("memory", f"嵌入模型自检通过：{model}（本地目录）")
            else:
                vlog(
                    "memory",
                    f"⚠ 嵌入模型目录 {model} 里没有权重文件（pytorch_model.bin / "
                    "model.safetensors）—— 语义检索会**静默降级为 md5 向量**",
                )
            return

        from huggingface_hub import try_to_load_from_cache

        for fname in ("pytorch_model.bin", "model.safetensors"):
            if isinstance(try_to_load_from_cache(model, fname), str):
                vlog("memory", f"嵌入模型自检通过：{model}（已缓存 {fname}）")
                return
        vlog(
            "memory",
            f"⚠ 嵌入模型 {model} 的权重未缓存 —— Embedder 会**静默降级为 md5 向量**"
            "（无语义，检索≈随机）。补齐：python scripts/fetch_bge.py；"
            '或明确接受降级：[memory].embedder = "md5"',
        )
    except Exception as exc:  # noqa: BLE001 — 体检失败绝不影响启动
        vlog("memory", f"嵌入模型自检跳过（{exc}）")


def _build_memory(cfg: AppConfig, shared_embedder=None) -> MemorySystem:
    """一次性装配持久化三层记忆 + 知识库 RAG（不依赖 daemon，须只创建一次）。

    BGE-M3 子进程隔离：每个 MemorySystem/KnowledgeStore 都会 spawn 一个嵌入 worker，
    重复装配会成倍 spawn 且旧 worker 的 pipe 在对象被 GC 后关闭，导致
    BrokenPipe。因此必须缓存复用，绝不在 lifespan 重建时重新创建。
    """
    from yuiro.memory import KnowledgeStore, MemorySystem

    # embedder 取值：
    #   "md5"                  -> None，显式降级为确定性向量（无需下载）
    #   "bge-m3" / 其他 repo id -> 透传给 FlagEmbedding，由其从 HuggingFace Hub 拉取
    #   本地绝对/相对路径        -> 透传，FlagEmbedding/transformers 检测到目录存在即本地加载，
    #                              不再触发任何下载（见 scripts/download_bge_m3_modelscope.py）
    db_path = Path(cfg.memory.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    embedder_model = None if cfg.memory.embedder == "md5" else cfg.memory.embedder
    if embedder_model:
        # S42：配了真嵌入模型就体检一次 —— 权重缺失时 Embedder 会静默降级到 md5
        # 向量（无语义），不主动查就只能等用户"感觉记忆不准"（实测拖了数周）。
        _probe_embedder_files(str(embedder_model))
    knowledge = KnowledgeStore(str(db_path), rrf_k=cfg.memory.rrf_k,
                               embedder_model=embedder_model, embedder=shared_embedder)
    # L3 事实主体：以 persona.memory_subject 为准（按角色隔离事实），
    # 回退到 memory.facts_subject（兼容旧配置）。
    facts_subject = cfg.persona.memory_subject or cfg.memory.facts_subject
    memory = MemorySystem(
        db_path=str(db_path),
        rrf_k=cfg.memory.rrf_k,
        top_k=cfg.memory.auto_inject_top_k,
        facts_subject=facts_subject,
        knowledge=knowledge,
        embedder_model=embedder_model,
        embedder=shared_embedder,
    )
    vlog(
        "memory",
        f"记忆系统已装配（db={db_path}, embedder={cfg.memory.embedder}, "
        f"rrf_k={cfg.memory.rrf_k}, 注入 top_k={cfg.memory.auto_inject_top_k}，知识库已启用）",
    )
    return memory


def _build_system_backend(cfg, txn_cfg=None):
    """按 [systemd].backend 装配系统执行后端（S10：native 默认 / daemon 可选）。

    两者同签名（call(tool, args, dry_run) -> SystemActionResult），可随时切换。
    S33：native 后端附带文件事务存储（``[transaction]`` 段）——文件的改/移/删可回滚。
    """
    from yuiro.native import NativeBackend
    from yuiro.transaction import TxnStore

    name = (getattr(cfg, "backend", "native") or "native").strip().lower()
    if name == "daemon":
        return SystemDaemonClient(cfg)

    enabled = bool(getattr(txn_cfg, "enabled", True)) if txn_cfg is not None else True
    root = str(getattr(txn_cfg, "backup_root", "") or "") if txn_cfg is not None else ""
    keep = int(getattr(txn_cfg, "keep", 20) or 20) if txn_cfg is not None else 20
    return NativeBackend(
        file_roots=getattr(cfg, "file_roots", None),
        # 指定了 backup_root 才显式建 store；否则由 NativeBackend 用默认目录（<cwd>/.yuiro/txn）
        txn_store=TxnStore(root, keep=keep) if (enabled and root) else None,
        txn_enabled=enabled,
    )


def _build_agent(cfg: AppConfig, api_key: str, system_daemon=None, memory=None, events=None,
                 system_backend=None):
    """装配 AgentLoop（工厂在 agent 包，审批门/连接注册在 approval 模块）。

    ``memory`` 为已缓存的 MemorySystem；传入则复用（避免重复 spawn 嵌入 worker），
    缺省时新建（仅模块级首次装配调用）。
    """
    from yuiro.agent import build_agent_loop
    from yuiro.approval import approval_gate, set_approval_mode

    # 按配置设置审批模式：auto（默认，直接通过）/ manual（人工审批弹窗）
    set_approval_mode(getattr(cfg.systemd, "approval_mode", "auto"))

    if memory is None:
        memory = _build_memory(cfg)
        # 挂到 app.state 供 debug API（查看/清除记忆）
        app.state.memory = memory
    # S51：空闲期记忆整理调度器 —— 与 6h 兜底循环**分工不同**：
    # 兜底循环"不管有没有人都按时跑"，它则抓"用户刚聊完 / 这一场刚结束"这两个
    # 线索还热的时机（见 memory/idle.py 的模块说明）。
    if getattr(app.state, "memory_idle", None) is None:
        from yuiro.memory.idle import MemoryIdleScheduler

        app.state.memory_idle = MemoryIdleScheduler(memory.tidy)
    # S08：TaskRuntime（跨多轮目标）；首次构建时装配并挂到 app.state
    # S18：注入 EventBus——task.completed 事件用于驱动庆祝表演（事件驱动，非 if 判断）
    tasks = getattr(app.state, "tasks", None)
    if tasks is None:
        from yuiro.task import TaskRuntime

        task_dir = "data/tasks" if _character_id == "hiyori" else f"data/characters/{_character_id}/tasks"
        tasks = TaskRuntime(events=events, store_dir=task_dir)
        app.state.tasks = tasks
    return build_agent_loop(
        base_url=cfg.llm.base_url,
        model=cfg.llm.model,
        api_key=api_key,
        temperature=cfg.llm.temperature,
        approval_gate=approval_gate,
        memory_system=memory,
        system_daemon=system_daemon,
        system_backend=system_backend,
        persona=cfg.persona,
        memory_config=cfg.memory,
        netease_config=cfg.netease,
        music_identity_getter=lambda sid: _client_search_identity(sid),
        search_config=cfg.search,
        # S51：日记回顾工具（延迟绑定 —— 日记稍后在 lifespan 里装配）
        diary_getter=lambda: getattr(app.state, "diary_store", None),
        context_config=cfg.context,
        task_runtime=tasks,
        capability_config=cfg.capability,
        # S18：表演工具（延迟绑定，避免与 avatar 装配顺序耦合）
        avatar_getter=lambda: getattr(app.state, "avatar", None),
        # S26：关系记忆（经 ContextEngine 注入【我们的关系】）
        relationship=getattr(app.state, "relationship", None),
        events=events,
        # S47 / B4：TurnJournal 靠它查"未完成的回合"（EventBus 负责**写**，
        # EventLog 负责**查** —— 缺它就只能记录、无法回溯）。
        event_log=getattr(app.state, "event_log", None),
        # S47 / B3：回合预算（[agent] 段：max_seconds / max_tokens / max_rounds）
        agent_config=cfg.agent,
    )


async def _interaction_reward() -> None:
    """用户互动奖励：情绪加成 + 经验/亲密度；主情绪变化推送到壳层。"""
    engine = getattr(app.state, "emotion_engine", None)
    character = getattr(app.state, "character", None)
    if engine is None:
        return
    engine.boost("happy", 0.03)
    engine.boost("bored", -0.02)
    if character is not None:
        character.add_xp(5)
        character.add_affinity(0.1)
    changed = engine.decay()
    if changed:
        from yuiro.approval import broadcast_control

        await broadcast_control({
            "type": "emotion:set",
            "emotion": changed,
            "values": engine.state.values(),
        })
        vlog("emotion", f"主情绪变化: {changed} -> 已推送壳层")
        # S05：表情随主情绪变化（avatar:intent 是 Live2D 表情的唯一通道）
        avatar = getattr(app.state, "avatar", None)
        if avatar is not None:
            await avatar.push_emotion("", changed)


async def _agent_reply(
    text: str, session_id: str, trace: TraceContext | None = None, session=None,
    on_sentence=None, web_search: bool | None = None, on_reset=None,
) -> str:
    """AgentLoop 聚合流式：拼接 token，工具调用/结果打日志。

    ``trace``（S01）：可选交互 trace，仅打点、不改变行为。
    ``session``（S02）：AgentSession —— 传入时 generation 权威收敛到 Session。
    ``on_sentence``（A1）：可选**按句回调** —— 每凑出一个完整句子就立刻交出去
    （语音链路借此把首句提前 1~3 秒送进 TTS，而不是等整段回复结束）。
    默认 None，行为与原先完全一致。
    """
    loop = app.state.agent_loop
    from yuiro.netease import official_client as client
    media_reply = await client.control_text(text, _media_identity(session_id))
    if media_reply is not None:
        vlog('media', f'[{session_id[:8]}] 官方客户端短控制句已处理')
        if on_sentence is not None:
            await on_sentence(media_reply)
        return media_reply
    if loop is None:
        return await app.state.chat_responder.reply(text)
    # 情绪语气提示（M5：主情绪流入 prompt 风格）：作为 style_hint 传给 AgentLoop
    # 拼入人设段——绝不拼在用户消息里，否则会稀释意图识别（裸名词命令受害最大）。
    # S20：用户发言 = 用户在场信号（Presence 据此判断空闲与是否该克制）
    presence = getattr(app.state, "presence", None)
    if presence is not None:
        presence.note_user_activity()
    # S26：关系记忆——记一次互动（跨过天数里程碑时打日志）
    rel = getattr(app.state, "relationship", None)
    if rel is not None:
        try:
            for mark in rel.note_interaction():
                vlog("relationship", f"里程碑：{mark}")
        except Exception:  # noqa: BLE001 — 关系记录失败不影响对话
            pass
    engine = getattr(app.state, "emotion_engine", None)
    hint = engine.style_hint() if engine is not None else ""
    from yuiro.text_hygiene import has_debug_notes, strip_debug_notes

    parts: list[str] = []
    tool_ran = False
    # 收集工具结果状态，供兜底语判断成败——绝不无条件说"已经帮你执行了"。
    tool_statuses: list[str] = []
    # A1：尚未成句的尾部缓冲。只有**完整句子**才会立刻送去合成 ——
    # 否则会把半个词念出来（"我现在帮你打开记…" 然后才是 "…事本"）。
    pending = ""
    sent_any = False

    def _drain(flush: bool = False) -> list[str]:
        """从缓冲里切出可交付的句子；flush=True 时把残句也交出去。

        首句用更小的阈值（6 字）—— 首句决定用户什么时候听到第一个字，
        短一点值得；后续句用 12 字，避免"嗯。""好的。"这种碎句各占一次合成。
        """
        nonlocal pending, sent_any
        if on_sentence is None:
            return []
        out: list[str] = []
        while True:
            from yuiro.audio.speech_text import sentence_boundary

            limit = 12 if sent_any else 6
            # 跳过过短边界，向后找到足够长度的完整句；不能一直卡在“嗯。”。
            idx = sentence_boundary(pending, min_len=1 if flush else limit)
            if idx < 0:
                break
            out.append(pending[: idx + 1])
            pending = pending[idx + 1 :]
            sent_any = True
        if flush and pending.strip():
            out.append(pending)
            pending = ""
        if out:
            sent_any = True
        return out

    if trace is not None:
        trace.mark("agent_start")
    vlog("agent", f"[{session_id[:8]}] AgentLoop 流式开始（等待 LLM 首 token）")
    t_stream = time.monotonic()
    # S51：会话级联网开关（聊天坞发送键左侧按钮）—— 用户关掉时，本轮**不把
    # web_search 放进 schema**（模型看不到它，自然不会去调）。
    # ``None`` = 未指定 → 按配置默认（已注册即可见），保证语音链路等旧调用无行为变化。
    from yuiro.tools.web_tool import WEB_TOOL_NAMES

    # 旧取流/mpv 与账号写操作保留代码，但不再由日常聊天/语音静默触发。
    _disabled = {'netease_play', 'netease_control', 'netease_library', 'netease_login', 'netease_playlist', 'netease_lyric'}
    if web_search is False:
        _disabled.update(WEB_TOOL_NAMES)
    async for chunk in loop.send(
        session_id, text, style_hint=hint, trace=trace, session=session,
        disabled_tools=_disabled,
    ):
        if chunk.kind == "token":
            if not parts:
                if trace is not None:
                    trace.mark("llm_first_token")
                vlog("agent", f"[{session_id[:8]}] 收到 LLM 首 token（{int((time.monotonic() - t_stream) * 1000)}ms）")
            parts.append(chunk.content)
            if on_sentence is not None:
                pending += chunk.content
                # 出口净化逐句做：调试注记绝不能流到 TTS（S34 的同一条约束）。
                for sentence in _drain():
                    clean = strip_debug_notes(sentence)
                    if clean.strip():
                        await on_sentence(clean)
        elif chunk.kind == "reset":
            if on_reset is not None:
                await on_reset()
            # AgentLoop 判定"刚才那段文本是幻觉"（声称已执行但本轮零工具调用）——
            # 帧已发出无法撤回，故在此丢弃已收集的文本，后续重新累积。
            # ⚠ A1 已知限制：**已经交给 TTS 的句子收不回来**。好在 reset 是罕见
            # 路径，且此时多半只说出了"我这就帮你…"这类无害内容；停顿与纠偏
            # 由后续重新累积的文本完成。真流式必然有这个代价，这里选择接受。
            vlog("agent", f"[{session_id[:8]}] 收到 reset：丢弃已收集的 {len(parts)} 段幻觉文本")
            parts.clear()
            pending = ""
            sent_any = False
            tool_statuses.clear()
        elif chunk.kind == "tool_call":
            vlog("agent", f"[{session_id[:8]}] 工具调用: {chunk.tool_name} {chunk.tool_args}")
        elif chunk.kind == "tool_result":
            tool_ran = True
            vlog("agent", f"[{session_id[:8]}] 工具结果: {chunk.content[:200]}")
            try:
                tool_statuses.append(str(json.loads(chunk.content).get("status", "?")))
            except Exception:  # noqa: BLE001 — 非 JSON 纯文本结果，状态未知
                tool_statuses.append("?")
    if trace is not None:
        trace.mark("agent_end")
    vlog("agent", f"[{session_id[:8]}] AgentLoop 流式结束，共 {len(parts)} 段")
    reply = "".join(parts).strip()
    fallback = False
    if not reply:
        # AgentLoop 已内置"工具轮零文字时补收尾总结"；到这里的兜底只在收尾也
        # 超时/为空时触发。此时如实区分成败，绝不假装已执行。
        fallback = True
        _ok_statuses = {"ok", "done", "success", "opened", "text"}
        if tool_ran and tool_statuses and all(s == "error" for s in tool_statuses):
            vlog("agent", f"[{session_id[:8]}] 工具全部失败且无收尾文字，使用失败兜底语")
            reply = "刚想帮你弄，但没弄成……我再看看，你稍等再试一次？"
        elif tool_ran and tool_statuses and all(s in _ok_statuses for s in tool_statuses):
            # 有工具确实成功但 LLM 未生成转述（挂起/超时）：才可用中性完成语。
            reply = "刚帮你弄好了，还有什么需要吗？"
        else:
            # need_choice/pending（在等用户确认，不是完成）/状态未知 → 如实说没办完，
            # 绝不说"弄好了"（实测 need_choice 全程被兜底成"刚帮你弄好了"的撒谎）。
            vlog("agent", f"[{session_id[:8]}] 工具未完成（statuses={tool_statuses}），使用中性兜底语")
            reply = "嗯……刚才那步还没办成，你再说说想要什么？我接着弄。"
    clean_reply = strip_debug_notes(reply)
    # A1：收尾把残留补投一次 —— 兜底语单独投（它不在缓冲里），否则投残句。
    if on_sentence is not None:
        if fallback:
            if clean_reply.strip():
                await on_sentence(clean_reply)
        else:
            for sentence in _drain(flush=True):
                clean = strip_debug_notes(sentence)
                if clean.strip():
                    await on_sentence(clean)
    await _interaction_reward()
    # S34：出口净化 —— 模型可能从更早的 history 学到「（本轮操作：…）」格式并自行生成，
    # 此处统一剥离（chat 与 voice 两条链路都经这里，TTS 不会再念出调试注记）。
    if has_debug_notes(reply):
        vlog("agent", f"[{session_id[:8]}] 检测到模型模仿的调试注记，已在出口剥离")
    return clean_reply


async def _llm_reply_stream(text: str, session_id: str, on_sentence) -> str:
    """VoicePipeline 的**流式** LLM 回调（A1）。

    与 ``_llm_reply`` 的唯一区别：把 ``on_sentence`` 透传给 ``_agent_reply`` ——
    后者每凑出一个完整句子就交给它，进而立刻送去 TTS 合成（首句不必等整段回复）。
    返回值仍是完整回复（供日志/记忆等下游使用）。
    """
    t0 = time.monotonic()
    pipe = getattr(app.state, "voice_pipeline", None)
    trace = pipe.get_trace(session_id) if pipe is not None else None
    session = app.state.sessions.get(session_id)
    reply = await _agent_reply(
        text, session_id, trace, session, on_sentence=on_sentence
    )
    vlog(
        "chat",
        f"LLM 流式回调 {text!r} -> {reply!r}（{int((time.monotonic() - t0) * 1000)}ms, "
        f"backend={'agent' if app.state.agent_loop else app.state.chat_responder.backend_name}）",
    )
    return reply


async def _llm_reply(text: str, session_id: str) -> str:
    """VoicePipeline 的 LLM 回调：优先 AgentLoop（工具循环），否则单轮 responder。

    trace 从 VoicePipeline 侧读取（S01，只读），不改 llm_callback 既有签名。
    """
    t0 = time.monotonic()
    pipe = getattr(app.state, "voice_pipeline", None)
    trace = pipe.get_trace(session_id) if pipe is not None else None
    session = app.state.sessions.get(session_id)
    reply = await _agent_reply(text, session_id, trace, session)
    vlog(
        "chat",
        f"LLM 回调 {text!r} -> {reply!r}（{int((time.monotonic() - t0) * 1000)}ms, "
        f"backend={'agent' if app.state.agent_loop else app.state.chat_responder.backend_name}）",
    )
    return reply


async def _play_audio(session_id: str, segment: AudioSegment) -> None:
    """把 TTS 段回传给对应 session（wav base64 + 唇形音量数组）。"""
    from yuiro.approval import get_audio_conn

    ws = get_audio_conn(session_id)
    if ws is None:
        return
    import io
    import wave

    session = app.state.sessions.get(session_id)
    if session is None:
        return
    # 按WAV真实时长计算有界占用；损坏的段交给前端解码失败回执释放。
    try:
        with wave.open(io.BytesIO(segment.wav)) as audio:
            duration = audio.getnframes() / audio.getframerate()
    except (wave.Error, EOFError):
        duration = len(segment.volumes) * segment.slice_ms / 1000
    pipe = app.state.voice_pipeline
    identity = pipe.playback.offer(
        session_id, getattr(app.state.app_config, '_character_id', ''),
        session.generation, duration,
    )
    payload = {
        "type": "tts:audio",
        **identity,
        "wav": base64.b64encode(segment.wav).decode("ascii"),
        "sample_rate": segment.sample_rate,
        "streaming": segment.streaming,
        "stream_id": segment.stream_id,
        "tts_timing": getattr(segment, 'timings', {}),
        "slice_ms": segment.slice_ms,
        "volumes": segment.volumes,
    }
    vlog(
        "voice",
        f"[{session_id[:8]}] 回传 tts:audio "
        f"({len(segment.wav)}B, {segment.sample_rate}Hz, {len(segment.volumes)} 音量片)",
    )
    try:
        await ws.send_json(payload)
    except Exception:  # noqa: BLE001 — 连接断开时静默丢弃
        pipe.playback.receipt(session_id, {**identity, 'type': 'audio:playback_finished'})
        return


async def _emit_event(session_id: str, event_type: str, payload: dict) -> None:
    """把语音管线中间状态事件转发给对应 session 的 /ws/audio 连接。"""
    session = app.state.sessions.get(session_id)
    if session is None:
        return
    generation = session.generation
    character_id = getattr(app.state.app_config, '_character_id', '')
    def current():
        return (app.state.sessions.get(session_id) is session
                and session.generation == generation
                and getattr(app.state.app_config, '_character_id', '') == character_id)
    # S05：LLM 等待期显示"思考"表情；出结果后回落当前主情绪
    avatar = getattr(app.state, "avatar", None)
    if avatar is not None and event_type in ("llm:start", "llm:text"):
        try:
            if event_type == "llm:start":
                await avatar.push_emotion(session_id, "thinking")
            else:
                engine = getattr(app.state, "emotion_engine", None)
                await avatar.push_emotion(
                    session_id, engine.state.dominant() if engine is not None else None
                )
        except Exception:  # noqa: BLE001 — 表情失败不影响语音链路
            pass

    from yuiro.approval import get_audio_conn

    ws = get_audio_conn(session_id)
    if ws is None or not current():
        return
    message: dict = {"type": event_type, "session_id": session_id}
    if payload:
        message.update(payload)
    message.update(session_id=session_id, character_id=character_id, generation=generation)
    try:
        await ws.send_json(message)
    except Exception:  # noqa: BLE001 — 连接断开时静默丢弃
        return


def _build_renderer(cfg: AppConfig, api_key: str | None):
    """S52：装配出口语言渲染器（展示语言 / 朗读语言解耦）。

    用一个**独立的** OpenAI 兼容适配器做文本转换（无工具、temperature=0）——
    刻意不复用 AgentLoop 的 provider：两者一个跑工具循环、一个跑出口翻译，
    分开后互不影响（也便于单独热重载）。未配置 key 时传入 None，渲染器会透传
    并在首次真正需要转换时告警一次。
    """
    from yuiro.agent import OpenAIProvider
    from yuiro.audio.render import OutputRenderer

    llm = None
    if api_key:
        try:
            llm = OpenAIProvider(cfg.llm.base_url, cfg.llm.model, api_key)
        except Exception as exc:  # noqa: BLE001 — 转换器构造失败不该挡住引擎启动
            vlog("language", f"⚠ 输出语言渲染器的 LLM 初始化失败：{exc}（语言解耦不生效）")
    renderer = OutputRenderer(
        llm,
        display_language=getattr(cfg.language, "display_language", "zh"),
        speak_language=getattr(cfg.language, "speak_language", "auto"),
        mode=getattr(cfg.language, "translate_mode", "sentence"),
        timeout_s=getattr(cfg.language, "translate_timeout_s", 6.0),
    )
    vlog("language", f"输出语言渲染器已装配（{renderer.describe()}）")
    return renderer


def _log_reference_language(cfg: AppConfig) -> None:
    """S52：启动时判定**参考音频的语种**并给出建议（参考可能是英文/日文，不是中文）。

    为什么值得单独打一条日志：克隆效果主要取决于"朗读语言 == 参考音频语种"，
    而参考的语种肉眼不可见 —— 当前 SiliconFlow 用的就是英文的 Neuro 台词
    （`[tts].siliconflow_reference_text`）。不提示的话，用户只会觉得"她念中文怪怪的"，
    完全想不到要去把朗读语言改成参考的语种。
    """
    from yuiro.audio.render import detect_language

    provider = (cfg.tts.provider or "").lower()
    ref = ""
    if provider == "siliconflow":
        ref = cfg.tts.siliconflow_reference_text or ""
        # 该项允许填 .txt 路径（当前配置正是路径）→ 读内容再判定
        if ref.lower().endswith(".txt"):
            try:
                with open(ref, encoding="utf-8") as handle:
                    ref = handle.read().strip()
            except OSError:
                ref = ""
    elif provider in ("cosyvoice", "edge-tts"):
        ref = cfg.tts.reference_text or ""
    # gptsovits 的音色与参考在服务端固化，引擎侧无从得知 → 不提示
    if not ref:
        return
    lang = detect_language(ref)
    if lang == "unknown":
        return
    vlog(
        "language",
        f"参考音频转写语种判定={lang}（{ref[:40]!r}）｜朗读语言建议设为 {lang}："
        f"与参考一致时克隆效果最好；不一致时容易夹生、输出长度也会失稳",
    )


def _build_voice_pipeline(cfg: AppConfig, renderer=None) -> VoicePipeline:
    """按配置装配真实 VAD/ASR/TTS 的全局语音管线。

    默认后端：FSMN-VAD + SenseVoice-Small（FunASR，中文 SOTA 级），
    兼容旧 silero / faster-whisper。进度回调把冷启动加载状态广播给所有 audio WS。

    ``renderer``（S52）：出口语言渲染器；注入后朗读文本按 ``[language].speak_language``
    渲染再合成（None = 不做语言解耦，行为与引入前一致）。
    """
    from yuiro.approval import broadcast_audio_event
    from yuiro.audio import ASRProvider, CosyVoiceProvider, FSMNVAD, GPTSoVITSProvider, SenseVoiceASR, SiliconFlowProvider, TTSProvider, VADEngine

    def progress_callback(state: str, stage: str, progress: float) -> None:
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    broadcast_audio_event(
                        {"type": "pipeline:state", "state": state, "stage": stage, "progress": progress}
                    )
                )
        except Exception:  # noqa: BLE001
            pass

    if cfg.vad.provider == "fsmn":
        vad = FSMNVAD(
            max_end_silence_time=cfg.vad.max_end_silence_time,
            speech_pad=cfg.vad.speech_pad,
            chunk_size=list(cfg.vad.chunk_size),
            local_model_path=cfg.vad.local_model_path,
            progress_callback=progress_callback,
        )
    else:
        vad = VADEngine(
            probability_threshold=cfg.vad.probability_threshold,
            db_threshold=cfg.vad.db_threshold,
            smoothing_window=cfg.vad.smoothing_window,
            required_hits=cfg.vad.required_hits,
            required_misses=cfg.vad.required_misses,
        )

    if cfg.asr.provider == "funasr-sensevoice":
        asr = SenseVoiceASR(
            model=cfg.asr.model,
            device=cfg.asr.device,
            compute_type=cfg.asr.compute_type,
            language=cfg.asr.language,
            local_model_path=cfg.asr.local_model_path,
            llm_polish=cfg.asr.llm_polish,
            polish_callback=None,
            progress_callback=progress_callback,
        )
    else:
        asr = ASRProvider(
            model=cfg.asr.model,
            device=cfg.asr.device,
            compute_type=cfg.asr.compute_type,
            language=cfg.asr.language,
            beam_size=cfg.asr.beam_size,
            vad_filter=cfg.asr.vad_filter,
            initial_prompt=cfg.asr.initial_prompt,
        )

    # S52：朗读语种（[language].speak_language）在**装配期**注入各后端：
    # 它是静态设置，注入比改 synthesize_segment 签名代价小得多，也不波及测试桩。
    _speak_lang = (getattr(cfg.language, "speak_language", "auto") or "auto").lower()
    if cfg.tts.provider == "cosyvoice":
        tts = CosyVoiceProvider(
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
        tts = GPTSoVITSProvider(
            base_url=cfg.tts.tts_url,
            # 统一到朗读语言：设了 en/ja 就用它；auto 时沿用旧的 GPT-SoVITS 语种字段
            text_language=(
                _speak_lang if _speak_lang != "auto"
                else (cfg.tts.tts_text_language or cfg.tts.default_language)
            ),
            segment_streaming=cfg.tts.segment_streaming,
        )
    elif cfg.tts.provider == "fish":
        from yuiro.audio.fish import build_fish_provider

        tts = build_fish_provider(cfg.tts)
    elif cfg.tts.provider == "siliconflow":
        # 云端零样本克隆：key 优先用配置，否则从 keychain 读取
        from yuiro.keychain import load_siliconflow_key

        sf_key = cfg.tts.siliconflow_key or load_siliconflow_key() or ""
        if not sf_key:
            vlog("tts", "SiliconFlow 未配置 key（config.tts.siliconflow_key 与 keychain 均为空），回退 edge-tts")
            tts = TTSProvider(
                voice=cfg.persona.voice,
                segment_streaming=cfg.tts.segment_streaming,
                language=_speak_lang,
            )
        else:
            tts = SiliconFlowProvider(
                api_key=sf_key,
                voice=cfg.tts.siliconflow_voice,
                reference_wav=cfg.tts.siliconflow_reference_wav,
                reference_text=cfg.tts.siliconflow_reference_text,
                model=cfg.tts.siliconflow_model,
                segment_streaming=cfg.tts.segment_streaming,
            )
    else:
        tts = TTSProvider(
            voice=cfg.persona.voice,
            segment_streaming=cfg.tts.segment_streaming,
            language=_speak_lang,
        )
    return VoicePipeline(
        llm_callback=_llm_reply,
        # A1：默认走流式（句子一到就合成）；关掉则退回整段路径
        sentence_llm_callback=_llm_reply_stream if cfg.tts.stream_llm else None,
        vad=vad,
        asr=asr,
        tts=tts,
        # 播放期判定"用户插话"的能量余量（见 config.toml 的 [hard_of_hearing]）
        barge_margin_db=cfg.vad.barge_margin_db,
        # 打断总开关（默认关，见 config.toml）
        barge_in_enabled=cfg.vad.barge_in_enabled,
        play_callback=_play_audio,
        event_callback=_emit_event,
        progress_callback=progress_callback,
        # VAD 判定开始前保留的音频量：补回被吞掉的用户开口头几个字
        pre_roll_ms=getattr(cfg.vad, "pre_roll_ms", 400),
        # S03：VAD 检测到用户开口 → 统一取消入口（代际 + 停语音 + 前端停播）
        barge_in_callback=lambda sid: _schedule_cancel(sid, "barge-in"),
        # S04：分句流式（首句先出声；False 时整段合成，行为同旧）
        segment_streaming=getattr(cfg.tts, "segment_streaming", True),
        # S52：出口语言渲染器（展示语言 / 朗读语言解耦）
        renderer=renderer,
        # 统一「语音回复 TTS」开关：传 callable（回合时读 app.state.app_config，即时生效）。
        # 关闭时语音链路跳过合成（保留 ASR+LLM 文字回复），文字链路也不朗读。
        reply_tts_enabled=lambda: bool(app.state.app_config.tts.reply_tts_enabled),
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # S43：会话回收定时器 —— 挂起超时的会话从**内存**移除（事件日志留盘，可复活）。
    # 没有这个定时器的话 sweep 只能靠 API 手动触发，等于没做；而缺了回收，
    # _sessions 会只增不减（实测开发态热重载一天攒下多个，每个都带着上下文常驻）。
    async def _session_sweeper() -> None:
        while True:
            await asyncio.sleep(300.0)  # 5 分钟一次；TTL 30 分钟，精度足够
            try:
                app.state.sessions.sweep()
            except Exception as exc:  # noqa: BLE001 — 回收失败绝不能影响服务
                vlog("session", f"会话回收异常（忽略）：{exc}")

    sweeper = asyncio.create_task(_session_sweeper())

    # Startup: 装配系统执行后端（S10：native 默认 / daemon 可选）+ 重建 AgentLoop。
    backend = _build_system_backend(app_config.systemd, app_config.transaction)
    _app.state.system_backend = backend
    _app.state.system_daemon = backend if isinstance(backend, SystemDaemonClient) else None
    if isinstance(backend, SystemDaemonClient):
        await backend.connect()
    vlog(
        "systemd",
        f"系统执行后端: {type(backend).__name__}（[systemd].backend="
        f"{app_config.systemd.backend!r}；native = Python 原生，daemon = C++）",
    )
    # S33：文件事务（不可回滚时要让它显式可见——静默降级比报错更难排查）
    _txn = getattr(backend, "txn_store", None)
    vlog(
        "txn",
        f"文件事务: {'已启用（' + _txn.root + '）' if _txn else '未启用（文件操作不可回滚）'}",
    )
    # 后端就绪后重建 AgentLoop（SystemTool 注入后端，真实系统操作可用）。
    # 复用已装配的 memory（避免重复 spawn BGE-M3 嵌入 worker 导致 BrokenPipe）。
    if getattr(_app.state, "agent_loop", None) is not None:
        _app.state.agent_loop = _build_agent(
            app_config,
            _app.state.llm_api_key,
            system_backend=backend,
            memory=app.state.memory,
            events=_app.state.events,
        )
    _app.state.runtimes.register(AgentRuntimeAdapter(_app.state.agent_loop))
    # S51：日记（独立库 + 编排）。放在 AgentLoop 重建**之后** —— 解构/总评复用
    # 它的 LLM provider（不额外占资源）。日记是"受控的记忆上游"，与记忆系统
    # 解耦但可联动（shared 档位才写记忆）。
    _app.state.diary_store = None
    _app.state.diary = None
    _app.state.diary_session = None
    if app_config.diary.enabled:
        try:
            from yuiro.diary import DiaryStore
            from yuiro.diary.quip import QuipService
            from yuiro.diary.service import DiaryService
            from yuiro.diary.session import DiarySession

            _diary_store = DiaryStore(app_config.diary.db_path)
            _app.state.diary_store = _diary_store
            _app.state.diary = DiaryService(
                _diary_store,
                memory=getattr(_app.state, "memory", None),
                llm=getattr(getattr(_app.state, "agent_loop", None), "_llm", None),
                forget_memory=_forget_character_diary_text,
            )
            vlog(
                "diary",
                f"日记已装配（db={app_config.diary.db_path}，"
                f"吐槽默认{'开' if app_config.diary.quip_default_on else '关'}）",
            )
            # S51：日记模式会话（草稿 + 吐槽门控 + 控制意图）。
            # 吐槽是可选、低频、**可随时闭嘴**的伴随轨道（§8.1）；
            # 复用 AgentLoop 的 LLM provider，不额外占资源。
            _app.state.diary_session = DiarySession(
                service=_app.state.diary,
                quip=QuipService(
                    llm=getattr(getattr(_app.state, "agent_loop", None), "_llm", None)
                ),
            )
        except Exception as exc:  # noqa: BLE001 — 日记装配失败不应拖垮引擎
            vlog("diary", f"日记装配失败（该功能不可用）：{type(exc).__name__}: {exc}")
            _app.state.diary_store = None
            _app.state.diary = None
    emit_startup_summary(_app.state.chat_responder.backend_name)
    # 后台预热 VAD/ASR 模型，消除首次语音处理的模型加载延迟（不阻塞启动）。
    asyncio.create_task(_warmup_pipeline(_app.state.voice_pipeline))
    # 预热网易云播放守护进程（NCM_DAEMON）：没有它 play 只入队、mpv 不启动，
    # 冷启动实测会拖到 13s 才出声；预热后首次点歌约 3-4s。
    asyncio.create_task(_warmup_netease_daemon())
    # M5 情感定时衰减（每 60s；主情绪变化推送壳层）
    asyncio.create_task(_emotion_decay_loop())
    # S13：记忆维护循环（每 6h 遗忘一次过时记忆；启动后由定时器首次触发）
    asyncio.create_task(_memory_maintenance_loop())
    # S20：Presence（事件驱动）优先；未启用时回退 M5 的定时轮询调度（兼容）
    if app_config.presence.enabled:
        await _app.state.presence.start()
    elif app_config.proactive.enabled:
        _app.state.proactive = _build_proactive(backend)
        await _app.state.proactive.start()
    yield
    # S51：日记库有序关闭（WAL checkpoint + 释放句柄）——
    # 不关的话 Windows 上文件锁会残留（S50 实测过 tempfile 清理失败）。
    try:
        _diary_store = getattr(_app.state, "diary_store", None)
        if _diary_store is not None:
            _diary_store.close()
    except Exception:  # noqa: BLE001 — 关闭失败不影响退出
        pass
    if _app.state.system_daemon is not None:
        await _app.state.system_daemon.close()
    if getattr(_app.state, "proactive", None) is not None:
        await _app.state.proactive.stop()
    if getattr(_app.state, "presence", None) is not None:
        await _app.state.presence.stop()
    sweeper.cancel()
    await asyncio.gather(sweeper, return_exceptions=True)
    try:
        await _shutdown_character_resources()
    finally:
        from yuiro.audio.fish_transport import close_fish_http_client

        await _app.state.observation.close()
        await close_fish_http_client()


def _build_proactive(system_daemon=None):
    """装配主动互动调度器（观察→决策→打招呼→推送壳层）。"""
    from yuiro.approval import broadcast_control
    from yuiro.proactive import AttentionObserver, ProactiveDecider, ProactiveScheduler

    observer = AttentionObserver(
        min_interval_s=app_config.proactive.min_interval_s,
        max_interval_s=app_config.proactive.max_interval_s,
        system_daemon=system_daemon,
    )
    decider = ProactiveDecider(llm=None)  # 框架版启发式；调优接 LLM 决策
    return ProactiveScheduler(observer, decider, on_greet=_greet_push)


async def _greet_push(message: str) -> None:
    """打招呼推送到壳层（proactive:greet 事件）。"""
    from yuiro.approval import broadcast_control

    try:
        await broadcast_control({"type": "proactive:greet", "message": message})
    except Exception:  # noqa: BLE001
        pass


async def _emotion_decay_loop() -> None:
    """定时衰减情绪；主情绪变化时广播 emotion:set 到壳层。"""
    from yuiro.approval import broadcast_control

    while True:
        await asyncio.sleep(60)
        engine = getattr(app.state, "emotion_engine", None)
        if engine is None:
            continue
        changed = engine.decay()
        if changed:
            try:
                await broadcast_control({
                    "type": "emotion:set",
                    "emotion": changed,
                    "values": engine.state.values(),
                })
                vlog("emotion", f"定时衰减后主情绪: {changed}（已推送壳层）")
            except Exception:  # noqa: BLE001
                pass
            # S05：表情随主情绪变化
            avatar = getattr(app.state, "avatar", None)
            if avatar is not None:
                try:
                    await avatar.push_emotion("", changed)
                except Exception:  # noqa: BLE001
                    pass


def _note_memory_idle() -> None:
    """告诉整理调度器"刚聊完一轮"（**同步、不 await**）。

    它站在回复路径的末尾 —— 只重置一个计时器（O(1)），绝不阻塞回复；
    真正的整理跑在调度器自己的任务里（memory/idle.py）。
    """
    sched = getattr(app.state, "memory_idle", None)
    if sched is None:
        return
    try:
        sched.note_activity()
    except Exception:  # noqa: BLE001, S110 — 调度失败绝不能影响对话
        pass


def _note_memory_session_end() -> None:
    """会话（连接）结束 → 安排一次延迟整理（"这一场聊完了"）。"""
    sched = getattr(app.state, "memory_idle", None)
    if sched is None:
        return
    try:
        sched.note_session_end()
    except Exception:  # noqa: BLE001, S110 — 同上
        pass


async def _memory_maintenance_loop() -> None:
    """S13/S28：记忆维护——每 6 小时遗忘过时记忆 + 归纳稳定画像（失败静默）。

    规范红线（architecture-goal.md §3.10）：Consolidation **异步进行、不得阻塞聊天**，
    且只写 L3 facts（不改会话与近期记忆）。
    """
    while True:
        await asyncio.sleep(6 * 3600)
        memory = getattr(app.state, "memory", None)
        if memory is None:
            continue
        try:
            await memory.forget()
        except Exception:  # noqa: BLE001, S110 — 维护失败不影响主链路
            pass
        # S28：归纳（Episode → 稳定画像）
        try:
            await memory.consolidate()
        except Exception:  # noqa: BLE001, S110 — 归纳失败不影响主链路
            pass


async def _warmup_pipeline(pipeline) -> None:
    """后台预热语音管线；完成后广播状态（失败静默，转写时重试）。"""
    from yuiro.approval import broadcast_audio_event

    try:
        await pipeline.warmup()
        log_ring.emit("INFO", "voice", "VAD/ASR 模型预热完成，语音链路就绪")
    except Exception as exc:  # noqa: BLE001
        log_ring.emit("WARNING", "voice", f"语音模型预热失败（首次处理会重试）: {exc}")
    # 把最终状态广播给所有已连接的 audio WS（覆盖连接早于预热完成的场景）
    try:
        await broadcast_audio_event(
            {
                "type": "pipeline:state",
                "state": pipeline._state,
                "stage": pipeline._loading_stage,
                "progress": pipeline._loading_progress,
            }
        )
    except Exception:  # noqa: BLE001
        pass


async def _warmup_netease_daemon() -> None:
    """后台预热网易云播放守护进程（NCM_DAEMON=1 常驻进程）。

    没有该守护进程时 `ncm-cli play` 只把歌加进队列、mpv 不会被拉起，
    冷启动实测要 13s 才出声。预热后首次点歌可降到 3-4s。
    失败不阻断启动——点歌时会由 ensure_daemon() 再次尝试。
    """
    netease_cfg = getattr(app_config, "netease", None)
    if netease_cfg is None or not netease_cfg.enabled:
        return
    try:
        ok = await ensure_daemon_ready(netease_cfg.bin)
        if ok:
            log_ring.emit("INFO", "netease", "网易云播放守护进程已就绪")
        else:
            log_ring.emit("WARNING", "netease", "网易云播放守护进程未启动（首次点歌时会重试）")
    except Exception as exc:  # noqa: BLE001
        log_ring.emit("WARNING", "netease", f"网易云播放守护进程预热失败: {exc}")


app = FastAPI(title="Yuiro Engine", version="0.1.0", lifespan=lifespan)

# 状态在模块级即就位（debug API 依赖它们；不依赖 lifespan 是否已运行）。
# S02：统一 Session / Generation —— EventBus + SessionManager 先于 AgentLoop 装配。
app.state.events = EventBus()
# S12：事件日志（落盘 + 回放）—— EventLog 作为全局订阅者，记录所有 AgentEvent。
from yuiro.runtime.event_log import EventLog  # noqa: E402

_role_data = Path("data") if _character_id == "hiyori" else Path("data/characters") / _character_id
app.state.event_log = EventLog(store_dir=_role_data / "events")

async def _active_event_sink(event):
    # 回合恢复、会话与审批事实仍需等本条写完，不能把durable边界降级成仅入队。
    durable = event.type.startswith(('turn.', 'task.', 'session.', 'approval.', 'transaction.'))
    await app.state.observation.submit(event, app.state.event_log.sink, wait=durable)

app.state.observation = OrderedObservation()
app.state.events.subscribe_all(_active_event_sink)
# S43：SessionManager 需要 event_log（复活被回收的会话 / 列出历史会话）——
# 故装配顺序必须是 EventLog 在前（原先相反，那时 SessionManager 拿不到它）。
app.state.sessions = SessionManager(events=app.state.events, event_log=app.state.event_log)
# S26：Relationship Memory（"我们之间发生过什么"；不参与检索，always-on 注入）
from yuiro.memory.relationship import RelationshipMemory  # noqa: E402

app.state.relationship = RelationshipMemory(_role_data / "relationship.json")
vlog(
    "relationship",
    f"关系记忆已装配：{app.state.relationship.summary() or '初次见面（尚无关系记录）'}",
)
app.state.app_config = app_config
app.state.build_character_agent = lambda: _build_agent(
    app_config, app.state.llm_api_key,
    memory=getattr(app.state, "memory", None),
    system_backend=getattr(app.state, "system_backend", None),
    system_daemon=getattr(app.state, "system_daemon", None), events=app.state.events,
)
app.state.llm_api_key = load_llm_key() or ""
# S52：出口语言渲染器（展示语言 / 朗读语言解耦）。默认 zh/auto 时它**完全透传**，
# 不产生任何 LLM 调用 —— 线上行为与引入前逐字节一致。
app.state.output_renderer = _build_renderer(app_config, app.state.llm_api_key)
app.state.chat_responder = build_responder(
    app_config.llm, app.state.llm_api_key or None,
    app_config.persona.system_prompt + "\n\n" + app_config.persona.persona_prompt
)
app.state.agent_loop = (
    _build_agent(app_config, app.state.llm_api_key, events=app.state.events)
    if app.state.llm_api_key
    else None
)
# S52：开场就把"参考音频是什么语种、朗读语言该设什么"讲清楚（参考未必是中文）
_log_reference_language(app_config)
app.state.voice_pipeline = _build_voice_pipeline(app_config, app.state.output_renderer)
# 注册进度回调：warmup 每步状态变更都实时广播给 /ws/audio 客户端
def _on_pipeline_progress(state: str, stage: str, progress: float) -> None:
    from yuiro.approval import broadcast_audio_event

    asyncio.ensure_future(
        broadcast_audio_event(
            {"type": "pipeline:state", "state": state, "stage": stage, "progress": progress}
        ),
    )

app.state.voice_pipeline._progress_callback = _on_pipeline_progress
# M5 情感引擎 + 角色养成（互动加成/定时衰减/主情绪推送）
from yuiro.emotion import Character, EmotionEngine

app.state.emotion_engine = EmotionEngine(
    decay_rate=0.02,
    hints=app_config.persona.emotion_hints,
    expression_map=app_config.persona.expression_map,
)
app.state.character = Character()
vlog("emotion", "情感引擎已装配（happy/sad/excited/bored/angry + 亲密度/等级养成）")
# S05：头像意图运行时（表情的唯一出口；表情名来自 [persona.expression_map]）
from yuiro.approval import broadcast_control as _avatar_broadcast

from yuiro.avatar import AvatarRuntime

# S49：先按当前 model_path 选出该模型的表现档案，再装配 —— 换模型即整套表现跟着换
from yuiro.config import active_profile, effective_motion_slots, effective_persona_maps

_eff_expr, _eff_motion, _eff_perf = effective_persona_maps(app_config.persona)
_eff_slots = effective_motion_slots(app_config.persona)

def _avatar_generation(session_id: str) -> int | None:
    session = app.state.sessions.get(session_id)
    return session.generation if session is not None else None

app.state.avatar = AvatarRuntime(
    expression_map=_eff_expr,
    motion_map=_eff_motion,
    performance_map=_eff_perf,
    motion_slots=_eff_slots,
    broadcast=_avatar_broadcast,
    generation_getter=_avatar_generation,
)
_profile_hit = active_profile(app_config.persona)
vlog(
    "avatar",
    f"头像运行时已装配（表情 {len(_eff_expr)} 项 / "
    f"动作 {len(_eff_motion)} 项 / "
    f"自定搭配 {len(_eff_perf)} 项 / "
    f"档案 {_profile_hit[0] if _profile_hit else '(无，用全局表)'} / "
    f"表演库 {len(app.state.avatar.performances())} 个）",
)


# S18：任务完成 → 庆祝表演（事件驱动；Agent 里没有 if success: celebrate）
async def _avatar_on_task_completed(event) -> None:
    session_id = getattr(event, "session_id", "") or ""
    # S26：一起完成一件事（关系记忆；首次完成会留下里程碑）
    rel = getattr(app.state, "relationship", None)
    if rel is not None:
        try:
            rel.note_task_completed(str((getattr(event, "payload", None) or {}).get("goal", "")))
        except Exception:  # noqa: BLE001 — 关系记录失败不影响任务
            pass
    try:
        await app.state.avatar.perform(session_id, "celebrate", source="system")
    except Exception:  # noqa: BLE001 — 表演失败不影响任务
        pass


app.state.events.subscribe("task.completed", _avatar_on_task_completed)


# S29：计划提交 → 推到壳层，由用户确认后才执行（plan approval 的人工确认环节）
async def _push_task_planned(event) -> None:
    payload = getattr(event, "payload", None) or {}
    try:
        from yuiro.approval import broadcast_control

        await broadcast_control(
            {
                "type": "task:planned",
                "task_id": payload.get("task_id", ""),
                "goal": payload.get("goal", ""),
                "steps": payload.get("steps", []),
            }
        )
        vlog("task", f"计划已推送壳层待确认：{payload.get('goal', '')}")
    except Exception:  # noqa: BLE001 — 推送失败不影响任务
        pass


# S39：工具活动反馈（G4）—— "正在读取目录…" / "3/7｜在移动文件" 推到壳层状态行。
# 工具真在跑，但界面上几秒静默 —— 这正是"像卡死/像空壳"的主要来源。
async def _push_agent_activity(event) -> None:
    payload = getattr(event, "payload", None) or {}
    current = app.state.sessions.get(event.session_id)
    service = getattr(app.state, "characters", None)
    if (getattr(service, "switching", False) or current is None
            or current.generation != event.generation):
        return
    # S53：agent 侧只给语义槽位；这里先尝试用档案解析成具体动作，
    # 解析不出来就把槽位透传给壳层（由模型清单推断），绝不猜一个索引。
    slot = str(payload.get("motion_slot") or "")
    group, index = "", None
    if slot:
        avatar = getattr(app.state, "avatar", None)
        if avatar is not None:
            try:
                group, index = avatar.resolve_motion_slot(slot)
            except Exception:  # noqa: BLE001 — 解析失败只影响动作，不影响状态行
                group, index = "", None
    try:
        from yuiro.approval import broadcast_control

        await broadcast_control(
            {
                "type": "agent:activity",
                "session_id": event.session_id,
                "generation": event.generation,
                "character_id": getattr(app.state.app_config, "_character_id", ""),
                "character_revision": getattr(service, "revision", 0),
                "activity_id": payload.get("activity_id", ""),
                "outcome": payload.get("outcome", "running"),
                "stage": payload.get("stage", ""),
                "tool": payload.get("tool", ""),
                "text": payload.get("text", ""),
                "progress": payload.get("progress", ""),
                "motion_slot": slot,
                "motion_group": group,
                "motion_index": index,
            }
        )
    except Exception:  # noqa: BLE001 — 反馈推送失败不影响执行
        pass


app.state.events.subscribe("agent.activity", _push_agent_activity)


# G7（2026-09-15）：结构化结果卡 —— 把工具返回的**列表类数据**（歌单雷达 / 搜索
# 候选 / 歌曲列表）推到壳层展示。
# 此前这些数据只躺在工具返回的 JSON 里，界面上什么都不显示，
# 用户侧表现为"推荐了歌单却毫无反应/不知道发生了什么"（实测反馈原话）。
async def _push_agent_result(event) -> None:
    payload = getattr(event, "payload", None) or {}
    if payload.get("kind") in ('source','song','playlist'):
        service = getattr(app.state, "characters", None)
        current = app.state.sessions.get(event.session_id)
        if (getattr(service, "switching", False) or current is None
                or current.generation != event.generation):
            return
    try:
        from yuiro.approval import broadcast_control

        await broadcast_control(
            {
                "type": "agent:result",
                "session_id": event.session_id,
                "generation": event.generation,
                "character_id": getattr(app.state.app_config, "_character_id", ""),
                "character_revision": getattr(getattr(app.state, "characters", None), "revision", 0),
                "kind": payload.get("kind", ""),
                "title": payload.get("title", ""),
                "items": payload.get("items", []),
                "note": payload.get("note", ""),
            }
        )
        vlog("agent", f"结构化结果已推送壳层：{payload.get('title', '')}"
                      f"（{len(payload.get('items') or [])} 项）")
    except Exception:  # noqa: BLE001 — 推送失败不影响执行
        pass


app.state.events.subscribe("agent.result", _push_agent_result)


app.state.events.subscribe("task.planned", _push_task_planned)

async def _presence_speak(session_id: str, text: str) -> None:
    """S22：Presence 的 voice 通道——主动说话（复用对话 TTS 编排；忙时自行跳过）。"""
    pipe = getattr(app.state, "voice_pipeline", None)
    if pipe is None:
        raise RuntimeError("VoicePipeline 未装配")
    await pipe.speak_text(session_id or "presence", text, source="presence")


async def _render_display_text(text: str) -> str:
    """S52：把内部中文文本渲染成**展示语言**（无渲染器/失败时原样返回）。"""
    renderer = getattr(app.state, "output_renderer", None)
    if renderer is None or not (text or "").strip():
        return text
    try:
        return await renderer.render_display(text)
    except Exception as exc:  # noqa: BLE001 — 渲染失败绝不挡住回复
        vlog("language",
             f"⚠ 展示文本渲染失败（{type(exc).__name__}: {str(exc)[:120]}），回退原文")
        return text


# 统一「语音回复 TTS」：文字聊天回复的朗读任务表（按 session 记，新回合到来时取消旧任务）。
_reply_speak_tasks: dict[str, asyncio.Task] = {}
_reply_agent_tasks: dict[str, asyncio.Task] = {}


async def _render_reply_sentence(sentence):
    """内部中文到朗读语言的唯一文字出口，供HTTP/WS共用。"""
    from yuiro.audio.speech_text import speech_body
    renderer = getattr(app.state, "output_renderer", None)
    if renderer is not None:
        try:
            sentence = await renderer.render_speak(sentence)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            vlog("language", f"朗读转换失败，使用原文：{type(exc).__name__}")
    return speech_body(sentence)


async def _synthesize_reply_sentence(tts, sentence, *, streaming=False):
    """聊天与日记共用朗读语言转换、正文清洗及Provider超时策略。"""
    sentence = await _render_reply_sentence(sentence)
    if streaming:
        return tts.synthesize_stream(sentence) if any(ch.isalnum() for ch in sentence) else None
    return await tts.synthesize_segment(sentence) if sentence else None


async def _speak_reply(
    ws: WebSocket, session_id: str, text: str, generation: int | None = None,
    *, preconnected=None, sentence_iter=None, trace=None, reply_request_id='',
    already_rendered=False,
    render_speak=None,
    experiment_metrics=None,
) -> None:
    """把文字聊天回复合成并下发前端播放（统一 TTS 开关**开启**时）。

    chat:user 的句子流可在完整 `chat:assistant` 前开始朗读；媒体等旧入口仍可
    传入整段。合成失败/超时不伪造成功，复用 VoicePipeline 的
    TTS provider 与同一套分句策略（split_sentences），不另写一条合成路径。

    音频经 control WS 下发 `tts:reply_audio`（wav base64 + 口型 volumes），
    全部下完发 `tts:reply_end` 让前端判定"无音频则退回字数估算"。
    """
    if generation is None:
        generation = _avatar_generation(session_id)
    def current() -> bool:
        return generation is not None and _avatar_generation(session_id) == generation
    if not current():
        return
    identity = {"session_id": session_id, "generation": generation}
    role = getattr(getattr(app.state, 'app_config', None), '_character_id', '')
    if role:
        identity['character_id'] = role
    if reply_request_id:
        identity['reply_request_id'] = reply_request_id
    cfg = getattr(app.state, "app_config", None)
    if cfg is None or not bool(getattr(cfg.tts, "reply_tts_enabled", True)):
        return
    pipe = getattr(app.state, "voice_pipeline", None)
    tts = getattr(pipe, "_tts", None)
    if tts is None or (sentence_iter is None and not (text or "").strip()):
        return
    from yuiro.audio.speech_text import speech_body

    text = speech_body(text)
    sentences = split_sentences(text)
    vlog("chat", f"[{session_id[:8]}] 文字回复朗读：{text[:40]!r}（{len(sentences)} 句）")
    aborted = False
    import contextlib
    opener = getattr(tts, 'open_sentence_session', None)
    ws_session = preconnected if preconnected is not None else (opener() if callable(opener) else None)

    async def source():
        if sentence_iter is not None:
            async for sentence in sentence_iter:
                yield sentence
        else:
            for sentence in sentences:
                yield sentence

    def check():
        if not current():
            raise asyncio.CancelledError('旧回合译文失效')

    async def chunks(sentence):
        if callable(getattr(tts, 'synthesize_stream', None)):
            stream = await _synthesize_reply_sentence(tts, sentence, streaming=True)
            if stream is not None:
                async with contextlib.aclosing(stream):
                    async for part in stream:
                        yield part
        else:
            yield await _synthesize_reply_sentence(tts, sentence)

    async def ws_texts():
        from yuiro.audio.output import translated_sentences
        if already_rendered:
            async for value in source():
                check()
                if experiment_metrics is not None:
                    experiment_metrics.setdefault('speech_sentences', []).append(value)
                yield value
            return
        async for value in translated_sentences(source(), render_speak or _render_reply_sentence, check, trace):
            if experiment_metrics is not None:
                experiment_metrics.setdefault('speech_sentences', []).append(value)
            yield value

    async def segments():
        if ws_session is not None or sentence_iter is not None:
            from yuiro.audio.output import sentence_audio
            async with contextlib.aclosing(sentence_audio(tts, ws_texts(), prepared=ws_session)) as stream:
                async for part in stream:
                    yield part
        else:
            async for sentence in source():
                if not current():
                    return
                try:
                    async with contextlib.aclosing(chunks(sentence)) as stream:
                        async for part in stream:
                            yield part
                except Exception as exc:
                    vlog('voice', f'文字回复单句合成失败: {type(exc).__name__}')

    try:
        if sentence_iter is not None:
            await ws.send_json({"type": "tts:reply_start", **identity})
        if trace:
            trace.mark('tts_start')
        async with contextlib.aclosing(segments()) as outputs:
            async for segment in outputs:
                if not current():
                    aborted = True
                    return
                if segment is None or not segment.wav:
                    continue
                if trace:
                    trace.mark('tts_first_audio')
                try:
                    await ws.send_json({
                        "type": "tts:reply_audio", **identity,
                        "wav": base64.b64encode(segment.wav).decode("ascii"),
                        "sample_rate": segment.sample_rate,
                        "slice_ms": segment.slice_ms,
                        "volumes": segment.volumes,
                        "streaming": segment.streaming,
                        "stream_id": segment.stream_id,
                        "tts_timing": getattr(segment, 'timings', {}),
                        "server_sent_unix_ms": round(time.time()*1000, 3),
                        **({"trace_id": trace.trace_id, "stages_ms": dict(trace._marks)} if trace else {}),
                    })
                    if trace:
                        trace.mark('audio_sent')
                except Exception:
                    aborted = True
                    vlog('chat', f'[{session_id[:8]}] 回复音频下发失败')
                    return
    except asyncio.CancelledError:
        # 新回合到来：取消旧回复的剩余合成/下发（前端已本地停播）
        aborted = True
        vlog("chat", f"[{session_id[:8]}] 文字回复朗读被新回合打断")
        raise
    except Exception as exc:
        vlog('tts', f'文字回复传输失败: {type(exc).__name__}；未切换传输或音色')
    finally:
        if ws_session is not None:
            await ws_session.close()
        if not aborted and current():
            try:
                if experiment_metrics is not None:
                    await ws.send_json({'type':'experiment:audio_metrics', **identity,
                                        'metrics':experiment_metrics})
                await ws.send_json({"type": "tts:reply_end", **identity})
            except Exception:  # noqa: BLE001 — 连接断开静默
                pass
        if trace:
            trace.mark('tts_end')
            trace.emit()


def _start_preconnected_reply(ws, session_id):
    """将等待回复的连接登记为原有朗读任务，统一取消/换角负责回收。"""
    cfg = getattr(app.state, 'app_config', None)
    pipe = getattr(app.state, 'voice_pipeline', None)
    tts = getattr(pipe, '_tts', None)
    opener = getattr(tts, 'open_sentence_session', None)
    if (not cfg or not cfg.tts.reply_tts_enabled or not callable(opener)
            or getattr(tts, 'transport', None) != 'websocket'
            or not getattr(tts, '_segment_streaming', False)):
        return None
    ready = asyncio.get_running_loop().create_future()

    async def speak_when_ready():
        prepared = None
        try:
            prepared = opener()
            text, generation = await ready
            await _speak_reply(ws, session_id, text, generation=generation, preconnected=prepared)
        finally:
            if prepared is not None:
                await prepared.close()

    _reply_speak_tasks[session_id] = asyncio.create_task(speak_when_ready())
    return ready


async def _presence_broadcast(payload: dict) -> None:
    """S20/S52：主动表达的气泡文本同样走**展示语言**。

    Presence 的文案（"回来啦。""欸，刚刚编译成功了。"）在引擎内部是中文；
    若用户把展示语言设成了英文/日文，气泡也该跟着变（声音那边由渲染器按
    朗读语言单独处理）——两路出口口径保持一致，否则会出现"气泡中文、嘴里英文"
    这种本可避免的错位。
    """
    if isinstance(payload, dict) and payload.get("type") == "proactive:intent":
        original = str(payload.get("text") or "")
        rendered = await _render_display_text(original)
        if rendered != original:
            payload = {**payload, "text": rendered, "source_text": original}
    await _avatar_broadcast(payload)


# S20：Presence Runtime（事件驱动 + Attention Policy）——取代 M5 的定时轮询打招呼。
# 想说 ≠ 说出口：所有主动表达都经 AttentionPolicy（冷却/静默时段/打扰上限）。
from yuiro.presence import AttentionPolicy, PresenceRuntime, parse_urgency  # noqa: E402

app.state.presence = PresenceRuntime(
    policy=AttentionPolicy(
        cooldown_s=app_config.presence.cooldown_s,
        quiet_hours=app_config.presence.quiet_hours,
        max_urgency=parse_urgency(app_config.presence.max_urgency),
    ),
    broadcast=_presence_broadcast,
    avatar_getter=lambda: getattr(app.state, "avatar", None),
    voice_speaker=lambda sid, text: _presence_speak(sid, text),
    idle_trigger_s=app_config.presence.idle_trigger_s,
    tick_s=app_config.presence.tick_s,
)
# 消费全部事件（内部只关心 task.* / session.*；用户活动信号由此重置空闲计时）
app.state.events.subscribe_all(app.state.presence.on_event)
vlog("presence", "Presence 已装配（事件驱动；proactive:intent 气泡 + 表演）")
if app.state.agent_loop is not None:
    vlog("chat", f"AgentLoop 已装配（LLM: {app_config.llm.base_url}/{app_config.llm.model}，工具: app_open/app_focus/media_control/file_*）")
elif app.state.llm_api_key:
    vlog("chat", "AgentLoop 装配失败（将使用单轮 responder）")
else:
    vlog("chat", "未配置 LLM API key（当前为 mock 后端，可在调试台设置并持久化到 keychain）")

# S15：Runtime 注册表（统一生命周期广播 + 状态视图）；大模块以 Adapter 包装。
from yuiro.runtime.adapters import (  # noqa: E402
    AgentRuntimeAdapter,
    SpeechRuntimeAdapter,
    TaskRuntimeAdapter,
)
from yuiro.runtime.contract import RuntimeRegistry  # noqa: E402

app.state.runtimes = RuntimeRegistry()
if app.state.agent_loop is not None:
    app.state.runtimes.register(AgentRuntimeAdapter(app.state.agent_loop))
if getattr(app.state, "voice_pipeline", None) is not None:
    app.state.runtimes.register(SpeechRuntimeAdapter(app.state.voice_pipeline))
if getattr(app.state, "avatar", None) is not None:
    app.state.runtimes.register(app.state.avatar)
if getattr(app.state, "tasks", None) is not None:
    # TaskRuntime 已有业务 cancel(task_id)：契约 cancel(session_id) 由适配器提供
    app.state.runtimes.register(TaskRuntimeAdapter(app.state.tasks))
vlog("runtime", f"Runtime 注册表：{', '.join(app.state.runtimes.names())}")

# 调试窗口（Electron renderer）跨 origin 访问 localhost:8200 需要 CORS。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # engine 只监听 127.0.0.1，仅本地可触达
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(debug_router)


def _authorized(ws: WebSocket) -> bool:
    """Shared-secret check; when secret is empty (dev) allow unauthenticated.

    浏览器 WebSocket 无法自定义 header，故同时接受 ?secret= 查询参数兜底。
    dev 默认值 'dev-only-change-me' 也视为未配置（本地开发不需要强鉴权）。
    """
    secret = ws.headers.get("x-yuiro-secret") or ws.query_params.get("secret") or ""
    cfg_secret = app_config.server.shared_secret
    if not cfg_secret or cfg_secret == "dev-only-change-me":
        return True  # dev: no real secret configured -> allow
    return secret == cfg_secret


def _cancel_reply_speech(session_id: str):
    """立即取消该会话的文字朗读；调用者在停止通知派发后join清理。"""
    task = _reply_speak_tasks.pop(session_id, None)
    if task is not None and task is not asyncio.current_task():
        if not task.done():
            task.cancel()
        return task
    return None


async def _prepare_text_turn(session_id: str) -> None:
    """先交接语音输出，再进入文本Agent；不取消持久Task/Plan。"""
    previous = _cancel_reply_speech(session_id)
    pipe = getattr(app.state, 'voice_pipeline', None)
    producers = [getattr(pipe, attr, {}).get(session_id)
                 for attr in ('_turn_tasks', '_speak_tasks', '_pending_end')]
    notification = pipe.interrupt(session_id) if pipe is not None else None
    pending = {task for task in (previous, notification, *producers)
               if task is not None and task is not asyncio.current_task()}
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _cancel_turn(session_id: str, reason: str) -> None:
    """S03：统一取消入口（Session.cancel 语义的编排层）。

    代际作废（旧代际结果沿 S02 语义丢弃）→ 停语音（LLM 回合 + TTS + 前端停播回执）
    → 发布 session.cancelled 事件。
    """
    gen = app.state.sessions.cancel(session_id, reason)
    previous_speech = _cancel_reply_speech(session_id)
    previous_agent = _reply_agent_tasks.pop(session_id, None)
    if previous_agent is not None:
        previous_agent.cancel()
    # S15：统一广播取消到所有已注册 Runtime（voice/avatar/agent…各自响应；错误隔离）
    runtimes = getattr(app.state, "runtimes", None)
    if runtimes is not None:
        await runtimes.cancel_session(session_id, reason)
    else:  # 兼容：注册表未装配时退回旧路径（只停语音）
        pipe = getattr(app.state, "voice_pipeline", None)
        if pipe is not None:
            pipe.interrupt(session_id)
    if previous_speech is not None:
        await asyncio.gather(previous_speech, return_exceptions=True)
    if previous_agent is not None:
        await asyncio.gather(previous_agent, return_exceptions=True)
    await app.state.events.publish(AgentEvent(
        type="session.cancelled",
        source="SessionManager",
        session_id=session_id,
        generation=gen,
        payload={"reason": reason},
    ))
    vlog("cancel", f"[{session_id[:8]}] 取消回合（reason={reason}, gen={gen}）")


def _schedule_cancel(session_id: str, reason: str) -> None:
    """同步包装：供 VoicePipeline 的 barge_in_callback 调用（fire-and-forget）。"""
    try:
        asyncio.create_task(_cancel_turn(session_id, reason))
    except Exception:  # noqa: BLE001 — 无事件循环等场景静默（不影响打断本身）
        pass


async def _send_session_ready(ws: WebSocket, session) -> None:
    """S02：向 control 通道下发会话身份（前端据此在 audio 通道绑定同一 session）。"""
    event = AgentEvent(
        type="session.started",
        source="SessionManager",
        session_id=session.session_id,
        generation=session.generation,
    )
    try:
        await ws.send_json(EventBus.to_wire(event))
    except Exception:  # noqa: BLE001 — 连接断开时静默
        return


async def _direct_media_play(payload: dict) -> tuple[bool, str]:
    """点选直连：按前端给的 ID 直接播放（S45）。返回 ``(是否成功, 给用户的一句话)``。

    **为什么单独开这条路**：用户点击一个具体条目是**确定意图** —— ID 就在手里，
    没有任何需要模型判断的东西。原实现把它转成一句自然语言、再让模型重搜，
    等于把确定的事交给模糊匹配，于是"点的这首、放的另一首"
    （实测：点《LIFE》(Neuro-sama) 因原唱无版权，被静默播成了 Life(Tobu)）。

    播放优先级：**加密 ID → 明文 ID**。接口只认加密 ID
    （实测 `song_detail(明文)` 报 400），所以明文只作兜底、失败就如实说明。
    """
    from yuiro.netease import api, player
    from yuiro.netease.availability import song_availability, unavailable_note
    from yuiro.tools.netease_tool import _play_songs, _resolve_playlist_encrypted

    name = str(payload.get("name") or "")
    if payload.get("backend", "builtin") != "builtin":
        return False, "点选播放仅绑定自管播放器，未切换到其他播放器"
    kind = str(payload.get("kind") or "song")
    encrypted = str(payload.get("encrypted_id") or "")
    song_id = str(payload.get("song_id") or "")
    playlist_id = str(payload.get("playlist_id") or "")

    # 歌单：解析成加密 id 后整列播放
    if kind == "playlist" and (playlist_id or encrypted):
        enc = await _resolve_playlist_encrypted(encrypted or playlist_id)
        tracks = await api.playlist_tracks(enc or playlist_id, 50)
        if not tracks:
            return False, f"《{name}》里没读到歌"
        ok, briefs, _ = await _play_songs(tracks, 30)
        if ok:
            return True, f"开始放《{name}》了（{len(briefs)} 首）"
        return False, f"《{name}》没能播起来"

    # 单曲：加密 ID 优先，明文 ID 兜底
    for sid in (encrypted, song_id):
        if not sid:
            continue
        try:
            detail = await api.song_detail(sid)
        except Exception as exc:  # noqa: BLE001 — 形态不对（明文 ID 会 400）→ 试下一个
            vlog("media", f"song_detail({sid[:12]}…) 不可用：{str(exc)[:80]}")
            continue
        url = detail.get("playUrl")
        if song_id and str(detail.get("originalId") or "") != song_id:
            return False, "歌曲 ID 缺失或版本不一致，未播放"
        if not url or song_availability(detail, detail=True)["availability"] != "api_available":
            continue
        title = str(detail.get("name") or name)
        if await player.play_urls([url], [title]):
            return True, f"在放《{title}》"
        return False, "播放器没能起来，检查一下 mpv 或系统音量"

    return False, unavailable_note(name)


def _media_identity(session_id: str) -> tuple:
    return (getattr(app.state.app_config, '_character_id', ''),
            getattr(getattr(app.state, 'characters', None), 'revision', 0), session_id)


def _client_search_identity(session_id: str) -> tuple:
    current = app.state.sessions.get(session_id)
    if (current is None or current.state.value != 'active'
            or getattr(getattr(app.state, 'characters', None), 'switching', False)):
        raise RuntimeError('搜索所属角色会话已失效')
    return _media_identity(session_id)


async def _official_media(payload: dict, session_id: str) -> dict | None:
    from yuiro.netease import official_client as client, player

    identity = _media_identity(session_id)
    supplied = (payload.get('character_id'), payload.get('character_revision'), payload.get('session_id'))
    if (supplied != identity or getattr(getattr(app.state, 'characters', None), 'switching', False)
            or payload.get('backend') != 'netease_client'):
        raise RuntimeError('角色或播放归属已失效，未操作任何播放器')
    if payload.get('type') == 'media:control':
        return await client.control(identity, str(payload.get('playback_id') or ''), str(payload.get('action') or ''))
    if payload.get('kind', 'song') != 'song':
        raise RuntimeError('本轮官方客户端仅支持明确的单曲 ID，未转换为其他播放目标')
    state = await player.get_state()
    if state.get('status') not in ('stopped', 'paused'):
        raise RuntimeError('请先暂停或停止桌宠播放器，再明确选择网易云客户端；不会同时启动两路音乐')
    return await client.play(str(payload.get('song_id') or ''), identity)


async def _reply_official_media(ws: WebSocket, payload: dict, session_id: str) -> None:
    state, note = None, ''
    try:
        state = await _official_media(payload, session_id)
    except Exception as exc:
        note = str(exc) or '网易云操作未确认，未切换其他播放器或歌曲版本'
    identity = _media_identity(session_id)
    try:
        await ws.send_json({'type': 'media:state', 'backend': 'netease_client',
                            'character_id': identity[0], 'character_revision': identity[1],
                            'session_id': identity[2], 'request_id': payload.get('request_id'),
                            'state': state, 'note': note})
    except RuntimeError:
        pass  # 连接已关闭；归属仍由角色 quiesce 收敛。


async def _reply_client_search(ws: WebSocket, payload: dict, session_id: str) -> None:
    """显式 UI 搜索沿用当前角色会话，不需要 LLM/平台 API。"""
    from yuiro.netease import official_client as client
    try:
        identity = _client_search_identity(session_id)
    except RuntimeError:
        return
    keyword = str(payload.get('keyword') or '')
    status, items, note = 'error', [], ''
    try:
        if (payload.get('backend') != 'netease_client'
                or (payload.get('character_id'),payload.get('character_revision'),payload.get('session_id')) != identity):
            raise RuntimeError('旧角色的搜索请求已失效')
        if not app.state.app_config.netease.enabled:
            raise RuntimeError('网易云能力已关闭，未搜索')
        current = app.state.sessions.get(session_id)
        generation = current.next_generation()
        result = await client.search(keyword,identity,daily=payload.get('daily') is True)
        if _client_search_identity(session_id) != identity or current.generation != generation:
            return
        status, items = 'ok', result.get('items', [])
    except Exception as exc:
        note = str(exc)
    try:
        if _client_search_identity(session_id) != identity:
            return
    except RuntimeError:
        return
    try:
        await ws.send_json({'type':'media:search-result','request_id':payload.get('request_id'),
                           'character_id':identity[0],'character_revision':identity[1],'session_id':identity[2],
                           'status':status,'keyword':keyword,'items':items,'note':note})
    except RuntimeError:
        pass


async def _handle_diary_message(ws: WebSocket, session_id: str, item: dict) -> None:
    """S51：日记模式消息处理（草稿 / 吐槽 / 提交 / 控制意图）。

    ★ 刻意**不经过 AgentLoop**（`diary-feature-design.md` §2.2）：日记正文里
    "今天用记事本记了点东西"这类裸名词会让预路由**真的去打开应用**；
    且日记不是"对她说的话"，不该产生对话轮次或写入记忆。
    """
    from yuiro.diary.session import detect_control_intent

    sess = getattr(app.state, "diary_session", None)
    if sess is None:
        await _diary_send(ws, {"type": "diary:error", "note": "日记功能未启用"})
        return

    mtype = str(item.get("type") or "")
    text = str(item.get("text") or "")
    try:
        if mtype == "diary:start":
            if not sess.active:
                sess.start()
            await _diary_send(
                ws,
                {
                    "type": "diary:state",
                    "active": True,
                    "quip_default": bool(getattr(app_config.diary, "quip_default_on", False)),
                    "review_enabled": bool(getattr(app_config.diary, "review_enabled", True)),
                },
            )
            await _diary_send(ws, {"type":"diary:draft", "text":sess.draft(), "segments":sess.segments,"segment_ids":sess.segment_ids})
            return

        if mtype == "diary:save_raw":
            if hasattr(ws,"state"):
                ws.state.diary_companion = None
            res = await sess.save_raw(privacy=str(item.get("privacy") or "local_only"),
                metadata={"title":str(item.get("title") or "")[:160], "attachment_ids":item.get("attachment_ids") or []} if item.get("title") or item.get("attachment_ids") else None)
            await _diary_send(ws, {"type":"diary:submitted", **res})
            return

        if mtype == "diary:append":
            # 极简控制意图（§2.2 的缺口补丁）：只有**短句**才可能是指令；
            # 未识别的一律当正文 —— 宁可漏判控制，也不误判正文。
            intent = None if item.get("literal") is True else detect_control_intent(text)
            if intent == "exit":
                sess.reset()
                await _diary_send(ws, {"type": "diary:state", "active": False})
                return
            if intent == "undo":
                await _diary_send(ws, {"type": "diary:draft", "text": sess.undo(), "segments":sess.segments, "segment_ids":sess.segment_ids})
                return
            if intent == "recall":
                await _diary_send(ws, {"type": "diary:recall_hint"})
                return
            draft = sess.append(text)
            await _diary_send(
                ws, {"type": "diary:draft", "text": draft, "segments": sess.segments, "segment_ids":sess.segment_ids}
            )
            return

        if mtype == "diary:undo":
            await _diary_send(ws, {"type": "diary:draft", "text": sess.undo(), "segments":sess.segments, "segment_ids":sess.segment_ids})
            return

        if mtype == "diary:interact":
            from yuiro.diary.companion import DiaryCompanion
            companion = getattr(ws.state, "diary_companion", None)
            if companion is None or getattr(ws.state, "diary_owner", None) is not sess:
                companion = DiaryCompanion()
                ws.state.diary_companion = companion
                ws.state.diary_owner = sess
            request_id = item.get("request_id")
            if item.get("kind") == "paragraph" and item.get("segment_id") not in sess.segment_ids:
                await _diary_send(ws, {"type":"diary:response_end", "request_id":request_id, "note":"目标段落已失效"})
                return
            kind = "paragraph" if item.get("kind") == "paragraph" else "short"
            cfg = getattr(app.state, "app_config", app_config)
            llm = getattr(getattr(app.state, "agent_loop", None), "_llm", None)
            if llm is None or not sess.active:
                await _diary_send(ws, {"type":"diary:response", "request_id":request_id, "text":"", "note":"日记会话或大脑未就绪"})
                return
            try:
                reply = await companion.respond(text, kind=kind, llm=llm,
                    persona=cfg.persona.persona_prompt, memory=getattr(app.state,"memory",None))
                if sess is not getattr(app.state,"diary_session",None) or not sess.active:
                    return
                await _diary_send(ws, {"type":"diary:response", "request_id":request_id,
                    "segment_id":item.get("segment_id"), "text":reply})
                vlog("diary", f"[陪伴] 文字已发送 request={request_id} chars={len(reply)}")
                if not reply:
                    await _diary_send(ws, {"type":"diary:response_end", "request_id":request_id,"note":"大脑未返回正文，可重新请求"})
                    return
                if item.get("tts") is True and reply:
                    pipe = getattr(app.state,"voice_pipeline",None)
                    tts = getattr(pipe,"_tts",None)
                    if tts is None:
                        await _diary_send(ws, {"type":"diary:response_end", "request_id":request_id,"note":"文字已生成，语音服务尚未就绪"})
                        return
                    if tts is not None:
                        from yuiro.audio.speech_text import speech_body
                        for sentence in split_sentences(speech_body(reply)):
                            try:
                                audio = await _synthesize_reply_sentence(tts, sentence)
                                if audio is None:
                                    continue
                                if not audio.wav:
                                    raise RuntimeError("语音返回空音频")
                            except asyncio.CancelledError:
                                raise
                            except Exception as exc:
                                # Fish适配器异常只含本地固定文案/HTTP状态，不含云端正文。
                                detail = str(exc) if isinstance(exc, RuntimeError) and str(exc).startswith(("Fish ","语音返回")) else type(exc).__name__
                                vlog("diary", f"[陪伴:TTS] 失败 request={request_id} reason={detail}")
                                await _diary_send(ws, {"type":"diary:response_end", "request_id":request_id,
                                    "note":f"文字已生成，语音未能播放：{detail}"})
                                return
                            vlog("diary", f"[陪伴:TTS] 音频发送 request={request_id} bytes={len(audio.wav)}")
                            await _diary_send(ws, {"type":"diary:audio", "request_id":request_id,
                                "wav":base64.b64encode(audio.wav).decode("ascii")})
                await _diary_send(ws, {"type":"diary:response_end", "request_id":request_id})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                vlog("diary", f"[陪伴] 失败 {type(exc).__name__}")
                await _diary_send(ws, {"type":"diary:response_end", "request_id":request_id,
                                      "note":"回应或语音暂时不可用，原文仍保留"})
            return

        if mtype == "diary:quip":
            # 吐槽请求（前端停笔后发）—— 门控与情绪安全阀都在 QuipService 内部。
            try:
                idle_s = float(item.get("idle_s") or 0.0)
            except (TypeError, ValueError):
                idle_s = 0.0
            candidate = item.get("text")
            candidate = candidate[-600:] if isinstance(candidate, str) else None
            quip = await sess.maybe_quip(idle_s, text=candidate)
            if sess is getattr(app.state, "diary_session", None):
                await _diary_send(ws, {"type": "diary:quip", "text": quip or "",
                                       "request_id": item.get("request_id")})
            return

        if mtype == "diary:submit":
            # §2.1 审阅编辑态：先解构、**不落库** → 回对照稿。
            # 用户看过之后再 confirm —— 避免"未经确认就替用户改写了话"。
            preview = await sess.preview()
            await _diary_send(ws, {"type": "diary:preview", **preview})
            return

        if mtype == "diary:confirm":
            if sess._pending is not None:
                sess._pending["data"].update({"title":str(item.get("title") or "")[:160], "attachment_ids":item.get("attachment_ids") or []})
            if hasattr(ws,"state"):
                ws.state.diary_companion = None
            res = await sess.confirm(
                privacy=str(item.get("privacy") or "local_only"),
                quip_mode=bool(item.get("quip_mode", False)),
                use_polished=bool(item.get("use_polished", True)),
            )
            await _diary_send(ws, {"type": "diary:submitted", **res})
            await _maybe_closing_review(ws, res)
            return

        if mtype == "diary:exit":
            ws.state.diary_companion = None
            sess.reset()
            await _diary_send(ws, {"type": "diary:state", "active": False})
            return

        await _diary_send(ws, {"type": "diary:error", "note": f"未知日记消息：{mtype}"})
    except Exception as exc:  # noqa: BLE001 — 日记消息失败不能拖垮整个连接
        vlog("diary", f"日记消息处理异常（{mtype}）：{type(exc).__name__}: {exc}")
        await _diary_send(ws, {"type": "diary:error", "note": "日记处理出错了，稍后再试"})


async def _maybe_closing_review(ws: WebSocket, res: dict) -> None:
    """总评（§8.2）：确认录入后的收尾仪式。

    **失败不阻塞提交结果** —— 日记已经存好了，总评只是锦上添花；
    绝不因为总评失败弹错或回滚（那会把"写完了"的成就感毁掉）。
    """
    diary_id = int(res.get("diary_id") or 0)
    svc = getattr(app.state, "diary", None)
    if not (res.get("ok") and diary_id and svc is not None):
        return
    if not bool(getattr(app_config.diary, "review_enabled", True)):
        return
    review = await svc.closing_review(diary_id)
    if review.get("ok"):
        await _diary_send(
            ws,
            {
                "type": "diary:review",
                "diary_id": diary_id,
                "text": str(review.get("review") or ""),
            },
        )


async def _diary_send(ws: WebSocket, payload: dict) -> None:
    """日记事件回推（连接断开时静默，与聊天链路同款）。"""
    try:
        await ws.send_json(payload)
    except Exception:  # noqa: BLE001
        pass


@app.websocket("/ws/control")
async def control_channel(ws: WebSocket) -> None:
    """Control channel: frontend ⇄ engine.

    Handles text chat events:
      <- {type:'chat:user', text}
      -> {type:'chat:assistant', text}
    Also routes approval:resolve back to pending approval gates.
    """
    await ws.accept()
    if not _authorized(ws):
        await ws.close(code=4401, reason="unauthorized")
        return
    if getattr(getattr(app.state, "characters", None), "switching", False):
        await ws.close(code=1013, reason="character switching")
        return
    connection = asyncio.current_task()
    _character_workers.add(connection)
    connection.add_done_callback(_character_workers.discard)
    # S02：Session 由引擎权威创建/恢复（前端可带 ?session= 进程内 resume）
    session = app.state.sessions.attach_control(
        ws, session_id=ws.query_params.get("session")
    )
    session_id = session.session_id
    from yuiro.approval import register_control_conn, resolve_approval, unregister_control_conn

    register_control_conn(session_id, ws)
    await _send_session_ready(ws, session)
    vlog(
        "chat",
        f"WS /ws/control 连接建立 session={session_id[:8]}（gen={session.generation}）",
    )

    # 串行聊天工作队列：长任务（AgentLoop/工具/审批等待）不阻塞本协程的
    # receive 循环，保证 approval:resolve / interrupt 等控制消息能即时处理。
    chat_queue: asyncio.Queue = asyncio.Queue(maxsize=4)
    control_gate = asyncio.Event()
    control_gate.set()
    control_epoch = 0
    async def admit_chat(message):
        try:
            chat_queue.put_nowait({**message, '_queue_epoch': control_epoch})
        except asyncio.QueueFull:
            await ws.send_json({'type': 'chat:busy', 'message': '待处理消息已满，请稍后再发。'})
    search_task = None
    diary_quip_task = None

    async def chat_worker() -> None:
        while True:
            item = await chat_queue.get()
            await control_gate.wait()
            if item is None:
                return
            if item.get('_queue_epoch', 0) != control_epoch:
                continue
            if item.get('backend') == 'netease_client' or item.get('type') == 'media:control':
                if item.get('type') == 'media:play':
                    session.next_generation()
                    previous_speak = _reply_speak_tasks.pop(session_id, None)
                    if previous_speak is not None and not previous_speak.done():
                        previous_speak.cancel()
                await _reply_official_media(ws, item, session_id)
                continue
            # S45：点选直连 —— **确定意图，不经过 LLM**（见 _direct_media_play 的说明）。
            # 走同一个串行队列，保证与聊天回合互斥，不会两边抢播放器。
            if item.get("type") == "media:play":
                session.next_generation()
                # 新回合（点选直连）也取消上一轮还在朗读的回复
                _prev_speak = _reply_speak_tasks.pop(session_id, None)
                if _prev_speak is not None and not _prev_speak.done():
                    _prev_speak.cancel()
                try:
                    from yuiro.netease import official_client as client
                    identity = _media_identity(session_id)
                    if item.get('backend', 'builtin') != 'builtin':
                        raise RuntimeError('未知播放器，未控制任何播放器')
                    if ('character_id' in item and
                            (item.get('character_id'), item.get('character_revision'), item.get('session_id')) != identity):
                        raise RuntimeError('旧角色的播放请求已失效')
                    await client.release()
                    identity = _media_identity(session_id)
                    await ws.send_json({'type': 'media:state', 'backend': 'netease_client',
                                        'character_id': identity[0], 'character_revision': identity[1],
                                        'session_id': identity[2], 'state': None})
                    ok, note = await _direct_media_play(item)
                except Exception as exc:  # noqa: BLE001 — 直连失败也不能影响连接
                    ok, note = False, f"播放失败：{exc}"
                vlog("media", f"[{session_id[:8]}] 点选直连{'成功' if ok else '失败'}：{note}")
                try:
                    # S52：气泡文本走展示语言（点选直连的结果同样是她"说"的话）
                    await ws.send_json(
                        {"type": "chat:assistant", "text": await _render_display_text(note)}
                    )
                except Exception as exc:  # noqa: BLE001 — 连接断开静默，但要留痕
                    vlog("media", f"直连结果回推失败（连接可能已断）：{exc}")
                else:
                    # 统一 TTS 开关：点选直连的回应同样"说"出来（与 chat:user 同一条路径）
                    _reply_speak_tasks[session_id] = asyncio.create_task(
                        _speak_reply(ws, session_id, note, generation=_avatar_generation(session_id))
                    )
                continue
            # S51：日记模式消息 —— 走同一串行队列（与聊天回合互斥，不抢 TTS/播放器），
            # 但**不经过 AgentLoop**（见 _handle_diary_message 的说明）。
            if str(item.get("type", "")).startswith("diary:"):
                await _handle_diary_message(ws, session_id, item)
                continue
            user_text = str(item.get("text", ""))
            bilingual_order = item.get('bilingual_order')
            if bilingual_order is not None:
                import os

                from yuiro.audio.bilingual import experiment_allowed
                if not experiment_allowed(bilingual_order,
                        os.environ.get('YUIRO_BILINGUAL_EXPERIMENT'),
                        app.state.app_config.language.speak_language):
                    await ws.send_json({'type': 'chat:busy', 'reason': 'bilingual_experiment_disabled',
                                        'message': '双语实验未开启或当前角色未配置日语朗读。'})
                    continue
            streaming_reply = item.get('stream_reply') is True
            if bilingual_order:
                streaming_reply = True
            reply_request_id = str(item.get('reply_request_id') or '')[:64]
            await _prepare_text_turn(session_id)
            await control_gate.wait()
            if item.get('_queue_epoch', 0) != control_epoch:
                continue
            # S01：每轮文字交互一条 trace（只观测，不改行为）
            trace = TraceContext(session_id=session_id, mode="chat")
            trace.mark("turn_start")
            from yuiro.audio.output import ReplyStream
            experiment_renderer = None
            experiment_metrics = {} if bilingual_order else None
            if bilingual_order == 'baseline':
                from yuiro.audio.bilingual import MeasuredLLM
                from yuiro.audio.render import OutputRenderer
                _language = app.state.app_config.language
                experiment_renderer = OutputRenderer(MeasuredLLM(app.state.agent_loop._llm, experiment_metrics),
                    display_language=_language.display_language,
                    speak_language=_language.speak_language, cache_size=0,
                    timeout_s=_language.translate_timeout_s)

            async def speak_sentences(channel, generation, prepared, _trace=trace,
                                      _request=reply_request_id,
                                      _bilingual=bilingual_order in ('ja_first', 'zh_first'),
                                      _renderer=experiment_renderer, _metrics=experiment_metrics):
                await _speak_reply(ws, session_id, '', generation=generation,
                                   sentence_iter=channel, trace=_trace, preconnected=prepared,
                                   reply_request_id=_request, already_rendered=_bilingual,
                                   render_speak=_renderer.render_speak if _renderer else None,
                                   experiment_metrics=_metrics)

            _tts = getattr(app.state.voice_pipeline, '_tts', None)
            _prepare = getattr(_tts, 'open_sentence_session', None)
            speech = ReplyStream(speak_sentences,
                                 lambda task: _reply_speak_tasks.__setitem__(session_id, task),
                                 lambda: session.generation, trace,
                                 prepare=_prepare if (callable(_prepare) and
                                     app.state.app_config.tts.reply_tts_enabled) else None)

            async def reset_speech(_speech=speech, _request=reply_request_id):
                await _speech.abort()
                await ws.send_json({'type': 'tts:reply_end', 'session_id': session_id,
                                    'generation': session.generation, 'reason': 'agent_reset',
                                    'reply_request_id': _request})
            log_ring.emit("INFO", "chat", f"用户: {user_text}")
            vlog("chat", f"[{session_id[:8]}] 处理 chat:user {user_text!r}")
            t0 = time.monotonic()
            # 标记即将调用 AgentLoop/LLM——若此后长时间无「LLM 首 token」日志即卡在 LLM 请求
            vlog("chat", f"[{session_id[:8]}] 调用 AgentLoop/LLM（backend={getattr(app.state.agent_loop, '_llm', None) is not None}）")
            try:
                async def experimental_reply(_speech=speech, _trace=trace,
                                             _order=bilingual_order, _text=user_text,
                                             _request=reply_request_id, _metrics=experiment_metrics):
                    from yuiro.audio.bilingual import generate_conventional, generate_pairs
                    session.next_generation()
                    generation = session.generation
                    def check():
                        if generation != session.generation:
                            raise asyncio.CancelledError('bilingual stale generation')
                    async def deliver(pair):
                        check()
                        await ws.send_json({'type': 'chat:sentence', 'text': pair['zh'],
                                            'session_id': session_id, 'generation': generation,
                                            'reply_request_id': _request})
                        await _speech.send(pair.get('ja', pair['zh']))
                    metrics = _metrics
                    loop = app.state.agent_loop
                    if _order == 'baseline':
                        reply = await generate_conventional(loop._llm, loop._persona_prompt,
                            _text, deliver, check, _trace, metrics)
                    else:
                        reply = await generate_pairs(loop._llm, loop._persona_prompt, _text,
                                                     _order, deliver, check, _trace, metrics)
                    await ws.send_json({'type': 'experiment:metrics', **metrics,
                                        'session_id':session_id, 'generation':generation,
                                        'reply_request_id': _request, 'stages_ms': dict(_trace._marks)})
                    return reply
                agent_task = asyncio.create_task(experimental_reply() if bilingual_order else _agent_reply(
                    user_text, session_id, trace, session,
                    web_search=item.get("web_search"),
                    on_sentence=speech.send if streaming_reply else None,
                    on_reset=reset_speech if streaming_reply else None,
                ))
                _reply_agent_tasks[session_id] = agent_task
                reply = await agent_task
            except asyncio.CancelledError:
                await speech.abort()
                if asyncio.current_task().cancelling():
                    raise
                continue
            except Exception as exc:  # noqa: BLE001 — AgentLoop/LLM 异常兜底
                if bilingual_order:
                    await speech.abort()
                    await ws.send_json({'type':'tts:reply_end', 'session_id':session_id,
                                        'generation':session.generation,
                                        'reply_request_id':reply_request_id,
                                        'reason':'experiment_failed'})
                vlog("chat", f"[{session_id[:8]}] AgentLoop 异常: {traceback.format_exc(limit=4)}")
                log_ring.emit("ERROR", "chat", f"AgentLoop 异常: {exc}")
                reply = ('双语实验未完成，本轮后续朗读已停止，请用普通消息重试。'
                         if bilingual_order else f"抱歉，处理出错了：{exc}")
            finally:
                if _reply_agent_tasks.get(session_id) is locals().get('agent_task'):
                    _reply_agent_tasks.pop(session_id, None)
            if streaming_reply:
                await speech.finish(reply)
            if speech.failure:
                vlog('tts', f'[{session_id[:8]}] 朗读预算退出: {speech.failure}，文字继续')
                await ws.send_json({'type': 'tts:reply_end', 'session_id': session_id,
                                    'generation': session.generation, 'reason': speech.failure,
                                    'reply_request_id': reply_request_id})
            vlog(
                "chat",
                f"[{session_id[:8]}] 回复 chat:assistant {reply!r}"
                f"（{int((time.monotonic() - t0) * 1000)}ms）",
            )
            # S52：文字聊天的气泡同样走展示语言（内部原文由 source_text 带上，
            # 便于前端/调试台对照；AgentLoop 内部的中文 history/记忆不受影响）
            display_reply = await _render_display_text(reply)
            log_ring.emit("INFO", "chat", f"助手: {display_reply}")
            try:
                await ws.send_json(
                    {"type": "chat:assistant", "text": display_reply, "source_text": reply,
                     "speech_streaming": streaming_reply and speech.task is not None,
                     "trace_id": trace.trace_id, "reply_request_id": reply_request_id}
                )
            except Exception:  # noqa: BLE001 — 连接断开时静默
                return
            trace.mark("reply_sent")
            trace.emit()
            if not streaming_reply:
                await speech.finish(reply)  # 旧客户端保持先全文、后声音的顺序。
            # 统一「语音回复 TTS」：文本已发，声音作为后台任务补发（不阻塞下一轮）。
            # 记入 _reply_speak_tasks，下一轮 chat:user 到来时取消它（改口）。
            # 音频已由同轮句子桥投喂，禁止在完整回复到达时再朗读一次。
            # S51：回复已发出 → 告诉整理调度器"本轮结束"（它据此开始计"会话间隙"）。
            # 刻意放在**回复发送之后**：整理永远不占用这一轮的回复时间。
            _note_memory_idle()

    worker = asyncio.create_task(chat_worker())
    _character_workers.add(worker)
    worker.add_done_callback(_character_workers.discard)
    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "avatar:receipt":
                avatar = getattr(app.state, "avatar", None)
                owner = str(msg.get("session_id") or "")
                if avatar is not None and owner in ("", session_id):
                    try:
                        avatar.playback_receipt(owner, str(msg.get("intent_id") or ""),
                                                str(msg.get("phase") or ""),
                                                int(msg.get("duration_ms") or 0))
                    except (TypeError, ValueError, OverflowError):
                        pass
                continue
            if mtype == "chat:user":
                await admit_chat(msg)
            elif mtype == 'interrupt':
                cancel_started = time.monotonic()
                control_gate.clear()
                control_epoch += 1
                while not chat_queue.empty():
                    chat_queue.get_nowait()
                try:
                    await _cancel_turn(session_id, 'control_interrupt')
                finally:
                    control_gate.set()
                await ws.send_json({'type': 'interrupt:complete', 'session_id': session_id,
                                    'generation': session.generation,
                                    'settle_ms': round((time.monotonic()-cancel_started)*1000, 1)})
            elif mtype == 'media:control':
                # 暂停/状态不排在长 LLM 回合后；适配器自己的锁与归属保证互斥。
                control_task = asyncio.create_task(_reply_official_media(ws, msg, session_id))
                _character_workers.add(control_task)
                control_task.add_done_callback(_character_workers.discard)
            elif mtype == 'media:search':
                if search_task is not None:
                    search_task.cancel()
                search_task=asyncio.create_task(_reply_client_search(ws,msg,session_id))
                _character_workers.add(search_task)
                search_task.add_done_callback(_character_workers.discard)
            elif mtype == "media:play":
                # S45：点选直连（确定意图，不经 LLM）—— 见 _direct_media_play。
                await admit_chat(msg)
            elif isinstance(mtype, str) and mtype.startswith("diary:"):
                # 可选插话独立且可取消，不占用保存/撤销的串行队列。
                if diary_quip_task is not None:
                    diary_quip_task.cancel()
                    await asyncio.gather(diary_quip_task, return_exceptions=True)
                    diary_quip_task = None
                if mtype in ("diary:quip", "diary:interact"):
                    diary_quip_task = asyncio.create_task(_handle_diary_message(ws, session_id, msg))
                    _character_workers.add(diary_quip_task)
                    diary_quip_task.add_done_callback(_character_workers.discard)
                elif mtype != "diary:quip_cancel":
                    await admit_chat(msg)
            elif mtype == "approval:resolve":
                # 即时处理：不排队，审批 future 立刻完成
                resolve_approval(str(msg.get("request_id", "")), bool(msg.get("approved")))
            else:
                # Other events (motion, tool-call) handled in later milestones.
                await ws.send_json({"type": "ack", "echo": msg})
    except asyncio.CancelledError:
        if not getattr(getattr(app.state, "characters", None), "switching", False):
            raise
        return  # 角色切换主动取消连接是正常控制流，不打印 ASGI 异常栈。
    except WebSocketDisconnect:
        return
    finally:
        if diary_quip_task is not None:
            diary_quip_task.cancel()
            await asyncio.gather(diary_quip_task, return_exceptions=True)
        if search_task is not None:
            search_task.cancel()
            await asyncio.gather(search_task, return_exceptions=True)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        # 连接关闭：取消还在朗读的回复任务（其音频已无处可发）
        _leftover = _reply_speak_tasks.pop(session_id, None)
        if _leftover is not None and not _leftover.done():
            _leftover.cancel()
        if _leftover is not None:
            await asyncio.gather(_leftover, return_exceptions=True)
        unregister_control_conn(session_id)
        app.state.sessions.detach_control(session_id)
        # S51：连接关闭 = "这一场聊完了" → 安排一次整理（延迟执行，等尾音落定）
        _note_memory_session_end()
        vlog("chat", f"WS /ws/control 连接关闭 session={session_id[:8]}")


@app.websocket("/ws/audio")
async def audio_channel(ws: WebSocket) -> None:
    """Audio channel: mic int16 mono PCM in, tts:audio payloads out.

    每个连接分配独立 session_id；二进制帧喂 VoicePipeline.on_audio，
    JSON 帧支持 {type:'interrupt'} 触发 barge-in。
    """
    await ws.accept()
    if not _authorized(ws):
        await ws.close(code=4401, reason="unauthorized")
        return
    if getattr(getattr(app.state, "characters", None), "switching", False):
        await ws.close(code=1013, reason="character switching")
        return
    connection = asyncio.current_task()
    _character_workers.add(connection)
    connection.add_done_callback(_character_workers.discard)
    # S02：带 ?session= 绑定同一会话；不带则独立会话（兼容旧前端）
    bound = ws.query_params.get("session")
    session = app.state.sessions.attach_audio(ws, session_id=bound)
    session_id = session.session_id
    from yuiro.approval import register_audio_conn, resolve_approval, unregister_audio_conn

    register_audio_conn(session_id, ws)
    vlog(
        "voice",
        f"WS /ws/audio 连接建立 session={session_id[:8]}"
        f"（secret 校验通过, {'绑定' if bound else '新建'}）",
    )

    # 主动下发当前语音管线加载状态：预热常在引擎启动后 1-2s 完成，而前端
    # audio WS 往往晚于此时才连上，广播已错过 → 必须在此补发，否则前端
    # engineReady 永远为 false、start() 永久等待超时。
    pipe = getattr(app.state, "voice_pipeline", None)
    if pipe is not None:
        try:
            await ws.send_json(
                {
                    "type": "pipeline:state",
                    "state": pipe._state,
                    "stage": pipe._loading_stage,
                    "progress": pipe._loading_progress,
                }
            )
        except Exception:  # noqa: BLE001
            pass

    # 与 control 通道同理：PCM 帧进队列由 worker 串行处理（on_audio 可能
    # 长阻塞于 ASR/LLM/审批），主循环保持空闲以即时处理 interrupt / approval:resolve。
    pcm_queue: asyncio.Queue = asyncio.Queue(maxsize=32)

    async def admit_pcm(data):
        if len(data) > 64000:
            await ws.close(code=1009, reason='audio frame exceeds budget')
            return False
        try:
            pcm_queue.put_nowait(data)
            return True
        except asyncio.QueueFull:
            vlog('voice', f'[{session_id[:8]}] PCM积压超限，关闭音频连接而非静默丢帧')
            await ws.close(code=1013, reason='audio backlog exceeds budget')
            return False

    async def pcm_worker() -> None:
        while True:
            frame = await pcm_queue.get()
            if frame is None:
                return
            try:
                await app.state.voice_pipeline.on_audio(frame, session_id)
            except Exception:  # noqa: BLE001 — 外部组件错误不得断开 WS
                log_ring.emit(
                    "ERROR", "voice", f"语音管线处理异常: {traceback.format_exc(limit=3)}"
                )

    worker = asyncio.create_task(pcm_worker())
    _character_workers.add(worker)
    worker.add_done_callback(_character_workers.discard)
    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                return
            data = message.get("bytes")
            if data is not None:
                if not await admit_pcm(data):
                    pipe = app.state.voice_pipeline
                    producers = [getattr(pipe, attr, {}).get(session_id)
                                 for attr in ('_turn_tasks', '_speak_tasks', '_pending_end')]
                    notification = pipe.interrupt(session_id)
                    pending = {task for task in (*producers, notification)
                               if task is not None and task is not asyncio.current_task()}
                    await asyncio.gather(*pending, return_exceptions=True)
                    return
                continue
            text = message.get("text")
            if text is not None:
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict) and msg.get("type") == "interrupt":
                    vlog("voice", f"[{session_id[:8]}] 收到 interrupt（前端打断）")
                    # S03：走统一取消入口（代际作废 + 停语音 + session.cancelled 事件）
                    await _cancel_turn(session_id, "frontend-interrupt")
                elif isinstance(msg, dict) and msg.get("type") in (
                    "audio:playback_started", "audio:playback_finished",
                ):
                    current = app.state.sessions.get(session_id)
                    if (current is not None
                        and msg.get('generation') == current.generation
                        and msg.get('character_id') == getattr(app.state.app_config, '_character_id', '')
                        and app.state.voice_pipeline.playback.receipt(session_id, msg)):
                        if msg['type'] == 'audio:playback_started':
                            app.state.voice_pipeline.mark_playback_started(session_id)
                elif isinstance(msg, dict) and msg.get("type") == "approval:resolve":
                    # 即时处理：不排队，审批 future 立刻完成
                    resolve_approval(str(msg.get("request_id", "")), bool(msg.get("approved")))
    except asyncio.CancelledError:
        if not getattr(getattr(app.state, "characters", None), "switching", False):
            raise
        return
    except WebSocketDisconnect:
        return
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        from yuiro.approval import get_audio_conn
        if get_audio_conn(session_id) is ws:
            app.state.voice_pipeline.playback.clear(session_id)
            unregister_audio_conn(session_id)
            app.state.sessions.detach_audio(session_id)
        vlog("voice", f"WS /ws/audio 连接关闭 session={session_id[:8]}")


_character_workers: set[asyncio.Task] = set()
_character_cache: dict[str, dict] = {}
_CHARACTER_STATE = (
    "memory", "relationship", "tasks", "event_log", "sessions", "emotion_engine",
    "avatar", "agent_loop", "memory_idle", "output_renderer", "chat_responder",
)


def _character_config_signature(cfg):
    from dataclasses import asdict
    from yuiro.characters import ROLE_SECTIONS

    result = {key: asdict(getattr(cfg, key)) for key in ROLE_SECTIONS}
    result["tts"].pop("siliconflow_key", None)
    return result


def _character_snapshot():
    return {**{key: getattr(app.state, key, None) for key in _CHARACTER_STATE},
            "_tts": app.state.voice_pipeline._tts, "_ready": True,
            "_config": _character_config_signature(app_config)}


async def _prepare_character(role, cfg):
    """只准备轻量 store；同一嵌入配置借用现有 worker，不复制模型权重。"""
    from urllib.parse import unquote
    from yuiro.avatar.runtime import AvatarRuntime
    from yuiro.emotion import EmotionEngine
    from yuiro.memory.idle import MemoryIdleScheduler
    from yuiro.task import TaskRuntime

    model = unquote(cfg.persona.model_path)
    public = Path(__file__).resolve().parents[2] / "shell/src/renderer/public"
    resolved = (public / model.lstrip("/")).resolve()
    if not resolved.is_relative_to((public / "live2d").resolve()) or not resolved.is_file():
        raise ValueError("角色模型不在现有 Live2D 素材目录或文件不存在")
    current = app_config._character_id
    _character_cache[current] = _character_snapshot()
    if role in _character_cache:
        cached_config = _character_cache[role].get("_config")
        if cached_config and cached_config != _character_config_signature(cfg):
            raise ValueError("缓存角色的磁盘配置已被外部改动；请重启引擎后加载，避免配置与运行对象不一致")
        return _character_cache[role]
    if Path(cfg.memory.db_path).resolve() == Path(app_config.memory.db_path).resolve():
        raise ValueError("两个角色不能使用同一个记忆数据库")
    shared = None
    if cfg.memory.embedder == app_config.memory.embedder:
        shared = getattr(getattr(app.state, "memory", None), "embedder", None)
    memory = _build_memory(cfg, shared_embedder=shared)
    data = Path("data") if role == "hiyori" else Path("data/characters") / role
    event_log = EventLog(store_dir=data / "events")
    expr, motion, perf = effective_persona_maps(cfg.persona)
    bundle = {
        "memory": memory,
        "relationship": RelationshipMemory(data / "relationship.json"),
        "tasks": TaskRuntime(events=app.state.events, store_dir=data / "tasks"),
        "event_log": event_log,
        "sessions": SessionManager(events=app.state.events, event_log=event_log),
        "emotion_engine": EmotionEngine(hints=cfg.persona.emotion_hints, expression_map=expr),
        "avatar": AvatarRuntime(expression_map=expr, motion_map=motion, performance_map=perf,
                                motion_slots=effective_motion_slots(cfg.persona),
                                generation_getter=_avatar_generation,
                                broadcast=app.state.avatar._broadcast),
        "agent_loop": None,
        "memory_idle": MemoryIdleScheduler(memory.tidy),
        "output_renderer": _build_renderer(cfg, app.state.llm_api_key),
        "chat_responder": None,
        "_ready": False,
    }
    _character_cache[role] = bundle
    return bundle


async def _quiesce_character():
    """关闭旧连接并等待真实工作终止；超时拒绝切换，不让旧副作用串角色。"""
    from yuiro.approval import broadcast_control
    from yuiro.netease import official_client as client

    client.invalidate()

    await broadcast_control({"type": "character:switching"})
    tasks = set(_character_workers) | set(_reply_speak_tasks.values())
    pipe = app.state.voice_pipeline
    for attr in ("_turn_tasks", "_pending_end", "_speak_tasks"):
        tasks.update(getattr(pipe, attr, {}).values())
    for item in app.state.sessions.list_sessions():
        sid = item["session_id"]
        app.state.sessions.cancel(sid, "character_switch")
        pipe._recording[sid] = False
        pipe.interrupt(sid)
        session = app.state.sessions.get(sid)
        if session:
            for ws in (session.control_ws, session.audio_ws):
                if ws:
                    try:
                        await ws.close(code=1012, reason="character switch")
                    except RuntimeError:
                        pass
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=3.0)
        if pending:
            raise RuntimeError("旧角色任务尚未收敛，请稍后再切换")
    await client.release()
    idle = getattr(app.state, "memory_idle", None)
    if idle:
        await idle.stop()
    # Presence 的策略/功能共用，但它的在途输出不能跨过角色切换边界。
    await app.state.presence.stop()
    proactive = getattr(app.state, "proactive", None)
    if proactive:
        await proactive.stop()


async def _activate_character(role, bundle):
    from yuiro.debug_api import _rebuild_responder

    bundle = bundle or _character_cache[role]
    previous_agent = bundle.get("agent_loop")
    for key in _CHARACTER_STATE:
        setattr(app.state, key, bundle.get(key))
    if bundle.get("_ready"):
        app.state.voice_pipeline._tts = bundle["_tts"]
        app.state.voice_pipeline.set_renderer(app.state.output_renderer)
    else:
        _rebuild_responder(app)
    if previous_agent and app.state.agent_loop:
        app.state.agent_loop._history = previous_agent._history
    app.state.runtimes.register(AgentRuntimeAdapter(app.state.agent_loop))
    app.state.runtimes.register(TaskRuntimeAdapter(app.state.tasks))
    app.state.runtimes.register(app.state.avatar)
    diary = getattr(app.state, "diary", None)
    if diary:
        diary._memory = app.state.memory
        diary._llm = getattr(app.state.agent_loop, "_llm", None)
    # 日记草稿属于用户，但旧角色的伴随点评不能带入新角色。
    if getattr(app.state, "diary_session", None):
        from yuiro.diary.quip import QuipService
        app.state.diary_session._service = diary
        app.state.diary_session._quip = QuipService(llm=getattr(app.state.agent_loop, "_llm", None))
    if app_config.presence.enabled:
        await app.state.presence.start()
    elif getattr(app.state, "proactive", None) and app_config.proactive.enabled:
        await app.state.proactive.start()


async def _notify_character(role, revision):
    from yuiro.approval import broadcast_control

    await broadcast_control({"type": "character:changed", "character_id": role,
                             "revision": revision, "model_path": app_config.persona.model_path})


async def _forget_character_diary_text(text):
    """共享日记撤销授权时删除两角色的精确源条目，包括尚未热加载的库。"""
    from yuiro.characters import IDS
    from yuiro.memory import MemorySystem

    removed = 0
    seen = set()
    for role in IDS:
        cfg = _character_store.resolve(role, app_config)
        path = Path(cfg.memory.db_path).resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        memory = (getattr(app.state, "memory", None) if role == app_config._character_id
                  else _character_cache.get(role, {}).get("memory"))
        temporary = memory is None
        if temporary:
            # 删除只需要 SQLite，不加载嵌入模型，不计算新向量。
            memory = MemorySystem(str(path), embedder_model=None)
        try:
            removed += await memory.forget_text(text)
        finally:
            if temporary:
                memory.close()
    return removed


def _invalidate_inactive_characters():
    service = getattr(app.state, "characters", None)
    if service and service.switching:
        return
    for role, bundle in _character_cache.items():
        if role != app_config._character_id:
            # 共用凭证/工具配置变化后不能恢复旧 key 或旧工具清单；数据 store 仍复用。
            bundle["_ready"] = False


async def _shutdown_character_resources():
    """先关借用 store，再关拥有嵌入 worker 的 store；不重复 close 同一对象。"""
    bundles = list(_character_cache.values()) + [
        {key: getattr(app.state, key, None) for key in _CHARACTER_STATE}
    ]
    memories = {id(b["memory"]): b["memory"] for b in bundles if b.get("memory")}
    for bundle in bundles:
        idle = bundle.get("memory_idle")
        if idle:
            await idle.stop()
    for memory in sorted(memories.values(), key=lambda m: m.retriever._owns_embedder):
        pending = list(getattr(memory, "_pending_tasks", ()))
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        memory.close()


from yuiro.character_switch import CharacterSwitch  # noqa: E402

app.state.characters = CharacterSwitch(
    _character_store, app_config, prepare=_prepare_character, quiesce=_quiesce_character,
    activate=_activate_character, notify=_notify_character,
)
app.state.invalidate_inactive_characters = _invalidate_inactive_characters


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}

