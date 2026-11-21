"""S42 测试：提示词必须是「原则」，不是「规则清单」。

**为什么值得专门有一条测试守着它**：
提示词最容易的退化方式，就是"每遇到一个具体问题就补一条具体规则"
（"用户说 X 就调用 Y"）。那样每次都能修好眼前那个问题，
但系统不会因此变聪明 —— 只会越补越长、越补越脆，换个说法照样漏。

历史代价：S18/S31/S38/S39/S40 一路都在"发现问题 → 补规则"，
最终 system_prompt 膨胀到 28 行、点名 12 个工具、附 6 段示例对话，
而**新场景依然靠指哪打哪**。

这条测试把"泛化"变成可执行约束：
1. 长度上限（超了说明又在堆规则）；
2. **不许出现具体工具名**（工具怎么选是 schema 的职责，不该写进提示词）；
3. **不许出现具体示例对话**（"用户：xxx → 调用 yyy"这类）。

删规则时请先想清楚：这条能不能抽象成已有四条原则之一？能就抽象，不能才加。
"""
from __future__ import annotations

from yuiro.agent import _DEFAULT_PERSONA_PROMPT, _DEFAULT_SYSTEM_PROMPT

#: 系统提示词长度上限（字符）。原则是短的；逼近这个数说明又在写说明书了。
MAX_SYSTEM_CHARS = 1100
MAX_PERSONA_CHARS = 420

#: 具体工具名一律不该出现在提示词里（由工具 schema 自描述）。
FORBIDDEN_TOOL_NAMES = (
    "app_open", "app_focus", "media_control",
    "netease_play", "netease_search", "netease_control", "netease_playlist",
    "netease_lyric", "netease_login", "netease_recommend", "netease_library",
    "file_create", "file_read", "file_write", "file_move", "file_delete",
    "transaction_rollback", "avatar_perform",
)


def test_system_prompt_is_compact() -> None:
    n = len(_DEFAULT_SYSTEM_PROMPT)
    assert n <= MAX_SYSTEM_CHARS, (
        f"系统提示词已膨胀到 {n} 字符（上限 {MAX_SYSTEM_CHARS}）。"
        "新增规则前先问：能否抽象成已有的四条原则？"
    )


def test_persona_prompt_is_compact() -> None:
    n = len(_DEFAULT_PERSONA_PROMPT)
    assert n <= MAX_PERSONA_CHARS, f"人设提示词已膨胀到 {n} 字符（上限 {MAX_PERSONA_CHARS}）"


def test_system_prompt_names_no_tools() -> None:
    """提示词不该**罗列**工具名 —— 但要给「工具之间的区分」留出空间。

    判据说的是**数量**而不是"零出现"，因为有些知识天然需要点名，例如：
    "系统媒体控制（media_control）用于你自己开着的播放器，不要用它去控桌宠放的音乐"
    —— 这是**工具之间**的边界，单个工具的 description 说不清"别用那个工具"。

    真正要防的是 S42 之前那种做法：列 12 个工具名 + 每条意图对应一个工具
    （等于把工具 schema 抄进提示词，工具一变就得改提示词）。
    单个工具怎么用，属于它自己的 description。
    """
    hits = [name for name in FORBIDDEN_TOOL_NAMES if name in _DEFAULT_SYSTEM_PROMPT]
    assert len(hits) <= 2, (
        f"提示词里出现了 {len(hits)} 个具体工具名 {hits} —— 超过 2 个通常说明又在罗列清单了。"
        "单个工具的用法请写进它的 description；只有**工具之间需要区分**时才在提示词里点名。"
    )


def test_system_prompt_has_no_scripted_dialogue() -> None:
    """不许写死"用户：X → 调用 Y"这类示例对话（提示词退化成 if-else 的标志）。"""
    for marker in ("用户：", "用户:", "Yui：", "Yui:"):
        assert marker not in _DEFAULT_SYSTEM_PROMPT, (
            f"提示词里出现了示例对话（{marker!r}）——"
            "示例越具体，覆盖的场景越窄；请抽象成原则"
        )


def test_system_prompt_keeps_the_four_principles() -> None:
    """抽象可以，但这四条原则不能被删掉（它们是泛化能力的骨架）。"""
    for principle in ("先做，再说", "如实", "别撞墙", "领域边界"):
        assert principle in _DEFAULT_SYSTEM_PROMPT, f"缺少核心原则：{principle}"
