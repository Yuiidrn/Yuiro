"""双角色配置存储：复用 AppConfig，运行时切换由 composition root 注入。"""
from __future__ import annotations

import copy
import json
import tomllib
from dataclasses import asdict
from pathlib import Path

from yuiro.config import AppConfig, PersonaConfig, _emit_table

ROLE_SECTIONS = ("llm", "tts", "persona", "language", "agent", "context", "memory")
IDS = ("hiyori", "hotaru")


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


class CharacterStore:
    def __init__(self, config_path: Path = Path("config.toml")) -> None:
        self.config_path = config_path
        self.root = config_path.parent / "characters"

    def active(self) -> str:
        path = self.root / "active.json"
        if not path.exists():
            return ""
        value = json.loads(path.read_text(encoding="utf-8"))["id"]
        self.check_id(value)
        return value

    @staticmethod
    def check_id(value: str) -> None:
        if value not in IDS:
            raise ValueError("未知角色；当前仅支持 hiyori / hotaru")

    def commit(self, role: str) -> None:
        self.check_id(role)
        _atomic(self.root / "active.json", json.dumps({"id": role}))

    def save(self, role: str, cfg: AppConfig) -> None:
        self.check_id(role)
        lines = ["# 独立角色卡；凭证使用公共 keychain，不在此保存。"]
        for section in ROLE_SECTIONS:
            values = asdict(getattr(cfg, section))
            if section == "tts":
                values.pop("siliconflow_key", None)
            _emit_table(lines, section, values)
        _atomic(self.root / f"{role}.toml", "\n".join(lines) + "\n")

    def resolve(self, role: str, shared: AppConfig) -> AppConfig:
        self.check_id(role)
        data = tomllib.loads((self.root / f"{role}.toml").read_text(encoding="utf-8"))
        if set(data) - set(ROLE_SECTIONS):
            raise ValueError("角色卡不能覆盖设备、权限或公共服务配置")
        cfg = copy.deepcopy(shared)
        for section in ROLE_SECTIONS:
            if section not in data or not isinstance(data[section], dict):
                raise ValueError(f"角色卡缺少 {section}")
            # 整段替换，禁止空映射继承上一角色的 Live2D 资源。
            current = getattr(cfg, section)
            unknown = set(data[section]) - set(asdict(current))
            if unknown:
                raise ValueError(f"角色卡 {section} 含未知字段")
            values = dict(data[section])
            if section == "tts":
                # 兼容旧公共配置里的凭证，但角色卡不能覆盖公共凭证。
                values["siliconflow_key"] = shared.tts.siliconflow_key
            setattr(cfg, section, type(current)(**values))
        cfg._character_id = role
        cfg._config_path = self.config_path
        return cfg

    def ensure(self, cfg: AppConfig) -> str:
        """惰性迁移，旧配置只归给当前角色，另一角色不继承人设与表演。"""
        original = "hotaru" if "Hotaru Shiomi" in cfg.persona.model_path else "hiyori"
        for role in IDS:
            if (self.root / f"{role}.toml").exists():
                continue
            seed = copy.deepcopy(cfg)
            if role != original:
                seed.persona = PersonaConfig()
                seed.persona.name = "Hiyori" if role == "hiyori" else "Hotaru Shiomi"
                seed.persona.display_name = seed.persona.name
                seed.persona.persona_prompt = (
                    f"你是 {seed.persona.name}，温柔自然地用中文与用户交谈。"
                    "保持回答简洁；未配置的角色背景不要编造。"
                )
                seed.persona.profiles = {}
                if role == "hotaru":
                    base = Path(__file__).resolve().parents[2] / "shell/src/renderer/public/live2d"
                    choices = sorted((base / "Hotaru Shiomi").rglob("*.model3.json"))
                    casual = [p for p in choices if "casual" in str(p).lower()]
                    if not casual:
                        raise ValueError("未找到 Hotaru casual model3，不能生成角色卡")
                    seed.persona.model_path = "/live2d/" + casual[0].relative_to(base).as_posix()
                    seed.persona.expression_map = {}
                    seed.persona.motion_map = {}
                    seed.persona.performance_map = {}
                    seed.persona.motion_slots = {}
                seed.tts.provider = "edge-tts"
                seed.persona.voice = "zh-CN-XiaoyiNeural"
                seed.tts.siliconflow_reference_wav = ""
                seed.tts.siliconflow_reference_text = ""
                seed.memory.db_path = f"data/characters/{role}/memory.db"
            self.save(role, seed)
        active = self.active() or original
        if not self.active():
            self.commit(active)
        return active

    def view(self) -> dict:
        return {"active_id": self.active(), "items": [
            {"id": role, "label": "Hiyori" if role == "hiyori" else "Hotaru Shiomi"}
            for role in IDS
        ], "role_sections": list(ROLE_SECTIONS)}


def apply_active(cfg: AppConfig, path: Path) -> AppConfig:
    store = CharacterStore(path)
    role = store.active()
    return store.resolve(role, cfg) if role else cfg
