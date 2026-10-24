"""E5 with the live Gemini policy: the same 12 clips as run_all.py, run sequentially against the real API.

    python eval/e5_gemini.py --tag after           # needs GEMINI_API_KEY (from .env); resumes if interrupted
    python eval/e5_gemini.py --tag after --fresh   # ignore saved progress

Two labelled runs are kept side by side in the results:
  before  the first run, before `file_report` was changed to refuse a stale classification
  after   the rerun with that change (file_report returns an error telling the model to run classify_peaks)

Calls are paced (GEMINI_MIN_INTERVAL_S, default 7 s) to respect free-tier rate limits. Nothing is hidden:
if the API fails mid-job the agent falls back to the rules policy, and the per-clip record says how many
tool calls were really chosen by the model (source == "llm"). Writes eval/results/e5_gemini_<tag>.json and
refreshes eval/results/E5.md and the E5 block of eval/results/summary.md with every run found.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
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


def run_one(sp: dict) -> dict:
    frames, _ = C.generate(sp)
    clip = clip_from_gray(frames, sp["fps"])
    t0 = time.time()
    with tempfile.TemporaryDirectory() as d:
        st = JobState(clip, JobParams(policy="llm", render=False), d)
        try:
            r = run_agent(st)
        except Exception as e:  # keep going: a crash is a result too
            return {"verdict": "ERROR", "findings": [], "n_calls": 0, "source": "error", "error": f"{type(e).__name__}: {e}"[:300],
                    "tools": [], "tool_sources": [], "notes": [], "llm_calls": 0, "tool_errors": 0,
                    "stale_report_errors": 0, "runtime_s": round(time.time() - t0, 1)}
    tools = [e for e in r["trace"] if e["kind"] == "tool"]
    notes = [e["rationale"] for e in r["trace"] if e["kind"] == "note"]
    return {"verdict": r["verdict"], "findings": r["findings"], "n_calls": r["n_tool_calls"], "source": r["source"],
            "tools": [e["tool"] for e in tools], "tool_sources": [e["source"] for e in tools],
            "llm_calls": sum(1 for e in tools if e["source"] == "llm"), "notes": notes,
            "tool_errors": sum(1 for e in tools if "error" in e["result"]),
            "stale_report_errors": sum(1 for e in tools if e["tool"] == "file_report" and "error" in e["result"]
                                       and "classify_peaks" in str(e["result"]["error"])),
            "summary": r.get("summary"), "reason": r.get("reason"), "runtime_s": round(time.time() - t0, 1), "error": None}


def commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=C.ROOT).stdout.strip()
    except Exception:
        return "unknown"


def make_note(tag: str, g: dict) -> str:
    res = g["results"]
    n_full = sum(1 for r in res if r["n_calls"] and r["llm_calls"] == r["n_calls"])
    n_fb = sum(1 for r in res if r["source"].startswith("rules"))
    n_guard = sum(1 for r in res for x in r["notes"] if "guard" in x.lower())
    tot, llm = sum(r["n_calls"] for r in res), sum(r["llm_calls"] for r in res)
    stale = sum(r.get("stale_report_errors", 0) for r in res)
    return (f"live API run on {g['started_utc'][:10]} (model `{g['model']}`, code at commit `{g['commit']}`, sequential, "
            f"paced at {g['interval_s']} s between calls): {llm} of {tot} tool calls were chosen by the model; "
            f"{n_full} of {len(res)} clips ran entirely on Gemini and {n_fb} fell back to the rules policy partway; "
            f"the number guard fired {n_guard} time(s); `file_report` was refused for a stale classification {stale} time(s).")


def details(label: str, res: list[dict]) -> list[str]:
    return ["", f"### Gemini run details ({label})", "",
            C.md_table(["clip", "verdict", "calls (model / total)", "tool sequence", "refusals / guard notes", "seconds"],
                       [[r["name"], r["verdict"] + (f" ({r['error']})" if r.get("error") else ""),
                         f"{r['llm_calls']}/{r['n_calls']}", " > ".join(t.replace('_', ' ') for t in r["tools"]),
                         "; ".join(([f"file_report refused x{r['stale_report_errors']}"] if r.get("stale_report_errors") else [])
                                   + [x[:60] for x in r["notes"]]) or "-", r["runtime_s"]] for r in res])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", choices=["before", "after"], required=True)
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    env.load_dotenv(os.path.join(C.ROOT, ".env"))
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set (put it in .env)")
    os.environ.setdefault("GEMINI_MIN_INTERVAL_S", "7")
    os.environ.setdefault("GEMINI_RETRY_SLEEP_S", "20")
    out = os.path.join(C.RESULTS, f"e5_gemini_{a.tag}.json")

    clips = e5_clips(False)
    g = {"results": [], "model": provider_gemini.DEFAULT_MODEL, "commit": commit(), "tag": a.tag,
         "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
         "interval_s": os.environ["GEMINI_MIN_INTERVAL_S"]}
    if os.path.exists(out) and not a.fresh:
        g = json.load(open(out, encoding="utf-8"))
    for i, (name, sp, expect) in enumerate(clips):
        if i < len(g["results"]):
            continue
        print(f"[{i + 1}/{len(clips)}] {name} ...", flush=True)
        rec = run_one(sp)
        rec["name"] = name
        g["results"].append(rec)
        ok, _ = e5_judge(sp, expect, rec)
        print(f"    -> {rec['verdict']} ({'correct' if ok else 'WRONG'}) llm_calls={rec['llm_calls']}/{rec['n_calls']} "
              f"refused={rec['stale_report_errors']} {rec['runtime_s']}s notes={len(rec['notes'])}", flush=True)
        json.dump(g, open(out, "w", encoding="utf-8"), indent=1)
    g["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    g["note"] = make_note(a.tag, g)
    json.dump(g, open(out, "w", encoding="utf-8"), indent=1)

    # report every labelled run that exists, side by side
    runs, notes, det = [], [], []
    for lab in ("before", "after"):
        p = os.path.join(C.RESULTS, f"e5_gemini_{lab}.json")
        if os.path.exists(p):
            gg = json.load(open(p, encoding="utf-8"))
            if len(gg["results"]) == len(clips):
                runs.append((lab, gg["results"]))
                notes.append(f"**Gemini, {lab}** " + gg.get("note", make_note(lab, gg)))
                det += details(lab, gg["results"])
    e5 = json.load(open(os.path.join(C.RESULTS, "e5.json"), encoding="utf-8"))
    text = e5_table(clips, e5["rules"], e5["fixed"], runs, "\n\n".join(notes))
    if len(runs) == 2:
        (_, rb), (_, ra) = runs
        n_diff = sum(1 for x, y in zip(rb, ra) if x["tools"] != y["tools"])
        refused = sum(y.get("stale_report_errors", 0) for y in ra)
        ok_b = sum(e5_judge(sp, ex, x)[0] for (_, sp, ex), x in zip(clips, rb))
        ok_a = sum(e5_judge(sp, ex, y)[0] for (_, sp, ex), y in zip(clips, ra))
        text += ("\n\n'before' = the first run, when `file_report` silently downgraded a verdict filed without a current "
                 "classification; 'after' = the rerun in which `file_report` returns an error telling the model to run "
                 "`classify_peaks`. Both runs used the same clips, model, prompt and settings, one run per clip each.\n\n"
                 f"**How to read the difference ({ok_b}/{len(clips)} before, {ok_a}/{len(clips)} after).** In the 'after' run the new refusal "
                 f"fired {refused} time(s), so the change was never exercised against the live model. The model's tool sequence "
                 f"nevertheless differed between the two runs on {n_diff} of {len(clips)} clips. The change of outcome on the "
                 "failing clip therefore cannot be credited to the change: it is consistent with ordinary run-to-run variation "
                 "of the model, and one run each cannot separate the two. What the change is known to do is covered by unit tests "
                 "with a scripted model (a stale `file_report` is refused, the model can classify again and then file).")
    text += "\n".join(det)
    open(os.path.join(C.RESULTS, "E5.md"), "w", encoding="utf-8", newline="\n").write(text + "\n")
    sp_ = os.path.join(C.RESULTS, "summary.md")
    s = open(sp_, encoding="utf-8", newline="").read().replace("\r\n", "\n")
    m = re.search(r"## E5 Agent vs fixed pipeline.*?(?=\n## E6)", s, re.S)
    if m:
        s = s[:m.start()] + text + "\n" + s[m.end():]
        open(sp_, "w", encoding="utf-8", newline="\n").write(s)
    print("\n" + g["note"])


if __name__ == "__main__":
    main()
