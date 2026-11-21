"""交互级 Trace：一次用户输入 = 一个 trace（阶段时间戳 + 一行汇总）。

S01（Voice Latency Observatory）定位：**只观测、不改行为**。
所有打点均为旁路——任何异常静默吞掉，绝不影响主链路。

阶段命名（见 docs/plan/S01-voice-latency-observatory.md）：

    chat  ：turn_start → agent_start → memory_retrieve → llm_first_token
            → agent_end → reply_sent
    voice ：speech_start → speech_end → asr_final → llm_start
            → llm_first_token → llm_final → tts_start → tts_first_audio
            → playback_started → tts_end
    S52 追加：``lang_render``（本轮**首个句子**完成展示/朗读语言渲染的时刻）。
    它落在 ``tts_start`` 之后、``tts_first_audio`` 之前 —— 两者之差能直接回答
    "首句慢是因为翻译还是因为合成"。

``mark`` 记录的是"相对起点的绝对时刻（ms）"，任意两个 marks 相减即阶段耗时。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from uuid import uuid4

from yuiro.logger import vlog

# 汇总输出时的阶段展示顺序（缺失阶段自动跳过；未知阶段按记录顺序追加）
_STAGE_ORDER: tuple[str, ...] = (
    "turn_start",
    "speech_start",
    "speech_end",
    "agent_start",
    "memory_retrieve_start",
    "memory_retrieve",
    "asr_final",
    "llm_start",
    "llm_request_start",
    "llm_provider_first_token",
    "llm_first_token",
    "llm_final",
    "tts_start",
    "lang_render",  # S52：首个句子完成语言渲染（仅非中文朗读/展示时出现）
    "tts_first_audio",
    "playback_started",
    "tts_end",
    "agent_end",
    "reply_sent",
)


@dataclass
class TraceContext:
    """单次交互（一轮文字或一轮语音）的阶段计时器。"""

    session_id: str
    mode: str  # "chat" | "voice"
    trace_id: str = field(default_factory=lambda: uuid4().hex[:8])
    _t0: float = field(default_factory=time.monotonic)
    _marks: dict[str, float] = field(default_factory=dict)
    # S47：本轮 LLM 的 token 用量（provider 原样返回，含前缀缓存命中字段）。
    # 为什么值得单独记：上下文注入顺序直接决定**前缀缓存命中率**，而命中率若
    # 看不见，优化就只能靠"感觉快了"来判断 —— 那是打补丁，不是工程。
    usage: dict = field(default_factory=dict)

    def set_usage(self, usage: dict | None) -> None:
        """记录 token 用量（多次调用合并，后到者补缺项；异常静默）。"""
        try:
            if usage:
                self.usage.update(dict(usage))
        except Exception:  # noqa: BLE001 — 观测失败不阻断业务
            return

    def mark(self, stage: str) -> float:
        """记录阶段完成时刻（相对起点毫秒）。

        重复 mark 保留首个值；任何异常静默（打点绝不阻断主流程）。
        """
        try:
            dt = (time.monotonic() - self._t0) * 1000
            self._marks.setdefault(stage, round(dt, 1))
            return dt
        except Exception:  # noqa: BLE001 — 观测失败不阻断业务
            return -1.0

    def get(self, stage: str) -> float | None:
        """读取某阶段时刻（ms）；未记录返回 None。"""
        return self._marks.get(stage)

    def elapsed_ms(self) -> float:
        """E2E 耗时：所有阶段中最晚的时刻（无可比最终阶段时的兜底）。"""
        try:
            return max(self._marks.values()) if self._marks else 0.0
        except Exception:  # noqa: BLE001
            return 0.0

    def cache_line(self) -> str:
        """前缀缓存一行摘要；拿不到字段时返回空串（保持旧日志格式不变）。

        provider 的字段名不统一，这里归一成一个口径：
        DeepSeek ``prompt_cache_hit_tokens``、OpenAI ``prompt_tokens_details
        .cached_tokens``、Anthropic ``cache_read_input_tokens``。
        """
        try:
            u = self.usage or {}
            if not u:
                return ""
            total = int(u.get("prompt_tokens") or 0)
            details = u.get("prompt_tokens_details") or {}
            hit = int(
                u.get("prompt_cache_hit_tokens")
                or details.get("cached_tokens")
                or u.get("cache_read_input_tokens")
                or 0
            )
            completion = int(u.get("completion_tokens") or 0)
            pct = f"（{hit * 100 // total}%）" if total else ""
            return f"prompt={total} completion={completion} cache_hit={hit}{pct}"
        except Exception:  # noqa: BLE001
            return ""

    def summary(self) -> str:
        """一行汇总（缺失阶段不报错，顺序稳定便于人工比对）。"""
        try:
            ordered = [s for s in _STAGE_ORDER if s in self._marks]
            ordered += [s for s in self._marks if s not in _STAGE_ORDER]
            stages = " ".join(f"{s}={self._marks[s]:.0f}" for s in ordered)
            cache = self.cache_line()
            suffix = f" | {cache}" if cache else ""
            return (
                f"trace={self.trace_id} session={self.session_id[:8]} "
                f"mode={self.mode} e2e={self.elapsed_ms():.0f}ms | {stages}{suffix}"
            )
        except Exception:  # noqa: BLE001
            return f"trace={self.trace_id} summary 生成失败（观测异常）"

    def emit(self) -> None:
        """输出汇总到终端日志（stdout）与调试面板（log_ring）；只读不阻断。"""
        try:
            line = self.summary()
            vlog("trace", line)
            from yuiro.debug_api import log_ring

            log_ring.emit("INFO", "trace", line)
        except Exception:  # noqa: BLE001 — 观测失败不影响业务
            return
