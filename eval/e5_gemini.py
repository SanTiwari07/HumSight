"""E5 with the live Gemini policy: the same 12 clips as run_all.py, run sequentially against the real API.

    python eval/e5_gemini.py            # needs GEMINI_API_KEY (from .env); resumes if interrupted
    python eval/e5_gemini.py --fresh    # ignore saved progress

Calls are paced (GEMINI_MIN_INTERVAL_S, default 7 s) to respect free-tier rate limits. Nothing is hidden:
if the API fails mid-job the agent falls back to the rules policy, and the per-clip record says how many
tool calls were really chosen by the model (source == "llm") and how many were not. Writes
eval/results/e5_gemini.json (with a note), eval/results/e5_gemini.md and refreshes the E5 block in
eval/results/E5.md and eval/results/summary.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from run_all import e5_clips, e5_judge, e5_table  # noqa: E402

from humsight import env  # noqa: E402
from humsight.agent import provider_gemini  # noqa: E402
from humsight.agent.loop import run_agent  # noqa: E402
from humsight.agent.state import JobParams, JobState  # noqa: E402
from humsight.io import clip_from_gray  # noqa: E402

OUT = os.path.join(C.RESULTS, "e5_gemini.json")


def run_one(sp: dict) -> dict:
    frames, _ = C.generate(sp)
    clip = clip_from_gray(frames, sp["fps"])
    t0 = time.time()
    error = None
    with tempfile.TemporaryDirectory() as d:
        st = JobState(clip, JobParams(policy="llm", render=False), d)
        try:
            r = run_agent(st)
        except Exception as e:  # keep going: a crash is a result too
            return {"verdict": "ERROR", "findings": [], "n_calls": 0, "source": "error", "error": f"{type(e).__name__}: {e}"[:300],
                    "tools": [], "tool_sources": [], "notes": [], "llm_calls": 0, "runtime_s": round(time.time() - t0, 1)}
    tools = [e for e in r["trace"] if e["kind"] == "tool"]
    notes = [e["rationale"] for e in r["trace"] if e["kind"] == "note"]
    return {"verdict": r["verdict"], "findings": r["findings"], "n_calls": r["n_tool_calls"], "source": r["source"],
            "tools": [e["tool"] for e in tools], "tool_sources": [e["source"] for e in tools],
            "llm_calls": sum(1 for e in tools if e["source"] == "llm"), "notes": notes,
            "summary": r.get("summary"), "reason": r.get("reason"), "runtime_s": round(time.time() - t0, 1), "error": error}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    env.load_dotenv(os.path.join(C.ROOT, ".env"))
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set (put it in .env)")
    os.environ.setdefault("GEMINI_MIN_INTERVAL_S", "7")
    os.environ.setdefault("GEMINI_RETRY_SLEEP_S", "20")

    clips = e5_clips(False)
    done: list[dict] = []
    if os.path.exists(OUT) and not a.fresh:
        done = json.load(open(OUT, encoding="utf-8")).get("results", [])
    started = dt.datetime.now(dt.timezone.utc)
    for i, (name, sp, expect) in enumerate(clips):
        if i < len(done):
            continue
        print(f"[{i + 1}/{len(clips)}] {name} ...", flush=True)
        rec = run_one(sp)
        rec["name"] = name
        done.append(rec)
        ok, ms = e5_judge(sp, expect, rec)
        print(f"    -> {rec['verdict']} ({'correct' if ok else 'WRONG'}) llm_calls={rec['llm_calls']}/{rec['n_calls']} "
              f"{rec['runtime_s']}s notes={len(rec['notes'])}", flush=True)
        json.dump({"results": done, "model": provider_gemini.DEFAULT_MODEL}, open(OUT, "w", encoding="utf-8"), indent=1)

    # report
    n_full = sum(1 for r in done if r["n_calls"] and r["llm_calls"] == r["n_calls"])
    n_fb = sum(1 for r in done if r["source"].startswith("rules"))
    n_guard = sum(1 for r in done for x in r["notes"] if "guard" in x.lower())
    tot_calls = sum(r["n_calls"] for r in done)
    llm_calls = sum(r["llm_calls"] for r in done)
    note = (f"Gemini column: live API run on {started:%Y-%m-%d} (model `{provider_gemini.DEFAULT_MODEL}`, sequential, "
            f"paced at {os.environ['GEMINI_MIN_INTERVAL_S']} s between calls). {llm_calls} of {tot_calls} tool calls were "
            f"chosen by the model; {n_full} of {len(done)} clips ran entirely on Gemini and {n_fb} fell back to the rules policy "
            f"partway; the number guard fired {n_guard} time(s).")
    g = json.load(open(OUT, encoding="utf-8"))
    g["note"] = note
    g["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    json.dump(g, open(OUT, "w", encoding="utf-8"), indent=1)

    e5 = json.load(open(os.path.join(C.RESULTS, "e5.json"), encoding="utf-8"))
    table = e5_table(clips, e5["rules"], e5["fixed"], done, note)

    detail = ["", "### Gemini run details", "",
              C.md_table(["clip", "verdict", "tool calls (model / total)", "tool sequence", "fallback / guard notes", "seconds"],
                         [[r["name"], r["verdict"] + (f" ({r['error']})" if r.get("error") else ""),
                           f"{r['llm_calls']}/{r['n_calls']}", " > ".join(t.replace('_', ' ') for t in r["tools"]),
                           "; ".join(x[:70] for x in r["notes"]) or "-", r["runtime_s"]] for r in done])]
    # does the model choose a different sequence from the rules policy?
    diff = sum(1 for r, rr in zip(done, e5["rules"]) if r["tools"] != rr.get("tools"))
    detail += ["", f"The model's tool sequence differed from the rules policy's on {diff} of {len(done)} clips."]
    text = table + "\n".join(detail)
    open(os.path.join(C.RESULTS, "E5.md"), "w", encoding="utf-8", newline="\n").write(text + "\n")

    sp = os.path.join(C.RESULTS, "summary.md")
    s = open(sp, encoding="utf-8", newline="").read().replace("\r\n", "\n")
    m = re.search(r"## E5 Agent vs fixed pipeline.*?(?=\n## E6)", s, re.S)
    if m:
        s = s[:m.start()] + text + "\n" + s[m.end():]
        open(sp, "w", encoding="utf-8", newline="\n").write(s)
    print("\n" + note)


if __name__ == "__main__":
    main()
