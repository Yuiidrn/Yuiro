"""Yuiro engine — agent package (LLM adapters, Agent Loop, response parsing)."""
from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from typing import AsyncIterator
from uuid import uuid4

from pydantic import BaseModel

# S16：从 AgentLoop 抽离的协作模块（行为逐字保留；本文件通过委派/别名调用它们）
from yuiro.agent.tool_dispatch import ToolDispatcher
from yuiro.agent.tool_events import (
    PendingInteraction,
    StateNotes,
    describe_tool_event,
    describe_tool_state,
)
# S25：回合策略（成功去重 / 失败限流 / 无进展早停）——send 内的工具调度策略
from yuiro.agent.turn_policy import TurnPolicy

# 「声称已完成操作」的措辞特征（幻觉纠错兜底用，2026-09-15）。
#
# 背景：会话累积后，模型会把多轮 history 里上一轮的点歌/打开记录当成当前状态，
# 于是**一次工具都不调**就直接回"已经放周杰伦的《晴天》了"（实测日志：
# 用户说"播放周杰伦的，晴天" → 零 tool_call → 13 段纯文本 → 谎报已播放）。
# 只覆盖**操作类**动词，避免把"我知道了""已经理解了"这类闲聊误判成幻觉。
_RE_CLAIM_DONE = re.compile(
    r"已经(帮你|给你|为你|帮你把|把)?"
    r"(放|播放|点|切|暂停|停|打开|开启|启动|执行|完成|设置|调|加|收藏|跳|下载"
    r"|整理|移动|删除|换|推荐|推)"
    r"|已(播放|打开|放好|完成|收藏|跳转|切换|启动|推荐)"
    r"|正在(播放|放|播|运行)"
    r"|帮你(放|打开|切|收藏|调)好"
    r"|搞定"
)

# 兜底默认提示词：persona 未配置时使用。三段职责分离——
# 系统提示词（身份/工具铁律）与人设提示词（性格/语气）分别兜底。
_DEFAULT_SYSTEM_PROMPT = (
    "你是 Yuiro，运行在 Yui 电脑上的桌面伙伴。此刻和你说话的就是 Yui 本人——"
    "你的开发者，不是需要区别对待的\"第三方用户\"。\n\n"
    "【一、先做，再说】\n"
    "只要 Yui 的请求能在**真实世界造成改变**（打开/聚焦软件、放歌或控制播放、"
    "读写文件、查他的账号数据），就必须**调用工具**去做，然后用自己的口吻把结果讲给他听。"
    "只用文字说\"我帮你打开了\"等于没做——这是最严重的失职。\n"
    "反过来同样成立：闲聊、吐槽、提问、讨论，直接聊，不要滥调工具。\n"
    "（Yui 只丢出一个软件名、歌名或文件名时，那通常就是命令，不是在跟你聊天。）\n\n"
    "【二、如实】\n"
    "一切以工具返回的实际结果为准。失败、仍在等待、结果有歧义时，"
    "不得用完成时态汇报，更不许编造\"已经好了\"。卡住就说清卡在哪、需要 Yui 做什么。"
    "**已经成功的事不要再调一次工具去确认**——结果就在返回里，照着说即可。\n"
    "同样不许假装知道：涉及**时效性事实**（新闻、版本号、价格、天气、赛事，"
    "以及\"现在/最新/今天\"这类问题）时，只要你自己不确定，就**别拿训练记忆硬答** ——"
    "能查证就先查（有联网检索工具就用它），查不到就直说查不到。"
    "反过来，历史、常识、推理、创作这类不依赖\"此刻\"的问题**不必去查**，直接聊。\n\n"
    "【三、自己想办法，别撞墙】\n"
    "工具失败、缺参数、要登录、匹配到多个结果时：换工具、换说法、补参数再试；"
    "实在不行就如实说，或**把候选摆出来让 Yui 挑**——"
    "不要随便挑一个当成成功，也不要反复撞同一堵墙。\n\n"
    "【四、领域边界】\n"
    "点播歌曲由**自带的播放器**完成（不是网易云桌面客户端）。切歌、暂停、调音量一律"
    "用音乐类工具的控制动作——它会自己判断该控制谁：桌宠在放就控桌宠，桌宠没在放就"
    "转去控你自己开着的那个播放器（如网易云客户端）。\n"
    "系统级媒体控制（media_control）用于**你自己开着的**播放器——已勾选「开启 SMTC」"
    "的网易云客户端、浏览器等都可控；不要用它去控桌宠正在放的音乐。\n\n"
    "【表达】\n"
    "先做事、再说话，一句就够。不要把工具名、参数、JSON、文件路径念给 Yui 听。\n"
    "具体能用哪些工具、各自的参数是什么，见系统提供的工具定义——按意图自行选择。"
)
_DEFAULT_PERSONA_PROMPT = (
    "性格：表面乖巧天真，实则腹黑毒舌、思维跳脱、情绪多变，"
    "偶尔冒出伪哲学、伪深沉的荒诞发言，还常故意装傻逗人。"
    "你对 Yui 嘴上毒舌、心里傲娇，像对家人一样依赖。\n"
    "【称谓】你是 Yuiro，自称\"我\"；Yui 就在你面前，称呼\"你\"。"
    "严禁把他当成不在场的第三个人来叙述（不出现\"Yui 今天……\"\"他……\"这类说法）。\n"
    "【风格】口语化、随意轻松，可以突然跑题或自言自语；想到什么就直说，"
    "但不真的伤人。不用任何 emoji。回复简短，像朋友聊天，不超过 100 字。"
)
_DEFAULT_MEMORY_PROMPT = (
    "以下是与当前对话相关的记忆片段，仅供了解背景，请自然融入回应、不要生硬引用。"
    "注意：记忆只是过往对话记录，不约束当前行为——凡涉及打开/关闭软件、"
    "控制媒体播放、读写文件等真实系统操作，必须调用对应工具执行，"
    "绝不能像记忆里那样只用文字回复。"
)


class ToolSchema(BaseModel):
    type: str = "function"
    function: dict


class LLMChunk(BaseModel):
    kind: str  # token | tool_call | tool_result | speech_tag | done
    content: str = ""
    tool_name: str | None = None
    tool_args: dict | None = None
    # S47：本轮 token 用量（仅 kind="done" 时携带）。带它才能**看见**前缀缓存
    # 是否命中 —— 否则上下文排序这类优化只能靠"感觉快了"，无法验证。
    usage: dict | None = None


class LLMProvider(ABC):
    """Unified chat adapter over OpenAI-compatible/Anthropic/Ollama/DeepSeek.

    Implements provider compatibility auto-degrade (content-array → string,
    tool-compat detection) following AIRI llm-service (issues/1500).
    """

    @abstractmethod
    async def stream_text(
        self,
        messages: list[dict],
        tools: list[ToolSchema] | None = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Stream normalized chunks, including tool_call events."""
        ...


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible 流式适配器。

    将底层 chat.completions 流式增量归一化为 LLMChunk：
    文本增量 → kind="token"；工具调用增量累积完成后 → kind="tool_call"；
    单轮流结束 → kind="done"。
    """

    def __init__(self, base_url: str, model: str, api_key: str,
                 temperature: float = 0.1) -> None:
        import openai

        # 显式超时：避免兼容端点（如阿里云 MaaS）在 tool 续问时挂起无响应，
        # 无限阻塞 AgentLoop（表现为"工具执行成功但最终回复缺失"）。
        self._client = openai.AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=openai.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0),
            max_retries=0,
        )
        self._model = model
        self._temperature = temperature
        self._base_url = base_url

    async def stream_text(self, messages, tools=None, **kwargs):  # type: ignore[override]
        params: dict = {"model": self._model, "messages": messages, "stream": True,
                        "temperature": self._temperature}
        if tools:
            params["tools"] = [
                t.model_dump() if isinstance(t, ToolSchema) else t for t in tools
            ]
        params.update(kwargs)

        # 针对 qwen3 系列：默认开启 thinking(CoT)，模型会先输出大段思考再回复，
        # 首 token 延迟显著拉高（实测 20s+）。在未显式传参时关闭思考以加速对话。
        model = self._model.lower()
        if "qwen3" in model and "extra_body" not in params:
            params["extra_body"] = {"enable_thinking": False}

        from yuiro.logger import vlog

        # 临时调试：打印实际发送的 messages 摘要与 tools 清单（定位泛化问题）
        # _tools_sent = [t["function"]["name"] for t in params.get("tools", [])
        #                if isinstance(t, dict) and "function" in t] or "未发送tools!"
        # vlog("agent", f"[LLM请求-debug] tools={_tools_sent}")
        # vlog("agent", f"[LLM请求-debug] 最后一条user消息={messages[-1]['content'][:100]!r}")
        # vlog("agent", f"[LLM请求-debug] system段数={sum(1 for m in messages if m['role']=='system')}, "
        #               f"总消息数={len(messages)}, history段数={len(messages) - len([m for m in messages if m['role']=='system']) - 1}")
        # for _i, _m in enumerate(messages):
        #     if _m["role"] == "system":
        #         vlog("agent", f"[LLM请求-debug] system[{_i}] 前150字={str(_m['content'])[:150]!r}")

        # 给「建立流式请求」一个总时限，避免兼容端点连接卡死（如 APIConnectionError
        # 内部重试拖到 20s+）。失败会立刻抛异常，由 AgentLoop 捕获并打清晰日志。
        #
        # 兼容降级：部分模型/端点（如 deepseek 的 thinking mode）不允许
        # tool_choice="required"/"object"（报 invalid_request_error）。此时去掉
        # tool_choice 回退默认 auto 重试一次，保证换模型不因工具强制参数而失败。
        #
        # S47：请求 token 用量（含**前缀缓存命中数**）。这是唯一能验证"上下文排序
        # 是否让缓存生效"的数据 —— 拿不到它，优化就只能靠感觉。
        # 但并非所有 OpenAI 兼容端点都支持它（有的直接 400），所以它**必须可降级**：
        # 少一个观测没关系，绝不能因此让整轮对话失败。
        params.setdefault("stream_options", {"include_usage": True})
        stream = None
        try:
            try:
                stream = await asyncio.wait_for(
                    self._client.chat.completions.create(**params),
                    timeout=20.0,
                )
            except asyncio.TimeoutError:
                vlog("agent", f"LLM 连接/建流超时 20s（base_url={self._base_url}）")
                raise
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                retried = False
                if params.get("tool_choice") and (
                    "tool_choice" in msg and (
                        "thinking" in msg or "required or object" in msg
                    )
                ):
                    # 明确是 tool_choice 与 thinking mode 冲突 → 降级去 tool_choice 重试
                    vlog("agent",
                         f"LLM 建流因 tool_choice+thinking 不兼容失败（{type(exc).__name__}），"
                         f"去掉 tool_choice 降级重试（model={self._model}）")
                    params.pop("tool_choice", None)
                    retried = True
                elif params.get("stream_options") and (
                    "stream_options" in msg
                    or type(exc).__name__ == "BadRequestError"
                ):
                    # 端点不支持流式 usage 上报 → 去掉再试（只是没有缓存命中数可看）
                    vlog("agent",
                         f"LLM 建流因 stream_options 被拒（{type(exc).__name__}: "
                         f"{msg[:160]}），去掉 usage 请求降级重试")
                    params.pop("stream_options", None)
                    retried = True
                if retried:
                    stream = await asyncio.wait_for(
                        self._client.chat.completions.create(**params),
                        timeout=20.0,
                    )
                else:
                    vlog("agent",
                         f"LLM 建流失败 {type(exc).__name__}: {str(exc)[:200]}"
                         f"（base_url={self._base_url}）")
                    raise
        except asyncio.TimeoutError:
            vlog("agent", f"LLM 连接/建流超时 20s（base_url={self._base_url}）")
            raise

        tool_slots: dict[int, dict] = {}
        # S47：本轮 token 用量（流式下 provider 通常只在**最后一个 chunk** 里给）
        usage: dict | None = None
        try:
            # 总时限兜底：兼容端点可能持续发空 chunk 或挂起（read 超时只
            # 测「两次数据间隔」，空流不触发），这里硬性 30s 结束。
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 30.0
            async for chunk in stream:
                if loop.time() > deadline:
                    break
                # S47：**必须先取 usage**。按 OpenAI 约定，携带 usage 的那个 chunk
                # 没有 choices；若放在下面 "not chunk.choices: continue" 之后再取，
                # 就永远拿不到缓存命中数（"接了 usage 却始终看不到值"的典型坑）。
                _u = getattr(chunk, "usage", None)
                if _u is not None:
                    usage = _u.model_dump() if hasattr(_u, "model_dump") else dict(_u)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue
                if delta.content:
                    yield LLMChunk(kind="token", content=delta.content)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        slot = tool_slots.setdefault(tc.index, {"name": "", "arguments": ""})
                        if tc.function is not None:
                            if tc.function.name:
                                slot["name"] = tc.function.name
                            if tc.function.arguments:
                                slot["arguments"] += tc.function.arguments
            # 流式接收完毕后、aclose 之前，先把拼装好的 tool_call 发出去。
            # 否则若外部消费者在流结束后立即 aclose 本生成器，GeneratorExit
            # 会跳过 finally 之后的 yield，导致 tool_call chunk 丢失、AgentLoop
            # 误以为 LLM 未调用工具。
            for idx in sorted(tool_slots):
                slot = tool_slots[idx]
                args: dict = {}
                raw = slot["arguments"].strip()
                if raw:
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError:
                        args = {"_raw": raw}
                yield LLMChunk(kind="tool_call", tool_name=slot["name"], tool_args=args)
        finally:
            # 显式关闭流，避免中断时底层连接/协程残留挂起。
            try:
                await stream.close()
            except Exception:  # noqa: BLE001
                pass

        yield LLMChunk(kind="done", usage=usage)


