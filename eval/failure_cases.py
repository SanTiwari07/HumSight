"""Documented failure cases: run the rules agent on clips built to break it, keep the evidence.

    python eval/failure_cases.py

Writes eval/results/failure_cases.md and eval/results/failure_cases/<case>/heatmap.png.
These are reported as found, including cases where the tool is wrong.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

import numpy as np  # noqa: E402

from humsight import synth  # noqa: E402
from humsight.agent.loop import run_agent  # noqa: E402
from humsight.agent.state import JobParams, JobState  # noqa: E402
from humsight.io import clip_from_gray  # noqa: E402

OUT = os.path.join(C.RESULTS, "failure_cases")
DIRS = {"Codec damage": "codec_damage", "Aliasing, frequency not given": "alias_unknown_frequency",
        "Low texture": "low_texture", "Large motion": "large_motion", "Lighting flicker": "lighting_flicker"}
SHAKE = dict(f_hz=3.5, amp_px=0.6, dir=(0.7071, 0.7071), drift=True)


def run_case(name, frames, fps, expected_hz=None):
    out = os.path.join(OUT, name)
    shutil.rmtree(out, ignore_errors=True)
    clip = clip_from_gray(frames, fps)
    st = JobState(clip, JobParams(policy="rules", render=False, expected_hz=expected_hz,
                                  workers=os.cpu_count() or 1), out)
    r = run_agent(st)
    probe = next((e["result"] for e in r["trace"] if e["tool"] == "probe_clip"), {})
    cls = next((e["result"] for e in r["trace"] if e["tool"] == "classify_peaks"), {})
    return r, probe, cls


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []

    # 1. codec damage: same scene as the pump demo, after an mp4v encode/decode
    sp = C.spec(f=58.5, amp=0.05, noise=0.004, shake_spec=SHAKE, codec=True)
    fr, _ = C.generate(sp)
    r, probe, cls = run_case("codec_damage", fr, 240.0)
    rows.append(("Codec damage", "58.5 Hz, 0.05 px fault + shake, after mp4v round-trip", "FAULT at 58.5 Hz", r, probe, cls,
                 "The encoder's motion compensation and quantisation smooth sub-pixel motion away; the noise floor "
                 "looks normal, so the clip looks quiet. Use a high-bitrate / lossless original, never a messaging-app copy."))

    # 2. aliasing when the user does not give an expected frequency
    sp = C.spec(f=144.0, amp=0.2, fps=240.0, noise=0.004)
    fr, _ = C.generate(sp)
    r, probe, cls = run_case("alias_unknown_frequency", fr, 240.0)
    rows.append(("Aliasing, frequency not given", "144 Hz fault recorded at 240 fps (Nyquist 120 Hz)",
                 "REVIEW (aliasing)", r, probe, cls,
                 "Without expected_hz the guard cannot know. The 144 Hz motion folds to 96 Hz and is reported there as a "
                 "confident FAULT. Give an expected Hz/RPM whenever possible."))

    # 3. low texture
    sp = C.spec(f=24.5, amp=0.1, noise=0.0)
    fr, _ = C.generate(sp)
    flat = (128 + 0.06 * (fr.astype(np.float32) - 128))
    flat = flat + np.random.default_rng(1).normal(0, 1.2, flat.shape)
    flat = np.clip(flat, 0, 255).astype(np.uint8)
    r, probe, cls = run_case("low_texture", flat, 240.0)
    rows.append(("Low texture", "24.5 Hz, 0.1 px fault on a nearly flat surface (6% contrast)", "FAULT at 24.5 Hz or REVIEW", r, probe, cls,
                 "Phase correlation needs gradient energy. Patches below TEXTURE_MIN are dropped; with almost none left the agent must "
                 "ask for review rather than report a negative (an earlier version filed NO_FAULT here: fixed)."))

    # 4. large motion
    sp = C.spec(f=15.0, amp=6.0, noise=0.004)
    fr, _ = C.generate(sp)
    r, probe, cls = run_case("large_motion", fr, 240.0)
    rows.append(("Large motion", "15 Hz, 6 px fault (far outside the sub-pixel regime)", "one FAULT at 15 Hz, amplitude 6 px", r, probe, cls,
                 "Magnification and the sub-pixel estimator assume small motion. The main peak is found (amplitude within a few percent) "
                 "but the estimator's nonlinearity adds spurious harmonic peaks that are also classified as faults; do not trust "
                 "secondary findings or magnification for motion of several pixels."))

    # 5. lighting flicker (guard works): brightness modulated at the 100 Hz mains-light frequency, no motion
    sp = C.spec(amp=None, noise=0.004)
    fr, _ = C.generate(sp)
    t = np.arange(len(fr)) / 240.0
    mod = 1.0 + 0.08 * np.sin(2 * np.pi * 100.0 * t)
    fl = np.clip(fr.astype(np.float32) * mod[:, None, None], 0, 255).astype(np.uint8)
    r, probe, cls = run_case("lighting_flicker", fl, 240.0)
    rows.append(("Lighting flicker", "no motion; 100 Hz mains-light brightness modulation (8%)", "NO_FAULT or REVIEW", r, probe, cls,
                 "Guard case: brightness oscillation is flagged from the mean-frame signal instead of being read as motion."))

    L = ["# Failure cases", "", "Built to break the tool; results are reported as found.", ""]
    L.append(C.md_table(["case", "scene", "ideal outcome", "actual verdict", "findings", "probe warnings"],
                        [[a, b, c, d["verdict"], json.dumps([(f["f_hz"], f["amp_px"]) for f in d["findings"]]),
                          "; ".join(p.get("warnings", [])) or "-"] for a, b, c, d, p, _, _ in rows]))
    L.append("")
    for a, b, c, d, p, k, why in rows:
        L += [f"## {a}", "", f"- scene: {b}", f"- ideal: {c}", f"- actual: **{d['verdict']}** - {d['summary']}",
              f"- texture coverage: {p.get('texture_coverage')}; noise floor: {k.get('noise_floor_px')} px; "
              f"lighting_flicker: {k.get('lighting_flicker')}", f"- why: {why}", ""]
        if os.path.exists(os.path.join(OUT, DIRS[a], "heatmap.png")):
            L += [f"![{a}: amplitude per patch](failure_cases/{DIRS[a]}/heatmap.png)", ""]
        else:
            L += ["_No heatmap: the agent stopped before measuring any motion._", ""]
    open(os.path.join(C.RESULTS, "failure_cases.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
