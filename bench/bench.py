"""Per-stage benchmark: COOL vs stock OpenCV on the same machine.

    python bench/bench.py --label cool  --out bench/cool.json
    python bench/bench.py --label stock --out bench/stock.json
    python bench/bench.py --compare bench/cool.json bench/stock.json --md bench/RESULTS.md [--spot-price 0.03]

Protocol: 1 warm-up run, then N timed runs (default 7) for cv2.setNumThreads(n), n in {1, 2};
median and IQR are reported. Whatever the result, it is reported.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from humsight import env, magnify, shake, spectrum, synth  # noqa: E402
from humsight.io import VideoSink, clip_from_gray, load_video  # noqa: E402
from humsight.motion import patch_shifts  # noqa: E402
from humsight.texture import make_grid, make_roi_grid, reference_frame  # noqa: E402

DATA = os.path.join(ROOT, "bench", "data")
STAGES = ["load+downscale", "stabilise(warp)", "patch_shifts(coarse)", "patch_shifts(fine)",
          "spectra", "magnify(ROI)", "encode"]


def io_probe() -> dict:
    from humsight.io import probe_codecs
    with tempfile.TemporaryDirectory() as d:
        return probe_codecs(d)


def make_clips(quick: bool, size: tuple[int, int, float] | None = None) -> dict[str, str]:
    """Synthetic benchmark clips written once as mp4v (so 'load' includes real decode)."""
    os.makedirs(DATA, exist_ok=True)
    W, H, dur = size or ((320, 240, 1.0) if quick else (640, 360, 4.0))
    specs = {
        "synth_clean": dict(parts=[synth.default_part(58.5, 0.05, bbox=(W // 2, H // 4, W // 3, H // 3))], shake=None),
        "synth_shake": dict(parts=[synth.default_part(58.5, 0.05, bbox=(W // 2, H // 4, W // 3, H // 3))],
                            shake=synth.ShakeSpec(3.5, 0.6, drift=True)),
    }
    out = {}
    for name, sp in specs.items():
        path = os.path.join(DATA, f"{name}_{W}x{H}.mp4")
        if not os.path.exists(path):
            fr, _ = synth.generate(synth.SynthParams(fps=240, duration_s=dur, width=W, height=H, **sp))
            w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 30, (W, H))
            for f in fr:
                w.write(cv2.cvtColor(f, cv2.COLOR_GRAY2BGR))
            w.release()
        out[name] = path
    return out


def run_stages(path: str, fps: float = 240.0) -> dict[str, float]:
    t: dict[str, float] = {}

    def timed(name, fn):
        t0 = time.perf_counter()
        r = fn()
        t[name] = (time.perf_counter() - t0) * 1000
        return r

    clip = timed("load+downscale", lambda: load_video(path, fps))
    ref = reference_frame(clip.frames_y)
    grid = make_grid(ref, 8, 6)
    ms0 = patch_shifts(clip.frames_y, grid)   # untimed: input for the warp stage
    timed("stabilise(warp)", lambda: shake.warp(clip.frames_y, grid, ms0, clip.fps))
    ms = timed("patch_shifts(coarse)", lambda: patch_shifts(clip.frames_y, grid, valid_only=True))
    H, W = clip.frames_y.shape[1:]
    roi = (W // 2 - 16, H // 4 - 16, W // 3 + 32, H // 3 + 32)
    fgrid = make_roi_grid(ref, roi)
    timed("patch_shifts(fine)", lambda: patch_shifts(clip.frames_y, fgrid, valid_only=True))
    timed("spectra", lambda: spectrum.analyze_patches(ms.dx, ms.dy, clip.fps, grid.valid))
    mag = timed("magnify(ROI)", lambda: magnify.magnify_roi(clip.frames_y, clip.fps, list(roi), 58.5, 2.0, 20.0, 0.05))

    def enc():
        with tempfile.TemporaryDirectory() as d:
            magnify.render_videos(clip, mag, d, "m", write_original=False, overlay=False)
    timed("encode", enc)
    return t


def micro(shape=(360, 640), n=200) -> dict[str, float]:
    rng = np.random.default_rng(0)
    g = rng.random(shape, dtype=np.float32)
    bgr = (rng.random((*shape, 3)) * 255).astype(np.uint8)
    g2 = np.roll(g, 1, 1)
    win = cv2.createHanningWindow((64, 64), cv2.CV_32F)
    a, b = np.ascontiguousarray(g[:64, :64]), np.ascontiguousarray(g2[:64, :64])
    Hm = np.array([[1, 0, 0.3], [0, 1, 0.2], [0, 0, 1]], np.float64)
    edges = cv2.Canny((g * 255).astype(np.uint8), 50, 150)
    ops = {
        "GaussianBlur": lambda: cv2.GaussianBlur(g, (0, 0), 1.5),
        "pyrDown": lambda: cv2.pyrDown(g),
        "pyrUp": lambda: cv2.pyrUp(g),
        "warpPerspective": lambda: cv2.warpPerspective(g, Hm, shape[::-1]),
        "phaseCorrelate(64x64)": lambda: cv2.phaseCorrelate(a, b, win),
        "phaseCorrelateIterative(64x64)": lambda: cv2.phaseCorrelateIterative(a * win, b * win, 5),
        "cvtColor(BGR2YCrCb)": lambda: cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb),
        "resize(INTER_AREA 0.5x)": lambda: cv2.resize(bgr, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA),
        "Sobel": lambda: cv2.Sobel(g, cv2.CV_32F, 1, 0),
        "findContours": lambda: cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE),
    }
    out = {}
    for k, fn in ops.items():
        fn()
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        out[k] = (time.perf_counter() - t0) / n * 1e6   # microseconds
    return out


def bench(label: str, out: str, runs: int, quick: bool, extra_clips: list[str],
          size: tuple[int, int, float] | None = None) -> None:
    clips = make_clips(quick, size)
    for i, p in enumerate(extra_clips):
        clips[f"real_{i}"] = p
    meta = {"label": label, "date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "uname": platform.platform(), "python": sys.version.split()[0], "runs": runs,
            "workload": {"clips": list(clips), "size": list(size) if size else ("quick" if quick else [640, 360, 4.0])},
            "codecs_available": io_probe(), "forced_codec": os.environ.get("HUMSIGHT_FORCE_CODEC"),
            "env": env.cv2_info(), "instance_type": os.environ.get("INSTANCE_TYPE", ""),
            "ami_id": os.environ.get("AMI_ID", "")}
    try:
        meta["uname_a"] = subprocess.run(["uname", "-a"], capture_output=True, text=True).stdout.strip()
    except Exception:
        pass
    res: dict = {}
    for name, path in clips.items():
        res[name] = {}
        for thr in (1, 2):
            cv2.setNumThreads(thr)
            run_stages(path)                       # warm-up
            samples = {s: [] for s in STAGES}
            for _ in range(runs):
                for s, v in run_stages(path).items():
                    samples[s].append(v)
            res[name][str(thr)] = samples
            print(f"[{label}] {name} threads={thr}: " +
                  ", ".join(f"{s}={statistics.median(v):.0f}ms" for s, v in samples.items()), flush=True)
    cv2.setNumThreads(2)
    m = {}
    for thr in (1, 2):
        cv2.setNumThreads(thr)
        m[str(thr)] = micro()
    json.dump({"meta": meta, "stages": res, "micro": m}, open(out, "w"), indent=1)
    print("wrote", out)


def _iqr(v):
    q = statistics.quantiles(v, n=4) if len(v) >= 4 else [min(v), statistics.median(v), max(v)]
    return q[2] - q[0]


def compare(a_path: str, b_path: str, md: str, spot_price: float | None) -> None:
    A, B = json.load(open(a_path)), json.load(open(b_path))
    L = ["# COOL vs stock OpenCV benchmark", "",
         f"- **{A['meta']['label']}**: cv2 {A['meta']['env']['cv2_version']} @ `{A['meta']['env']['cv2_path']}` "
         f"(COOL={A['meta']['env']['cool']}, KleidiCV={A['meta']['env']['kleidicv']}), {A['meta']['date']}",
         f"- **{B['meta']['label']}**: cv2 {B['meta']['env']['cv2_version']} @ `{B['meta']['env']['cv2_path']}` "
         f"(COOL={B['meta']['env']['cool']}, KleidiCV={B['meta']['env']['kleidicv']}), {B['meta']['date']}",
         f"- machine: {A['meta'].get('uname_a') or A['meta']['uname']} · instance {A['meta'].get('instance_type')} "
         f"· AMI {A['meta'].get('ami_id')}",
         f"- {A['meta']['runs']} timed runs after 1 warm-up; median (IQR) in ms. Speedup = {B['meta']['label']} / {A['meta']['label']}.",
         "", "Numbers below are generated by `bench/bench.py --compare`; nothing is retyped.", ""]
    for clip in A["stages"]:
        for thr in ("1", "2"):
            L += [f"## {clip}, cv2.setNumThreads({thr})", "",
                  f"| stage | {A['meta']['label']} | {B['meta']['label']} | speedup |", "|---|---|---|---|"]
            ta = tb = 0.0
            for s in STAGES:
                va, vb = A["stages"][clip][thr][s], B["stages"][clip][thr][s]
                ma, mb = statistics.median(va), statistics.median(vb)
                ta += ma
                tb += mb
                L.append(f"| {s} | {ma:.1f} ({_iqr(va):.1f}) | {mb:.1f} ({_iqr(vb):.1f}) | {mb / ma:.2f}x |")
            L.append(f"| **total** | **{ta:.0f}** | **{tb:.0f}** | **{tb / ta:.2f}x** |")
            if spot_price:
                ca, cb = ta / 1000 * spot_price / 3600 * 1000, tb / 1000 * spot_price / 3600 * 1000
                L.append(f"\nCompute cost per 1,000 clips at ${spot_price}/h: "
                         f"{A['meta']['label']} ${ca:.3f} · {B['meta']['label']} ${cb:.3f}")
            L.append("")
    L += ["## Micro-benchmark (microseconds per call, 640x360 float32)", ""]
    for thr in ("1", "2"):
        L += [f"### threads={thr}", "", f"| op | {A['meta']['label']} | {B['meta']['label']} | speedup |", "|---|---|---|---|"]
        for k in A["micro"][thr]:
            a, b = A["micro"][thr][k], B["micro"][thr][k]
            L.append(f"| {k} | {a:.1f} | {b:.1f} | {b / a:.2f}x |")
        L.append("")
    L += ["If COOL is not faster on a stage, that is the result: for example NumPy FFT and Python-level loops "
          "dominate several stages and COOL does not accelerate NumPy."]
    open(md, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("wrote", md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label")
    ap.add_argument("--out")
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--quick", action="store_true", help="small clips, for a smoke test")
    ap.add_argument("--width", type=int, help="synthetic clip width (default 640)")
    ap.add_argument("--height", type=int, help="synthetic clip height (default 360)")
    ap.add_argument("--dur", type=float, help="synthetic clip seconds at 240 fps (default 4; 960 frames need > 4 GB RAM)")
    ap.add_argument("--clip", action="append", default=[], help="extra real clip (capture fps 240)")
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("--md")
    ap.add_argument("--spot-price", type=float)
    a = ap.parse_args()
    if a.compare:
        compare(a.compare[0], a.compare[1], a.md or "bench/RESULTS.md", a.spot_price)
    else:
        size = (a.width or 640, a.height or 360, a.dur or 4.0) if (a.width or a.height or a.dur) else None
        bench(a.label or "local", a.out or "bench/local.json", a.runs, a.quick, a.clip, size)


if __name__ == "__main__":
    main()
