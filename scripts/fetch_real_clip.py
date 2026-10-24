"""Fetch the real demo clip from Wikimedia Commons and store it like the synthetic demos.

    python scripts/fetch_real_clip.py

"Washing machine 120fps" by Golha, CC BY-SA 4.0:
https://commons.wikimedia.org/wiki/File:Washing_machine_120fps.webm
Handheld phone, 120 fps, 1080p. The machine's display reads 1400 RPM, i.e. 23.33 Hz drum speed.
We keep 4 s (the Lambda limit) starting at 2 s, downscaled to 640 px (at 960 px the rules agent takes
~140 s, over the 120 s Lambda timeout; at 640 px ~45 s and the same frequency), as lossless luma in
clip.npz (so the Lambda path, which only reads clip.npz, works unchanged).
The clip is not committed; credit the author in anything that shows it.
"""
import argparse
import json
import os
import sys
import urllib.request

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

URL = "https://upload.wikimedia.org/wikipedia/commons/b/b4/Washing_machine_120fps.webm"
PAGE = "https://commons.wikimedia.org/wiki/File:Washing_machine_120fps.webm"
CREDIT = "\"Washing machine 120fps\" by Golha, CC BY-SA 4.0, via Wikimedia Commons"
FPS, START_S, DUR_S, WIDTH = 120.0, 2.0, 4.0, 640
RPM = 1400


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "demo_clips", "real_washer"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    src = os.path.join(a.out, "source.webm")
    if not os.path.exists(src):
        print("downloading", URL)
        req = urllib.request.Request(URL, headers={"User-Agent": "HumSight/0.1 (github.com/SanTiwari07/HumSight)"})
        with urllib.request.urlopen(req) as r, open(src + ".part", "wb") as fh:
            fh.write(r.read())
        os.replace(src + ".part", src)

    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        sys.exit(f"cannot open {src}")
    skip, n = int(START_S * FPS), int(DUR_S * FPS)
    frames = []
    i = 0
    while len(frames) < n:
        ok, f = cap.read()
        if not ok:
            break
        i += 1
        if i <= skip:
            continue
        h, w = f.shape[:2]
        f = cv2.resize(f, (WIDTH, round(h * WIDTH / w)), interpolation=cv2.INTER_AREA)
        frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2YCrCb)[..., 0])
    cap.release()
    if len(frames) < n:
        sys.exit(f"only {len(frames)} of {n} frames decoded")
    frames = np.stack(frames)
    np.savez_compressed(os.path.join(a.out, "clip.npz"), frames=frames, fps=np.float32(FPS))

    T, H, W = frames.shape
    with open(os.path.join(a.out, "gt.json"), "w", encoding="utf-8") as fh:
        json.dump({"fps": FPS, "n_frames": T, "width": W, "height": H, "real": True,
                   "expected_hz": round(RPM / 60, 2),
                   "expected_source": f"machine display reads {RPM} RPM (set spin speed, not a measurement)",
                   "source": PAGE, "credit": CREDIT, "segment_s": [START_S, START_S + DUR_S]}, fh, indent=2)
    with open(os.path.join(a.out, "demo.json"), "w", encoding="utf-8") as fh:
        json.dump({"title": f"Real washing machine at {RPM} RPM, handheld phone (120 fps)",
                   "description": f"Real footage. The display reads {RPM} RPM = {RPM / 60:.2f} Hz drum speed; "
                                  f"the camera is handheld. Source: {CREDIT}.",
                   "expect": "FAULT", "params": {}, "fps": FPS, "duration": DUR_S,
                   "credit": CREDIT, "source": PAGE}, fh, indent=2)
    print("wrote", a.out, frames.shape, f"{os.path.getsize(os.path.join(a.out, 'clip.npz')) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
