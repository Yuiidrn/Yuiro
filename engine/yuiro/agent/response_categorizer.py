"""Parse LLM output: strip <think>/<reasoning> tags from TTS speech (AIRI-style)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CategorizedResponse:
    speech: str  # text outside tags → goes to TTS
    reasoning: str  # filtered thought/OS
    raw: str


def categorize_response(response: str) -> CategorizedResponse:
    """Extract complete <tag>...</tag> blocks as reasoning; rest is speech.

    Uses a small state machine; rehype/Hast optional for robustness.
    """
    segments: list[str] = []
    reasoning: list[str] = []
    pos = 0
    n = len(response)
    while pos < n:
        if response[pos] == "<":
            end = response.find(">", pos)
            if end == -1:
                # Dangling '<' mark with no closing '>': keep remainder as speech.
                segments.append(response[pos:])
                break
            tag = response[pos + 1 : end].strip()
            if not tag or tag.startswith("/"):
                pos = end + 1
                continue
            close = response.find(f"</{tag}>", end)
            if close == -1:
                # Unclosed tag: keep the opening '<...>' as literal speech.
                segments.append(response[end + 1 :])
                pos = end + 1
                continue
            reasoning.append(response[end + 1 : close])
            pos = close + len(f"</{tag}>")
        else:
            nxt = response.find("<", pos)
            if nxt == -1:
                segments.append(response[pos:])
                break
            segments.append(response[pos:nxt])
            pos = nxt
    return CategorizedResponse(
        speech="".join(segments),
        reasoning="\n".join(reasoning),
        raw=response,
    )
