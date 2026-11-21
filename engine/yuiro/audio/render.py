"""输出语言解耦（S52）：出口文本渲染器。

**要解决的问题**：此前「气泡里的文字」与「嘴里念的语音」是**同一段 LLM 原文**
（`chat:assistant` / `llm:text` 与 `TTSTaskManager.enqueue` 共用），于是
"想让她用英文念"必须让整条链路都变英文，而语音克隆的参考音频/参考转写是**单语**的，
跨语言克隆效果明显更差（实测夹生腔）。

**本模块的定位**：Agent 内部（LLM 往返、工具参数与结果、history、L1/L2/L3 记忆、
事实抽取）**恒为中文**，只在**出口**分叉成两路可独立配置的语言：

- ``render_display``：内部中文 → **展示语言**（气泡文字）；
- ``render_speak``：内部中文 → **朗读语言**（送进 TTS 的文本）。

**三条硬约束**（都是实测/架构推论，改代码前先读）：

1. **默认零回归**：目标语言等于内部语言（或 ``speak_language="auto"``）时**直接透传**，
   不产生任何 LLM 调用 —— 默认 `zh/auto` 下线上行为与引入本模块前逐字节一致；
2. **已是对应语言就透传**：先做语种判定，原文已是目标语言（如英文回复要英文朗读）
   时不发起无谓翻译（顺带解决"嗯。""OK"这类短句）；
3. **绝不静默**：转换超时/异常/空结果一律**回退原文**并打告警日志 ——
   宁可念错语言，也不能让用户听不到声音。

不 import 任何重型依赖（不需要 torch/transformers），只依赖既有 LLM 适配器。
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict

from yuiro.logger import vlog

#: 支持的目标语种。内部流通语言固定为中文（``internal_language="zh"``），
#: 它**不暴露为配置项** —— 用户明确要求"内部 Agent 循环的流通语言为中文，
#: 仅是最终回复文本与 TTS 语音可调"。
SUPPORTED_LANGUAGES = ("zh", "en", "ja")

_LANGUAGE_NAME = {"zh": "中文", "en": "英文", "ja": "日文"}

#: 翻译用系统提示词。刻意"短、硬、只输出译文"：这是一条**很窄**的转换任务，
#: 不要让模型发挥人设/解释/加引号（多余内容会被直接念出来）。
_TRANSLATE_SYSTEM = (
    "你是文本本地化引擎，把用户输入改写成{lang}，并且**只输出改写后的内容本身**。\n"
    "硬性要求：\n"
    "1. 不解释、不评论、不加引号、不加任何前后缀（不要出现「译文：」这类字样）；\n"
    "2. 保持原意、语气、口吻与情感色彩；句子数量与顺序不变；\n"
    "3. 人名、品牌、软件名、URL、代码、数字与单位保留原文，不要音译或翻译；\n"
    "4. 不要新增、删减或合并信息；出现拟声词/语气词时用{lang}里最自然的对应说法；\n"
    "5. 如果输入已经是{lang}，原样返回。"
)


def detect_language(text: str) -> str:
    """极简语种判定：返回 ``"zh" | "en" | "ja" | "unknown"``。

    判定顺序即优先级：**假名 > 谚文 > 汉字 > 拉丁**。
    假名优先是必须的 —— 日文里必然夹汉字，只有先认假名才能把日文与中文分开
    （旧实现把假名区间和汉字混在一起判成 ``zh``，导致日文朗读走错语气指令）。

    谚文（韩文）暂不支持：返回 ``unknown``，调用方据此**透传原文**而非瞎翻。
    纯标点/数字/emoji 同样返回 ``unknown``。
    """
    kana = hangul = han = latin = 0
    for ch in text:
        cp = ord(ch)
        if 0x3040 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF:  # 平假名/片假名
            kana += 1
        elif 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF:  # 谚文
            hangul += 1
        elif 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:  # 汉字
            han += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            latin += 1
    if kana:
        return "ja"
    if hangul:
        return "unknown"
    if han:
        return "zh"
    if latin:
        return "en"
    return "unknown"


def _strip_wrapping(text: str) -> str:
    """清掉模型偶发加的包裹（引号/书名号/前缀），并压缩首尾空白。

    只处理**最外层**：不动句内的引号（那可能是原文的一部分）。
    """
    out = (text or "").strip()
    for prefix in ("译文：", "译文:", "改写：", "改写:", "英文：", "日文：", "中文："):
        if out.startswith(prefix):
            out = out[len(prefix):].strip()
    for left, right in (('"', '"'), ("'", "'"), ("「", "」"), ("『", "』"), ("“", "”")):
        if len(out) >= 2 and out.startswith(left) and out.endswith(right):
            out = out[1:-1].strip()
    return out


class OutputRenderer:
    """出口文本渲染：内部中文 → 展示语言 / 朗读语言。

    契约（见模块 docstring 的三条硬约束）：

    - 目标语种 == 内部语种（``zh``）或 ``speak_language == "auto"`` → **透传，零调用**；
    - 原文判定结果已等于目标语种 → **透传，零调用**；
    - 单句转换超时/异常/空结果 → **回退原文** + 告警日志；
    - 无状态副作用、不持有 TTS 依赖，可独立单测。

    ``llm`` 为 ``None``（或未注入）时全部透传，并在首次调用时**告警一次** ——
    配置里开了非中文却不生效，必须能从日志看出来。
    """

    def __init__(
        self,
        llm=None,
        *,
        internal_language: str = "zh",
        display_language: str = "zh",
        speak_language: str = "auto",
        mode: str = "sentence",
        timeout_s: float = 6.0,
        cache_size: int = 256,
        max_concurrency: int = 2,
    ) -> None:
        self._llm = llm
        self._internal = (internal_language or "zh").lower()
        self._display = (display_language or "zh").lower()
        self._speak = (speak_language or "auto").lower()
        self._mode = (mode or "sentence").lower()
        self._timeout_s = float(timeout_s or 6.0)
        self._cache_size = max(0, int(cache_size))
        self._cache: OrderedDict[tuple[str, str], str] = OrderedDict()
        # 并发上限：翻译是"窄任务"，但一次回复可能 3~5 句同时到；限流避免打爆 LLM。
        self._sem = asyncio.Semaphore(max(1, int(max_concurrency)))
        self._warned_no_llm = False
        # 观测计数（日志/Trace 之外的低成本体检：有没有真的在翻、命中多少、失败几次）
        self.stats: dict[str, int] = {"calls": 0, "cache_hits": 0, "failures": 0, "skipped": 0}

    # ---- 配置（支持热重载） -------------------------------------------------
    def set_languages(
        self,
        *,
        display_language: str | None = None,
        speak_language: str | None = None,
        mode: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        """热重载语言设置（调试台保存配置时调用，无需重启引擎）。"""
        if display_language is not None:
            self._display = (display_language or "zh").lower()
        if speak_language is not None:
            self._speak = (speak_language or "auto").lower()
        if mode is not None:
            self._mode = (mode or "sentence").lower()
        if timeout_s is not None:
            try:
                self._timeout_s = float(timeout_s) or self._timeout_s
            except (TypeError, ValueError):
                pass

    def set_llm(self, llm) -> None:
        """热重载 LLM（换模型/provider 后重建 renderer 用）。"""
        self._llm = llm

    @property
    def display_language(self) -> str:
        return self._display

    @property
    def speak_language(self) -> str:
        return self._speak

    @property
    def mode(self) -> str:
        return self._mode

    def describe(self) -> dict:
        """当前生效设置（日志/调试端点用）。"""
        return {
            "internal": self._internal,
            "display": self._display,
            "speak": self._speak,
            "mode": self._mode,
            "enabled": self.enabled,
            "stats": dict(self.stats),
        }

    @property
    def enabled(self) -> bool:
        """是否可能发生转换（两个出口都透传时为 False = 零开销）。"""
        return (
            self._target_for("display") is not None
            or self._target_for("speak") is not None
        )

    # ---- 目标语种决策 -------------------------------------------------------
    def _target_for(self, kind: str) -> str | None:
        """返回该出口需要转换到的语种；``None`` 表示透传（零调用）。"""
        want = (self._display if kind == "display" else self._speak) or ""
        want = want.lower()
        if want in ("", "auto"):
            # auto：展示语言 = 跟随内部语言；朗读语言 = 沿用"按文本判定"的既有行为
            # （由 provider 自己按文本选语种/语气），出口层一律不转换 → 零调用。
            return None
        if want not in SUPPORTED_LANGUAGES or want == self._internal:
            return None  # 写错（如 "jp"）或与内部语言相同 → 透传，绝不让声音出问题
        return want

    @staticmethod
    def _needs_translate(text: str, target: str) -> bool:
        """原文是否真的需要转换（已是对应语种/无法判定则不需要）。"""
        detected = detect_language(text)
        if detected == "unknown":
            return False
        return detected != target

    # ---- 对外渲染 -----------------------------------------------------------
    async def render_display(self, text: str) -> str:
        """内部中文 → 展示语言（气泡文字）。"""
        return await self._render(text, "display")

    async def render_speak(self, text: str) -> str:
        """内部中文 → 朗读语言（送进 TTS）。"""
        from yuiro.audio.speech_text import speech_body

        return speech_body(await self._render(speech_body(text), "speak"))

    async def render_speak_many(self, texts: list[str]) -> list[str]:
        """批量渲染朗读文本（**保序**，每句独立并发）。

        pipeline 逐句渲染会对每个句子各起一个 task，这个入口供"一次性给一批"
        的调用方使用（如整段模式下的分句结果、调试台试听）。
        """
        if not texts:
            return []
        return list(await asyncio.gather(*(self._render(t, "speak") for t in texts)))

    # ---- 内部实现 -----------------------------------------------------------
    async def _render(self, text: str, kind: str) -> str:
        raw = text or ""
        if not raw.strip():
            return raw
        target = self._target_for(kind)
        if target is None or not self._needs_translate(raw, target):
            self.stats["skipped"] += 1
            return raw
        if self._llm is None:
            if not self._warned_no_llm:
                self._warned_no_llm = True
                vlog("language",
                     f"⚠ 已设 {kind} 语言为 {target}，但未注入 LLM —— 输出语言解耦不生效（透传原文）")
            return raw

        key = (target, raw)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            self.stats["cache_hits"] += 1
            return cached

        self.stats["calls"] += 1
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        try:
            async with self._sem:
                out = await asyncio.wait_for(
                    self._translate_once(raw, target), timeout=self._timeout_s
                )
        except TimeoutError:
            # 3.11+ 起 asyncio.wait_for 抛的是内建 TimeoutError（无需 asyncio 别名）
            self.stats["failures"] += 1
            vlog("language",
                 f"⚠ {kind} 转换超时（{self._timeout_s}s，{self._internal}→{target}），回退原文："
                 f"{raw[:60]!r}")
            return raw
        except Exception as exc:  # noqa: BLE001 — 转换失败绝不能阻断出声
            self.stats["failures"] += 1
            vlog("language",
                 f"⚠ {kind} 转换失败（{type(exc).__name__}: {str(exc)[:120]}），回退原文："
                 f"{raw[:60]!r}")
            return raw

        out = _strip_wrapping(out)
        if not out:
            self.stats["failures"] += 1
            vlog("language", f"⚠ {kind} 转换结果为空，回退原文：{raw[:60]!r}")
            return raw

        self._remember(key, out)
        vlog("language",
             f"{kind} 渲染 {self._internal}→{target}（{int((loop.time() - t0) * 1000)}ms）："
             f"{raw[:60]!r} → {out[:60]!r}")
        return out

    async def _translate_once(self, text: str, target: str) -> str:
        """单次转换：直接复用既有 LLM 适配器（无工具、temperature=0）。"""
        lang_name = _LANGUAGE_NAME.get(target, target)
        messages = [
            {"role": "system", "content": _TRANSLATE_SYSTEM.format(lang=lang_name)},
            {"role": "user", "content": text},
        ]
        parts: list[str] = []
        stream = self._llm.stream_text(messages, temperature=0.0)
        try:
            async for chunk in stream:
                if chunk.kind == "token":
                    parts.append(chunk.content)
        finally:
            # 生成器被取消（超时/打断）时必须关底层流，否则 httpx 子流残留。
            # 关闭失败**刻意静默**：这条路径本身就在异常/取消中，再抛只会掩盖原因；
            # 真正的失败由上层的 calls/failures 计数与告警日志体现。
            try:
                await stream.aclose()
            except Exception:  # noqa: BLE001,S110
                pass
        return "".join(parts).strip()

    def _remember(self, key: tuple[str, str], value: str) -> None:
        """LRU 写入（短句重复率高，命中即零成本）。"""
        if self._cache_size <= 0:
            return
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
