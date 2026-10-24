"""Number guard: any number in LLM-written text must come from a tool result."""
from __future__ import annotations

import re

NUM_RE = re.compile(r"(?<![\w.])[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def collect_numbers(obj, out: list[float] | None = None) -> list[float]:
    out = [] if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_numbers(v, out)
    elif isinstance(obj, str):
        for m in NUM_RE.findall(obj):
            try:
                out.append(float(m))
            except ValueError:
                pass
    return out


def _decimals(token: str) -> int:
    t = token.lower()
    if "e" in t:
        return 6
    return len(t.split(".")[1]) if "." in t else 0


def _matches(token: str, value: float, known: list[float], rel_tol: float = 0.02) -> bool:
    n = abs(value)
    if float(token) == int(float(token)) and 0 <= n <= 10 and "." not in token:
        return True  # small integer used as a count
    d = _decimals(token)
    for k in known:
        k = abs(k)
        if k == n or round(k, d) == n:
            return True
        if k > 0 and abs(k - n) <= rel_tol * k:
            return True
        # same number expressed in other units (kHz/Hz, mm/px)
        for fac in (1000.0, 0.001):
            kk = k * fac
            if kk > 0 and abs(kk - n) <= rel_tol * kk:
                return True
    return False


def check(text: str, known_sources: list) -> list[str]:
    """Return the numeric tokens in `text` that no tool result / job input supports."""
    known: list[float] = []
    for src in known_sources:
        collect_numbers(src, known)
    bad = []
    for tok in NUM_RE.findall(text or ""):
        try:
            v = float(tok)
        except ValueError:
            continue
        if not _matches(tok, v, known):
            bad.append(tok)
    return bad
