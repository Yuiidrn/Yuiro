"""S40 测试：事实抽取的"卫生"（防画像污染）。

动机来自**实测记忆库**里的两条污染记录：

- ``名字: 什么名字`` —— 用户反问「我的名字是什么名字？」被当成事实；
- ``歌曲偏好: 《谁》Live版`` —— 单首歌被当成稳定画像。

它们一旦入库就进入「自我认知」常驻注入，人设被噪声带偏。
本测试固化四道闸门：值过滤 / 规则收紧 / LLM 触发门槛 / 二次确认。
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

from yuiro.memory import MemorySystem


def _make() -> tuple[MemorySystem, str]:
    db = os.path.join(tempfile.gettempdir(), f"yuiro_fact_{uuid.uuid4().hex}.db")
    return MemorySystem(db, embedder_model="md5"), db


def _cleanup(db: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db + suffix)
        except OSError:
            pass


# ── 闸门 1：值过滤（疑问词 / 指示代词 / 测试性发言）──────────────────────
def test_question_like_value_rejected() -> None:
    """「我的名字是什么名字？」绝不能抽成 `名字: 什么名字`（实测污染）。"""
    assert MemorySystem._is_plausible_fact_value("什么名字") is False
    assert MemorySystem._is_plausible_fact_value("哪个") is False
    assert MemorySystem._is_plausible_fact_value("不知道") is False


def test_demonstrative_value_rejected() -> None:
    """「我喜欢这首歌」是当下感受，不是稳定偏好。"""
    assert MemorySystem._is_plausible_fact_value("这首歌") is False
    assert MemorySystem._is_plausible_fact_value("刚才那个") is False
    assert MemorySystem._is_plausible_fact_value("现在的游戏") is False


def test_test_like_value_rejected() -> None:
    assert MemorySystem._is_plausible_fact_value("试试看") is False
    assert MemorySystem._is_plausible_fact_value("随便") is False


def test_stable_value_accepted() -> None:
    for v in ("吃辣", "老派浪漫", "广东", "一只猫", "周杰伦"):
        assert MemorySystem._is_plausible_fact_value(v) is True, v


def test_extract_facts_skips_question_text() -> None:
    """规则抽取：真提问整句丢弃（既有行为）。"""
    ms, db = _make()
    try:
        assert ms._extract_facts("我的名字是什么名字？") == []
        assert ms._extract_facts("我喜欢吃什么？") == []
    finally:
        ms.close()
        _cleanup(db)


def test_extract_facts_filters_bad_value() -> None:
    """「我喜欢这首歌」命中规则但值被闸门拦下。"""
    ms, db = _make()
    try:
        facts = ms._extract_facts("我喜欢这首歌。")
        assert facts == [], f"指示代词值不该入库，实际：{facts}"
        # 稳定偏好仍然抽得出
        ok = ms._extract_facts("我喜欢吃火锅。")
        assert ("喜欢", "吃火锅") in ok, ok
    finally:
        ms.close()
        _cleanup(db)


# ── 闸门 2：LLM 触发门槛（去掉"长句就抽"）──────────────────────────────
def test_has_fact_signal_no_longer_triggers_on_length() -> None:
    """S40：长度不再触发 LLM 抽取 —— 否则闲聊/测试性长句都会被记。"""
    long_chat = "今天天气不错啊我们聊点别的吧随便说说而已你别当真哦"  # 27 字，无信号词
    assert MemorySystem._has_fact_signal(long_chat) is False
    assert MemorySystem._has_fact_signal("我可是土生的广东人") is True


# ── 闸门 3：二次确认（弱信号事实"说两次"才入库）────────────────────────
@pytest.mark.asyncio
async def test_weak_fact_needs_two_occurrences() -> None:
    ms, db = _make()
    try:
        # 第一次：只计数，不入库
        assert ms._needs_confirmation("喜欢", "吃辣") is True
        # 第二次：够了
        assert ms._needs_confirmation("喜欢", "吃辣") is False
        # 不同值各自计数（互不影响）
        assert ms._needs_confirmation("喜欢", "甜食") is True
    finally:
        ms.close()
        _cleanup(db)


def test_strong_fact_keys_bypass_confirmation() -> None:
    """声明式事实（名字/住址/工作/宠物）首次即入库 —— 它们几乎不可能是临时感受。"""
    ms, db = _make()
    try:
        for key in ("名字", "住址", "工作", "宠物"):
            assert ms._needs_confirmation(key, "X") is False, key
    finally:
        ms.close()
        _cleanup(db)


@pytest.mark.asyncio
async def test_gate_then_apply_weak_fact() -> None:
    """端到端：弱信号事实过确认门 —— 第一次不落库、第二次落库。

    确认门刻意放在 `_gate_facts`（**写入策略**层）而不是 `_apply_facts`
    （**写入原语**层）：后者的契约是"调用即写入"，遗忘 / 衰减 / 归纳链路都依赖它。
    第一版把门放进 `_apply_facts`，直接打挂了 6 个既有记忆测试 —— 这就是分层的价值。
    """
    ms, db = _make()
    try:
        first = ms._gate_facts([("喜欢", "吃辣")], "rule")
        assert first == [], "首次应被确认门拦下"
        assert not (await ms._facts.query(ms.facts_subject)), "库里不该有"

        second = ms._gate_facts([("喜欢", "吃辣")], "rule")
        assert second == [("喜欢", "吃辣")], "第二次应放行"
        await ms._apply_facts(second, source="rule")
        rows = await ms._facts.query(ms.facts_subject)
        assert any(r.get("value") == "吃辣" for r in rows), rows
    finally:
        ms.close()
        _cleanup(db)


@pytest.mark.asyncio
async def test_strong_fact_written_immediately() -> None:
    ms, db = _make()
    try:
        # 「名字」属于强信号键 → 首次即入库（不需要说两次）
        await ms._apply_facts([("名字", "古锦安")], source="llm")
        rows = await ms._facts.query(ms.facts_subject)
        assert any(r.get("value") == "古锦安" for r in rows), rows
    finally:
        ms.close()
        _cleanup(db)


def test_gate_bypasses_explicit_source() -> None:
    """用户明确要求记住的，一次即当（不受确认门限制）。"""
    ms, db = _make()
    try:
        assert ms._gate_facts([("喜欢", "算法竞赛")], "explicit") == [("喜欢", "算法竞赛")]
        assert ms._gate_facts([], "rule") == []
    finally:
        ms.close()
        _cleanup(db)


def test_gate_only_applies_to_rule_source() -> None:
    """确认门**只卡粗规则抽取**。

    LLM 抽取已有两重闸门（prompt 明确排除提问/临时感受 + 值过滤），
    再叠加"二次确认"会把合理画像（"我是广东人 → 籍贯"）无谓延迟
    —— 第一版就是这样打挂了 `test_llm_fact_extraction_captures_implicit_profile`。
    """
    ms, db = _make()
    try:
        assert ms._gate_facts([("籍贯", "广东")], "llm") == [("籍贯", "广东")]
        assert ms._gate_facts([("饮食偏好", "不吃辣")], "consolidation") == [
            ("饮食偏好", "不吃辣")
        ]
    finally:
        ms.close()
        _cleanup(db)
