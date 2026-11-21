"""ContextEngine：Hot Context 的组装器（S06）。

职责：
- 收集各来源（persona / memory / state / tools / nudges / conversation / user）
  → ``ContextItem``；
- **排序**：稳定前缀 + 变化后缀（S47，见 ``build`` 的说明）；
- 预算裁剪（mandatory 优先；超预算丢低优先级）；
- 输出 LLM messages。

★ S47 起这里是**唯一的消息组装入口**。此前存在两条路径：首轮走 ContextEngine、
工具轮走 ``AgentLoop._build_messages`` —— 后者绕过预算裁剪与组装日志，
于是"上下文由什么组成"没有单一答案（也正因如此，前缀缓存不可能稳定）。
旧方法保留仅作无 ContextEngine 时的兜底，**文案不再要求与其逐字节一致**：
顺序已按"缓存友好"重排，这是有意的行为变更，不是漂移。

所有注入**文案**（含"人设前置铁律""白熊效应"等实测调优结论）在此照搬，禁止改写。
"""
from __future__ import annotations

from yuiro.context.item import ContextBudget, ContextItem, estimate_tokens
from yuiro.logger import vlog

# 注入优先级（越大越重要；数字非对外承诺，仅用于**超预算时丢谁**的排序）
#
# ★ S47 关键区分：**优先级 ≠ 注入位置**。
# 位置由 build() 的收集顺序决定（稳定前缀 + 变化后缀，为了前缀缓存命中）；
# 优先级只决定"预算不够时先丢谁"。两者**刻意解耦** —— 缓存要求稳定段排前面，
# 而稳定段未必最重要；把两者混为一谈，正是此前排序破坏缓存的根源。
P_MANDATORY = 100  # system / 本轮用户输入
P_PERSONA = 90  # 人设
P_TASK = 80  # 当前目标（S08；跨多轮任务，仅次于人设）
P_PENDING = 78  # 等待用户确认的事项（工具抛回的问题；紧邻当前目标，高于普通事实）
P_NUDGE = 76  # 本轮推进提示（S47；强指令，不可随意丢）
P_EXPLICIT = 75  # 用户明确要求记住的事（S07；高于普通事实）
P_RELATION = 72  # 我们的关系（S26；稳定背景知识，高于普通事实）
P_FACT = 70  # L3 事实（自我认知锚点）
P_TOOL_RESULTS = 68  # 本轮工具结果（S47；模型据此继续下一步，丢了会重复调工具）
P_KNOWLEDGE = 60  # 知识库
P_STATE = 50  # 环境状态摘要
P_EPISODE = 40  # L2 情景记忆
P_HISTORY = 30  # 原始多轮 history
P_STYLE = 28  # 情绪语气微调（S47；最次要，丢了只影响口吻）


def fit_budget(
    items: list[ContextItem], budget: ContextBudget
) -> tuple[list[ContextItem], list[ContextItem]]:
    """按预算裁剪：mandatory 全保留；其余按 priority 从高到低装入。

    返回 ``(kept, dropped)``；kept 保持原始收集顺序（= 注入顺序）。
    """
    mandatory = [it for it in items if it.mandatory]
    optional = sorted(
        (it for it in items if not it.mandatory), key=lambda it: -it.priority
    )
    used = sum(it.token_cost for it in mandatory)
    keep_ids = {id(it) for it in mandatory}
    if used > budget.total:
        vlog(
            "context",
            f"mandatory 段已超预算（{used}/{budget.total} tokens），不再裁剪但需关注",
        )
    dropped: list[ContextItem] = []
    for it in optional:
        if used + it.token_cost <= budget.total:
            used += it.token_cost
            keep_ids.add(id(it))
        else:
            dropped.append(it)
    kept = [it for it in items if id(it) in keep_ids]
    return kept, dropped


