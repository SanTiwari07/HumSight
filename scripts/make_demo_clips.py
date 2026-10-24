"""Generate the curated demo clips (lossless .npz + gt.json + demo.json). Deterministic (seeded).

    python scripts/make_demo_clips.py [--only pump_shake_fault ...]

Clips are not committed (tens of MB of sensor noise do not compress); regenerate them here.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from humsight import synth  # noqa: E402

W, H, FPS, DUR = 384, 216, 240.0, 3.0
BBOX = (136, 56, 144, 108)
SHAKE = synth.ShakeSpec(f_hz=3.5, amp_px=0.6, drift=True)


def part(f, amp, **kw):
    return synth.default_part(f, amp, bbox=BBOX, **kw)


DEMOS = {
    "pump_shake_fault": dict(
        title="Pump: hidden 58.5 Hz fault + handheld camera shake",
        description="Ground truth: 58.5 Hz, 0.05 px at the bearing cap; 3.5 Hz camera shake of 0.6 px with drift.",
        expect="FAULT", params={}, p=dict(parts=[part(58.5, 0.05)], shake=SHAKE)),
    "fan_fault_only": dict(
        title="Fan housing: 24.5 Hz fault, tripod (no shake)",
        description="Ground truth: 24.5 Hz, 0.10 px.", expect="FAULT", params={},
        p=dict(parts=[part(24.5, 0.1)], shake=None)),
    "shake_only": dict(
        title="Healthy machine, shaky camera (should be NO_FAULT)",
        description="Only camera shake. A fixed pipeline magnifies the shake; the agent rejects it.",
        expect="NO_FAULT", params={}, p=dict(parts=[], shake=SHAKE)),
    "quiet": dict(
        title="Healthy machine, steady camera (should be NO_FAULT)",
        description="No motion at all, only sensor noise.", expect="NO_FAULT", params={},
        p=dict(parts=[], shake=None)),
    "alias_130hz": dict(
        title="Aliasing: 130 Hz fault at 240 fps (should be REVIEW)",
        description="Expected frequency 130 Hz exceeds 0.45 x fps. The agent asks for a faster recording.",
        expect="REVIEW", params={"expected_hz": 130}, p=dict(parts=[part(130.0, 0.2)], shake=None)),
    "codec_damaged": dict(
        title="Failure case: same fault as the pump clip, after lossy codec",
        description="Identical scene as pump_shake_fault but round-tripped through an mp4v encoder. "
                    "The codec smooths the 0.05 px motion away, so the fault is missed (documented limitation).",
        expect="FAULT (expected miss)", params={}, p=dict(parts=[part(58.5, 0.05)], shake=SHAKE, codec_roundtrip=True)),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default=os.path.join(ROOT, "demo_clips"))
    a = ap.parse_args()
    for name, d in DEMOS.items():
        if a.only and name not in a.only:
            continue
        params = synth.SynthParams(fps=FPS, duration_s=DUR, width=W, height=H, noise_sigma=0.004,
                                   seed=42, **d["p"])
        frames, gt = synth.generate(params)
        out = os.path.join(a.out, name)
        synth.save(frames, gt, out, mp4=False, npz=True)
        with open(os.path.join(out, "demo.json"), "w", encoding="utf-8") as fh:
            json.dump({k: d[k] for k in ("title", "description", "expect", "params")}
                      | {"fps": FPS, "duration": DUR}, fh, indent=2)
        print("wrote", out)


if __name__ == "__main__":
    main()
