"""Memory Consolidation（S28）：Episode → Semantic / Fact。

规范依据（``docs/spec/architecture-goal.md`` §3.10）：

```
Current Turn → Short-Term → Episode → (async) Consolidation
    → Semantic Memory → Fact Memory → Relationship Memory
```

三条红线（本模块与其调用方共同遵守）：

1. **异步、不阻塞聊天** —— 只在维护循环 / 手动触发时运行；
2. **不污染当前状态** —— 只写 L3 facts（不改会话与近期记忆），且只读快照；
3. **推断 ≠ 事实** —— 归纳来源的事实带更低置信度 + **更快衰减**，错的会自然淡出。

核心机制是**支持度**：同一个 ``(key, value)`` 需在**多条不同 episode** 中出现才升级为事实。
这避免了"每条 episode 都让 LLM 归纳一遍"必然带来的幻觉事实——
复用的是既有规则抽取器（精确、无幻觉），LLM 只作为可选的补充通道。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from yuiro.logger import vlog

# 推断事实的置信度上限：用户亲口说的（explicit / 规则命中）永远更可信
CONSOLIDATION_CONFIDENCE = 0.7

# 从 LLM 输出里提取 JSON 对象（宽松：第一个 { 到最后一个 }）
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class ConsolidationResult:
    """一次归纳的结果（可观测：扫描量 / 候选量 / 采纳量 / 跳过原因）。"""

    scanned: int = 0  # 扫描的 episode 数
    candidates: int = 0  # 候选 (key,value) 数
    accepted: int = 0  # 通过安全阀的候选数
    written: int = 0  # 实际写入的事实数
    skipped_low_support: int = 0  # 支持度不足被跳过
    skipped_existing: int = 0  # 已有更可信事实被跳过
    llm_used: bool = False
    details: list[dict] = field(default_factory=list)  # [{key, value, support}]

    def to_dict(self) -> dict:
        return asdict(self)


class Consolidator:
    """支持度驱动的归纳器（纯逻辑；IO 全由 ``MemorySystem.consolidate`` 编排）。"""

    def __init__(
        self,
        *,
        min_support: int = 3,
        confidence_cap: float = CONSOLIDATION_CONFIDENCE,
    ) -> None:
        self.min_support = max(1, int(min_support))
        self.confidence_cap = float(confidence_cap)

    # ---- 规则路径 -----------------------------------------------------------
    def collect_candidates(self, episodes: list[str], extractor) -> Counter:
        """统计 ``(key, value)`` 在多少条**不同** episode 中出现（支持度）。

        ``extractor(text) -> list[(key, value)]``：复用 MemorySystem 的规则抽取器
        （同一条 episode 内重复出现的同一对只计一次，避免同一句重复计分）。
        """
        counter: Counter = Counter()
        for text in episodes:
            seen: set[tuple[str, str]] = set()
            try:
                pairs = extractor(text)
            except Exception:  # noqa: BLE001, S112 — 单条异常不影响整体归纳
                continue
            for key, value in pairs or []:
                k, v = str(key).strip(), str(value).strip()
                if not k or not v or (k, v) in seen:
                    continue
                seen.add((k, v))
                counter[(k, v)] += 1
        return counter

    # ---- LLM 路径（可选）----------------------------------------------------
    @staticmethod
    def parse_llm_json(raw: str) -> list[tuple[str, str]]:
        """从 LLM 输出中提取 ``{"facts":[{"key":..,"value":..}]}``；失败返回 []（不猜）。"""
        text = (raw or "").strip()
        if not text:
            return []
        match = _JSON_BLOCK.search(text)
        if match is None:
            return []
        try:
            data = json.loads(match.group(0))
        except Exception:  # noqa: BLE001 — 非合法 JSON 一律放弃
            return []
        items = data.get("facts") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        out: list[tuple[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()[:40]
            value = str(item.get("value", "")).strip()[:60]
            if key and value:
                out.append((key, value))
        return out

    async def llm_candidates(self, llm, episodes: list[str]) -> list[tuple[str, str]]:
        """让 LLM 从 episode 里归纳画像（严格 JSON 契约；失败即放弃）。"""
        sample = "\n".join(f"- {t[:200]}" for t in episodes[:40])
        prompt = (
            "你在帮一个桌面助手归纳对用户的长期认识。下面是它记住的对话片段。\n"
            "只提取**反复出现、稳定**的用户画像（身份/习惯/偏好/技能/长期状态），"
            "忽略一次性事件与台词。\n"
            "严格只输出 JSON，不要解释、不要 markdown：\n"
            '{"facts":[{"key":"简短中文键（如 职业/技术栈/饮食偏好）",'
            '"value":"简短的取值"}]}\n'
            "没有可归纳的稳定画像时输出 {\"facts\":[]}。\n\n片段：\n" + sample
        )
        parts: list[str] = []
        try:
            async for chunk in llm.stream_text(
                [
                    {"role": "system", "content": "你只输出 JSON，不解释。"},
                    {"role": "user", "content": prompt},
                ]
            ):
                if getattr(chunk, "kind", "") == "token":
                    parts.append(str(getattr(chunk, "content", "")))
        except Exception as exc:  # noqa: BLE001 — LLM 不可用则退回规则路径
            vlog("memory", f"[归纳] LLM 调用失败：{exc}")
            return []
        facts = self.parse_llm_json("".join(parts))
        if facts:
            vlog("memory", f"[归纳] LLM 归纳出 {len(facts)} 条候选")
        return facts

    # ---- 安全阀 -------------------------------------------------------------
    def apply_safety(
        self,
        counter: Counter,
        existing: list[dict] | None,
        *,
        llm_facts: list[tuple[str, str]] | None = None,
    ) -> tuple[list[tuple[str, str, float]], int, int]:
        """过滤候选 → ``(accepted[(key,value,confidence)], skipped_existing, skipped_low_support)``。

        安全阀（按序）：

        1. **不降级已有**：同 key 已存在且有效置信度 ≥ 本次上限 → 跳过（保护用户亲口说的）；
        2. **支持度**：规则候选需 ≥ ``min_support``（LLM 候选视为已满足——它读的是全量片段）；
        3. **键内去重**：同一 key 只采纳支持度最高的一条（避免一次写多个冲突值）。
        """
        existing_map: dict[str, tuple[str, float]] = {}
        for f in existing or []:
            key = str(f.get("key", "")).strip()
            if not key:
                continue
            existing_map[key] = (
                str(f.get("value", "")).strip(),
                float(f.get("effective_confidence", 1.0)),
            )

        accepted: list[tuple[str, str, float]] = []
        used_keys: set[str] = set()
        skipped_existing = 0
        skipped_low_support = 0

        for (key, value), support in counter.most_common():
            if support < self.min_support:
                skipped_low_support += 1
                continue
            if not self._passes(key, value, existing_map):
                skipped_existing += 1
                continue
            if key in used_keys:
                continue
            used_keys.add(key)
            accepted.append((key, value, self.confidence_cap))

        # LLM 候选：同样过"不降级已有"与"键内去重"（支持度由 LLM 的语义判断承担）
        for key, value in llm_facts or []:
            if not self._passes(key, value, existing_map):
                skipped_existing += 1
                continue
            if key in used_keys:
                continue
            used_keys.add(key)
            accepted.append((key, value, self.confidence_cap))

        return accepted, skipped_existing, skipped_low_support

    def _passes(self, key: str, value: str, existing_map: dict[str, tuple[str, float]]) -> bool:
        """该候选是否可以写入（不降级已有 / 不重复写同值）。"""
        known = existing_map.get(key)
        if known is None:
            return True
        old_value, old_conf = known
        if old_value == value:
            return False  # 完全一样 → 无需写（避免无谓 IO）
        return old_conf < self.confidence_cap  # 已有更可信 → 不覆盖
