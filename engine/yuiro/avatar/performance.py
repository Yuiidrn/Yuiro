"""Performance：命名表演包 + Resolver（S18）。

规范依据（``docs/spec/roadmap.md`` Era 1 Perform）：

- **不要把 LLM 输出绑到具体 Live2D motion**：语义（"该庆祝了"）经
  ``Performance Resolver`` → 依当前状态选出 expression / motion，
  换模型或换素材只改配置，Agent 与引擎代码不动；
- 第一批表演包（9 个）：Idle / Happy / Sad / Surprised / Thinking /
  Embarrassed / Excited / Angry / Sleepy —— 每个拥有 Expression / Motion / Timing；
- **不要在 Agent 里写 ``if success: celebrate``**：表演由事件或 LLM 语义触发，
  经本模块解析为具体意图（``docs/spec/阶段性总评和后续方向.md`` §32）。

本模块只描述"该表演成什么样"（语义 → 资源名的映射），
不触碰 Live2D（那是前端 adapter 的职责），也不做广播（那是 AvatarRuntime 的职责）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 各动作组的真实时长（ms），下标 = `.model3.json` 里该组 Motions 的声明顺序
# （即前端 Alt+M 预览的编号 - 1）。由 `engine/scripts/motion_scan.py` 扫描 motion3 的
# Meta.Duration 得出。
# 用途：**表演时长跟随动作时长** —— 否则动作还在播、表情已被情绪回落（观感"动作闪一下就没了"）。
#
# ⚠ 这两张表描述的是**官方 Hiyori 的那批动作文件**（肥牛的 motion 就是复用它们的，
# 只是分组不同）：肥牛把 13 个都塞进 TapBody；Hiyori 把 9 个放进 Idle、m04 单独放 TapBody。
# 换成别的模型时组名与顺序都会变 —— 查不到就回落基准时长，不会算错，
# 只是长于基准的动作会让表情提前回落（想精确就对该模型跑一遍 motion_scan.py 补表）。
TAPBODY_DURATIONS_MS: tuple[int, ...] = (
    4700,  # #0  Hiyori_m01  AngleY 46（点头）
    5930,  # #1  Hiyori_m02  AngleZ 60（大幅歪头）
    4200,  # #2  Hiyori_m03  AngleZ 39 + AngleY 31（温和歪头）
    4430,  # #3  Hiyori_m04  三轴均衡（环顾）
    8570,  # #4  Hiyori_m05  全身最大幅 + 最长
    5370,  # #5  Hiyori_m06  HandLB/RB（手部动作）
    1900,  # #6  Hiyori_m07  短促轻快
    2100,  # #7  Hiyori_m08  HandLB/RB（手部动作）
    1600,  # #8  Hiyori_m09  最短（低头）
    4170,  # #9  Hiyori_m10  抬头
    1100,  # #10 micoff      极短（微动）
    1100,  # #11 micon       = micoff 副本（数值完全相同）
    4700,  # #12 singing     = m01 副本（数值完全相同）
)

# Hiyori 官方 Idle 组的声明顺序 = m01,m02,m03,m05,m06,m07,m08,m09,m10（跳过 m04），
# 时长直接取自上面的表。肥牛没有这个组，但 Hiyori 档案会用 `Idle#4` 这类索引配表演。
IDLE_DURATIONS_MS: tuple[int, ...] = (
    4700,  # #0 m01 点头
    5930,  # #1 m02 大幅歪头
    4200,  # #2 m03 温和歪头
    8570,  # #3 m05 全身最大幅 + 最长
    5370,  # #4 m06 手部动作
    1900,  # #5 m07 短促轻快
    2100,  # #6 m08 手部动作（招手）
    1600,  # #7 m09 最短（低头）
    4170,  # #8 m10 抬头
)

# Hiyori 的 Extra 组：从肥牛迁移过来的 3 个额外动作（S49），顺序 = model3.json 声明顺序。
#   来源：肥牛的 micoff / micon / singing，迁移时剥掉了 mic1 曲线
#   （Hiyori 没有这个参数；留着就是死数据），时长不变。
EXTRA_DURATIONS_MS: tuple[int, ...] = (
    1100,  # #0 micoff   微动（原 mic-off）
    1100,  # #1 micon    微动（原 mic-on，剥掉 mic1 后与 #0 曲线相同）
    4700,  # #2 singing  "唱歌"用的长动作
)

#: 组名（小写）→ 该组时长表。查不到 → 0（调用方回落到 DEFAULT_PERFORMANCE_MS）。
MOTION_DURATIONS_BY_GROUP: dict[str, tuple[int, ...]] = {
    "tapbody": TAPBODY_DURATIONS_MS,
    "idle": IDLE_DURATIONS_MS,
    "extra": EXTRA_DURATIONS_MS,
}

# ── 语义槽位（S53）─────────────────────────────────────────────────────────
# 引擎只表达"要什么语义"，具体用哪个表情/动作由**模型清单**（壳层 manifest）解析。
# 这样内置表演包不再写死 ``TapBody#5`` 这类模型私有坐标：
#   · Hiyori / 肥牛 的字幕文件名无语义 → 由档案的 motion_slots 指定；
#   · Hotaru 的动作名自带语义（mtn_bye01_C）→ 自动推断，无需配置。
EXPRESSION_SLOTS: tuple[str, ...] = (
    "neutral", "happy", "sad", "angry", "surprised", "shy", "thinking", "playful",
)
MOTION_SLOTS: tuple[str, ...] = (
    "idle", "greet", "celebrate", "comfort", "surprise",
    "thinking", "sing", "angry", "nod", "look",
)

# 情绪 → 表情槽位（与壳层 shared/live2d.ts 的 EMOTION_TO_SLOT 保持一致）
EMOTION_EXPRESSION_SLOT: dict[str, str] = {
    "happy": "happy",
    "sad": "sad",
    "angry": "angry",
    "excited": "surprised",
    "bored": "neutral",
    "thinking": "thinking",
}

#: 一次表演的语义描述：``(情绪, 表情槽位, 动作槽位, 说明)``。
#: - 表情/动作具体值优先取 performance_map / expression_map / motion_slots；
#: - 都取不到时把**槽位**下发给壳层，由模型清单解析；
#: - 动作槽位为空 = 只演表情（说话时一直大幅挥手很吵）。
_BUILTIN_PERFORMANCES: dict[str, tuple[str, str, str, str]] = {
    "idle": ("neutral", "neutral", "", "待机（回落默认）"),
    "happy": ("happy", "happy", "", "开心（仅表情）"),
    "sad": ("sad", "sad", "", "低落（仅表情）"),
    "excited": ("excited", "surprised", "", "兴奋（仅表情）"),
    "thinking": ("thinking", "thinking", "thinking", "思考中（表情 + 微动作）"),
    "bored": ("bored", "neutral", "", "无聊（仅表情）"),
    "angry": ("angry", "angry", "", "生气（仅表情）"),
    "celebrate": ("excited", "playful", "celebrate", "庆祝（任务完成 / 用户报喜）"),
    "comfort": ("sad", "sad", "comfort", "安抚（失败 / 用户受挫）"),
    "greet": ("happy", "happy", "greet", "打招呼（用户回来）"),
    "surprise": ("excited", "surprised", "surprise", "惊讶"),
    "sing": ("happy", "playful", "sing", "唱歌"),
    "shy": ("shy", "shy", "", "害羞"),
}

#: 可点播的表演名（工具 enum / 调试台列表的唯一来源）。
BUILTIN_PERFORMANCE_NAMES: tuple[str, ...] = tuple(_BUILTIN_PERFORMANCES)

# 一次性表演的基准时长：短动作用它，长动作按真实时长自动延长（见 resolve）。
DEFAULT_PERFORMANCE_MS = 2600

#: 表演结束后额外保留的余量（动作淡出需要时间，避免表情过早回落）
_PERFORMANCE_TAIL_MS = 300


def parse_motion_spec(value: str) -> tuple[str, int | None]:
    """解析动作配置值：``"TapBody"`` → 随机；``"TapBody#7"`` → 指定第 8 个动作。

    ``#`` / ``:`` 均可作分隔（TOML 值里写 ``"TapBody#7"`` 最直观）。
    """
    raw = (value or "").strip()
    if not raw:
        return "", None
    for sep in ("#", ":"):
        if sep in raw:
            group, _, idx = raw.partition(sep)
            try:
                return group.strip(), int(idx.strip())
            except ValueError:  # 分隔符后不是数字 → 整串当组名
                return raw, None
    return raw, None


def parse_performance_spec(value: str) -> tuple[str, str]:
    """解析自由搭配值：``"表情名, 动作组#索引"`` → ``(表情名, 动作描述)``。

    ``[persona.performance_map]`` 的取值语法（见 config.py 该字段注释）：

    - 以**第一个逗号**分两段：前段 = 表情名，后段 = 动作描述（可带 ``#索引``）；
    - 缺哪一段就留空那一段：``"expression6"``（只表情）、``", TapBody#7"``（只动作）；
    - 无逗号且不含 ``#`` → 整串当表情；无逗号但含 ``#`` → 当作动作。

    返回的动作描述仍需交给 :func:`parse_motion_spec` 解析成 ``(组名, 索引)``。
    """
    raw = (value or "").strip()
    if not raw:
        return "", ""
    if "," in raw:
        expr, _, motion = raw.partition(",")
        return expr.strip(), motion.strip()
    # 无逗号：含 "#" 说明写的是动作索引（表情名不会有 #），否则按表情处理
    if "#" in raw:
        return "", raw
    return raw, ""


def motion_duration_ms(group: str, index: int | None) -> int:
    """查该动作的真实时长（未知组/未知索引/随机 → 0，调用方回退基准时长）。"""
    if index is None:
        return 0
    table = MOTION_DURATIONS_BY_GROUP.get((group or "").strip().lower())
    if table is not None and 0 <= index < len(table):
        return table[index]
    return 0


@dataclass
class Performance:
    """一次命名表演的语义描述（资源名在 resolve 时才确定）。"""

    name: str
    emotion: str = "neutral"
    expression: str = ""  # 模型表情名（来自 expression_map；空 = 交给槽位/回落默认）
    # 表情语义槽位：具体名不可用时由壳层按模型清单解析（S53）
    expression_slot: str = ""
    motion: str = ""  # 动作组名（空 = 不做动作）
    motion_index: int | None = None  # None = 该组随机
    # 动作语义槽位：具体组名不可用时由壳层按模型清单解析（S53）
    motion_slot: str = ""
    duration_ms: int = DEFAULT_PERFORMANCE_MS
    note: str = ""
    # 是否内置表演包（False = performance_map 里自定的）——
    # 调试台据此区分「内置」与「自定」，并提示前者表情由情绪映射决定。
    builtin: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "emotion": self.emotion,
            "expression": self.expression,
            "expression_slot": self.expression_slot,
            "motion": self.motion,
            "motion_index": self.motion_index,
            "motion_slot": self.motion_slot,
            "duration_ms": self.duration_ms,
            "note": self.note,
            "builtin": self.builtin,
        }


class PerformanceResolver:
    """语义表演名 → ``Performance``（配置驱动 + 缺省降级）。

    降级策略：某表演未在库中 → 回退按情绪解析（expression_map 直查），
    仍无 → 返回仅表情（可能为空串，即"保持现状"）而不抛错。
    """

    def __init__(
        self,
        *,
        expression_map: dict[str, str] | None = None,
        motion_map: dict[str, str] | None = None,
        performance_map: dict[str, str] | None = None,
        motion_slots: dict[str, str] | None = None,
    ) -> None:
        self._expression_map = dict(expression_map or {})
        self._motion_map = dict(motion_map or {})
        self._performance_map = dict(performance_map or {})
        # 槽位 → "组#索引"（per-model 档案）：给动作文件名无语义的模型用
        self._motion_slots = dict(motion_slots or {})

    # ---- 配置（人设热重载）--------------------------------------------------
    def update(
        self,
        *,
        expression_map: dict[str, str] | None = None,
        motion_map: dict[str, str] | None = None,
        performance_map: dict[str, str] | None = None,
        motion_slots: dict[str, str] | None = None,
    ) -> None:
        if expression_map is not None:
            self._expression_map = dict(expression_map)
        if motion_map is not None:
            self._motion_map = dict(motion_map)
        if performance_map is not None:
            self._performance_map = dict(performance_map)
        if motion_slots is not None:
            self._motion_slots = dict(motion_slots)

    # ---- 查询 ---------------------------------------------------------------
    def expression_for(self, emotion: str) -> str:
        return self._expression_map.get(emotion, "")

    def motion_for(self, emotion_or_group: str) -> str:
        return self._motion_map.get(emotion_or_group, "")

    def slot_motion(self, slot: str) -> tuple[str, int | None]:
        """语义槽位 → ``(组名, 索引)``；未配置返回 ``("", None)``。

        给两类调用方：
          · 工具活动联动（look / greet 等）；
          · 具体名不可用、但当前模型在档案里登记了槽位的表演。
        未登记的槽位由壳层按模型清单解析（不在这里猜）。
        """
        return parse_motion_spec(self._motion_slots.get((slot or "").strip().lower(), ""))

    def names(self) -> list[str]:
        """全部表演名 = 内置表演包 ∪ performance_map 里自定的名字。

        自定名一并列出，才能进表演库（调试台列表 / Alt+G 现场试演）。
        """
        return sorted(set(_BUILTIN_PERFORMANCES) | set(self._performance_map))

    def library(self) -> list[Performance]:
        """全部表演包（供调试台 / Performance Gallery 列表）。"""
        return [self.resolve(n) for n in self.names()]

    # ---- 解析 ---------------------------------------------------------------
    def resolve(self, name: str, *, fallback_emotion: str = "") -> Performance:
        """解析一次表演；未知 name 时按 ``fallback_emotion`` 或 ``name`` 当情绪处理。

        解析顺序：
          表情：``performance_map`` 具体值 > ``expression_map[情绪]`` > 空（下发槽位）
          动作：``performance_map`` 具体值 > ``motion_map`` > ``motion_slots[槽位]`` > 空
        两者都同时带上语义槽位；具体名不可用时由壳层按**当前模型清单**解析，
        模型没有对应资源时只演表情（绝不随机凑一个动作）。
        """
        key = (name or "").strip().lower()
        # 自由搭配：表情与动作都能独立指定 —— 这是"DIY 自己搭配"的入口
        ov_expr, ov_motion = parse_performance_spec(self._performance_map.get(key, ""))
        spec = _BUILTIN_PERFORMANCES.get(key)
        if spec is None:
            # 未知表演名：把 name 当作情绪尝试（宽松：LLM 可能直接给 "happy"）。
            # 若已在 performance_map 里登记，则表情/动作都按自由搭配走（= 自定表演）。
            emotion = fallback_emotion or key or "neutral"
            motion, index = parse_motion_spec(ov_motion)
            return Performance(
                name=key or "unknown",
                emotion=emotion,
                expression=ov_expr or self.expression_for(emotion),
                expression_slot=EMOTION_EXPRESSION_SLOT.get(emotion, ""),
                motion=motion,
                motion_index=index,
                duration_ms=self._duration_for(motion, index),
                note=("自定表演（performance_map）" if (ov_expr or ov_motion)
                      else "未登记的表演名，按情绪解析"),
                builtin=False,
            )
        emotion, expression_slot, motion_slot, note = spec
        # 表情：performance_map 优先；否则由情绪经 expression_map 推出
        expression = ov_expr or self.expression_for(emotion)
        # 动作：performance_map 优先；其次 motion_map（键可用表演名或情绪名）；
        # 再次 motion_slots（per-model 语义槽位）；都没有 → 留空，交给壳层按槽位解析
        if ov_motion:
            final_motion, final_index = parse_motion_spec(ov_motion)
        else:
            mapped = (
                self._motion_map.get(key)
                or self._motion_map.get(emotion)
                or (self._motion_slots.get(motion_slot, "") if motion_slot else "")
            )
            final_motion, final_index = parse_motion_spec(mapped)
        return Performance(
            name=key,
            emotion=emotion,
            expression=expression,
            expression_slot=expression_slot,
            motion=final_motion,
            motion_index=final_index,
            motion_slot=motion_slot,
            duration_ms=self._duration_for(final_motion, final_index),
            note=note,
            builtin=True,
        )

    @staticmethod
    def _duration_for(motion: str, motion_index: int | None) -> int:
        """表演时长 = max(基准, 动作真实时长 + 余量)。

        动作播完前不让情绪回落表情 —— 否则观感是"动到一半表情就变回去了"。
        """
        real = motion_duration_ms(motion, motion_index)
        if real <= 0:
            return DEFAULT_PERFORMANCE_MS
        return max(DEFAULT_PERFORMANCE_MS, real + _PERFORMANCE_TAIL_MS)

    def for_emotion(self, emotion: str) -> Performance:
        """情绪 → 表演（情绪名本身也是表演名时复用同一条）。"""
        e = (emotion or "").strip().lower()
        if e in _BUILTIN_PERFORMANCES:
            return self.resolve(e)
        ov_expr, ov_motion = parse_performance_spec(self._performance_map.get(e, ""))
        motion, index = parse_motion_spec(ov_motion or self._motion_map.get(e, ""))
        return Performance(
            name=e or "unknown",
            emotion=e or "neutral",
            expression=ov_expr or self.expression_for(e),
            expression_slot=EMOTION_EXPRESSION_SLOT.get(e, ""),
            motion=motion,
            motion_index=index,
            duration_ms=self._duration_for(motion, index),
            note="按情绪直接解析",
            builtin=False,
        )
