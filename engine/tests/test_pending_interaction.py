"""S42 / P0-B 测试：结构化的「等用户回应」状态。

原先是 StateNotes 里的一个裸字符串。结构化的三个实际收益（都必须被钉住）：

1. **选项不丢** —— "让用户从歌单里挑一个"时，选项要能传到前端点选，
   而不是只剩一句"请从下面选一个"（S41 就卡在这儿）；
2. **TTL 分类型** —— 扫码登录能等久一点，选歌版本几轮不答就该失效；
3. **向后兼容** —— 老的 set_pending/pending 字符串接口必须继续可用，
   否则 agent 循环、ContextEngine、前端会一起挂。
"""
from __future__ import annotations

from yuiro.agent.tool_events import PendingInteraction, StateNotes


# ── 向后兼容（重构绝不能砸掉的地方）──────────────────────────────────
def test_legacy_set_pending_still_readable_as_text() -> None:
    st = StateNotes()
    st.set_pending("s1", "要放哪个版本？")
    assert st.pending("s1") == "要放哪个版本？"
    assert st.pending("other") == ""


def test_empty_note_is_ignored() -> None:
    st = StateNotes()
    st.set_pending("s1", "   ")
    assert st.pending("s1") == "" and st.interaction("s1") is None


def test_clear_pending() -> None:
    st = StateNotes()
    st.set_pending("s1", "问题")
    st.clear_pending("s1")
    assert st.pending("s1") == "" and st.interaction("s1") is None


# ── 结构化：选项 ──────────────────────────────────────────────────────
def test_interaction_carries_options() -> None:
    st = StateNotes()
    st.set_interaction("s1", PendingInteraction(
        question="「学习」没能唯一定位，选一个",
        kind="choice",
        options=[{"name": "24小时自习室", "encrypted_id": "A1"},
                 {"name": "六级词汇", "encrypted_id": "A2"}],
    ))
    it = st.interaction("s1")
    assert it is not None and it.kind == "choice" and it.has_options
    assert [o["name"] for o in it.options] == ["24小时自习室", "六级词汇"]
    # 文本接口仍然工作
    assert "学习" in st.pending("s1")


def test_latest_interaction_wins() -> None:
    """新问询覆盖旧问询 —— 语义由"工具成功执行"表达，不靠堆积多条待办。"""
    st = StateNotes()
    st.set_pending("s1", "旧问题")
    st.set_interaction("s1", PendingInteraction(question="新问题", kind="login"))
    assert st.pending("s1") == "新问题"
    assert st.interaction("s1").kind == "login"


# ── TTL ──────────────────────────────────────────────────────────────
def test_ttl_expires_after_limit() -> None:
    st = StateNotes()
    st.set_pending("s1", "问题")          # 默认 ttl=3
    for _ in range(3):
        st.age_pending("s1")
    assert st.pending("s1") == "问题", "第 3 轮仍在有效期内"
    st.age_pending("s1")
    assert st.pending("s1") == "", "第 4 轮应失效"


def test_ttl_is_per_interaction() -> None:
    """扫码登录要能等更久（TTL 按类型给，而不是全局一个值）。"""
    st = StateNotes()
    st.set_interaction("s1", PendingInteraction(question="请扫码", kind="login", ttl_turns=10))
    for _ in range(6):
        st.age_pending("s1")
    assert st.pending("s1") == "请扫码", "长 TTL 不该被默认值提前清掉"


def test_ttl_resets_on_new_interaction() -> None:
    st = StateNotes()
    st.set_pending("s1", "问题")
    st.age_pending("s1")
    st.set_pending("s1", "新问题")
    assert st.interaction("s1").turns == 0, "新问询应从 0 开始计龄"


def test_age_pending_is_safe_when_absent() -> None:
    st = StateNotes()
    st.age_pending("nobody")  # 不该抛异常


# ── 环境状态不受影响 ──────────────────────────────────────────────────
def test_state_notes_still_work() -> None:
    st = StateNotes()
    st.record("s1", "app_open", {"name": "记事本"})       # 已成功打开并运行：…
    st.record("s1", "app_focus", {"name": "网易云音乐"})  # 已聚焦应用：…
    assert len(st.get("s1")) == 2
    st.clear("s1")
    assert st.get("s1") == []
