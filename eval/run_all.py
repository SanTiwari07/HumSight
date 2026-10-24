"""Regenerate every evaluation table and plot (E1-E6, E8 if a real clip exists).

    python eval/run_all.py                # full (about 10-20 min on 12 cores)
    python eval/run_all.py --quick        # small subset, for a smoke test
    python eval/run_all.py --only E1 E3   # selected experiments

Writes eval/results/*.md|json|png and eval/results/summary.md. Seeds are fixed; every number in
the README is copied from these files by script, never retyped.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

import numpy as np  # noqa: E402

from humsight import config  # noqa: E402

SEED = 42
FPS_LIST = [60, 120, 240]
F_LIST = [7.5, 15, 24.5, 40, 58.5]
AMP_LIST = [0.01, 0.02, 0.05, 0.1, 0.3, 1.0]
NOISE_LIST = [0.002, 0.005, 0.01]
SHAKE = dict(f_hz=3.5, amp_px=0.6, dir=(0.7071, 0.7071), drift=False)
SHAKE_DRIFT = dict(f_hz=3.5, amp_px=0.6, dir=(0.7071, 0.7071), drift=True)


def pmap(ex, fn, items, desc):
    t0 = time.time()
    out = list(ex.map(fn, items, chunksize=1))
    print(f"  {desc}: {len(items)} jobs in {time.time() - t0:.0f}s", flush=True)
    return out


def q(v, p):
    return float(np.percentile(v, p)) if len(v) else float("nan")


def fmt(x, nd=4):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}g}"


# --------------------------------------------------------------------------------------------
def e1_e2(ex, quick):
    """Pass A (fps=240, f x amp x noise, no shake) and Pass B (f=24.5, amp=0.05, fps x shake)."""
    fl = [24.5, 58.5] if quick else F_LIST
    al = [0.05, 0.3] if quick else AMP_LIST
    nl = [0.005] if quick else NOISE_LIST
    specsA = [C.spec(f=f, amp=a, fps=240, noise=n, seed=SEED) for f in fl for a in al for n in nl]
    resA = pmap(ex, C.task_measure, specsA, "E1/E2 pass A")
    shakes = [None, SHAKE, SHAKE_DRIFT]
    specsB = [C.spec(f=24.5, amp=0.05, fps=fps, noise=0.005, seed=SEED, shake_spec=s)
              for fps in ([240] if quick else FPS_LIST) for s in shakes]
    resB = pmap(ex, C.task_measure, specsB, "E1/E2 pass B")

    L = ["## E1 Frequency accuracy (pass A: fps 240, no shake, 4 s, Δf = 0.25 Hz)", "",
         "Error |f̂ − f| measured on the patches fully inside the vibrating part, median over patches.", ""]
    rows = []
    for a, n in itertools.product(al, nl):
        sel = [r for r in resA if r["spec"]["amp"] == a and r["spec"]["noise"] == n and r["f_est"] is not None]
        e = [abs(r["f_est"] - r["spec"]["f"]) for r in sel]
        eb = [abs(r["f_est"] - r["spec"]["f"]) / r["df"] for r in sel]
        rows.append([a, n, len(sel), fmt(statistics.median(e) if e else None), fmt(q(e, 95)),
                     fmt(statistics.median(eb) if eb else None), fmt(q(eb, 95))])
    L.append(C.md_table(["amp (px)", "noise σ", "n", "median |Δf| (Hz)", "p95 |Δf| (Hz)",
                         "median (bins)", "p95 (bins)"], rows))
    L += ["", "### Pass B (f = 24.5 Hz, amp 0.05 px, noise 0.005)", ""]
    rows = []
    for r in resB:
        s = r["spec"]
        tag = "none" if not s["shake"] else ("3.5 Hz + drift" if s["shake"]["drift"] else "3.5 Hz")
        rows.append([s["fps"], tag, fmt(r["f_est"]), fmt(r["amp_est"]), fmt(r["snr"]), r["detected"],
                     fmt(r["roi_iou"], 2)])
    L.append(C.md_table(["fps", "shake", "f̂ (Hz)", "Â (px)", "SNR", "detected", "ROI IoU"], rows))
    e1 = "\n".join(L)

    # E2 amplitude + plot
    L = ["## E2 Amplitude accuracy (pass A)", "", "Relative error |Â − A| / A, median over patches inside the part.", ""]
    rows = []
    for a, n in itertools.product(al, nl):
        sel = [r for r in resA if r["spec"]["amp"] == a and r["spec"]["noise"] == n and r["amp_est"] is not None]
        e = [abs(r["amp_est"] - a) / a for r in sel]
        rows.append([a, n, len(sel), fmt(statistics.median(e) if e else None, 3), fmt(q(e, 95), 3),
                     fmt(statistics.median([r["amp_est"] for r in sel]) if sel else None)])
    L.append(C.md_table(["amp (px)", "noise σ", "n", "median rel. err", "p95 rel. err", "median Â (px)"], rows))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5.5, 4.2))
        for n in nl:
            xs, ys = [], []
            for a in al:
                v = [r["amp_est"] for r in resA if r["spec"]["amp"] == a and r["spec"]["noise"] == n and r["amp_est"]]
                if v:
                    xs.append(a)
                    ys.append(statistics.median(v))
            ax.plot(xs, ys, "o-", label=f"noise σ={n}")
        ax.plot(al, al, "k--", lw=1, label="ideal")
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("true amplitude (px)"); ax.set_ylabel("estimated amplitude (px)")
        ax.set_title("E2: estimated vs true amplitude (synthetic)"); ax.legend(); ax.grid(alpha=.3)
        fig.tight_layout(); fig.savefig(os.path.join(C.RESULTS, "e2_amplitude.png"), dpi=130); plt.close(fig)
        L += ["", "![E2](e2_amplitude.png)"]
    except Exception as e:  # plotting is optional
        L += ["", f"(plot skipped: {e})"]
    json.dump({"A": resA, "B": resB}, open(os.path.join(C.RESULTS, "e1_e2.json"), "w"))
    return e1, "\n".join(L)


def e3(ex, quick, codec: bool):
    """Detection floor: smallest amp with detection rate >= 90% (10 seeds per cell)."""
    seeds = 3 if quick else 10
    al = [0.02, 0.1] if quick else AMP_LIST
    nl = [0.005] if quick else NOISE_LIST
    specs = [C.spec(f=24.5, amp=a, noise=n, seed=SEED + s, codec=codec)
             for a in al for n in nl for s in range(seeds)]
    nullspecs = [C.spec(f=24.5, amp=None, noise=n, seed=SEED + 100 + s, codec=codec)
                 for n in nl for s in range(seeds)]
    res = pmap(ex, C.task_measure, specs + nullspecs, f"E3{'b' if codec else ''}")
    pos, neg = res[:len(specs)], res[len(specs):]
    rows, floors = [], {}
    for n in nl:
        floor = None
        for a in al:
            sel = [r for r in pos if r["spec"]["noise"] == n and r["spec"]["amp"] == a]
            rate = sum(r["detected"] for r in sel) / len(sel)
            if floor is None and rate >= 0.9:
                floor = a
            rows.append([n, a, f"{rate * 100:.0f}%"])
        fp = [r for r in neg if r["spec"]["noise"] == n]
        floors[n] = (floor, sum(r["detected"] for r in fp), len(fp))
    name = "E3b Codec impact (mp4v round-trip)" if codec else "E3 Detection floor"
    L = [f"## {name}", "", f"f = 24.5 Hz, fps 240, {seeds} seeds per cell, no shake. Detection = a classified fault within 2 bins.", "",
         C.md_table(["noise σ", "amp (px)", "detection rate"], rows), "",
         C.md_table(["noise σ", "detection floor (px, ≥90%)", "false positives on empty clips"],
                    [[n, f if f is not None else "not reached", f"{fp}/{tot}"] for n, (f, fp, tot) in floors.items()])]
    json.dump(res, open(os.path.join(C.RESULTS, f"e3{'b' if codec else ''}.json"), "w"))
    return "\n".join(L)


def e4(ex, quick):
    """Localisation: fault in 1 of 4 parts; top-1 ROI IoU >= 0.3 (agent, rules)."""
    boxes = [(16, 16, 96, 72), (144, 16, 96, 72), (16, 104, 96, 72), (144, 104, 96, 72)]
    n = 6 if quick else 24
    rng = np.random.default_rng(SEED)
    items = []
    for i in range(n):
        k = int(rng.integers(0, 4))
        f = float(rng.choice([15.0, 24.5, 40.0, 58.5]))
        parts = [dict(id=f"p{j}", bbox=list(b), f=f if j == k else 5.0, amp=0.1 if j == k else 0.0)
                 for j, b in enumerate(boxes)]
        items.append((C.spec(parts=parts, noise=0.005, seed=SEED + i), "rules", None, k, f))
    res = pmap(ex, C.task_agent, [(s, p, e) for s, p, e, _, _ in items], "E4")
    hits, rows = 0, []
    for (s, _, _, k, f), r in zip(items, res):
        ok_iou = None
        if r["verdict"] == "FAULT" and r["findings"]:
            ok_iou = C.iou(r["findings"][0]["roi"], boxes[k])
            hit = ok_iou >= 0.3
        else:
            hit = False
        hits += hit
        rows.append([k, f, r["verdict"], fmt(ok_iou, 2), "yes" if hit else "no"])
    L = ["## E4 Localisation", "",
         f"Fault injected into 1 of 4 textured parts (0.1 px); the other parts are static. "
         f"Hit = verdict FAULT and final ROI IoU ≥ 0.3 with the true part.", "",
         f"**Hit rate: {hits}/{n} = {100 * hits / n:.0f}%**", "",
         C.md_table(["true part", "f (Hz)", "verdict", "IoU", "hit"], rows)]
    json.dump(res, open(os.path.join(C.RESULTS, "e4.json"), "w"))
    return "\n".join(L)


def e5_clips(quick):
    sh = [dict(f_hz=3.5, amp_px=0.6, dir=(0.7071, 0.7071), drift=True),
          dict(f_hz=5.0, amp_px=0.8, dir=(1.0, 0.0), drift=False),
          dict(f_hz=2.5, amp_px=0.4, dir=(0.0, 1.0), drift=True)]
    clips = []
    for i, (f, a) in enumerate([(58.5, 0.05), (24.5, 0.1), (40.0, 0.08)]):
        clips.append((f"shake+fault #{i + 1}", C.spec(f=f, amp=a, seed=SEED + i, shake_spec=sh[i]), "FAULT"))
    for i in range(3):
        clips.append((f"shake only #{i + 1}", C.spec(amp=None, seed=SEED + 10 + i, shake_spec=sh[i]), "NO_FAULT"))
    for i, (f, a) in enumerate([(58.5, 0.05), (15.0, 0.1), (40.0, 0.2)]):
        clips.append((f"fault only #{i + 1}", C.spec(f=f, amp=a, seed=SEED + 20 + i), "FAULT"))
    for i, n in enumerate([0.002, 0.005, 0.01]):
        clips.append((f"nothing #{i + 1}", C.spec(amp=None, noise=n, seed=SEED + 30 + i), "NO_FAULT"))
    return clips[:6] if quick else clips


def e5_judge(sp, expect, r):
    """Correct verdict (and right frequency for FAULT); did the reported fault sit at the shake frequency?"""
    shake_f = sp["shake"]["f_hz"] if sp["shake"] else None
    f_true = sp["parts"][0]["f"] if sp["parts"] else None
    fs = [f["f_hz"] for f in r["findings"]]
    magnified_shake = bool(shake_f and any(abs(f - shake_f) < 1.0 for f in fs))
    if expect == "FAULT":
        ok = r["verdict"] == "FAULT" and any(abs(f - f_true) < 1.0 for f in fs)
    else:
        ok = r["verdict"] == "NO_FAULT"
    return ok, magnified_shake


def e5_table(clips, rules, fixed, llm, llm_note=""):
    """Markdown for E5. llm is None (not run) or a list of per-clip results like rules/fixed."""
    rows, tot = [], {"rules": [0, 0], "fixed": [0, 0], "llm": [0, 0]}
    for i, (name, sp, expect) in enumerate(clips):
        row = [name, expect]
        for key, arr in (("rules", rules), ("llm", llm), ("fixed", fixed)):
            if arr is None:
                row.append("not run")
                continue
            ok, ms = e5_judge(sp, expect, arr[i])
            tot[key][0] += ok
            tot[key][1] += ms
            row.append(f"{arr[i]['verdict']} {'✓' if ok else '✗'}{' · shake magnified' if ms else ''}")
        rows.append(row)
    n = len(clips)
    L = ["## E5 Agent vs fixed pipeline", "",
         f"{n} clips (4 groups x 3): shake + hidden fault, shake only, fault only, nothing. ✓ = correct verdict "
         "(and for FAULT, the right frequency). 'shake magnified' = the reported fault frequency is the camera-shake frequency.", "",
         C.md_table(["clip", "truth", "agent (rules)", "agent (Gemini)", "fixed pipeline"], rows), "",
         C.md_table(["policy", "correct", "shake wrongly magnified"],
                    [["agent (rules)", f"{tot['rules'][0]}/{n}", tot["rules"][1]],
                     ["agent (Gemini)", f"{tot['llm'][0]}/{n}" if llm else "not run", tot["llm"][1] if llm else "-"],
                     ["fixed", f"{tot['fixed'][0]}/{n}", tot["fixed"][1]]])]
    if llm_note:
        L += ["", llm_note]
    return "\n".join(L)


def e5(ex, quick):
    clips = e5_clips(quick)
    rules = pmap(ex, C.task_agent, [(s, "rules", None) for _, s, _ in clips], "E5 agent(rules)")
    fixed = pmap(ex, C.task_fixed, [s for _, s, _ in clips], "E5 fixed")
    llm, note = None, ""
    gj = os.path.join(C.RESULTS, "e5_gemini.json")      # written by eval/e5_gemini.py (live API, sequential)
    if os.path.exists(gj) and not quick:
        g = json.load(open(gj, encoding="utf-8"))
        if len(g["results"]) == len(clips):
            llm = g["results"]
            note = g.get("note", "")
    json.dump({"rules": rules, "fixed": fixed, "llm": llm}, open(os.path.join(C.RESULTS, "e5.json"), "w"))
    return e5_table(clips, rules, fixed, llm, note)


def e6(ex, quick):
    """Aliasing guard: f > 0.45 fps with expected_hz given must give REVIEW."""
    fps_list = [240] if quick else FPS_LIST
    items, meta = [], []
    for fps in fps_list:
        for frac in (0.48, 0.6, 0.8):
            f = round(fps * frac, 2)
            items.append((C.spec(f=f, amp=0.2, fps=fps, seed=SEED), "rules", f))
            meta.append((fps, f))
    res = pmap(ex, C.task_agent, items, "E6")
    nores = pmap(ex, C.task_agent, [(s, "rules", None) for s, _, _ in items], "E6 (no expected_hz)")
    flagged = sum(r["verdict"] == "REVIEW" for r in res)
    rows = [[fps, f, r["verdict"], n["verdict"]] for (fps, f), r, n in zip(meta, res, nores)]
    L = ["## E6 Aliasing guard", "",
         f"**{flagged}/{len(res)} = {100 * flagged / len(res):.0f}% flagged REVIEW** when the expected frequency is given "
         f"(target 100%). Last column: what happens when the user gives no expected frequency (the guard cannot "
         f"know, the search band stops at 0.45 x fps).", "",
         C.md_table(["fps", "f (Hz)", "verdict (expected_hz given)", "verdict (not given)"], rows)]
    json.dump({"given": res, "not_given": nores}, open(os.path.join(C.RESULTS, "e6.json"), "w"))
    return "\n".join(L)


def e8():
    clip = os.path.join(C.ROOT, "demo_clips", "real_fan", "clip.mp4")
    if not os.path.exists(clip):
        return ("## E8 Real clip (fan + coin)\n\nNot run: no real clip present at `demo_clips/real_fan/`. "
                "Record one with the protocol in docs/planning/IMPLEMENTATION.md §10 and run `python eval/e8_real.py <clip> "
                "--capture-fps 240 --expected-hz <phyphox Hz>`. Synthetic results above are labelled synthetic.")
    return "## E8 Real clip (fan + coin)\n\nSee `eval/results/e8.md` (written by `eval/e8_real.py`)."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    os.makedirs(C.RESULTS, exist_ok=True)
    want = lambda k: not a.only or k in a.only
    parts = {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers, initializer=C.init_worker) as ex:
        if want("E1") or want("E2"):
            parts["E1"], parts["E2"] = e1_e2(ex, a.quick)
        if want("E3"):
            parts["E3"] = e3(ex, a.quick, False)
        if want("E3b"):
            parts["E3b"] = e3(ex, a.quick, True)
        if want("E4"):
            parts["E4"] = e4(ex, a.quick)
        if want("E5"):
            parts["E5"] = e5(ex, a.quick)
        if want("E6"):
            parts["E6"] = e6(ex, a.quick)
    if want("E8"):
        parts["E8"] = e8()
    head = ["# HumSight evaluation summary", "",
            f"Generated by `python eval/run_all.py{' --quick' if a.quick else ''}` in {time.time() - t0:.0f} s. "
            f"Seeds fixed (base {SEED}). Synthetic clips: {C.W}x{C.H}, {C.DUR:.0f} s. "
            f"cv2 {__import__('cv2').__version__}. Thresholds: SNR_MIN={config.SNR_MIN}, K_LOCAL={config.K_LOCAL}.", ""]
    for k, v in parts.items():
        open(os.path.join(C.RESULTS, f"{k}.md"), "w", encoding="utf-8").write(v + "\n")
    order = [k for k in ("E1", "E2", "E3", "E3b", "E4", "E5", "E6", "E8") if k in parts]
    open(os.path.join(C.RESULTS, "summary.md"), "w", encoding="utf-8").write(
        "\n".join(head) + "\n\n".join(parts[k] for k in order) + "\n")
    print("wrote", os.path.join(C.RESULTS, "summary.md"))


if __name__ == "__main__":
    main()
