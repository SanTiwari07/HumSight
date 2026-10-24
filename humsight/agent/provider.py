"""LLM provider interface. A provider picks the next tool; it never computes numbers."""
from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    name: str

    def next_action(self, system: str, history: list[dict], tools: list[dict]) -> dict:
        """Return {"tool": name, "args": {...}, "rationale": str}, or {"final": True, ...}.

        history is a list of {"tool", "args", "result"} for the calls made so far
        (the last item is the result the provider has not seen yet).
        """
