"""Yuiro engine — skill system.

Brings in Agentic-Desktop-Pet's two-layer skill loading and deskpet's
SKILL.md + script.py model with hot reload:

- Layer 1: name + description in system prompt.
- Layer 2: full skill body lazy-loaded only when the run_skill tool is invoked
           (keeps context lean).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SkillManifest:
    name: str
    description: str
    version: str = "0.1.0"
    author: str = ""
    requires_script: bool = False
    allowed_tools: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


@dataclass
class Skill:
    manifest: SkillManifest
    body_md: str = ""           # full body; lazy-loaded
    script_path: str | None = None

    @property
    def prompt_entry(self) -> str:
        """Layer-1 metadata for the system prompt."""
        ...


class SkillLoader:
    """Scans built-in/ + user/ dirs for SKILL.md (YAML frontmatter).

    Two-layer: metadata always available; full body loaded on demand.
    Hot reload via watchdog on user dir with debounce (deskpet).
    """

    def __init__(self, builtin_dir: str, user_dir: str) -> None:
        ...

    def list_metadata(self) -> list[SkillManifest]:  # pragma: no cover - stub
        ...

    def load_body(self, name: str) -> Skill:  # pragma: no cover - stub
        """Load full body + optional script.py for a skill."""
        ...

    async def invoke_script(self, name: str, args: dict) -> str:  # pragma: no cover - stub
        """Run skill's sibling script.py in a restricted subprocess (deskpet)."""
        ...