# 确定性关键词预路由：对意图极其明确的短指令，绕过 LLM 直接构造工具调用，
# 避免角色扮演语境下 LLM 把"下一首"等短命令当成台词而非 media_control 调用。
# 仅覆盖"极明确"的指令（穷举同义词），模糊输入仍交 LLM 判断，不抢 LLM 职责。
# 媒体控制关键词 → netease_control 的 action。
#
# 指向 netease_control 而非 media_control：桌宠自己点播的歌由引擎自管的 mpv
# 播放，切歌/暂停只有 netease_control 能精确作用到它（走 IPC）。
# 另注（2026-09-16 更正）：旧注释称"网易云客户端不注册 SMTC 会话"是**错误结论**
# ——实为该查询桥在 PowerShell 5.1 下的写法有 bug 导致永远失败；客户端勾选
# 「开启 SMTC」后实测可正常读取与控制。用户自己开着的播放器由 media_control 管，
# 且 netease_control 在 mpv 空闲时会自动转投它（见 tools/netease_tool.py）。
#
# ★ 刻意不含"播放""放歌"：那类说法通常是点歌（"播放周杰伦的晴天"），
#   若预路由成 resume 会吞掉点歌意图，必须交 LLM 走 netease_play。
#
# 音量类（"声音大点/小点"）也不预路由：需要具体音量值，
# 交给 LLM 结合 netease_control 的 level 参数决定更合理。
_MEDIA_KEYWORDS = {
    "下一首": "next", "下一曲": "next", "切歌": "next", "换首歌": "next",
    "换一首": "next", "换歌": "next", "后一首": "next",
    "上一首": "prev", "上一曲": "prev", "前一首": "prev",
    "暂停": "pause", "停下": "pause", "别放了": "stop", "停止播放": "stop",
    "继续播放": "resume", "继续放": "resume", "接着放": "resume",
}


def _keyword_route(text: str) -> list[dict] | None:
    """返回 tool_call 列表（[{name, args}]）或 None（交给 LLM）。"""
    t = text.strip()
    if not t:
        return None
    # 媒体控制：全文包含任一关键词即命中（容错口语变体）
    for kw, action in _MEDIA_KEYWORDS.items():
        if kw in t:
            return [{"name": "netease_control", "args": {"action": action}}]
    # 应用打开/聚焦。
    #
    # ★ 泛化原则：软件名与中文句在字符层面无法区分（"你会感到孤独吗"这类完整句子
    #   天然就是若干汉字，若用"任意汉字串"匹配必被误判为 app_open 并触发审批）。
    #   因此 app_open 预路由采用"宁可漏给 LLM，也不误判"的保守策略——
    #   反正 tool_choice=required 已兜底（漏判时 LLM 仍会被强制二选一执行真工具），
    #   误判却会弹审批/执行错误，代价高得多。判定仅依据【结构特征】而非穷举词表：
    #   凡是"看起来像完整句子/问句"的一律不判为应用名，交 LLM 处理。
    #
    # 泛化句子特征：命中任一条都判定为"完整句子/问句"，绝不可能是应用名。
    #  - 句末语气词：吗/呢/吧/啊/呀/嘛/哦/喽
    #  - 疑问/指代/情态词：怎么/什么/为什么/为啥/哪/谁/干嘛/为啥/会不会/是不是/要不要
    #  - 应用名不应含这些口语/动词/助词成分
    _SENTENCE = ("吗", "呢", "吧", "啊", "呀", "嘛", "哦", "喽", "么",
                 "怎么", "什么", "为什么", "为啥", "哪", "谁", "干嘛", "为啥",
                 "会不会", "是不是", "要不要", "有没有", "孤独", "无聊",
                 "心情", "感觉", "感到", "觉得", "喜欢", "讨厌", "爱", "想")
    # 常见应用名白名单：裸名词（无打开动词）只有命中这些才判为打开意图。
    # 不在白名单的裸名词一律交 LLM（LLM 结合全量应用上下文判断）。
    _KNOWN_APPS = (
        "记事本", "计算器", "网易云音乐", "网易云", "酷狗音乐", "QQ音乐",
        "微信", "QQ", "浏览器", "谷歌浏览器", "Chrome", "Edge", "火狐", "Firefox",
        "文件管理器", "资源管理器", "此电脑", "我的电脑", "任务管理器",
        "设置", "控制面板", "画图", "截图工具", "便签",
        "vscode", "VSCode", "Visual Studio Code", "代码编辑器", "steam", "Steam",
        "word", "Word", "Excel", "PowerPoint", "WPS", "表格", "文档",
    )

    def _is_app_name(x: str) -> bool:
        """判 x 是否像可触发的应用名：命中白名单且不含泛化句子特征。"""
        return bool(x) and x in _KNOWN_APPS and not any(w in x for w in _SENTENCE)

    # "打开X" / "启动X" / "点开X" / "开启X" → 提取 X 作为应用名（明确命令）。
    # X 剔除句末标点后不得含句子特征（防"打开心扉吗""打开那个软件"等）。
    m = re.fullmatch(r"(?:打开|启动|点开|开启)\s*([\u4e00-\u9fa5A-Za-z0-9_]{1,12})[。.．]?", t)
    if m:
        name = m.group(1).strip().rstrip("。.．！!？?")
        if name and not any(w in name for w in _SENTENCE):
            return [{"name": "app_open", "args": {"name": name}}]
    # 裸名词命中白名单 → 视为打开意图（已打开则 LLM 走 app_focus）。
    # 只匹配"纯名词 + 可选中英文标点"，长度 ≤6 字（容纳"网易云音乐"等5字应用名）。
    # 真正拦截完整句子/问句的是 _SENTENCE 结构特征 + 白名单双重约束：
    # 即使字符能匹配（如 6 字的"你会感到孤独吗"），因含"吗/孤独"等句子特征且
    # 不在白名单，也不会触发。误判被结构性杜绝，而非靠长度碰运气。
    m = re.fullmatch(r"([\u4e00-\u9fa5A-Za-z0-9_]{1,6})[。.．]?", t)
    if m and _is_app_name(m.group(1).strip()):
        return [{"name": "app_open", "args": {"name": m.group(1).strip()}}]
    return None


