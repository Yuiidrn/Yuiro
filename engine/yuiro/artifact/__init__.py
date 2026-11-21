"""Artifact 包（S09 起）：大对象的落盘与按需回读。

spec §3.3 铁律：``Tool Result → Artifact Store → Result Summary → LLM Context``
（需要细节时 read artifact slice），避免"截断即丢弃"。

规范：``docs/spec/architecture-goal.md`` §3.3、``docs/plan/S09-artifact-store.md``。
"""
from yuiro.artifact.store import Artifact, ArtifactStore

__all__ = ["Artifact", "ArtifactStore"]
