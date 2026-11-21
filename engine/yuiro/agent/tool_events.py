"""工具事件与状态摘要（S16：从 AgentLoop 抽离）。

两块产出，语义严格区分：

- ``describe_tool_state``：产出「当前环境状态」（注入给模型看环境，中性描述，
  不诱导"光说不做"）——由 ``StateNotes`` 按会话维护（同类型覆盖而非追加）；
- ``describe_tool_event``：产出「刚才发生了什么」（过去式叙述，存档进 L2 记忆）。

抽离自 ``agent/__init__.py``（原 ``_update_state`` / ``_describe_tool_state`` /
``_describe_tool_event``），**行为逐字保留**。
"""
from __future__ import annotations

from dataclasses import dataclass, field


def describe_tool_state(tool_name: str, args: dict) -> str | None:
    """将工具调用映射为中性状态摘要文本；不支持的工具返回 None。"""
    if tool_name == "app_open":
        name = args.get("name") or args.get("app")
        if name:
            return f"已成功打开并运行：{name}（窗口已启动，如要切到前台再用 app_focus）"
    elif tool_name == "app_focus":
        name = args.get("name") or args.get("app")
        if name:
            return f"已聚焦应用：{name}"
    elif tool_name == "media_control":
        action = args.get("action", "")
        verb = {
            "next": "下一首", "prev": "上一首", "play": "播放",
            "pause": "暂停", "stop": "停止", "resume": "继续",
        }.get(action, action)
        return f"媒体状态：{verb}" if verb else "媒体状态：已操作"
    elif tool_name in ("file_create", "file_read", "file_write"):
        path = args.get("path") or args.get("filename") or ""
        return f"文件操作：{path}" if path else "文件操作：已执行"
    return None


def describe_tool_event(tool_name: str, args: dict, status: str) -> str | None:
    """把一次工具调用转成一句自然语言事件，供 L2 情景记忆与多轮历史摘要使用。

    与 ``describe_tool_state`` 的区别：那个产出「当前环境状态」（注入给模型看环境），
    这个产出「刚才发生了什么」（存档进记忆 / 写进多轮历史），是过去式的事件叙述。

    三态措辞：成功 / 失败 / **等待用户确认**（need_choice、pending）。
    后者对「点歌版本选择、扫码登录」这类交互式流程尤其关键——它让下一轮的模型
    知道"我上一轮抛了个问题在等用户回答"，而不是断片。

    例如：app_open 成功 → "我帮用户打开了网易云音乐"
          app_open 失败 → "我尝试打开网易云音乐，但没成功"
    """
    name = args.get("name") or args.get("app") or ""
    waiting = status in ("need_choice", "pending")
    ok = status not in ("error", "skipped", "need_choice", "pending")
    if tool_name == "app_open":
        if not name:
            return None
        if waiting:
            return f"我打算打开{name}，但要先等用户确认"
        return f"我帮用户打开了{name}" if ok else f"我尝试打开{name}，但没成功"
    if tool_name == "app_focus":
        if not name:
            return None
        if waiting:
            return f"我准备把{name}切到前台，但要先等用户确认"
        return f"我把{name}切到了前台" if ok else f"我想把{name}切到前台，但没找到它的窗口"
    if tool_name == "media_control":
        # 兼容两套 action 命名：工具 schema 用 volume_up/down，预路由用 vol_up/down。
        action = str(args.get("action", ""))
        verb = {
            "next": "切到下一首", "prev": "切到上一首", "play": "开始播放",
            "play_pause": "切换了播放状态", "pause": "暂停播放", "stop": "停止播放",
            "resume": "继续播放", "mute": "静音",
            "vol_up": "调大了音量", "volume_up": "调大了音量",
            "vol_down": "调小了音量", "volume_down": "调小了音量",
        }.get(action, "")
        if not verb:
            if waiting:
                return "我操作媒体时遇到了需要用户确认的情况"
            return "我帮用户操作了媒体播放" if ok else "媒体操作没成功"
        if waiting:
            return f"我本想{verb}，但要先等用户确认"
        return f"我帮用户{verb}" if ok else f"我本想{verb}，但没成功"
    if tool_name in ("file_create", "file_read", "file_write"):
        path = args.get("path") or args.get("filename") or ""
        verb = {"file_create": "新建", "file_read": "读取", "file_write": "写入"}.get(
            tool_name, "操作"
        )
        if not path:
            return f"我帮用户执行了文件{verb}操作" if ok else f"文件{verb}操作失败了"
        return f"我帮用户{verb}了文件 {path}" if ok else f"{verb}文件 {path} 时出错了"
    # 通用兜底：未单独映射的工具（如 netease_play / task / avatar）也产出可读事件。
    # 否则这些工具轮会在多轮历史与记忆里「消失」，导致跨轮接不上话（点歌即此例）。
    _kv = "，".join(f"{k}={v}" for k, v in list(args.items())[:2])
    _what = f"我调用了 {tool_name}" + (f"（{_kv}）" if _kv else "")
    if waiting:
        return f"{_what}，正在等用户确认"
    if status in ("error", "skipped"):
        return f"{_what}，但没成功"
    return f"{_what}，已完成"


