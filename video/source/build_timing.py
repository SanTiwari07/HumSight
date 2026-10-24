"""Builds timing.js (scene starts, narration, captions) and recindex.js (screencast frame lookup)."""
import json, re, subprocess, os

HERE = os.path.dirname(os.path.abspath(__file__))
LEAD, TAIL = 0.5, 0.7
EXTRA = {"cold": 0.8, "aws": 4.0, "close": 3.5}
CHAPTER = {"cold": "", "title": "", "problem": "01 · The problem", "users": "02 · Who it's for",
           "idea": "03 · Our idea", "agent": "04 · How we solve it", "aws": "05 · How it runs on AWS",
           "proof": "05 · How it runs on AWS", "demo1": "06 · Live demo", "demo2": "06 · Live demo",
           "demo3": "06 · Live demo", "fixed": "07 · Why the agent matters", "alias": "08 · When it can't tell",
           "washer": "09 · Real footage", "results": "10 · Results", "close": ""}


def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", path]).decode().strip())


def captions(text, start, length):
    # sentence-ish chunks, timed in proportion to their length
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    chunks = []
    for p in parts:  # split long sentences at commas
        if len(p) > 95:
            sub = re.split(r"(?<=,)\s+", p)
            cur = ""
            for s in sub:
                if cur and len(cur) + len(s) > 95:
                    chunks.append(cur); cur = s
                else:
                    cur = (cur + " " + s).strip()
            if cur: chunks.append(cur)
        else:
            chunks.append(p)
    total = sum(len(c) + 8 for c in chunks)
    out, t = [], start
    for c in chunks:
        d = length * (len(c) + 8) / total
        out.append({"t0": round(t, 3), "t1": round(t + d, 3), "text": c})
        t += d
    return out


items = json.load(open(os.path.join(HERE, "narration.json"), encoding="utf-8"))
scenes, t = [], 0.0
for it in items:
    vo = dur(os.path.join(HERE, "vo", it["id"] + ".wav"))
    d = LEAD + vo + TAIL + EXTRA.get(it["id"], 0)
    scenes.append({"id": it["id"], "start": round(t, 3), "dur": round(d, 3), "voStart": LEAD, "voDur": round(vo, 3),
                   "text": it["text"], "chapter": CHAPTER[it["id"]],
                   "captions": captions(it["text"], LEAD, vo)})
    t += d
timing = {"scenes": scenes, "total": round(t, 3), "fps": 30}
open(os.path.join(HERE, "timing.js"), "w", encoding="utf-8").write("window.TIMING = " + json.dumps(timing) + ";\n")
print("total", round(t, 2), "s")

rec = {}
for seg in ["pump_agent", "pump_fixed", "alias", "washer"]:
    d = json.load(open(os.path.join(HERE, "rec", seg, "index.json")))
    t0 = d["frames"][0]["t"]
    rec[seg] = {"t": [round(f["t"] - t0, 3) for f in d["frames"]], "f": [f["name"] for f in d["frames"]],
                "marks": {m["label"]: round(m["t"] - t0, 2) for m in d["marks"]}}
open(os.path.join(HERE, "recindex.js"), "w", encoding="utf-8").write("window.REC = " + json.dumps(rec) + ";\n")
