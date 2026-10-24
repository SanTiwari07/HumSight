"""Run a real command, keep its transcript with real timings, and render it as PNG + MP4 evidence.

    python scripts/evidence_terminal.py NAME --title "ubuntu@host: ~/humsight" \
        --shown 'python scripts/verify_cool.py' --caption "..." -- bash -c 'ssh ... "cmd"'

Writes evidence/NAME/{transcript.json,transcript.txt,screenshot.png,recording.mp4}.

What this is: a faithful re-rendering of a real session (every character of output is the command's
actual output, with its real arrival times; idle gaps longer than --max-gap seconds are shortened).
It is NOT a pixel capture of a screen, and the images say so in their footer.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BG, BAR, FG = (25, 25, 28), (44, 44, 48), (232, 226, 214)
DIM, ACC, PROMPT = (150, 148, 140), (222, 170, 97), (132, 160, 113)
W = 1280
FONT_SIZE = 17
PAD = 22
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _font(size: int) -> ImageFont.FreeTypeFont:
    import matplotlib
    cands = ["C:/Windows/Fonts/consola.ttf",
             os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf", "DejaVuSansMono.ttf")]
    for c in cands:
        if os.path.exists(c):
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def capture(argv: list[str], timeout: float) -> tuple[list[tuple[float, str]], int]:
    """Run argv, return ([(seconds_since_start, text_chunk)], exit_code)."""
    t0 = time.monotonic()
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    events: list[tuple[float, str]] = []

    def pump():
        while True:
            chunk = p.stdout.read1(4096)
            if not chunk:
                break
            events.append((time.monotonic() - t0, chunk.decode("utf-8", "replace")))

    th = threading.Thread(target=pump, daemon=True)
    th.start()
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
    th.join(timeout=5)
    return events, p.returncode if p.returncode is not None else -1


def clean(text: str) -> str:
    return ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def compress(events, max_gap: float):
    """Shorten idle gaps so the video stays watchable. Returns (events, original_seconds, shown_seconds)."""
    out, last_real, t = [], 0.0, 0.0
    for real, txt in events:
        t += min(real - last_real, max_gap)
        last_real = real
        out.append((t, txt))
    return out, (events[-1][0] if events else 0.0), t


def wrap(lines: list[str], cols: int) -> list[str]:
    out = []
    for ln in lines:
        ln = ln.expandtabs(4)
        if not ln:
            out.append("")
        while ln:
            out.append(ln[:cols])
            ln = ln[cols:]
    return out


def draw_frame(lines: list[str], title: str, footer: str, height: int, cursor: bool = True):
    font, small = _font(FONT_SIZE), _font(13)
    cw = font.getlength("M")
    lh = FONT_SIZE + 6
    top = 46
    img = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 34], fill=BAR)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse([16 + i * 22, 11, 28 + i * 22, 23], fill=c)
    d.text((W / 2 - small.getlength(title) / 2, 9), title, font=small, fill=DIM)
    rows = int((height - top - 34) // lh)
    cols = int((W - 2 * PAD) // cw)
    vis = wrap(lines, cols)[-rows:]
    for i, ln in enumerate(vis):
        color = PROMPT if ln.startswith("$ ") else FG
        d.text((PAD, top + i * lh), ln, font=font, fill=color)
    if cursor and vis:
        x = PAD + font.getlength(vis[-1]) + 2
        d.rectangle([x, top + (len(vis) - 1) * lh + 3, x + cw * 0.6, top + (len(vis) - 1) * lh + lh - 3], fill=ACC)
    d.rectangle([0, height - 30, W, height], fill=BAR)
    d.text((PAD, height - 23), footer, font=small, fill=DIM)
    return img


def render(events, shown: str, title: str, caption: str, outdir: str, max_gap: float,
           rendered_note: str) -> dict:
    head = f"$ {shown}\n"
    txt = clean("".join(e[1] for e in events))
    full_lines = (head + txt).rstrip("\n").split("\n")
    font = _font(FONT_SIZE)
    cols = int((W - 2 * PAD) // font.getlength("M"))
    n_lines = len(wrap(full_lines, cols))
    lh = FONT_SIZE + 6
    height = max(360, min(1500, 46 + 34 + n_lines * lh + 24))
    footer = f"{caption} | {rendered_note}"
    png = os.path.join(outdir, "screenshot.png")
    draw_frame(full_lines, title, footer, height, cursor=False).save(png)

    # video: fixed 1280x720, scrolling, frames at output-arrival times
    comp, real_s, shown_s = compress(events, max_gap)
    frames, durations = [], []
    acc = head
    states = [(0.0, acc)]
    bucket_t = -1.0
    for t, chunk in comp:
        acc += chunk
        if t - bucket_t >= 0.15:
            states.append((t, acc))
            bucket_t = t
        else:
            states[-1] = (states[-1][0], acc)
    if states[-1][1] != acc:
        states.append((comp[-1][0] if comp else 0.0, acc))
    framedir = os.path.join(outdir, "_frames")
    os.makedirs(framedir, exist_ok=True)
    listing = []
    for i, (t, s) in enumerate(states):
        lines = clean(s).rstrip("\n").split("\n")
        fn = os.path.join(framedir, f"f{i:05d}.png")
        draw_frame(lines, title, footer, 720, cursor=(i < len(states) - 1) or True).save(fn)
        nxt = states[i + 1][0] if i + 1 < len(states) else t + 4.0
        listing.append((fn, max(0.04, nxt - t)))
    lst = os.path.join(framedir, "list.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        for fn, du in listing:
            fh.write(f"file '{fn.replace(os.sep, '/')}'\nduration {du:.3f}\n")
        fh.write(f"file '{listing[-1][0].replace(os.sep, '/')}'\n")
    mp4 = os.path.join(outdir, "recording.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                        "-vf", "format=yuv420p", "-c:v", "libx264", "-crf", "20", "-r", "20", mp4],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("ffmpeg failed:", r.stderr[:300])
        mp4 = None
    for fn, _ in listing:
        os.remove(fn)
    os.remove(lst)
    os.rmdir(framedir)
    return {"png": png, "mp4": mp4, "real_seconds": round(real_s, 2), "video_seconds": round(shown_s + 4, 2),
            "frames": len(listing)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("--title", default="terminal")
    ap.add_argument("--shown", required=True, help="the command line shown in the image (must match what runs)")
    ap.add_argument("--caption", default="")
    ap.add_argument("--max-gap", type=float, default=1.5)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--out-root", default=os.path.join(ROOT, "evidence"))
    argv = sys.argv[1:]
    if "--" not in argv:
        ap.error("put the command after --")
    i = argv.index("--")
    a = ap.parse_args(argv[:i])
    cmd = argv[i + 1:]
    outdir = os.path.join(a.out_root, a.name)
    os.makedirs(outdir, exist_ok=True)
    started = dt.datetime.now(dt.timezone.utc)
    events, code = capture(cmd, a.timeout)
    note = f"rendered from a real session transcript, {started:%Y-%m-%d %H:%M} UTC; not a pixel screen capture"
    info = render(events, a.shown, a.title, a.caption, outdir, a.max_gap, note)
    with open(os.path.join(outdir, "transcript.json"), "w", encoding="utf-8") as fh:
        json.dump({"shown_command": a.shown, "title": a.title, "caption": a.caption,
                   "started_utc": started.isoformat(timespec="seconds"), "exit_code": code,
                   "events": [{"t": round(t, 3), "text": s} for t, s in events]}, fh, indent=1)
    with open(os.path.join(outdir, "transcript.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"$ {a.shown}\n" + clean("".join(e[1] for e in events)))
    print(json.dumps({"name": a.name, "exit": code, **info}))


if __name__ == "__main__":
    sys.exit(main())