@dataclass
class PendingInteraction:
    """一次「正在等用户回应」的结构化状态（S42 / P0-B）。

    原先它只是一个裸字符串。为什么值得结构化：

    1. **选项要能被点** —— 歌单候选 / 点歌版本这类"让用户挑"的场景，引擎其实
       知道有哪些选项、每个选项的 id 是什么，但字符串里只能塞一句"请从下面选一个"。
       前端拿不到可点的东西，只能让模型把候选复述一遍（S41 就卡在这儿）。
    2. **TTL 要能按类型区分** —— "扫码登录"可能等几分钟仍有效，"选歌版本"
       几轮不答就该失效；单槽 + 固定轮数做不到这件事。
    3. **判据要能测** —— 原来"还有没有在等"等价于 `bool(str)`，没有可测语义。
    """

    #: 抛给用户的问题（原先的 note 文本）
    question: str
    #: 交互类型：confirm（是/否）/ choice（多选一）/ login（扫码）…
    kind: str = "confirm"
    #: 可选项（保持原样透传，供前端渲染成可点条目 / 模型复述）
    options: list[dict] = field(default_factory=list)
    #: 期望用户提供什么（自由文本时的提示，如"直接说个歌名"）
    expected: str = ""
    #: 已存活轮数（由 age_pending 维护）
    turns: int = 0
    #: 存活上限（轮）；超过即失效，避免陈年问询一直挂在上下文里
    ttl_turns: int = 3

    @property
    def has_options(self) -> bool:
        return bool(self.options)


class StateNotes:
    """按会话维护的「当前环境状态」+「等待用户回应的事项」。

    两块语义严格区分：
    - 环境状态（``record``）：中性描述"现在是什么状态"，同类型覆盖而非追加；
    - 待回应事项（``set_pending`` / ``set_interaction``）：工具抛回一个问题
      （need_choice / pending）后登记"我正等用户回答什么"，下一轮作为高优先级
      上下文注入，解决「点歌选版本 / 扫码登录」这类交互式流程的跨轮断片。
    """

    # 待回应事项的默认存活轮数：超过即失效，避免陈年问询一直挂在上下文里。
    PENDING_MAX_TURNS = 3

    def __init__(self) -> None:
        self._notes: dict[str, list[str]] = {}
        # session_id -> PendingInteraction（S42/P0-B：由裸字符串升级为结构化）
        self._pending: dict[str, PendingInteraction] = {}

    def record(self, session_id: str, tool_name: str, args: dict) -> None:
        """记录一次成功工具调用的状态（同类型前缀去重后追加）。"""
        note = describe_tool_state(tool_name, args)
        if note is None:
            return
        notes = self._notes.setdefault(session_id, [])
        prefix = note.split("：", 1)[0]
        self._notes[session_id] = [
            n for n in notes if not n.startswith(prefix + "：")
        ] + [note]

    def get(self, session_id: str) -> list[str]:
        """该会话的状态摘要（dict 语义兼容：不存在返回空列表）。"""
        return self._notes.get(session_id, [])

    def set(self, session_id: str, notes: list[str]) -> None:
        """直接设置该会话的状态集合（覆盖式；供测试注入与状态恢复）。"""
        self._notes[session_id] = list(notes)

    def clear(self, session_id: str) -> None:
        self._notes.pop(session_id, None)
        self._pending.pop(session_id, None)

    def clear_all(self) -> int:
        """清空**全部会话**的状态与待回应事项（"清空全部记忆"联动，S50）。

        返回清掉的会话数（供响应反馈）。
        """
        n = len(self._notes)
        self._notes.clear()
        self._pending.clear()
        return n

    # ---- 待回应事项 ---------------------------------------------------------
    def set_interaction(self, session_id: str, interaction: PendingInteraction) -> None:
        """登记一次「等用户回应」（结构化入口）。

        同一会话只保留最新一条 —— 新问询覆盖旧问询（用户已回答上一个问题的
        语义由"工具成功执行"来表达，而不是靠堆积多条待办）。
        """
        if not (interaction.question or "").strip():
            return
        interaction.turns = 0
        self._pending[session_id] = interaction

    def set_pending(self, session_id: str, note: str) -> None:
        """纯文本登记（兼容入口，等价于 kind=confirm 且无选项）。"""
        self.set_interaction(session_id, PendingInteraction(question=note))

    def interaction(self, session_id: str) -> PendingInteraction | None:
        """读取结构化待回应状态（无则 None）—— 前端/引擎用它拿可选项。"""
        return self._pending.get(session_id)

    def pending(self, session_id: str) -> str:
        """读取待回应问题的文本（无则空串）。"""
        item = self._pending.get(session_id)
        return item.question if item else ""

    def clear_pending(self, session_id: str) -> None:
        """清除待回应事项（用户已确认并执行成功 / 显式取消）。"""
        self._pending.pop(session_id, None)

    def age_pending(self, session_id: str) -> None:
        """每轮调用一次：累计轮数，超过该事项自己的 TTL 则失效。"""
        item = self._pending.get(session_id)
        if not item:
            return
        item.turns += 1
        if item.turns > max(1, item.ttl_turns):
            self._pending.pop(session_id, None)

    def snapshot(self) -> dict[str, int]:
        return {sid: len(notes) for sid, notes in self._notes.items()}
