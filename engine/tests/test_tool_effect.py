"""S48：工具副作用等级（方案 D 的基础）。

**为什么值得测**：崩溃恢复时"这一步能不能安全重放"完全取决于这个标记。
判错的两种代价都不是小事：

- **判太松**（把 external 当 read）→ 静默**重复放歌、重复发消息**；
- **判太严**（把 read 当 external）→ 每步都问用户，**唠叨到没人看，等于没防护**。

所以两侧都要钉死：危险的工具必须被认出来，**安全的工具不能被误伤**。
"""
from __future__ import annotations

from yuiro.tools import (
    EFFECT_EXTERNAL,
    EFFECT_LOCAL,
    EFFECT_READ,
    ToolRegistry,
    infer_effect,
    resolve_effect,
)


# ---- 保守推断：只读 ---------------------------------------------------------
def test_read_tools_are_read() -> None:
    for name in (
        "file_read", "file_list", "netease_search", "netease_lyric",
        "netease_state", "artifact_read", "capability_view", "netease_recommend",
    ):
        assert infer_effect(name) == EFFECT_READ, name


# ---- 保守推断：对外产生影响 --------------------------------------------------
def test_external_tools_are_external() -> None:
    for name in (
        "netease_play", "netease_login", "netease_control", "app_open",
        "app_focus", "media_control", "avatar_perform",
    ):
        assert infer_effect(name) == EFFECT_EXTERNAL, name


# ---- 本地写入 ---------------------------------------------------------------
def test_local_tools_are_local() -> None:
    for name in ("file_write", "file_create", "file_move", "file_delete",
                 "task_create", "memory_forget"):
        assert infer_effect(name) == EFFECT_LOCAL, name


def test_unknown_defaults_to_external() -> None:
    """★ 认不出来就**保守** —— 宁可多问一句，也不要静默重复副作用。"""
    assert infer_effect("some_brand_new_tool") == EFFECT_EXTERNAL
    assert infer_effect("") == EFFECT_EXTERNAL
    assert infer_effect(None) == EFFECT_EXTERNAL  # type: ignore[arg-type]


def test_external_hint_wins_over_read_hint() -> None:
    """名字同时含两类线索时，**危险优先**（顺序即优先级）。

    否则一个叫 ``netease_play_state`` 的工具会被 "state" 线索带成只读，
    恢复时静默重放 —— 正好是我们要防的事故。
    """
    assert infer_effect("netease_play_state") == EFFECT_EXTERNAL


# ---- resolve：显式声明优先 --------------------------------------------------
def test_resolve_prefers_declared_effect() -> None:
    class _NewTool:
        name = "some_brand_new_tool"   # 推断会落到 external
        effect = "read"                # 但作者显式声明了只读

    assert resolve_effect(_NewTool()) == EFFECT_READ


def test_resolve_ignores_bogus_declaration() -> None:
    """非法声明值 → 回退到推断（而不是当成安全）。"""

    class _Bad:
        name = "file_read"
        effect = "totally-bogus"

    assert resolve_effect(_Bad()) == EFFECT_READ


def test_resolve_none_is_external() -> None:
    assert resolve_effect(None) == EFFECT_EXTERNAL


# ---- 注册表 -----------------------------------------------------------------
def test_registry_effect_of() -> None:
    reg = ToolRegistry()
    # 未注册 / 已下线的工具也要能给出（保守）答案 —— 恢复时可能遇到历史工具名
    assert reg.effect_of("???") == EFFECT_EXTERNAL
    assert reg.effect_of("file_read") == EFFECT_READ
    assert reg.get("file_read") is None  # 未注册
