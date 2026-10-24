"""Shared helpers for the evaluation scripts. Everything is seeded; nothing is retyped by hand."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from humsight import config, detect, shake, spectrum, synth  # noqa: E402
from humsight.io import clip_from_gray  # noqa: E402
from humsight.motion import patch_shifts  # noqa: E402
from humsight.texture import make_grid, reference_frame  # noqa: E402

W, H = 256, 192                       # evaluation resolution (keeps the 90+ clip grids fast)
DUR = 4.0
BBOX = (88, 48, 96, 80)               # default fault part: >= 4 full 32x32 patches inside
RESULTS = os.path.join(ROOT, "eval", "results")


def init_worker() -> None:
    cv2.setNumThreads(1)


def spec(f=24.5, amp=0.05, fps=240.0, noise=0.005, seed=42, shake_spec=None, codec=False,
         bbox=BBOX, parts=None, dur=DUR) -> dict:
    if parts is None:
        parts = [] if amp is None else [dict(id="part", bbox=list(bbox), f=f, amp=amp)]
    return dict(f=f, amp=amp, fps=fps, noise=noise, seed=seed, shake=shake_spec, codec=codec,
                parts=parts, dur=dur)


def generate(sp: dict):
    parts = [synth.PartSpec(p["id"], tuple(p["bbox"]), p["f"], p["amp"], tuple(p.get("dir", (1, 0))),
                            p.get("phase", 0.3)) for p in sp["parts"]]
    shk = synth.ShakeSpec(**sp["shake"]) if sp["shake"] else None
    params = synth.SynthParams(fps=sp["fps"], duration_s=sp["dur"], width=W, height=H, parts=parts,
                               shake=shk, noise_sigma=sp["noise"], codec_roundtrip=sp["codec"],
                               seed=sp["seed"])
    return synth.generate(params)


def inside_mask(grid, bbox) -> np.ndarray:
    x, y, w, h = bbox
    b = grid.boxes
    return (b[:, 0] >= x) & (b[:, 0] + b[:, 2] <= x + w) & (b[:, 1] >= y) & (b[:, 1] + b[:, 3] <= y + h)


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / (aw * ah + bw * bh - inter + 1e-9)


def run_coarse(frames, fps: float, comp: bool = True):
    clip = clip_from_gray(frames, fps)
    grid = make_grid(reference_frame(clip.frames_y), *config.COARSE_GRID)
    ms = patch_shifts(clip.frames_y, grid, valid_only=True)
    bx, by = shake.background_signal(ms, grid)
    dx, dy = ms.dx, ms.dy
    if comp:
        c = shake.subtract(ms, grid, fps)
        dx, dy = c.dx, c.dy
    return clip, grid, dx, dy, bx, by


def task_measure(sp: dict) -> dict:
    """E1/E2/E3: measurement accuracy on ground-truth patches + detection outcome."""
    frames, gt = generate(sp)
    clip, grid, dx, dy, bx, by = run_coarse(frames, sp["fps"])
    out = {"spec": sp, "f_est": None, "amp_est": None, "snr": None, "detected": False,
           "roi_iou": None, "df": sp["fps"] / clip.n_frames}
    cls, _ = detect.classify(dx, dy, grid, sp["fps"], bx, by, (H, W))
    out["n_faults"] = len(cls["faults"])
    if sp["parts"]:
        p = sp["parts"][0]
        ins = inside_mask(grid, p["bbox"]) & grid.valid
        pk = spectrum.analyze_patches(dx, dy, sp["fps"], ins)
        if pk:
            out["f_est"] = float(np.median([q.f_hz for q in pk]))
            out["amp_est"] = float(np.median([q.amp_px for q in pk]))
            out["snr"] = float(np.median([q.snr for q in pk]))
        tol = config.BIN_TOL * out["df"]
        for f in cls["faults"]:
            if abs(f["f_hz"] - p["f"]) <= tol:
                out["detected"] = True
                out["roi_iou"] = iou(f["roi_tight"], p["bbox"])
                break
    else:
        out["detected"] = len(cls["faults"]) > 0   # false positive
    return out


def agent_result(sp: dict, policy: str = "rules", expected_hz=None) -> dict:
    from humsight.agent.loop import run_agent
    from humsight.agent.state import JobParams, JobState
    import tempfile
    frames, gt = generate(sp)
    clip = clip_from_gray(frames, sp["fps"])
    with tempfile.TemporaryDirectory() as d:
        st = JobState(clip, JobParams(policy=policy, render=False, expected_hz=expected_hz), d)
        r = run_agent(st)
    return {"spec": sp, "gt": gt, "verdict": r["verdict"], "findings": r["findings"],
            "n_calls": r["n_tool_calls"], "source": r["source"], "reason": r.get("reason"),
            "tools": [e["tool"] for e in r["trace"] if e["kind"] == "tool"]}


def task_agent(args) -> dict:
    sp, policy, expected = args
    return agent_result(sp, policy, expected)


def task_fixed(sp: dict) -> dict:
    from humsight.pipeline import run_fixed
    import tempfile
    frames, gt = generate(sp)
    clip = clip_from_gray(frames, sp["fps"])
    with tempfile.TemporaryDirectory() as d:
        r = run_fixed(clip, d, render=False)
    return {"spec": sp, "gt": gt, "verdict": r["verdict"], "findings": r["findings"]}


def md_table(header: list[str], rows: list[list]) -> str:
    L = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        L.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(L)