class ContextEngine:
    """把各来源组装为受预算约束的 LLM 消息序列。"""

    def __init__(
        self,
        *,
        system_prompt: str,
        persona_prompt: str,
        budget: ContextBudget | None = None,
        tool_result_max_chars: int = 2000,
        artifacts=None,
    ) -> None:
        self._system_prompt = system_prompt
        self._persona_prompt = persona_prompt
        self._budget = budget or ContextBudget()
        self._tool_result_max_chars = tool_result_max_chars
        # S09：ArtifactStore | None —— 超长工具结果落盘后可按需回读（None 时退化为纯截断）
        self._artifacts = artifacts

    # ---- 唯一出口 -----------------------------------------------------------
    async def build(
        self,
        *,
        session_id: str,
        user_text: str,
        style_hint: str = "",
        memory_items: list | None = None,
        state_notes: list[str] | None = None,
        history: list[dict] | None = None,
        episodic_inject: bool = False,
        task_summary: str = "",
        relationship_summary: str = "",
        pending_note: str = "",
        tool_results: list[str] | None = None,
        nudges: list[str] | None = None,
    ) -> list[dict]:
        """组装本轮 Hot Context。

        ★ S47 排序原则：**稳定前缀 + 变化后缀**。

        为什么这件事值钱：我们用的是 OpenAI 兼容端点，**前缀缓存是自动的**，
        但只在"逐字节稳定的前缀"上命中。此前顺序是 persona → task → pending →
        relationship → memory → state → history → user，于是：
        - 一旦有 task/pending（长任务、点歌确认），relationship 及其后全部失效；
        - memory 每轮检索结果不同，它之后的所有段也跟着失效；
        - 情绪提示被拼进 persona 段，情绪一变连第 2 段都保不住。
        实测可缓存前缀因此常退回到 system 一段（约 30%）。

        现在把「每轮几乎不变」的排到最前（system / persona / relationship /
        用户画像事实），把「每轮都会变」的排到最后（检索到的知识 / 目标 /
        待确认 / 状态 / 工具结果 / 推进提示 / 情绪 / history / 本轮输入），
        让稳定前缀尽可能长 —— 这是**不需要换模型、不需要加机器**就能拿到的
        延迟收益，也是这套注入体系里杠杆最大的一条。

        另注：`tool_results` 与 `nudges`（S47）原先是 AgentLoop 侧直接 append
        到 messages 的**旁路** —— 既绕过预算，也不出现在上面的组装日志里。
        收进这里之后，"上下文到底由什么组成"才第一次有了单一答案。
        """
        splits = self._split_memory(memory_items or [])
        items: list[ContextItem] = []
        # ── ① 稳定前缀区：顺序与内容都尽量稳定 → provider 前缀缓存可命中 ──
        items += self._collect_persona()
        items += self._collect_relationship(relationship_summary)
        items += self._collect_memory_stable(splits)
        # ── ② 变化后缀区：每轮都可能变，放在缓存断裂点之后 ──
        items += self._collect_memory_dynamic(splits, episodic_inject)
        items += self._collect_task(task_summary)
        items += self._collect_pending(pending_note)
        items += self._collect_state(state_notes or [])
        items += self._collect_tool_results(tool_results or [])
        items += self._collect_nudges(nudges or [])
        items += self._collect_style(style_hint)
        items += self._collect_history(history or [])
        items += self._collect_user(user_text)

        kept, dropped = fit_budget(items, self._budget)
        used = sum(it.token_cost for it in kept)
        detail = " / ".join(f"{it.label or it.source}:{it.token_cost}" for it in kept)
        vlog(
            "context",
            f"[{session_id[:8]}] 组装 {len(kept)} 段 / 估算 {used} tokens"
            f"（预算 {self._budget.total}）｜{detail}"
            + (f"｜裁剪 {len(dropped)} 段: {[it.label for it in dropped]}" if dropped else ""),
        )
        return [self._to_message(it) for it in kept]

    # ---- 工具结果 Context-aware ---------------------------------------------
    def clip_tool_result(self, result: str, tool_name: str = "") -> str:
        """超长工具结果 → 摘要 + artifact 指引（只影响喂给 LLM 的副本）。

        - 有 ArtifactStore（S09）：完整内容落盘，返回前 N 字符 + artifact_id 读取指引；
        - 无 store：退化为 S06 的纯截断行为（兼容）。
        """
        if len(result) <= self._tool_result_max_chars:
            return result
        head = result[: self._tool_result_max_chars]
        if self._artifacts is not None:
            try:
                art = self._artifacts.put(tool_name or "tool_result", result)
                vlog(
                    "context",
                    f"工具结果存入 artifact: {tool_name or '?'} "
                    f"{len(result)} 字符 → {art.id}",
                )
                return (
                    f"{head}\n…（结果过长：完整 {len(result)} 字符已存入 artifact：{art.id}；"
                    f"本轮内可用 artifact_read 读剩余部分（artifact_id={art.id}）。"
                    "若本轮已结束或需要最新数据，请直接重新调用原工具。）"
                )
            except Exception as exc:  # noqa: BLE001 — 落盘失败退化为纯截断
                vlog("context", f"工具结果存 artifact 失败（退化为截断）：{exc}")
        clipped = (
            f"{head}\n…（结果过长已截断：原 {len(result)} 字符，"
            f"仅前 {self._tool_result_max_chars} 字符可见）"
        )
        vlog(
            "context",
            f"工具结果截断: {tool_name or '?'} {len(result)} → {self._tool_result_max_chars} 字符",
        )
        return clipped

    # ---- 各来源（文案与旧 _build_messages 逐字节一致）------------------------
    @staticmethod
    def _to_message(it: ContextItem) -> dict:
        if it.raw is not None:
            return it.raw
        return {"role": it.role, "content": it.content}

    def _collect_persona(self) -> list[ContextItem]:
        """system + persona 两段（**不含情绪提示** —— S47 已移出，见 ``_collect_style``）。

        情绪为什么必须移出：它每轮都可能变（EmotionEngine 有衰减与互动加成），
        而被拼进 persona 段意味着**第 2 段就失去缓存前缀资格**，连带它后面的
        relationship / 用户画像一起失效。情绪只是语气微调，放末尾更合适。
        """
        items = [
            ContextItem(
                source="persona",
                scope="global",
                content=self._system_prompt,
                priority=P_MANDATORY,
                mandatory=True,
                label="system",
            )
        ]
        # 分两段 system 消息：工具约束 → 人设。人设段开头强制前置工具铁律：
        # 实测 PERSONA（傲娇人设）会稀释意图识别，把"下一首"等短命令当角色台词。
        # 把约束前置到人设段首双保险；人设段放 system 而非 user suffix（实测前者 6/8、后者 4/8）。
        persona_content = (
            "【人设前置铁律】无论你此刻扮演什么性格，只要用户意图涉及系统操作"
            "（打开/聚焦软件、媒体控制、文件读写），必须直接调用对应工具，"
            "绝不能在文字里假装操作。这条约束高于人设。\n"
            + self._persona_prompt
        )
        if persona_content.strip():
            items.append(
                ContextItem(
                    source="persona",
                    scope="global",
                    content=persona_content,
                    priority=P_PERSONA,
                    mandatory=True,
                    label="persona",
                )
            )
        return items

    def _collect_style(self, style_hint: str) -> list[ContextItem]:
        """当前情绪语气提示（S47 从 persona 段独立出来）。

        独立成段并放到**变化后缀区**（靠近本轮输入），语义上也更贴切：
        它是"这一轮用什么口吻说话"，而不是"你是谁"。缓存上则让 persona
        及其前面的稳定段真正稳定下来。
        """
        if not style_hint.strip():
            return []
        return [
            ContextItem(
                source="persona",
                scope="session",
                label="style",
                priority=P_STYLE,
                content=f"（当前情绪提示：{style_hint}）",
            )
        ]

    def _collect_task(self, task_summary: str) -> list[ContextItem]:
        """当前目标（S08）：跨多轮任务的目标与进度，防止"忘了我们做到哪了"。"""
        if not task_summary.strip():
            return []
        return [
            ContextItem(
                source="task",
                scope="session",
                label="task",
                priority=P_TASK,
                content=(
                    "【当前目标】你正在帮用户完成一件事，请围绕它推进；"
                    "不要偏离目标、也不要重复已完成的步骤：\n" + task_summary
                ),
            )
        ]

    def _collect_pending(self, pending_note: str) -> list[ContextItem]:
        """等待用户确认的事项（B+C）：交互式工具（点歌选版本 / 扫码登录）抛回的
        问题。不注入的话，用户回「确认」时模型已不知道自己在等什么——这是
        「说了确认却答非所问」的直接原因。

        文案上明确两点：① 用户这句话很可能就是在回答它；② 得到答案后要继续
        把原任务做完（而不是当成新话题）。
        """
        if not pending_note.strip():
            return []
        return [
            ContextItem(
                source="pending",
                scope="session",
                label="pending",
                priority=P_PENDING,
                content=(
                    "【等待用户确认】你上一轮向用户提出了下面这个问题，正在等他回答。"
                    "如果用户这轮的话是在回应它，请据此继续完成原来那件事"
                    "（不要把话题当成全新的请求而丢掉上下文）：\n" + pending_note
                ),
            )
        ]

    def _collect_relationship(self, summary: str) -> list[ContextItem]:
        """我们的关系（S26）：背景知识，always-on（不参与检索）。

        与"对话记忆"的区别见 ``memory/relationship.py`` 模块说明；
        语气上要求"自然带入、不刻意复述"，避免变成报数字。
        """
        if not summary.strip():
            return []
        return [
            ContextItem(
                source="relationship",
                scope="global",
                label="relationship",
                priority=P_RELATION,
                content=(
                    "【我们的关系】以下是你们之间的相处背景，作为自然的亲近感来源；"
                    "可以在合适时机自然带入，但不要生硬复述这些数字：\n" + summary
                ),
            )
        ]

    @staticmethod
    def _split_memory(memory_items: list) -> dict[str, list[tuple[str, float]]]:
        """把记忆按 ``meta.kind`` 分成四类（S47）。

        拆出来的理由：**用途不同**。用户画像（explicit / facts）是稳定的背景认知，
        适合放进缓存前缀；检索来的知识 / 情景每轮都变，只能排在后缀。
        此前它们由单个方法一次性返回，位置被绑死在一起 —— 稳定段因此无法前置。
        """
        out: dict[str, list[tuple[str, float]]] = {
            "explicit": [], "facts": [], "knowledge": [], "episodes": [],
        }
        for m in memory_items or []:
            kind = m.meta.get("kind")
            score = float(getattr(m, "score", 0.0) or 0.0)
            entry = (m.text, score)
            if kind == "explicit":
                out["explicit"].append(entry)
            elif kind == "fact":
                out["facts"].append(entry)
            elif kind == "knowledge":
                out["knowledge"].append(entry)
            else:  # 无 kind → L2 情景记忆
                out["episodes"].append(entry)
        return out

    def _collect_memory_stable(self, splits: dict) -> list[ContextItem]:
        """记忆的**稳定部分**：显式记忆（S07）+ 用户画像事实。

        放在缓存前缀区：用户偏好这类事实一旦记住就长期不变，正是最该被缓存的内容。
        """
        items: list[ContextItem] = []
        explicit = splits.get("explicit") or []
        facts = splits.get("facts") or []
        # 显式记忆（S07）：用户明确要求记住的事，优先于普通事实注入
        if explicit:
            items.append(
                ContextItem(
                    source="memory",
                    scope="session",
                    label="explicit",
                    priority=P_EXPLICIT,
                    relevance=max((s for _, s in explicit), default=0.0),
                    content=(
                        "【你答应用户记住的事】以下是用户明确要求你记住的内容，"
                        "请在相关时主动提起（不要等用户提醒），也不要谎称没记住：\n"
                        + "\n".join(f"- {ln}" for ln, _ in explicit)
                    ),
                )
            )
        if facts:
            items.append(
                ContextItem(
                    source="memory",
                    scope="session",
                    label="facts",
                    priority=P_FACT,
                    relevance=max((s for _, s in facts), default=0.0),
                    content=(
                        "【用户画像·已知事实】以下是关于用户稳定、可信任的事实认知，"
                        "请据此自然贴合用户偏好，但不必特意提及：\n"
                        + "\n".join(f"- {ln}" for ln, _ in facts)
                    ),
                )
            )
        return items

    def _collect_memory_dynamic(self, splits: dict, episodic_inject: bool) -> list[ContextItem]:
        """记忆的**变化部分**：知识库 + L2 情景记忆（每轮检索结果不同）。

        事实层常驻作为「自我认知」锚点（稳定人设、不诱导不调工具）；知识层带来源；
        情境层（L2 无 kind）仅在 episodic_inject=True 时注入且标注「过往对话，仅供参考」，
        防止角色扮演被历史范例带偏。
        """
        items: list[ContextItem] = []
        knowledge = splits.get("knowledge") or []
        episodes = splits.get("episodes") or []
        if knowledge:
            items.append(
                ContextItem(
                    source="memory",
                    scope="session",
                    label="knowledge",
                    priority=P_KNOWLEDGE,
                    relevance=max((s for _, s in knowledge), default=0.0),
                    content=(
                        "【知识库】以下为相关参考资料，按需引用并注明来源：\n"
                        + "\n".join(f"- {ln}" for ln, _ in knowledge)
                    ),
                )
            )
        if episodes and episodic_inject:
            # 提示语用中性描述，不写「绝不可模仿…只用文字描述操作」这类禁令：
            # 负面指令反而会强化它想压制的行为（白熊效应）；L2 现已存为自然语言事件。
            items.append(
                ContextItem(
                    source="memory",
                    scope="session",
                    label="episodes",
                    priority=P_EPISODE,
                    relevance=max((s for _, s in episodes), default=0.0),
                    content=(
                        "【过往对话记录】以下是此前发生过的相关片段，用于了解背景脉络、"
                        "保持话题连贯。注意这是历史记录，不代表当前请求已经完成——"
                        "若用户现在提出了新的操作请求，仍需照常调用工具执行：\n"
                        + "\n".join(f"- {ln}" for ln, _ in episodes)
                    ),
                )
            )
        return items

    def _collect_tool_results(self, tool_results: list[str]) -> list[ContextItem]:
        """本轮已产生的工具结果（S38 的语义，S47 移入本引擎统一管理）。

        为什么必须收进来：它此前由 ``AgentLoop`` 直接 append 到 messages 末尾，
        是**绕过预算与组装日志的旁路** —— 上下文有相当一部分我们自己看不见。
        收进来之后，预算与观测才真正闭环。

        文案保持原样（挂在 system 角色）：模型据此继续下一步，但不会把结果
        当成"自己说过的话"来模仿。
        """
        if not tool_results:
            return []
        return [
            ContextItem(
                source="tools",
                scope="session",
                label="tool_results",
                priority=P_TOOL_RESULTS,
                content=(
                    "【本轮工具结果】以下是本轮你已经执行过的工具返回内容，"
                    "**直接基于它继续分析或执行下一步，不要重复调用同一个工具**：\n"
                    + "\n".join(f"- {t}" for t in tool_results)
                ),
            )
        ]

    def _collect_nudges(self, nudges: list[str]) -> list[ContextItem]:
        """本轮推进提示（原 ``TurnState.injections()``，S47 收进本引擎）。

        含义是"该继续动手了"这类**强指令**，所以优先级给得高（超预算时不该被丢）；
        但位置仍放在变化后缀区（它们每轮都不同，不能污染缓存前缀）。

        **优先级与位置刻意解耦** —— 这正是 S47 的核心设计。
        """
        return [
            ContextItem(
                source="nudge",
                scope="session",
                label=f"nudge{i}",
                priority=P_NUDGE,
                content=text,
            )
            for i, text in enumerate(nudges or [])
        ]

    def _collect_state(self, state_notes: list[str]) -> list[ContextItem]:
        """状态摘要：中性环境状态（已打开的应用/媒体状态等），替代原始对话重放。"""
        if not state_notes:
            return []
        return [
            ContextItem(
                source="state",
                scope="session",
                label="state",
                priority=P_STATE,
                content="当前环境状态：\n" + "\n".join(f"- {n}" for n in state_notes),
            )
        ]

    def _collect_history(self, history: list[dict]) -> list[ContextItem]:
        """多轮 history：默认关闭；开启后注入原始对话轮次（强连贯场景）。"""
        items: list[ContextItem] = []
        for msg in history:
            content = msg.get("content") or ""
            items.append(
                ContextItem(
                    source="conversation",
                    scope="session",
                    label="history",
                    priority=P_HISTORY,
                    content=content if isinstance(content, str) else "",
                    token_cost=estimate_tokens(content if isinstance(content, str) else ""),
                    role=str(msg.get("role", "user")),
                    raw=msg,
                )
            )
        return items

    def _collect_user(self, user_text: str) -> list[ContextItem]:
        return [
            ContextItem(
                source="user",
                scope="session",
                content=user_text,
                priority=P_MANDATORY,
                mandatory=True,
                label="user",
                role="user",
            )
        ]