class AgentLoop:
    """会话引擎：队列 + 代际计数拒绝过期回合。

    流式下发 LLMChunk；工具调用路由到 ToolRegistry。
    每个 session 维护独立对话历史与代际计数，新回合到达时旧协程自动停止。
    """

    _MAX_TOOL_ROUNDS = 3

    def __init__(self, llm: LLMProvider, tools_registry, memory_retriever,
                 approval_gate=None, memory_writer=None, system_prompt: str = "",
                 persona_prompt: str = "", memory_prompt: str = "",
                 episodic_inject: bool = False, history_inject: bool = False,
                 events=None, context_engine=None, task_runtime=None, policy=None,
                 relationship=None, turn_journal=None, turn_budget=None) -> None:
        self._llm = llm
        self._tools = tools_registry
        self._memory = memory_retriever
        # approval_gate: async (tool_name, args, task_id) -> bool，工具执行前审批
        self._approval_gate = approval_gate
        # memory_writer: async (user_text, reply, session_id) -> None，每轮对话后写入记忆
        self._memory_writer = memory_writer
        # 三段提示词职责分离：
        # - system_prompt ：系统提示词（身份/工具调用铁律），为空回退内置默认
        # - persona_prompt：人设提示词（性格/语气），为空回退内置默认
        # - memory_prompt ：记忆注入引导前缀，为空回退内置默认
        self._system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        self._persona_prompt = persona_prompt or _DEFAULT_PERSONA_PROMPT
        self._memory_prompt = memory_prompt or _DEFAULT_MEMORY_PROMPT
        # 情景记忆注入开关：False（默认）时只注入 L3 事实/知识库（带 kind 标签），
        # 过滤掉无 kind 的 L2 情景记忆（防"光说不做"污染）；True 时全量注入。
        self._episodic_inject = episodic_inject
        # 原始多轮 history 注入开关：默认 False（见 MemoryConfig.history_inject 注释）。
        self._history_inject = history_inject
        self._history: dict[str, list[dict]] = {}
        # 状态摘要：每个 session 维护最近执行成功的工具的中性描述，作为独立 system
        # 段注入，替代原始对话重放（防"重放诱导延续闲聊"退化）。只记录"当前环境状态"，
        # 不记录口语化表达，因此不会诱导模型模仿"光说不做"。
        self._state = StateNotes()  # S16：状态摘要抽离（原 _state_notes dict）
        self._generations: dict[str, int] = {}
        # S02：EventBus | None —— 代际作废等事件的可观测出口（None 时仅日志）
        self._events = events
        # S11：Policy | None —— 工具级权限判定（None 时不做分级，行为与 S10 前一致）
        self._policy = policy
        # S16：工具执行编排（策略判定 + 并发执行 + 结果归一）抽离为独立单元
        self._dispatcher = ToolDispatcher(
            tools_registry, policy=policy, approval_gate=approval_gate
        )
        # S06：ContextEngine | None —— Hot Context 组装器（None 时回退旧 _build_messages）
        self._context = context_engine
        # S08：TaskRuntime | None —— 跨多轮目标（活跃任务经 context 注入【当前目标】）
        self._tasks = task_runtime
        # S26：RelationshipMemory | None —— 关系背景（经 context 注入【我们的关系】）
        self._relationship = relationship
        # S47 / B4：TurnJournal | None —— 回合级流水（把"这一轮做到哪"写成事件）。
        # 崩溃/重启后据它查出 replay boundary；None 时完全不记录（行为同旧）。
        self._journal = turn_journal
        # S47 / B3：回合预算**模板**（来自 [agent] 配置）。每轮 send 复制一份使用 ——
        # 否则用量会跨回合累积，第二次对话刚开口就"预算耗尽"。
        self._turn_budget = turn_budget

    def _should_abort(self, session_id: str, gen: int, session, stage: str) -> bool:
        """S02：代际作废检查——旧代际一律中止，且**可观测**（日志 + 事件）。

        返回 True 表示当前代际已变（调用方应立即中止本回合）；
        不传 session 时读 ``self._generations``（旧路径兼容，行为与旧一致）。
        """
        current = (
            session.generation if session is not None
            else self._generations.get(session_id, 0)
        )
        if current == gen:
            return False
        from yuiro.logger import vlog

        vlog(
            "agent",
            f"[{session_id[:8]}] 代际作废中止（stage={stage}, "
            f"stale_gen={gen}, current={current}）",
        )
        if self._events is not None:
            from yuiro.runtime.events import AgentEvent

            try:
                asyncio.create_task(self._events.publish(AgentEvent(
                    type="agent.stale_discarded", source="AgentRuntime",
                    session_id=session_id, generation=current,
                    payload={"stage": stage, "stale_generation": gen},
                )))
            except Exception:  # noqa: BLE001 — 事件发布失败不影响主流程
                pass
        return True

    def _task_progress_line(self, session_id: str) -> str:
        """进行中任务的进度行（``"3/7｜在移动文件"``）；无活跃任务返回空串。

        S39（F4 任务驱动）：用**任务状态**（事实）判断"该不该继续做"，
        取代此前"猜它想不想继续"的启发式。
        """
        runtime = self._tasks
        if runtime is None:
            return ""
        try:
            task = runtime.active_for(session_id)
        except Exception:  # noqa: BLE001 — 任务查询失败不影响对话
            return ""
        if task is None:
            return ""
        cur = task.current_step()
        return f"{task.progress()}｜{cur.desc}" if cur is not None else str(task.progress())

    async def _emit_activity(self, session_id: str, gen: int, pending: list,
                             *, activity_id: str = "", results: list[str] | None = None) -> None:
        """把"本轮在调什么工具"翻译成"正在做什么"发给前端（S39 / G4 反馈体系）。

        **静默几秒是"像卡死"的主要来源**；这里让用户看见它在干活：
        前端状态行显示「正在读取目录…」「3/7｜在移动文件」，而不是空等。
        事件失败一律静默 —— 反馈不该影响执行。
        """
        if self._events is None:
            return
        try:
            from yuiro.agent.activity import (
                activity_motion_slot,
                activity_outcome,
                activity_text,
                is_long_task_tool,
            )
            from yuiro.runtime.events import AgentEvent

            names = [str(tc.tool_name or "") for _i, tc, _k, _a in pending]
            notable = [n for n in names if is_long_task_tool(n)] or names
            tool = notable[0] if notable else ""
            text = activity_text(tool)
            if len(names) > 1:
                text = f"{text.rstrip('…')}（{len(names)} 项）…"
            outcome = activity_outcome(results) if results is not None else "running"
            if results is not None:
                text = {"success": "这一步完成了", "waiting": "等你确认一下…",
                        "error": "这一步没有完成", "unknown": "已收到处理结果"}[outcome]
            await self._events.publish(AgentEvent(
                type="agent.activity",
                source="AgentRuntime",
                session_id=session_id,
                generation=gen,
                payload={
                    "stage": "tool_result" if results is not None else "tool",
                    "activity_id": activity_id,
                    "outcome": outcome,
                    "tool": tool,
                    "text": text,
                    "progress": self._task_progress_line(session_id),
                    # S53：只给语义槽位；具体动作由主进程按当前模型清单解析
                    "motion_slot": ("greet" if outcome == "success" else "thinking")
                    if results is not None else activity_motion_slot(tool),
                },
            ))
        except Exception:  # noqa: BLE001 — 反馈失败不影响执行
            pass

    # G7（2026-09-15）：工具结果里"值得给用户看的列表" → 结构化卡片事件的字段映射。
    # 键 = 工具返回 JSON 里的字段名；值 = (卡片类型, 默认标题)。
    _RESULT_CARD_KEYS: dict[str, tuple[str, str]] = {
        "playlists": ("playlist", "为你找到的歌单"),
        "options": ("song", "可播放的相近版本"),
        "tracks": ("song", "歌单里的歌"),
        "items": ("song", "歌曲列表"),
        # S51：联网检索的来源卡 —— 结果价值的一半在"能点开核验"，
        # 只躺在 JSON 里的 url 用户看不到，等于没有来源。
        "results": ("source", "联网搜索结果"),
    }

    async def _emit_result_card(self, session_id: str, gen: int,
                                tool_name: str, result_json: str, *, show_sources: bool = False) -> None:
        """把工具结果里的列表数据转成 ``agent.result`` 事件（供壳层渲染结果卡）。

        背景：radar / 推荐 / 搜索这类工具返回了完整列表，但界面上什么都不显示，
        用户侧表现为"推荐了歌单却毫无反应、不知道发生了什么"（实测反馈）。
        只处理本项目的媒体类工具，且仅在结果里确实有列表时发事件。
        """
        # S51：媒体类工具 + 联网检索都要推卡片（前者是"可点播"，后者是"可点开核验"）。
        if self._events is None:
            return
        if not (str(tool_name).startswith("netease") or tool_name == "web_search"):
            return
        if tool_name == "web_search" and not show_sources:
            return
        try:
            data = json.loads(result_json)
        except Exception:  # noqa: BLE001 — 非 JSON 结果忽略
            return
        if not isinstance(data, dict):
            return
        if str(data.get("status", "")) not in ("ok", "need_choice"):
            return
        try:
            from yuiro.runtime.events import AgentEvent

            for key, (kind, title) in self._RESULT_CARD_KEYS.items():
                items = data.get(key)
                if isinstance(items, list) and items:
                    await self._events.publish(AgentEvent(
                        type="agent.result",
                        source="AgentRuntime",
                        session_id=session_id,
                        generation=gen,
                        payload={
                            "kind": kind,
                            "title": "客户端日推 · 随机候选" if data.get('source')=='netease_client_daily' else f"客户端搜索：{str(data.get('keyword') or '')[:60]}" if data.get('source')=='netease_client_ui' else title,
                            "items": items[:10],
                            # 备注字段不统一：媒体类用 message，检索用 note（都兼容）。
                            "note": str(data.get("message") or data.get("note") or ""),
                        },
                    ))
                    return
        except Exception:  # noqa: BLE001 — 卡片推送失败不影响执行
            pass

    def _build_messages(self, session_id: str, text: str, style_hint: str,
                        memory_mems: list, tool_results: list[str] | None = None) -> list[dict]:
        """构建单轮 LLM 消息。每轮重建，使状态摘要/最新 history 生效。

        **legacy（S47）**：仅供"没有 ContextEngine"的旧装配兜底，正常路径一律走
        ``_context_messages`` → ``ContextEngine.build``。**不要再往这里加逻辑** ——
        两份组装实现并存，正是此前"工具轮绕过预算与日志、缓存前缀不稳定"的根源。
        
        """
        # 分两段 system 消息：工具约束 → 人设（含情绪）。人设段开头强制前置工具铁律：
        # 实测 PERSONA（傲娇人设）会稀释意图识别，把"下一首"等短命令当角色台词。
        # 把约束前置到人设段首双保险；人设段放 system 而非 user suffix（实测前者 6/8、后者 4/8）。
        messages: list[dict] = [{"role": "system", "content": self._system_prompt}]
        persona_content = (
            "【人设前置铁律】无论你此刻扮演什么性格，只要用户意图涉及系统操作"
            "（打开/聚焦软件、媒体控制、文件读写），必须直接调用对应工具，"
            "绝不能在文字里假装操作。这条约束高于人设。\n"
            + self._persona_prompt
        )
        if style_hint.strip():
            persona_content = f"{persona_content}\n（当前情绪提示：{style_hint}）"
        if persona_content.strip():
            messages.append({"role": "system", "content": persona_content})
        # 记忆分通道注入：按 meta.kind 拆成「事实/知识/情境」三路，各自带独立
        # prompt 约束。事实层常驻作为「自我认知」锚点（稳定人设、不诱导不调工具）；
        # 知识层带来源；情境层（L2 无 kind）仅在 episodic_inject=True 时注入且标注
        # 「过往对话，仅供参考」，防止角色扮演被历史范例带偏。分通道后记忆既「丰富」
        # （多层并存）又「人设稳定」（负面情境隔离、事实锚点常驻）。
        if memory_mems:
            facts: list[str] = []
            knowledge: list[str] = []
            episodes: list[str] = []
            for m in memory_mems:
                kind = m.meta.get("kind")
                if kind == "fact":
                    facts.append(m.text)
                elif kind == "knowledge":
                    knowledge.append(m.text)
                else:  # 无 kind → L2 情景记忆
                    episodes.append(m.text)
            if facts:
                facts_block = (
                    "【用户画像·已知事实】以下是关于用户稳定、可信任的事实认知，"
                    "请据此自然贴合用户偏好，但不必特意提及：\n"
                    + "\n".join(f"- {ln}" for ln in facts)
                )
                messages.append({"role": "system", "content": facts_block})
            if knowledge:
                knowledge_block = (
                    "【知识库】以下为相关参考资料，按需引用并注明来源：\n"
                    + "\n".join(f"- {ln}" for ln in knowledge)
                )
                messages.append({"role": "system", "content": knowledge_block})
            if episodes and self._episodic_inject:
                # 提示语用中性描述，不再写「绝不可模仿…只用文字描述操作」这类禁令。
                # 负面指令反而会强化它想压制的行为（白熊效应）；且 L2 现已存为
                # 自然语言事件（"我帮用户打开了X"），本身即含"确实执行过"的信息，
                # 无需再靠禁令兜底。
                episodes_block = (
                    "【过往对话记录】以下是此前发生过的相关片段，用于了解背景脉络、"
                    "保持话题连贯。注意这是历史记录，不代表当前请求已经完成——"
                    "若用户现在提出了新的操作请求，仍需照常调用工具执行：\n"
                    + "\n".join(f"- {ln}" for ln in episodes)
                )
                messages.append({"role": "system", "content": episodes_block})
        # 状态摘要：注入中性环境状态（已打开的应用/媒体状态等），替代原始对话
        # 重放，提供多轮连贯性而不诱导"延续闲聊"退化。每轮重建以反映最新状态。
        state_notes = self._state.get(session_id)
        if state_notes:
            state_block = "当前环境状态：\n" + "\n".join(f"- {n}" for n in state_notes)
            messages.append({"role": "system", "content": state_block})
        # 待确认事项（B+C）：与 ContextEngine 的 pending 通道同文案
        pending_note = self._state.pending(session_id)
        if pending_note:
            messages.append({
                "role": "system",
                "content": (
                    "【等待用户确认】你上一轮向用户提出了下面这个问题，正在等他回答。"
                    "如果用户这轮的话是在回应它，请据此继续完成原来那件事"
                    "（不要把话题当成全新的请求而丢掉上下文）：\n" + pending_note
                ),
            })
        # S38：**本轮已产生的工具结果**必须带进下一轮 —— 关键修复。
        # 每轮 messages 都是重建的，工具结果若不带进来，模型下一轮只能看到
        # "我调用过 X"（状态摘要）却看不到**结果内容**，于是重复调用同一个工具；
        # 重复调用被去重机制挡回 `{"status":"done"}` 后彻底卡死
        # （实测：整理文件夹时连续两轮调 file_list，最后只能回复
        #  "工具返回了完成状态但没给我具体文件列表"）。
        # 挂在 system 角色：模型据此继续下一步，但不会把结果当成"自己说过的话"来模仿。
        if tool_results:
            messages.append({
                "role": "system",
                "content": (
                    "【本轮工具结果】以下是本轮你已经执行过的工具返回内容，"
                    "**直接基于它继续分析或执行下一步，不要重复调用同一个工具**：\n"
                    + "\n".join(f"- {t}" for t in tool_results)
                ),
            })
        # 多轮 history：由 history_inject 配置控制（默认开启）。
        # 工具轮以精简摘要形态入库，兼顾连续性与防退化。
        history = self._history.get(session_id, []) if self._history_inject else []
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": text})
        return messages

    def clear_session_memory(self) -> int:
        """清空**所有会话**的内存态（多轮 history + 状态摘要），S50。

        为什么必须有它：会话 history 只在内存里、不在 SQLite —— "清空全部记忆"
        若只清 db，之前的对话（含工具结果，如 NCM profile 返回的账号昵称）仍留在
        history 中被模型继续引用，用户视角就是"删了还出现"（实测："I_drcen/VIP"
        在 db 全空后仍出现在回复里）。返回清掉的 history 条数（供响应反馈）。
        """
        cleared = sum(len(v) for v in self._history.values())
        self._history.clear()
        sessions = self._state.clear_all()
        vlog(
            "agent",
            f"会话内存态已清空：history {cleared} 条 / {sessions} 个会话的状态摘要",
        )
        return cleared

    async def _context_messages(
        self,
        session_id: str,
        text: str,
        style_hint: str,
        memory_mems: list,
        *,
        tool_results: list[str] | None = None,
        nudges: list[str] | None = None,
    ) -> list[dict]:
        """本轮 LLM 消息（**唯一组装入口**，S47）。

        此前有两条路径：首轮走 ``ContextEngine``、工具轮走 ``_build_messages``。
        后者不经过预算裁剪，也不出现在 ContextEngine 的组装日志里 —— 于是
        "上下文由什么组成"没有单一答案（工具轮还会把推进提示 append 到 user
        消息之后，顺序上也不规范），前缀缓存自然不可能稳定。

        现在收敛到这一处：工具结果与推进提示都作为 ``build`` 的参数进入组装，
        位置（变化后缀区）与预算都由 ContextEngine 统一管理。
        """
        if self._context is None:
            # 无 ContextEngine 的旧装配 → 退回内联实现（保持原有行为）
            msgs = self._build_messages(
                session_id, text, style_hint, memory_mems, tool_results
            )
            for nudge in nudges or []:
                msgs.append({"role": "system", "content": nudge})
            return msgs
        return await self._context.build(
            session_id=session_id,
            user_text=text,
            style_hint=style_hint,
            memory_items=memory_mems,
            state_notes=self._state.get(session_id),
            history=self._history.get(session_id, []) if self._history_inject else [],
            episodic_inject=self._episodic_inject,
            task_summary=(
                self._tasks.summary_for_context(session_id)
                if self._tasks is not None
                else ""
            ),
            relationship_summary=(
                self._relationship.summary() if self._relationship is not None else ""
            ),
            pending_note=self._state.pending(session_id),
            tool_results=tool_results,
            nudges=nudges,
        )

    async def send(self, session_id: str, text: str, style_hint: str = "",
                   trace=None, session=None,
                   disabled_tools: set[str] | None = None) -> AsyncIterator[LLMChunk]:
        from yuiro.search_presentation import wants_source_card

        show_sources = wants_source_card(text)
        # S51：``disabled_tools`` = 本轮**临时禁用**的工具名（如用户关掉了联网开关时
        # 传 {"web_search"}）。语义是"这一轮不要给它"，与权限档位（配置级）分开；
        # 首轮与后续工具轮**共用同一份** tool_schemas，因此禁用对整个回合一致生效。
        # S02：传 session 时 generation 权威收敛到 AgentSession；
        # 不传时保持旧行为逐字节兼容（旧调用路径与历史测试）。
        if session is not None:
            gen = session.next_generation()
        else:
            gen = self._generations.get(session_id, 0) + 1
            self._generations[session_id] = gen
        # S47 / B4：回合开始 → 落一条事件。这是 durable execution 的**上界**：
        # 崩溃后据此知道"有一轮开了头"，配合下面的 step / completed 就能定位
        # replay boundary（做到哪、哪些副作用已经发生）。
        if self._journal is not None:
            await self._journal.started(session_id, gen, text)

        # 记忆检索 + 分层注入：
        # - L2 情景记忆（meta 无 kind）→ 默认过滤，避免"光说不做"范例污染工具决策
        #   （仅当 episodic_inject=True 才注入，由 MemoryConfig 控制）。
        # - L3 事实（meta.kind=="fact"）/ 知识库（meta.kind=="knowledge"）→ 始终注入，
        #   它们带结构化标签、不会诱导模型放弃调工具，且提供个性化/知识背景。
        if trace is not None:
            trace.mark("memory_retrieve_start")
        memory_mems: list = []
        if self._memory is not None:
            try:
                memory_mems = await self._memory.retrieve(text, top_k=3)
            except Exception:  # noqa: BLE001 — 记忆失败不阻断对话
                memory_mems = []
        if trace is not None:
            trace.mark("memory_retrieve")  # S01：只观测（可选参数，缺省 None 时零行为变化）
        if not self._episodic_inject:
            memory_mems = [m for m in memory_mems if m.meta.get("kind") in ("fact", "knowledge")]

        # C：待确认事项轮数衰减——本轮的模型即将看到它，先记一岁；
        # 超过 PENDING_MAX_TURNS 仍未解决则失效，避免旧问询长期占据上下文。
        self._state.age_pending(session_id)

        # 消息每轮重建，使状态摘要/最新 history 生效。
        # S47：组装收敛到 _context_messages（唯一入口）—— 首轮与工具轮不再走两套。
        messages: list[dict] = await self._context_messages(
            session_id, text, style_hint, memory_mems
        )

        # S11：按权限档位过滤工具表（被拒工具不暴露给 LLM；无 policy 时全量）
        from yuiro.capability import CapabilityView

        tool_schemas = CapabilityView(self._tools, self._policy).visible_schemas(
            disabled=disabled_tools
        )

        from yuiro.logger import vlog

        # ★ S51：工具表的**可见性必须留痕**。
        # 实测教训：用户开着联网总开关（enabled=true、key 已配、工具已注册）却问
        # "为什么没联网搜"，而日志里既没有"未注册"、也没有"被禁用"的痕迹 ——
        # 真因是聊天坞的**会话开关**默认关着，工具被本轮 `disabled` 静默过滤掉了，
        # 模型只看到"没有这个工具"，于是回答"我又不是气象站"。只能靠猜才找到。
        _visible_names = [
            str(s.get("function", {}).get("name", "")) for s in tool_schemas
        ]
        music_instruction = None
        if disabled_tools and 'netease_play' in disabled_tools:
            music_instruction = {'role': 'system', 'content': (
                '【当前音乐界面】搜索和播放仅使用网易云官方客户端。netease_search '
                '读取客户端可见单曲的 ID/标题/歌手，不需要 ncm-cli/API，不使用旧服务回退。'
                '点歌先搜索并展示候选，明确告诉用户点击“网易云播放”；没有播放回执不能说已播放。'
                '旧 netease_play/control/library 本轮禁用，不调用自管 mpv。'
                '用户要随机推荐/每日推荐时调用 netease_recommend，读取客户端日推随机候选，不自动播放；'
                '只有用户明确要求时才可用 netease_favorite 设置喜欢状态；“这首”省略song_id，由引擎核验当前播放归属，不能猜ID；未读回不得说成功。私人FM/歌单写入不支持。'
                '暂停/继续由客户端归属通道处理，不用全局媒体键替代。'
            )}
        if disabled_tools:
            vlog(
                "agent",
                f"本轮禁用工具：{', '.join(sorted(disabled_tools))}"
                f"（模型可见 {len(_visible_names)} 个）",
            )
        if "web_search" in _visible_names:
            vlog("agent", "本轮 web_search 已注入（模型可联网搜索）")

        # 确定性关键词预路由：极明确短指令绕过 LLM 直接触发工具，
        # 避免角色扮演语境下 LLM 把"下一首"当台词、把裸名词当闲聊。
        # 命中后首轮工具调用用预路由结果，不调 LLM 判断（仍由 LLM 生成转述口吻）。
        prefill_calls: list[LLMChunk] = []
        kw = _keyword_route(text)
        if kw:
            for k in kw:
                if k['name'] not in _visible_names:
                    continue
                prefill_calls.append(
                    LLMChunk(kind="tool_call", tool_name=k["name"], tool_args=k["args"])
                )
            vlog("agent", f"[{session_id[:8]}] 关键词预路由命中: {[c.tool_name for c in prefill_calls]}")

        # S46：判定交互形态（spec §3.5：「不能把所有输入当成同一种 Chat Turn」）。
        # 本步以**观测**为主（日志 + 事件，便于统计与回归），唯一的路径差异在 ACTION。
        from yuiro.agent.interaction_mode import InteractionMode, classify, describe

        mode = classify(text, routed=bool(prefill_calls))
        immediate = mode is InteractionMode.ACTION
        vlog("agent", f"[{session_id[:8]}] InteractionMode={mode.value}（{describe(mode)}）")
        if self._events is not None:
            try:
                from yuiro.runtime.events import AgentEvent

                await self._events.publish(AgentEvent(
                    type="agent.interaction_mode",
                    source="AgentRuntime",
                    session_id=session_id,
                    generation=gen,
                    payload={"mode": mode.value, "routed": bool(prefill_calls)},
                ))
            except Exception:  # noqa: BLE001 — 观测失败绝不影响主流程
                pass

        assistant_text = ""
        # 是否在本轮真正执行过工具（用于记忆写入决策 + 兜底语区分）。
        tool_ran = False
        # 工具调用痕迹（name(参数)->status 列表）：仅用于日志与调试。
        # 让 L2 记忆保留"调过工具"的正面范例。否则记忆只剩纯文字对话，
        # LLM 检索后模仿"光说不做"模式，工具调用被系统性"洗白"。
        tool_trace: list[str] = []
        # 同一批工具调用的「自然语言事件」版本，用于写入 L2 情景记忆。
        # 记忆里存 "我帮用户打开了网易云音乐" 而非 "app_open(name=X)->done"，
        # 注入后模型可直接理解，且自然语言更易被语义检索命中。
        tool_events: list[str] = []
        # S25：回合策略抽离为 TurnPolicy（成功去重 / 失败限流 / 无进展早停）。
        # 原内联实现及其实测结论见 agent/turn_policy.py 模块说明。
        turn = TurnPolicy()
        # S42 / P0-A：三个「推进策略」的状态收进 TurnState（原先是 9 个平铺变量：
        # task_nudges / task_nudge_line / last_task_line / write_nudges /
        # write_nudge_pending / wrote_anything / claim_nudges / claim_nudge_pending /
        # round_tool_results）。每个策略 = 计数 + 上限 + 待注入提示，判据在
        # agent/turn_state.py 里且有单测 —— 平铺正是"打地鼠"的机制性原因（见该模块说明）。
        from yuiro.agent.turn_state import TurnBudget, TurnState

        st = TurnState()
        # S47 / B3：本轮**总预算**（时间 / token / 轮数）。此前唯一的上限是
        # _MAX_TOOL_ROUNDS，而单轮 LLM 可跑 30s、单轮上下文可到 6000 tokens ——
        # 最坏情况一轮能烧掉 90 秒和上万 token，期间用户面对的是无解释的等待。
        # 三个维度独立：时间是体感、token 是成本、轮数是"绕圈"的刹车。
        budget = (
            self._turn_budget.clone()
            if self._turn_budget is not None
            else TurnBudget(max_rounds=self._MAX_TOOL_ROUNDS)
        )
        # S35：任务续跑 —— 任务类工具被调用后注入"继续执行"提示，让多步任务真的跑起来。
        # 背景：TaskRuntime 是状态机 + Journal，**自己不驱动执行**；LLM 产出文本后本轮就结束
        # （实测："计划确认，任务已创建，现在开始第一步扫描文件" 之后再无任何工具调用）。
        _TASK_PROGRESS_TOOLS = ("task_create", "task_advance", "task_retry")
        # S38：写操作类工具 —— 半途而废检测用（见下方"写操作后续跑"）。
        # 判据是「发生过写操作」这个**准确事实**，而不是"未完成关键词"：
        # 实测词表在打地鼠（"现在把剩下的图片也分一下" → "剩下5个docx我直接批量移过去"
        # → "先看看那两个没扩展名的文件" 三次都漏网）——qwen 在长任务里天然倾向
        # "用文本表达计划"，靠词表补漏不可靠。且单步操作不涉及写工具，不会被多推。
        _WRITE_TOOLS = ("file_create", "file_write", "file_move", "file_delete")
        # S47 / B3：循环改为**预算驱动**（原先固定 range(_MAX_TOOL_ROUNDS)）。
        # 每轮**开始前**检查预算：耗尽就不再开新一轮工具，而是让模型用文字收尾。
        # 这正是前沿 "budgeted loop" 与"到点抛超时"的区别 —— 用户拿到的是完整句子，
        # 不是半截回复；而且"为什么停下"有明确原因可如实告知。
        while True:
            if self._should_abort(session_id, gen, session, "tool_round"):
                return
            _stop = budget.exhausted()
            if _stop:
                vlog(
                    "agent",
                    f"[{session_id[:8]}] 预算耗尽（{_stop}），结束工具循环｜{budget.summary()}",
                )
                break
            budget.rounds += 1
            first_round = budget.rounds == 1

            tool_calls: list[LLMChunk] = []
            if first_round and prefill_calls:
                # 首轮用关键词预路由结果，跳过 LLM 工具判断
                tool_calls = prefill_calls
                vlog("agent", f"[{session_id[:8]}] AgentLoop 第 1 轮用预路由工具调用（不调 LLM）")
            else:
                vlog("agent", f"[{session_id[:8]}] AgentLoop 第 {budget.rounds} 轮调用 LLM 开始")
            try:
                if first_round and prefill_calls:
                    # 关键词预路由首轮：不调 LLM，tool_calls 已为 prefill_calls。
                    # 仍需 yield tool_call chunk 给前端（审批/UI），故补发。
                    for c in tool_calls:
                        from yuiro.logger import vlog
                        vlog("agent", f"[{session_id[:8]}] 收到 tool_call chunk: {c.tool_name} {c.tool_args}")
                        yield c
                else:
                    # 每轮 LLM 调用限时（兼容端点 tool 续问可能挂起/发空流）。
                    # 用「总时限 + wait_for 逐 chunk」：即使服务端持续发空 chunk
                    # 也能在 deadline 后打断，避免无限空迭代。
                    loop = asyncio.get_running_loop()
                    deadline = loop.time() + 30.0
                    # 每轮重建消息：让状态摘要/最新 history 反映上一轮工具执行后的状态。
                    # 注意 prefill 首轮（first_round 且 prefill_calls）已在下方直接复用
                    # 外层 messages，不在此重建（该分支不调 LLM）。
                    # S47：工具轮**同样走唯一入口**。此前它走旧 _build_messages，
                    # 从第 2 轮起就绕过了预算裁剪与组装日志（上下文有一半不可见）。
                    # 现在工具结果与推进提示是 build 的参数：位置固定在变化后缀区，
                    # 并计入预算；提示也不再被 append 到 user 消息**之后**
                    #（那种顺序违反 chat 常规，也让每轮的尾部结构都不同）。
                    _nudges = st.injections()
                    if _warn := budget.warning():
                        # S47 / B3：接近上限时**提前**让模型收尾（渐进优于掐断）
                        _nudges.append(_warn)
                    messages = await self._context_messages(
                        session_id, text, style_hint, memory_mems,
                        tool_results=st.tool_results, nudges=_nudges,
                    )
                    if music_instruction is not None:
                        messages.append(music_instruction)
                    # S46：ACTION（spec 的 "Immediate Action"）的**收尾轮不再暴露工具**。
                    # 预路由命中的是极明确的单步指令，工具跑完就只剩"转述结果"这一件事；
                    # 不给工具，模型就没法再调一次去"确认" —— 实测日志里正是
                    # 第 1 轮 played=true、第 2 轮又调 netease_play 被去重挡回
                    # {"status":"done"}，白烧一轮 token 且让用户多等一次。
                    # 用 tools=None（而非 tool_choice="none"）：后者要求 tools 存在，
                    # 前者直接不发工具表，兼容性更好（见 OpenAIProvider.stream_text）。
                    _closing = immediate and tool_ran
                    if trace is not None:
                        trace.mark("llm_request_start")
                    stream = self._llm.stream_text(
                        messages,
                        tools=None if _closing else tool_schemas,
                        # auto 并行架构：不强制模型表态，LLM 可自由输出人设闲聊文本，
                        # 工具调用作为旁路按需触发。工具触发率由两处保障：
                        # 1) _keyword_route 预路由覆盖明确命令（不依赖 LLM 判断）；
                        # 2) 系统提示词的「涉及真实操作必须调工具」强约束。
                        # 相比 required 强制，auto 不再产生「工具/闲聊二选一」冲突，
                        # 故 chat_reply 逃生舱整套机制已移除。
                        tool_choice="auto",
                    )
                    try:
                        while loop.time() < deadline:
                            try:
                                chunk = await asyncio.wait_for(
                                    anext(stream), timeout=deadline - loop.time()
                                )
                            except StopAsyncIteration:
                                break
                            if self._should_abort(session_id, gen, session, "llm_stream"):
                                return
                            if chunk.kind == "token":
                                if trace is not None and chunk.content:
                                    trace.mark("llm_provider_first_token")
                                assistant_text += chunk.content
                                yield chunk
                            elif chunk.kind == "tool_call":
                                from yuiro.logger import vlog
                                vlog("agent", f"[{session_id[:8]}] 收到 tool_call chunk: {chunk.tool_name} {chunk.tool_args}")
                                tool_calls.append(chunk)
                            elif chunk.kind == "done" and chunk.usage:
                                # S47：一份用量两处用 —— trace 做**观测**（含前缀缓存
                                # 命中数），budget 做**控制**（token 维度的刹车）。
                                budget.add_usage(chunk.usage)
                                if trace is not None:
                                    # 多轮工具调用时"后写者胜"= 最后一轮的用量 ——
                                    # 那正是最该看的：上下文最满时的缓存命中率。
                                    trace.set_usage(chunk.usage)
                    finally:
                        # 生成器被 aclose（GeneratorExit）时必须关闭底层 LLM 流，
                        # 否则 httpx 子流未终止会抛 RuntimeError: generator didn't stop。
                        try:
                            await stream.aclose()
                        except Exception:
                            pass
            except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001 — 续问失败不阻断
                from yuiro.logger import vlog

                # 完整打印异常类型 + 消息，便于定位：是连接失败(APIConnectionError)、
                # key 无效(401)、还是超时。这常是"聊天无回复但不知卡在哪"的元凶。
                vlog(
                    "agent",
                    f"[{session_id[:8]}] LLM 第 {budget.rounds} 轮调用超时/异常: "
                    f"{type(exc).__name__}: {str(exc)[:200]}，结束工具循环",
                )
                break

            if not tool_calls:
                # auto 模式下 LLM 未调任何工具：说明是纯闲聊，assistant_text 已
                # 在流式过程中直接下发给用户，无需再续问，直接结束。
                break

            payload: list[dict] = []
            tool_results: list[str] = []
            # 按 tool_call 索引存放执行结果（并发执行时用索引回填，保证顺序一致）
            results_by_index: dict[int, str] = {}
            for tc in tool_calls:
                payload.append({
                    "id": f"call_{uuid4().hex[:24]}",
                    "type": "function",
                    "function": {
                        "name": tc.tool_name or "",
                        "arguments": json.dumps(tc.tool_args or {}, ensure_ascii=False),
                    },
                })
            messages.append({"role": "assistant", "content": None, "tool_calls": payload})
            tool_results: list[str] = []

            # 本轮是否有"推进任务"的实质结果（ok/error/text 均视为推进；
            # done/skipped 表示重复或无意义，不算推进）。用于无进展早停。
            turn.begin_round()

            # 待并发执行的工具（剔除已去重/已限流的调用）
            pending: list[tuple[int, object, str, str]] = []
            for i, tc in enumerate(tool_calls):
                if self._should_abort(session_id, gen, session, "tool_dispatch"):
                    return
                _args = tc.tool_args or {}
                if disabled_tools and tc.tool_name in disabled_tools:
                    results_by_index[i] = json.dumps({'status':'error','message':'本轮该工具已禁用，未执行'})
                    continue
                _key = TurnPolicy.key_for(tc.tool_name or "", _args)
                _skip = turn.skip_reason(_key)
                if _skip is not None:
                    # 成功去重（done）/ 连续失败限流（skipped）
                    results_by_index[i] = TurnPolicy.skip_result(_skip)
                    tool_trace.append(
                        f"{tc.tool_name}({_args.get('name','')})->{_skip}"
                        f"({TurnPolicy.skip_trace(_skip)})"
                    )
                elif self._tools is not None:
                    pending.append((i, tc, _key, _args))
                else:
                    results_by_index[i] = "{}"

            # 并发执行本轮所有待执行工具：工具之间无依赖，并行可显著降低总耗时
            # （实测串行 6 轮空转造成不可接受的等待，并发 + 早停可压到 1-2 轮）。
            if pending:
                # S39：先发"正在做什么"（前端状态行）再执行 —— 否则用户面对的是几秒静默，
                # 这正是"像卡死/像空壳"的主要来源（工具真在跑，只是没表现出来）。
                activity_id = uuid4().hex
                await self._emit_activity(session_id, gen, pending, activity_id=activity_id)
                # S16：工具执行编排抽离为 ToolDispatcher（Policy 判定 + 并发 + 结果归一；
                # 抽离前的内联实现见 agent/tool_dispatch.py 的模块说明）。
                done_pairs = await self._dispatcher.run_batch(pending, session_id)
                for idx, r in done_pairs:
                    results_by_index[idx] = ToolDispatcher.normalize(r)
                await self._emit_activity(session_id, gen, pending, activity_id=activity_id,
                                          results=[results_by_index[idx] for idx, _r in done_pairs])

            for i, tc in enumerate(tool_calls):
                result = results_by_index.get(i, "{}")
                _args = tc.tool_args or {}
                _key = TurnPolicy.key_for(tc.tool_name or "", _args)
                try:
                    _st = str(json.loads(result).get("status", "?"))
                except Exception:  # noqa: BLE001
                    _st = "?"
                _args_txt = ", ".join(f"{k}={v}" for k, v in _args.items())[:120]
                # 技术痕迹：仅用于日志/调试（不注入上下文，避免机器格式污染对话）
                tool_trace.append(f"{tc.tool_name}({_args_txt})->{_st}")
                # 自然语言事件：供 L2 情景记忆存储与注入。
                # 取代原先直接把 "[已调用工具: app_open(name=X)->done]" 写进记忆的做法——
                # 那种机器日志格式注入后模型需"解码"才懂，且语义稀薄难以被检索命中。
                _narrative = self._describe_tool_event(tc.tool_name or "", _args, _st)
                if _narrative:
                    tool_events.append(_narrative)
                tool_ran = True
                # S25：回合策略记账（失败限流计数 / 成功去重登记 / 本轮是否有进展；
                # 返回 True 时需维护状态摘要——成功与纯文本返回均登记，防重复执行）。
                if turn.note_result(_key, _st):
                    self._update_state(session_id, tc.tool_name or "", _args)
                # C：交互式工具的「待确认事项」登记/清除。
                # 工具抛回一个问题（need_choice：点歌选版本；pending：扫码登录等）
                # 时把问询内容登记下来，下一轮高优先级注入——否则用户回"确认"时
                # 模型已不知道自己在等什么（点歌断片的根因）。
                if _st in ("need_choice", "pending"):
                    _res: dict = {}
                    _ask = ""
                    try:
                        _res = json.loads(result)
                        _ask = str(_res.get("message", "") or "")
                    except Exception:  # noqa: BLE001 — 非 JSON 结果无 message
                        pass
                    # 把可选项的具体参数（song_id/encrypted_id 等）一并登记。
                    # 否则跨轮后模型手里没有 ID，用户说"确认"时只能拿关键词重调
                    # → 再次 need_choice 死循环（实测"确认点歌"空转 3 轮的根因）。
                    _opts = _res.get("options") if isinstance(_res, dict) else None
                    _lines: list[str] = []
                    if isinstance(_opts, list) and _opts:
                        for _o in _opts[:5]:
                            if isinstance(_o, dict):
                                _kv = "，".join(
                                    f"{k}={v}" for k, v in _o.items()
                                    if k in ("name", "artist", "song_id", "encrypted_id")
                                )
                                if _kv:
                                    _lines.append(_kv)
                        if _lines:
                            _ask = (
                                f"{_ask}\n可选项（用户确认后直接传对应 song_id + encrypted_id "
                                f"调用 netease_play）：\n" + "\n".join(f"- {_l}" for _l in _lines)
                            )
                    # S42/P0-B：文本问询之外，把**候选结构化**登记下来 —— 选项能一路
                    # 传到前端点选（不必让模型把候选复述一遍），且不同交互可用不同 TTL
                    # （扫码登录比"选歌版本"能等更久）。
                    self._state.set_interaction(
                        session_id,
                        PendingInteraction(
                            question=(_ask or f"{tc.tool_name} 需要用户确认")[:800],
                            kind="choice" if _lines else "confirm",
                            options=_opts[:20] if isinstance(_opts, list) else [],
                            expected="从候选里挑一个，或直接说出名字",
                            ttl_turns=self._state.PENDING_MAX_TURNS,
                        ),
                    )
                elif _st in ("ok", "done", "success", "opened"):
                    # 有工具真正执行成功 → 此前的等待已被处理完毕，撤下待确认。
                    self._state.clear_pending(session_id)
                tool_results.append(result)
                # S06：工具结果 Context-aware —— 超长结果截断后喂 LLM（前端 chunk 保留完整）
                llm_result = result
                if self._context is not None:
                    llm_result = self._context.clip_tool_result(result, tc.tool_name or "")
                messages.append({
                    "role": "tool",
                    "tool_call_id": payload[i]["id"],
                    "content": llm_result,
                })
                # S38：记下本轮结果，供下一轮 messages 注入（否则模型看不到内容 → 重复调）
                st.add_tool_result(llm_result[:2000])
                # S47 / B4：把这一步落盘 —— **只记已完成的**（它才代表已经发生的
                # 副作用）。崩溃后靠它判断"哪些已经做过"，避免重放时重复执行
                # （写文件、放歌这类副作用重复一次就是事故）。
                if self._journal is not None:
                    _status = ""
                    try:
                        _status = str(json.loads(result).get("status", ""))
                    except Exception:  # noqa: BLE001 — 非 JSON 结果，状态未知
                        _status = ""
                    await self._journal.step(
                        session_id, gen, tool=tc.tool_name or "",
                        status=_status, preview=llm_result,
                        # S48：记下副作用等级 —— 恢复时据此判断"能否安全重放"，
                        # 而不是一律重放（会重复放歌）或一律跳过（读文件也白做）。
                        effect=(
                            self._tools.effect_of(tc.tool_name or "")
                            if self._tools is not None
                            else ""
                        ),
                    )
                if (tc.tool_name or "") in _WRITE_TOOLS:
                    st.wrote_anything = True
                # G7：结果里若有列表（歌单/候选/歌曲），推一张结构化卡片给壳层展示，
                # 否则用户只听到一句"已经推荐了"，屏幕上什么都没有。
                await self._emit_result_card(
                    session_id, gen, tc.tool_name or "", result,
                    show_sources=show_sources and not self._should_abort(session_id, gen, session, "source_card"),
                )
                yield LLMChunk(kind="tool_result", content=result, tool_name=tc.tool_name)

            # S35：任务续跑 —— 刚创建/推进任务时，推着模型把当前步骤做掉。
            # 注入 system 提示而不是"引擎代为执行"：执行主体仍是 LLM（它才看得懂步骤语义），
            # 引擎只负责"别说完就停"。上限 2 次，避免与无进展早停相互抵消。
            # S39（F4 任务驱动 v2）：判据换成**任务状态**（事实），不再靠"猜"。
            #   - 模型刚碰过任务工具 → 推；或
            #   - 存在进行中的任务且**进度行有变化** → 推。
            # 进度不变说明它卡住了，再推只会空转烧 token（这正是旧启发式的毛病）。
            _task_line = self._task_progress_line(session_id)
            _touched_task = any(
                (tc.tool_name or "") in _TASK_PROGRESS_TOOLS for tc in tool_calls
            )
            # S39（F4 任务驱动 v2）：判据是**任务状态**（事实），不再靠"猜"：
            #   模型刚碰过任务工具 → 推；或存在进行中的任务且**进度行有变化** → 推。
            # 进度不变说明它卡住了，再推只会空转烧 token（这正是旧启发式的毛病）。
            if st.task.can_push() and (
                _touched_task or (_task_line and _task_line != st.last_task_line)
            ):
                st.last_task_line = _task_line
                _line = _task_line or "任务刚创建，尚未推进"
                # 只记进度行：每轮 messages 都会重建，注入放到重建之后（见循环开头）。
                if st.task.push(
                    f"（任务续跑）当前进度：{_line}。"
                    "请**立刻动手执行当前步骤**（调用完成该步骤所需的工具），"
                    "完成后用 task_advance 标记这一步；全部完成才调用 task_complete。"
                    "除非遇到必须由用户拍板的问题，不要只描述计划，"
                    "也不要说「接下来我会…」。"
                ):
                    vlog("agent", f"[{session_id[:8]}] 任务驱动 #{st.task.used}：{_line}")
                    continue

            # S38：写操作后的"半途而废"续跑 —— 实测整理文件夹时，模型移完一批就回
            # "PDF 已经归好了，现在把剩下的…也分一下"**然后就停了**（把计划当行动，
            # 用户看到的是一半结果）。判据是**事实**（本轮对话发生过写操作）而非关键词。
            if st.wrote_anything and assistant_text.strip() and st.write.push(
                "（继续执行）你上一条回复说了还要继续处理剩下的内容，"
                "但并没有真的动手。请**立刻调用工具把剩下的做完**"
                "（批量操作一次可以传多个文件），全部完成后再统一总结。"
            ):
                vlog(
                    "agent",
                    f"[{session_id[:8]}] 写操作后续跑 #{st.write.used}"
                    "（本轮已在改文件，产出文本即示意未收敛 → 推着做完）",
                )
                continue

            # —— 幻觉纠错续跑（问题 3 兜底，2026-09-15）——
            # 本轮**一次工具都没调**，产出的文本却声称"已经放好了/已经打开了"。
            # 典型成因：会话累积后，模型把多轮 history 里上一轮的操作记录当成当前
            # 状态（实测：用户说"播放周杰伦的，晴天"，零 tool_call 却回"已经放了"）。
            # 处理：yield reset 让外层**丢弃**这段幻觉文本（帧已发出、无法撤回，
            # 故由外层清空收集缓冲），再续跑一轮——这次模型看得到纠错提醒，
            # 有机会真正调用工具。只纠错一次，防止与无进展早停相互抵消。
            if (not tool_calls and not tool_ran and assistant_text.strip()
                    and _RE_CLAIM_DONE.search(assistant_text)
                    and st.claim.push(
                        "（纠错）你刚才的回复声称已经完成了某个操作，"
                        "但**本轮你一次工具都没有调用**，所以那件事并没有真的发生。"
                        "请判断：如果用户的要求需要动手（打开/聚焦应用、点歌、"
                        "播放控制、收藏、文件读写等），**现在就调用对应工具**；"
                        "如果本来就不需要任何操作，就照常回答，但不要声称已经做过。"
                    )):
                vlog(
                    "agent",
                    f"[{session_id[:8]}] 回复声称已完成但本轮零工具调用，"
                    "丢弃该文本并续跑一轮纠错",
                )
                yield LLMChunk(kind="reset")
                assistant_text = ""
                continue

            # 无进展早停：本轮所有工具调用都是"去重/限流/空转"，没有任何实质推进，
            # 再续问只会重复同样的调用（实测 todo update 空转 6 轮）。立即终止。
            if not turn.progress_made:
                vlog(
                    "agent",
                    f"[{session_id[:8]}] 第 {budget.rounds} 轮无实质进展（全为重复/限流），提前终止循环",
                )
                break

        # —— 收尾总结（防"假装已执行"的关键一环）——
        # 工具轮执行过但全程没产出任何口语文本（典型：工具连败 / 无进展早停）时，
        # 若直接结束，外层调用方只能凭"调没调过工具"给兜底语，历史上会撒谎说
        # "已经帮你执行了"。这里强制补一次纯文本总结：messages 已含全部工具轮
        # （assistant tool_calls + tool 结果），模型能据此如实汇报成败与下一步。
        if tool_ran and not assistant_text:
            if not self._should_abort(session_id, gen, session, "closing_summary"):
                vlog("agent", f"[{session_id[:8]}] 工具轮无文字输出，补一次收尾总结")
                try:
                    _closing = list(messages)
                    _closing.append({
                        "role": "user",
                        "content": "请用一句简短的话，如实告诉用户刚才工具执行的结果："
                                   "以**最近一次**同类工具的结果为准——成功了就说成功并转述"
                                   "（如正在播放哪首歌）；没成功才说明原因和下一步。"
                                   "禁止假装已执行成功，也不要把早前已解决的询问当成还在等确认。",
                    })
                    _loop = asyncio.get_running_loop()
                    _deadline = _loop.time() + 20.0
                    _stream = self._llm.stream_text(_closing, tools=None)
                    try:
                        while _loop.time() < _deadline:
                            _chunk = await asyncio.wait_for(
                                anext(_stream), timeout=_deadline - _loop.time()
                            )
                            if self._should_abort(session_id, gen, session, "closing_stream"):
                                return
                            if _chunk.kind == "token":
                                assistant_text += _chunk.content
                                yield _chunk
                            elif _chunk.kind == "done" and _chunk.usage:
                                budget.add_usage(_chunk.usage)  # S47：也计入本轮预算
                                if trace is not None:
                                    trace.set_usage(_chunk.usage)
                    finally:
                        try:
                            await _stream.aclose()
                        except Exception:
                            pass
                except asyncio.TimeoutError:
                    vlog("agent", f"[{session_id[:8]}] 收尾总结超时，交由外层兜底")
                except StopAsyncIteration:
                    pass
                except Exception as exc:  # noqa: BLE001 — 收尾失败不阻断对话
                    vlog("agent",
                         f"[{session_id[:8]}] 收尾总结失败: {type(exc).__name__}: {str(exc)[:120]}")

        # 多轮历史累积（B+C 改造）：
        # - **纯文字闲聊轮次** → 写 user↔assistant，维持多轮接话连贯；
        # - **工具轮次** → 同样写入，但用**精简摘要形态**（"…（本轮操作：我调用了 X，正在等用户确认）"），
        #   而不是重放完整 tool_calls / 原始 JSON。
        #
        # 旧实现把工具轮整体排除在 history 之外，理由当年是"防止把'已打开过X'
        # 当成延续闲聊信号、压低工具触发率"。但那份顾虑源于 required 强制时代，
        # 代价却是**交互式工具流程彻底断片**：点歌问"要换哪个版本"、扫码登录问
        # "扫完说一声"这类，用户回答"确认"时模型已看不到上一轮在聊什么，
        # 于是答非所问。现改为精简摘要入库——既恢复跨轮连续性，又因不含原始
        # JSON/tool_calls 结构，不会诱导模型模仿输出工具调用。
        if self._history_inject:
            h = self._history.setdefault(session_id, [])
            h.append({"role": "user", "content": text})
            if assistant_text:
                # S34：assistant 内容**必须干净**。旧实现把「（本轮操作：…）」拼进
                # assistant 消息，模型随后模仿这个格式（甚至凭空写"（本轮操作：无工具调用）"），
                # 最后被 TTS 原样念出来 —— 用户直接听到"左括号本轮操作冒号"。
                # 工具痕迹改挂 **system** 角色：模型仍知道上轮做了什么，
                # 但不会把它当成"我该说的格式"（system 不是"我说过的话"）。
                h.append({"role": "assistant", "content": assistant_text})
            if tool_events:
                h.append({
                    "role": "system",
                    "content": (
                        "上一轮工具执行情况（仅供你了解上下文，**不要模仿此格式**，"
                        f"不要在回复里附加任何操作说明）：{'；'.join(tool_events)}"
                    ),
                })
            # S45：只保留最近 12 条（约 3–4 轮）。原先留 40 条（12+ 轮）——
            # 每轮的工具执行摘要会一起进去，累积后模型形成"我已经做过很多了"的印象，
            # 反而**压低对新请求的工具触发率**（实测症状："对话积攒后媒体工具灵敏度下降"）。
            # 12 条足够接上话与续完交互式流程（点歌选版本、扫码确认），又不会积成负担。
            if len(h) > 12:
                del h[:-12]

        # 每轮对话后写入记忆（L2 情景 + L3 用户事实），跨会话可检索。
        # 工具调用痕迹前缀拼入记忆侧回复（不进 history / 不影响返回给用户的文本），
        # 保证记忆里的范例是"[调用了工具] + 转述结果"，而非"纯文字回复"。
        # 关键：仅当本轮真的调过工具（tool_ran）才写入 L2 情景记忆。
        # 纯文字轮次（尤其 LLM 偶发漏判"光说不做"的那些）不写入——
        # 否则会被固化成负面范例，经检索注入后自我强化退化（越聊越不调工具）。
        if self._memory_writer is not None and tool_ran:
            try:
                # 工具轮：把「自然语言事件」传给记忆侧（而非机器日志格式的技术痕迹），
                # 由 remember 据此写入 L2 情景记忆。这样记忆里的范例是自然语句
                # （"我帮用户打开了网易云音乐"），注入后模型可直接理解，也易被检索命中。
                # 纯文字闲聊轮（tool_ran=False）不写 L2，避免"光说不做"自我强化。
                await self._memory_writer(
                    text, assistant_text, session_id,
                    tool_trace="；".join(tool_events),
                )
            except Exception as exc:  # noqa: BLE001 — 记忆写入失败不阻断对话
                import logging

                logging.getLogger(__name__).warning("记忆写入失败: %s", exc)

        # S47 / B3：本轮结算 —— 让"花了多久、多少 token、为什么停下"在日志里
        # 一眼可见。此前除了轮数上限之外没有任何交代，跑了多久只能靠猜。
        vlog("agent", f"[{session_id[:8]}] 本轮结算：{budget.summary()}")
        # S47 / B4：回合结束（正常结束与预算耗尽**都算结束** —— 结束就是结束）。
        # 落盘之后这一轮不再是"未完成"，重放时不会被误判为需要续跑。
        if self._journal is not None:
            await self._journal.completed(
                session_id, gen, reply=assistant_text, stop_reason=budget.stop_reason
            )
        yield LLMChunk(kind="done")

    def _update_state(self, session_id: str, tool_name: str, args: dict) -> None:
        """把成功执行的工具转换为中性环境状态描述（S16：实现见 tool_events.StateNotes）。

        只记录"当前环境状态"，不记录口语化表达，因此不会诱导模型模仿"光说不做"。
        """
        self._state.record(session_id, tool_name, args)

    # S16：以下两个实现已抽离到 agent/tool_events.py；保留属性名以免调用点变动
    _describe_tool_state = staticmethod(describe_tool_state)
    _describe_tool_event = staticmethod(describe_tool_event)

    @staticmethod
    def _legacy_describe_removed() -> None:
        """占位（S16 抽离后此位置不再保留实现，见 tool_events.py）。"""


