"""Trace events: one per tool call, plus notes (guard, fallback)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np


def jsonable(o):
    """Recursively convert numpy types so a value can be json.dumps'd."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    return o


@dataclass
class TraceEvent:
    step: int
    kind: str                 # "tool" | "note"
    tool: str | None
    args: dict
    result: dict
    source: str               # "llm" | "rules" | "rules (fallback: <error>)" | "guard" | "system"
    rationale: str = ""
    t: float = 0.0            # seconds since job start
    runtime_ms: float = 0.0

    def to_dict(self) -> dict:
        return jsonable({"step": self.step, "kind": self.kind, "tool": self.tool, "args": self.args,
                         "result": self.result, "source": self.source, "rationale": self.rationale,
                         "t": round(self.t, 3), "runtime_ms": round(self.runtime_ms, 1)})


@dataclass
class Trace:
    events: list[TraceEvent] = field(default_factory=list)
    on_event: Callable[[dict], None] | None = None
    t0: float = field(default_factory=time.perf_counter)

    def add(self, tool: str, args: dict, result: dict, source: str, rationale: str = "",
            runtime_ms: float = 0.0) -> TraceEvent:
        ev = TraceEvent(len([e for e in self.events if e.kind == "tool"]) + 1, "tool", tool, args,
                        result, source, rationale, time.perf_counter() - self.t0, runtime_ms)
        self.events.append(ev)
        if self.on_event:
            self.on_event(ev.to_dict())
        return ev

    def note(self, message: str, source: str = "system", **extra) -> TraceEvent:
        ev = TraceEvent(len([e for e in self.events if e.kind == "tool"]), "note", None, {},
                        {"message": message, **extra}, source, message, time.perf_counter() - self.t0)
        self.events.append(ev)
        if self.on_event:
            self.on_event(ev.to_dict())
        return ev

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self.events]
