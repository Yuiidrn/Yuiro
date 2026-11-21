"""S49 测试：每模型表现档案（``[persona.profiles]``）。

覆盖三件事：

1. 档案命中规则（按 ``model`` 字段命中 / 档案名直接写模型路径）；
2. 生效映射表的合成 —— 命中档案里**出现过的**表整表替换，没写的表沿用全局；
3. TOML 往返（三层嵌套子表 ``dump`` → ``tomllib`` → ``load``）—— 最容易被写坏的一环，
   一旦写出非法 TOML，整份配置都会读不回来。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from yuiro.config import (
    AppConfig,
    PersonaConfig,
    active_profile,
    dump_toml,
    effective_motion_slots,
    effective_persona_maps,
    load_config,
)

FEINIU = "/live2d/肥牛/feiniu.model3.json"
HIYORI = "/live2d/hiyori/Hiyori.model3.json"


def _persona(**kw) -> PersonaConfig:
    base: dict = {
        "model_path": HIYORI,
        "expression_map": {"happy": "expression2"},
        "motion_map": {"greet": "TapBody#7"},
        "performance_map": {"celebrate": "expression7, TapBody#4"},
    }
    base.update(kw)
    return PersonaConfig(**base)


# ── 命中规则 ──────────────────────────────────────────────────────────────
def test_no_profiles_keeps_global_maps() -> None:
    expr, motion, perf = effective_persona_maps(_persona())
    assert expr == {"happy": "expression2"}
    assert motion == {"greet": "TapBody#7"}
    assert perf == {"celebrate": "expression7, TapBody#4"}
    assert active_profile(_persona()) is None


def test_profile_matched_by_model_path() -> None:
    p = _persona(profiles={"hiyori": {"model": HIYORI, "expression_map": {"happy": "happy"}}})
    hit = active_profile(p)
    assert hit is not None and hit[0] == "hiyori"


def test_profile_matched_by_name_equal_path() -> None:
    """档案名直接写模型路径也认（少写一个字段）。"""
    p = _persona(profiles={HIYORI: {"expression_map": {"happy": "happy"}}})
    hit = active_profile(p)
    assert hit is not None and hit[0] == HIYORI


def test_profile_not_matching_keeps_global() -> None:
    """档案存在、但对应的是别的模型 → 不受影响（换模型不该被别人的档案带跑）。"""
    p = _persona(profiles={"feiniu": {"model": FEINIU, "expression_map": {"happy": "expression2"}}})
    assert active_profile(p) is None
    expr, _, _ = effective_persona_maps(p)
    assert expr == {"happy": "expression2"}


# ── 生效映射合成 ──────────────────────────────────────────────────────────
def test_profile_replaces_whole_table_not_merge() -> None:
    """命中档案的表是**整表替换**：旧模型的键不该残留（否则表现"半新半旧"）。"""
    p = _persona(profiles={"hiyori": {"model": HIYORI, "expression_map": {"happy": "happy"}}})
    expr, _, _ = effective_persona_maps(p)
    assert expr == {"happy": "happy"}


def test_profile_replaces_only_provided_tables() -> None:
    """只写 expression_map 的档案，动作 / 表演表仍沿用全局。"""
    p = _persona(profiles={"hiyori": {"model": HIYORI, "expression_map": {"happy": "happy"}}})
    expr, motion, perf = effective_persona_maps(p)
    assert expr == {"happy": "happy"}
    assert motion == {"greet": "TapBody#7"}
    assert perf == {"celebrate": "expression7, TapBody#4"}


def test_effective_maps_are_copies() -> None:
    """返回的必须是副本：调用方（如运行时热重载）改动不能污染配置本身。"""
    p = _persona()
    expr, _, _ = effective_persona_maps(p)
    expr["happy"] = "被改了"
    assert p.expression_map["happy"] == "expression2"


# ── 语义动作槽位（S53）─────────────────────────────────────────────────────
def test_motion_slots_follow_profile_override() -> None:
    """档案写了 motion_slots 就整表替换；没档案时用全局表。"""
    p = _persona(motion_slots={"greet": "Idle#6", "look": "Idle#8"})
    assert effective_motion_slots(p) == {"greet": "Idle#6", "look": "Idle#8"}

    p.profiles = {"hiyori": {"model": HIYORI, "motion_slots": {"celebrate": "Idle#4"}}}
    assert effective_motion_slots(p) == {"celebrate": "Idle#4"}

    # 命中别的模型的档案 → 仍用全局
    p.model_path = FEINIU
    assert effective_motion_slots(p) == {"greet": "Idle#6", "look": "Idle#8"}


# ── TOML 往返（三层嵌套子表）──────────────────────────────────────────────
def test_toml_roundtrip_with_profiles() -> None:
    cfg = AppConfig()
    cfg.persona = _persona(profiles={
        "hiyori": {
            "model": HIYORI,
            "note": "桃瀬ひより（Neuro v1 同款官方示例）",
            "expression_map": {"happy": "happy", "sad": "sad"},
            "performance_map": {"celebrate": "happy, Idle#4"},
        },
        "feiniu": {"model": FEINIU, "motion_map": {"greet": "TapBody#7"}},
    })

    text = dump_toml(cfg)
    assert "[persona.profiles.hiyori.expression_map]" in text
    assert "[persona.profiles.hiyori.performance_map]" in text
    assert "[persona.profiles.feiniu.motion_map]" in text

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text(text, encoding="utf-8")
        fresh = load_config(path)

    prof = fresh.persona.profiles["hiyori"]
    assert prof["model"] == HIYORI
    assert prof["note"] == "桃瀬ひより（Neuro v1 同款官方示例）"
    assert prof["expression_map"] == {"happy": "happy", "sad": "sad"}
    assert prof["performance_map"] == {"celebrate": "happy, Idle#4"}
    assert fresh.persona.profiles["feiniu"]["motion_map"] == {"greet": "TapBody#7"}
    # 载入后仍能正确选中档案，且生效表来自档案
    assert active_profile(fresh.persona)[0] == "hiyori"
    expr, _, _ = effective_persona_maps(fresh.persona)
    assert expr == {"happy": "happy", "sad": "sad"}


def test_toml_key_quotes_weird_names() -> None:
    """档案名含点/斜杠等字符时必须加引号，否则会写出非法 TOML。"""
    cfg = AppConfig()
    cfg.persona = _persona(profiles={"with.dot": {"model": HIYORI, "note": "x"}})
    text = dump_toml(cfg)
    assert '[persona.profiles."with.dot"]' in text
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text(text, encoding="utf-8")
        fresh = load_config(path)
    assert "with.dot" in fresh.persona.profiles
