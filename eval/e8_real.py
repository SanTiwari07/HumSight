"""E8: run the agent on a real phone clip and compare with the expected frequency.

    python eval/e8_real.py demo_clips/real_fan/clip.mp4 --capture-fps 240 --expected-hz 24.8 [--label "coin on"]

Ground truth: phyphox "Acceleration Spectrum" peak on a second phone, or the fan's rated RPM / 60.
Pass the expected frequency here only for the comparison table; it is NOT given to the agent
(so the aliasing guard cannot cheat), unless you add --give-expected.
"""
import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from humsight.agent.loop import run_agent  # noqa: E402
from humsight.agent.state import JobParams, JobState  # noqa: E402
from humsight.io import load_video  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("clip")
ap.add_argument("--capture-fps", type=float, required=True)
ap.add_argument("--expected-hz", type=float)
ap.add_argument("--label", default="")
ap.add_argument("--give-expected", action="store_true")
ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"))
a = ap.parse_args()

clip = load_video(a.clip, a.capture_fps)
out_dir = os.path.join(a.out, "e8_" + (a.label.replace(" ", "_") or "clip"))
st = JobState(clip, JobParams(policy="rules", workers=os.cpu_count() or 1,
                              expected_hz=a.expected_hz if a.give_expected else None), out_dir)
r = run_agent(st)
f = r["findings"][0] if r["findings"] else None
line = (f"| {a.label or os.path.basename(a.clip)} | {a.expected_hz} | "
        f"{f['f_hz'] if f else '-'} | {f['amp_px'] if f else '-'} | {r['verdict']} | {r['summary']} |")
md = os.path.join(a.out, "e8.md")
new = not os.path.exists(md)
with open(md, "a", encoding="utf-8") as fh:
    if new:
        fh.write("## E8 Real clip (fan + coin)\n\n| clip | expected f (Hz) | measured f (Hz) | amp (px) | verdict | summary |\n|---|---|---|---|---|---|\n")
    fh.write(line + "\n")
print(line)
print("warnings:", clip.warnings)