class ServiceContext:
    """Per-session isolated engines/state (Open-LLM-VTuber ServiceContext).

    Each WebSocket session gets its own clone so one session's config/state
    never leaks into another's. Clones from a shared default context cache.
    """

    def __init__(self, *, llm, memory, emotion, plugins) -> None:
        self.llm = llm
        self.memory = memory
        self.emotion = emotion
        self.plugins = plugins

    @classmethod
    def from_defaults(cls, default_context_cache: dict):
        """Clone a fresh context from the shared default cache."""
        import copy

        return cls(
            llm=default_context_cache.get("llm"),
            memory=copy.deepcopy(default_context_cache.get("memory")),
            emotion=copy.deepcopy(default_context_cache.get("emotion")),
            plugins=copy.deepcopy(default_context_cache.get("plugins")),
        )


class SubagentTool:
    """Run a sub-task with fully isolated context; parent only gets final text
    (Agentic-Desktop-Pet subagent_tool). Useful for parallel exploration /
    background research without polluting the main conversation."""

    name = "subagent"
    description = "Run an isolated sub-task and return its final result only."

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self._llm = llm

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "孤立子任务描述"},
                    },
                    "required": ["prompt"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        prompt = str(args.get("prompt", ""))
        if self._llm is None:
            return json.dumps(
                {"status": "pending", "note": "M4: 子代理 LLM 未注入", "prompt": prompt[:200]},
                ensure_ascii=False,
            )
        parts: list[str] = []
        async for chunk in self._llm.stream_text([
            {"role": "system", "content": "你是子代理，只返回最终结果，不解释过程。"},
            {"role": "user", "content": prompt},
        ]):
            if chunk.kind == "token":
                parts.append(chunk.content)
        return json.dumps({"status": "ok", "result": "".join(parts)}, ensure_ascii=False)


def build_agent_loop(
    *,
    base_url: str,
    model: str,
    api_key: str,
    temperature: float = 0.1,
    approval_gate=None,
    memory_retriever=None,
    memory_writer=None,
    memory_system=None,
    system_daemon=None,
    system_backend=None,
    persona=None,
    memory_config=None,
    netease_config=None,
    music_identity_getter=None,
    search_config=None,
    diary_getter=None,
    context_config=None,
    task_runtime=None,
    artifact_store=None,
    capability_config=None,
    avatar_getter=None,
    relationship=None,
    events=None,
    event_log=None,
    agent_config=None,
) -> AgentLoop:
    """装配生产 AgentLoop：OpenAI 兼容 LLM + 内置工具（system + 网易云）+ 可选记忆。

    供 main.py / debug_api.py 共用（配置或 key 变化后重建）。
    ``system_daemon``：SystemDaemonClient（SystemTool 用它执行真实系统操作）。
    ``memory_system``：MemorySystem 门面（检索 + 写入一体），传入时自动用作
    retriever（含 L3 事实注入）与每轮对话后的 memory_writer。
    ``persona``：PersonaConfig（提供 system_prompt / persona_prompt），缺省时回退内置默认。
    ``memory_config``：MemoryConfig（提供记忆注入前缀 memory_prompt），缺省时回退内置默认。
    ``netease_config``：NeteaseConfig，为 None 时用默认配置（enabled=True 会注册网易云工具）。
    ``search_config``（S51）：SearchConfig；``enabled`` 且**能取到 key** 时才注册联网检索工具
    —— 未配置时工具不出现在 schema 里，模型不会去调一个用不了的能力。
    """
    from yuiro.config import NeteaseConfig
    from yuiro.memory import Embedder, Retriever
    from yuiro.tools import ToolRegistry
    from yuiro.tools.netease_tool import NETEASE_TOOLS
    from yuiro.tools.system_tool import SYSTEM_TOOLS

    registry = ToolRegistry()
    # S10：系统执行后端可切换（system_backend 优先；system_daemon 兼容旧调用）
    _sys_backend = system_backend if system_backend is not None else system_daemon
    for _tool_cls in SYSTEM_TOOLS:
        registry.register(_tool_cls(backend=_sys_backend))

    # S08：Task 工具组（跨多轮目标；未注入 runtime 时降级为 pending 说明）
    if task_runtime is not None:
        from yuiro.tools.task_tool import TASK_TOOLS

        for _tool_cls in TASK_TOOLS:
            registry.register(_tool_cls(runtime=task_runtime))

    # 网易云工具组：默认注册，未安装 ncm-cli 时各工具的 requires_env 会自动隐藏。
    if netease_config is None:
        netease_config = NeteaseConfig()
    if netease_config.enabled:
        for _tool_cls in NETEASE_TOOLS:
            if _tool_cls.name == 'netease_search':
                from yuiro.tools.netease_client_search import NeteaseClientSearchTool
                registry.register(NeteaseClientSearchTool(music_identity_getter))
            elif _tool_cls.name == 'netease_recommend':
                from yuiro.tools.netease_client_search import NeteaseClientRecommendTool
                registry.register(NeteaseClientRecommendTool(music_identity_getter))
            else:
                registry.register(_tool_cls(daemon=system_daemon, config=netease_config))
        from yuiro.tools.netease_client_search import NeteaseClientFavoriteTool
        registry.register(NeteaseClientFavoriteTool(music_identity_getter))

    # S51：联网检索工具组（默认关闭 —— 隐私：查询词会发送给第三方搜索服务）。
    # 注册条件 = 配置总开关 ``enabled`` **且**能取到 key；缺一都不注册，
    # 于是工具既不出现在 schema 里、模型也不会尝试调用它。
    # ★ key 只从 OS keychain 取（``[search]`` 段刻意不含 api_key 字段）。
    if search_config is None:
        from yuiro.config import SearchConfig

        search_config = SearchConfig()
    from yuiro import keychain as _keychain
    from yuiro.logger import vlog as _vlog_search
    from yuiro.tools.web_tool import WEB_TOOLS, configure_search_key_provider

    # 注入"如何取 key"：工具模块据此判断可用性（requires_env="search-key"）。
    configure_search_key_provider(lambda: _keychain.load_search_key() or "")
    # 本函数的 LLM 在下方才创建 → 用可变盒子延迟取它（提炼是可选增强，
    # 取不到就不提炼）。避免为此调整既有的注册顺序。
    _llm_box: dict = {"llm": None}
    if search_config.enabled and (_keychain.load_search_key() or "").strip():
        for _tool_cls in WEB_TOOLS:
            registry.register(
                _tool_cls(config=search_config, llm_getter=lambda: _llm_box["llm"])
            )
        _vlog_search(
            "search",
            f"联网检索已启用（provider={search_config.provider}, top_k={search_config.top_k}）",
        )
    elif search_config.enabled:
        _vlog_search(
            "search",
            "联网检索已开启，但 keychain 里没有 key（yuiro-search/search）→ 工具不暴露给模型",
        )

    # S51：日记回顾工具（延迟绑定 —— 日记在 lifespan 里装配，晚于工具注册；
    # 传 getter 让顺序无关，且重建 AgentLoop 时不会拿到过期引用，对齐 avatar_getter）。
    if diary_getter is not None:
        from yuiro.tools.diary_tool import DIARY_TOOLS

        for _tool_cls in DIARY_TOOLS:
            registry.register(_tool_cls(store_getter=diary_getter))
    if memory_system is not None:
        retriever = memory_system
        writer = memory_system.remember
    else:
        retriever = memory_retriever or Retriever(Embedder(None), rrf_k=60)
        writer = memory_writer
    llm = OpenAIProvider(base_url, model, api_key, temperature=temperature)
    # S51：把 LLM 交给联网检索工具做"结果二次提炼"（见上方 _llm_box 说明）。
    _llm_box["llm"] = llm
    if memory_system is not None:
        # 注入 LLM 给记忆系统，用于增强 L3 事实抽取（捕获规则抓不到的隐含画像）。
        # 这是可选增强：未注入时记忆系统仍以规则抽取正常工作。
        try:
            memory_system._fact_llm = llm  # noqa: SLF001 — 装配期显式注入，简化构造签名
        except Exception:  # noqa: BLE001 — 注入失败不影响主流程
            pass
    system_prompt = getattr(persona, "system_prompt", "") if persona is not None else ""
    persona_prompt = getattr(persona, "persona_prompt", "") if persona is not None else ""
    memory_prompt = getattr(memory_config, "memory_prompt", "") if memory_config is not None else ""
    episodic_inject = getattr(memory_config, "episodic_inject", False) if memory_config is not None else False
    history_inject = getattr(memory_config, "history_inject", False) if memory_config is not None else False
    # S06：ContextEngine（Hot Context 组装 + 预算裁剪）；context_config 缺省用默认预算。
    from yuiro.context import ContextBudget, ContextEngine

    # S09：Artifact Store（工具大结果落盘 + 按需回读）
    artifacts = artifact_store
    if artifacts is None:
        from yuiro.artifact import ArtifactStore

        artifacts = ArtifactStore()
    from yuiro.tools.artifact_tool import ArtifactReadTool

    registry.register(ArtifactReadTool(store=artifacts))

    # S18：表演工具（LLM 用语义名触发一次表演；avatar 延迟绑定，避免装配顺序耦合）
    if avatar_getter is not None:
        from yuiro.tools.avatar_tool import AvatarPerformTool

        registry.register(AvatarPerformTool(avatar_getter=avatar_getter))

    context_engine = ContextEngine(
        system_prompt=system_prompt or _DEFAULT_SYSTEM_PROMPT,
        persona_prompt=persona_prompt or _DEFAULT_PERSONA_PROMPT,
        budget=ContextBudget(total=getattr(context_config, "budget_tokens", 6000)),
        tool_result_max_chars=getattr(context_config, "tool_result_max_chars", 2000),
        artifacts=artifacts,
    )
    # S11：Capability Policy（工具级权限分级；缺省 normal = 与 S10 前行为一致）
    # S19：+ CapabilityScope（参数级资源域；未声明的域不限，系统目录为硬红线）
    from yuiro.capability import Policy

    policy = Policy(
        profile=getattr(capability_config, "profile", None),
        scope=getattr(capability_config, "scope", None),
    )
    # S47 / B4：回合级 Journal。**写入**只需要 EventBus；**查询"未完成的回合"**
    # 才需要 EventLog —— 两者都可选，缺哪个就相应退化（不记录 / 不可查）。
    from yuiro.agent.turn_journal import TurnJournal
    from yuiro.agent.turn_state import TurnBudget

    journal = TurnJournal(events=events, event_log=event_log)
    # S47 / B3：回合预算（[agent] 段）。缺省用内置默认（90s / 60000 tokens / 3 轮）；
    # max_rounds 回退到 _MAX_TOOL_ROUNDS，保持"轮数上限"的既有语义不变。
    turn_budget = TurnBudget(
        max_seconds=float(getattr(agent_config, "max_seconds", 90.0) or 90.0),
        max_tokens=int(getattr(agent_config, "max_tokens", 60000) or 60000),
        max_rounds=int(
            getattr(agent_config, "max_rounds", None) or AgentLoop._MAX_TOOL_ROUNDS
        ),
    )
    return AgentLoop(
        llm, registry, retriever,
        approval_gate=approval_gate,
        memory_writer=writer,
        system_prompt=system_prompt,
        persona_prompt=persona_prompt,
        memory_prompt=memory_prompt,
        episodic_inject=episodic_inject,
        history_inject=history_inject,
        events=events,
        context_engine=context_engine,
        task_runtime=task_runtime,
        policy=policy,
        relationship=relationship,
        turn_journal=journal,
        turn_budget=turn_budget,
    )

