import os

import pytest

from conftest import make_clip
from humsight import config
from humsight.agent.loop import run_agent
from humsight.agent.state import JobParams, JobState
from humsight.pipeline import run_fixed


def _run(frames_gt, tmp_path, provider=None, **kw):
    clip = make_clip(frames_gt)
    st = JobState(clip, JobParams(policy="rules", render=False, workers=2, **kw), str(tmp_path))
    return st, run_agent(st, provider)


def _tools(r):
    return [e["tool"] for e in r["trace"] if e["kind"] == "tool"]


def test_shake_rejected_and_fault_found(shake_fault, tmp_path):
    st, r = _run(shake_fault, tmp_path)
    assert r["verdict"] == "FAULT"
    f = r["findings"][0]
    gt = shake_fault[1]["parts"][0]
    assert abs(f["f_hz"] - gt["f_hz"]) < 1.0
    assert abs(f["amp_px"] - gt["amp_px"]) / gt["amp_px"] < 0.25
    assert "compensate_shake" in _tools(r)
    comp = next(e for e in r["trace"] if e["tool"] == "compensate_shake")
    assert comp["result"]["bg_peak_hz"] == pytest.approx(3.5, abs=0.3)   # a measurement drove the next call
    assert all(abs(x["f_hz"] - 3.5) > 1.0 for x in r["findings"])
    assert r["n_tool_calls"] <= config.MAX_TOOL_CALLS
    assert os.path.exists(tmp_path / "work_order.md") and os.path.exists(tmp_path / "heatmap.png")


def test_shake_only_is_no_fault(shake_only, tmp_path):
    _, r = _run(shake_only, tmp_path)
    assert r["verdict"] == "NO_FAULT"


def test_quiet_skips_shake_compensation(quiet, tmp_path):
    _, r = _run(quiet, tmp_path)
    assert r["verdict"] == "NO_FAULT" and "compensate_shake" not in _tools(r)


def test_fault_only_no_compensation_needed(fault_only, tmp_path):
    _, r = _run(fault_only, tmp_path)
    assert r["verdict"] == "FAULT" and "compensate_shake" not in _tools(r)
    assert abs(r["findings"][0]["f_hz"] - 24.5) < 1.0


def test_aliasing_guard_gives_review(fault_only, tmp_path):
    _, r = _run(fault_only, tmp_path, expected_hz=130.0)
    assert r["verdict"] == "REVIEW"
    assert "aliasing" in r["reason"] and "fps" in r["suggestion"]
    assert _tools(r) == ["probe_clip", "request_review"]


def test_fixed_pipeline_magnifies_the_shake(shake_fault, tmp_path):
    r = run_fixed(make_clip(shake_fault), str(tmp_path), render=False)
    assert r["verdict"] == "FAULT"
    assert abs(r["findings"][0]["f_hz"] - 3.5) < 0.5   # the baseline's documented failure mode


class _Boom:
    name = "llm"

    def next_action(self, system, history, tools):
        raise RuntimeError("429 quota")


def test_provider_failure_falls_back_to_rules(fault_only, tmp_path):
    _, r = _run(fault_only, tmp_path, provider=_Boom())
    assert r["verdict"] == "FAULT"
    assert any(e["source"].startswith("rules (fallback") for e in r["trace"])


class _Never:
    name = "llm"

    def next_action(self, system, history, tools):
        return {"tool": "probe_clip", "args": {}, "rationale": ""}


def test_step_limit_forces_review(quiet, tmp_path):
    _, r = _run(quiet, tmp_path, provider=_Never())
    assert r["verdict"] == "REVIEW"
    assert r["n_tool_calls"] == config.MAX_TOOL_CALLS
    assert _tools(r)[-1] == "request_review"


class _Scripted:
    """A fake LLM: probe, scan, classify, then file the given report."""
    name = "llm"

    def __init__(self, verdict, summary):
        self.i, self.verdict, self.summary = 0, verdict, summary

    def next_action(self, system, history, tools):
        seq = [("probe_clip", {}), ("scan_motion", {"grid": "coarse"}), ("classify_peaks", {})]
        self.i += 1
        if self.i <= 3:
            return {"tool": seq[self.i - 1][0], "args": seq[self.i - 1][1], "rationale": ""}
        return {"tool": "file_report", "args": {"verdict": self.verdict, "summary": self.summary},
                "rationale": ""}


def test_number_guard_replaces_invented_summary(quiet, tmp_path):
    _, r = _run(quiet, tmp_path, provider=_Scripted("NO_FAULT", "All clear at 777 Hz."))
    assert r["verdict"] == "NO_FAULT"
    assert "777" not in r["summary"]
    notes = [e for e in r["trace"] if e["kind"] == "note" and e["source"] == "guard"]
    assert notes and "777" in notes[0]["rationale"]


def test_unsupported_fault_verdict_downgraded(quiet, tmp_path):
    _, r = _run(quiet, tmp_path, provider=_Scripted("FAULT", "Fault found."))
    assert r["verdict"] == "REVIEW"


def test_low_texture_asks_for_review_instead_of_no_fault(tmp_path):
    import numpy as np
    flat = np.full((480, 192, 256), 128, np.uint8)
    flat = (flat + np.random.default_rng(1).normal(0, 1.0, flat.shape)).clip(0, 255).astype(np.uint8)
    _, r = _run((flat, {}), tmp_path)
    assert r["verdict"] == "REVIEW" and "low texture" in r["reason"]
