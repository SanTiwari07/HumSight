"""The bounded agent loop: <= 10 tool calls, exactly one terminal tool, rules fallback."""
from __future__ import annotations

import os
import time

from .. import config
from . import guard
from .policy_rules import RulesProvider
from .state import JobState
from .tools import TERMINAL, TOOLS, known_numbers, run_tool

SYSTEM_PROMPT = """You are a vibration-analysis agent controlling measurement tools. You never compute or
invent numbers; every number you mention must come from a tool result in this conversation.
Goal: decide whether the clip shows a localized mechanical vibration fault, isolate its
frequency band, produce a magnified visualization, and file a report - or request human
review when evidence is insufficient.
Rules:
- Always start with probe_clip. Respect aliasing: if a frequency of interest exceeds 0.45 x fps,
  request review with a recording suggestion.
- A peak that also appears in background patches is camera shake, not a fault.
- Prefer a coarse scan, then a fine scan inside the candidate region.
- If magnify returns artifact_ratio > 0.5, narrow the band or lower alpha (max 3 magnify calls).
- Severity is indicative only; never claim ISO certification.
- Finish with exactly one of: file_report or request_review. Max 10 tool calls.
Before each tool call, state in one sentence which measurement motivated it."""


def make_provider(state: JobState):
    """Pick the provider for state.params.policy; falls back to rules with a trace note."""
    pol = state.params.policy
    if pol == "llm":
        try:
            from .provider_gemini import GeminiProvider
            return GeminiProvider(brief=state.params.brief()), "llm"
        except Exception as e:
            state.trace.note(f"LLM unavailable ({type(e).__name__}: {str(e)[:80]}); using rules",
                             source="system")
    return RulesProvider(state.params), "rules"


def _norm_args(args: dict) -> dict:
    """Gemini returns integers as floats (12.0); turn whole numbers in lists back into ints."""
    out = {}
    for k, v in args.items():
        if isinstance(v, list):
            v = [int(x) if isinstance(x, float) and x == int(x) and k == "roi" else x for x in v]
        out[k] = v
    return out


def run_agent(state: JobState, provider=None) -> dict:
    t0 = time.perf_counter()
    source = "rules"
    if provider is None:
        provider, source = make_provider(state)
    else:
        source = getattr(provider, "name", "rules")
    rules = RulesProvider(state.params)
    current = provider
    history: list[dict] = []

    while len(history) < config.MAX_TOOL_CALLS and state.terminal is None:
        try:
            action = current.next_action(SYSTEM_PROMPT, history, TOOLS)
        except Exception as e:
            if current is rules:
                raise
            source = f"rules (fallback: {type(e).__name__}: {str(e)[:100]})"
            state.trace.note(f"provider failed, switching to rules: {type(e).__name__}: {str(e)[:100]}",
                             source=source)
            current = rules
            action = current.next_action(SYSTEM_PROMPT, history, TOOLS)
        if action.get("final") or not action.get("tool"):
            break
        tool, args = action["tool"], _norm_args(action.get("args") or {})
        rationale = action.get("rationale", "")
        if len(history) == config.MAX_TOOL_CALLS - 1 and tool not in TERMINAL:
            tool, args = "request_review", {"reason": "step limit reached before a conclusion",
                                            "suggestion": "re-run with a clearer clip or narrower frequency range"}
            rationale = "Tool-call budget exhausted."
            state.trace.note("step limit: forcing request_review", source="system")

        if current.name == "llm" and rationale:
            bad = guard.check(rationale, known_numbers(state) + [args])
            if bad:
                state.trace.note(f"guard: replaced rationale (unverified number {bad[0]})", source="guard")
                rationale = "[rationale withheld: unverified number]"

        ts = time.perf_counter()
        result = run_tool(state, tool, args)
        state.trace.add(tool, args, result, source, rationale, (time.perf_counter() - ts) * 1000)
        history.append({"tool": tool, "args": args, "result": result})

    if state.terminal is None:
        state.trace.note("no terminal tool called: forcing request_review", source="system")
        res = run_tool(state, "request_review", {"reason": "step limit reached before a conclusion",
                                                 "suggestion": "re-run with a clearer clip"})
        state.trace.add("request_review", {"reason": "step limit reached before a conclusion"}, res, "system")

    return job_result(state, time.perf_counter() - t0, source)


def job_result(state: JobState, runtime_s: float, source: str = "rules") -> dict:
    t = state.terminal or {}
    return {
        "job_id": state.job_id,
        "verdict": t.get("verdict"),
        "summary": t.get("summary") or t.get("reason"),
        "reason": t.get("reason"),
        "suggestion": t.get("suggestion"),
        "findings": _findings(state),
        "severity": state.severity,
        "capture": state.capture(),
        "outputs": dict(state.outputs),
        "trace": state.trace.to_list(),
        "policy": state.params.policy,
        "source": source,
        "n_tool_calls": len([e for e in state.trace.events if e.kind == "tool"]),
        "runtime_s": round(runtime_s, 2),
    }


def _findings(state: JobState) -> list[dict]:
    from .tools import _findings as f
    return f(state)
