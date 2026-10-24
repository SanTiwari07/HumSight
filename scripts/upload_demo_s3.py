"""Upload the demo clips to s3://BUCKET/demo/<id>/ with a browser-playable original.webm.

    python scripts/make_demo_clips.py
    BUCKET=humsight-xxxx python scripts/upload_demo_s3.py [--only real_washer ...]

Uploads clip.npz, demo.json, gt.json and original.webm (the clip re-encoded at 30 fps playback, so the
page can show the original next to the magnified ROI). Needs AWS credentials (boto3). Not run by the tests.
"""
import argparse
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import boto3  # noqa: E402

from humsight.io import VideoSink, load_video  # noqa: E402

BUCKET = os.environ["BUCKET"]
DEMO_ROOT = os.path.join(ROOT, "demo_clips")


def main():
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    s3 = boto3.client("s3")
    for demo in sorted(os.listdir(DEMO_ROOT)):
        if a.only and demo not in a.only:
            continue
        d = os.path.join(DEMO_ROOT, demo)
        if not os.path.exists(os.path.join(d, "clip.npz")):
            continue
        meta = json.load(open(os.path.join(d, "demo.json"), encoding="utf-8"))
        clip = load_video(os.path.join(d, "clip.npz"), meta["fps"])
        H, W = clip.frames_y.shape[1:]
        with tempfile.TemporaryDirectory() as tmp:
            sink = VideoSink(os.path.join(tmp, "original"), (W, H))
            for f in clip.iter_bgr():
                sink.write(f)
            webm = sink.close()
            if not webm.endswith(".webm"):
                print(f"skip original for {demo}: this OpenCV build wrote {webm}, not .webm")
                webm = None
            for name in ("clip.npz", "demo.json", "gt.json"):
                s3.upload_file(os.path.join(d, name), BUCKET, f"demo/{demo}/{name}")
            if webm:
                s3.upload_file(webm, BUCKET, f"demo/{demo}/original.webm",
                               ExtraArgs={"ContentType": "video/webm"})
        print("uploaded", demo)


if __name__ == "__main__":
    main()
