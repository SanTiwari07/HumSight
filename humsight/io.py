"""Video load/save. Clips carry luma (float32) and a re-readable BGR stream."""
from __future__ import annotations

import math
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Iterator

import cv2
import numpy as np

from . import config


@dataclass
class Clip:
    frames_y: np.ndarray                 # (T, H, W) float32 in [0, 1], luma
    fps: float                           # CAPTURE fps, not container playback fps
    path: str
    meta: dict = field(default_factory=dict)  # width, height, n_frames, container_fps, duration_s
    scale: float = 1.0                   # orig_w / processed_w; multiply px by this
    warnings: list[str] = field(default_factory=list)
    bgr_iter: Callable[[], Iterator[np.ndarray]] | None = None

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.frames_y.shape

    @property
    def n_frames(self) -> int:
        return self.frames_y.shape[0]

    def iter_bgr(self) -> Iterator[np.ndarray]:
        """Yield uint8 BGR frames at processed resolution (re-decodes the source)."""
        if self.bgr_iter is not None:
            yield from self.bgr_iter()
            return
        for f in self.frames_y:
            g = np.clip(f * 255.0 + 0.5, 0, 255).astype(np.uint8)
            yield cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def clip_from_gray(frames_u8: np.ndarray, fps: float, path: str = "<memory>",
                   scale: float = 1.0, warnings: list[str] | None = None) -> Clip:
    """Build a Clip from (T, H, W) gray frames on a 0..255 scale (uint8, or float for tests)."""
    T, H, W = frames_u8.shape
    y = frames_u8.astype(np.float32) / 255.0

    def _iter() -> Iterator[np.ndarray]:
        for f in frames_u8:
            g = f if f.dtype == np.uint8 else np.clip(f + 0.5, 0, 255).astype(np.uint8)
            yield cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

    return Clip(y, float(fps), path,
                {"width": W, "height": H, "n_frames": T, "container_fps": float(fps),
                 "duration_s": T / float(fps)},
                scale, list(warnings or []), _iter)


def load_npz(path: str, fps: float | None = None, max_frames: int | None = None) -> Clip:
    d = np.load(path)
    frames = d["frames"]
    f = float(d["fps"]) if "fps" in d.files else fps
    if fps is not None:
        f = float(fps)
    if f is None:
        raise ValueError("npz has no fps and none was given")
    n = min(len(frames), max_frames or config.MAX_FRAMES, int(config.MAX_DURATION_S * f))
    warnings = [f"clip truncated to first {n} frames ({n / f:.2f} s)"] if n < len(frames) else []
    return clip_from_gray(np.ascontiguousarray(frames[:n]), f, path, warnings=warnings)


def _target_size(w: int, h: int, n_frames: int, max_width: int) -> tuple[int, int, float]:
    nw = min(w, max_width)
    while n_frames * nw * round(h * nw / w) > config.MAX_VOLUME and nw > 160:
        nw = int(nw * 0.9)
    nh = int(round(h * nw / w))
    return nw, nh, w / nw


def load_video(path: str, capture_fps: float | None = None,
               max_duration_s: float | None = None, max_frames: int | None = None,
               max_width: int | None = None) -> Clip:
    """Decode up to the limits, convert to luma, downscale with INTER_AREA.

    capture_fps overrides the container fps (slow-motion files store a playback
    rate such as 30 even when captured at 240).
    """
    if path.lower().endswith(".npz"):
        return load_npz(path, capture_fps, max_frames)
    max_duration_s = max_duration_s or config.MAX_DURATION_S
    max_frames = max_frames or config.MAX_FRAMES
    max_width = max_width or config.MAX_WIDTH

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {path}")
    container_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h0 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    warnings: list[str] = []
    if capture_fps:
        fps = float(capture_fps)
    else:
        fps = float(container_fps)
        warnings.append("fps taken from file metadata; slow-motion clips may be mislabelled")
    if not fps or fps <= 0:
        cap.release()
        raise ValueError("fps unknown: provide capture_fps")

    n_max = min(max_frames, int(max_duration_s * fps))
    if total > 0:
        n_max = min(n_max, total)
    if total > 0 and total > n_max:
        warnings.append(f"clip truncated to first {n_max} frames ({n_max / fps:.2f} s)")
    nw, nh, scale = _target_size(w0, h0, n_max, max_width)

    ys = np.empty((n_max, nh, nw), np.float32)
    n = 0
    while n < n_max:
        ok, f = cap.read()
        if not ok:
            break
        if (nw, nh) != (w0, h0):
            f = cv2.resize(f, (nw, nh), interpolation=cv2.INTER_AREA)
        ys[n] = cv2.cvtColor(f, cv2.COLOR_BGR2YCrCb)[..., 0].astype(np.float32) / 255.0
        n += 1
    cap.release()
    if n < 8:
        raise ValueError(f"too few frames decoded ({n})")
    ys = ys[:n]

    def _iter() -> Iterator[np.ndarray]:
        c = cv2.VideoCapture(path)
        for _ in range(n):
            ok, f = c.read()
            if not ok:
                break
            if (nw, nh) != (w0, h0):
                f = cv2.resize(f, (nw, nh), interpolation=cv2.INTER_AREA)
            yield f
        c.release()

    meta = {"width": w0, "height": h0, "proc_width": nw, "proc_height": nh, "n_frames": n,
            "container_fps": container_fps, "duration_s": n / fps}
    return Clip(ys, fps, path, meta, scale, warnings, _iter)


# --- writing ----------------------------------------------------------------

_CODECS = [("avc1", ".mp4"), ("VP80", ".webm"), ("mp4v", ".mp4")]
_WORKING: list[tuple[str, str]] = []


class VideoSink:
    """Write frames with the first codec the build supports. Records which."""

    def __init__(self, stem: str, size: tuple[int, int], fps: float = config.PLAYBACK_FPS):
        self.size = size  # (w, h)
        self.fps = fps
        self.writer = None
        self.path = None
        self.codec = None
        self.frames: list[np.ndarray] | None = None
        # remember the first codec that works so the probe errors are printed once per process
        forced = os.environ.get("HUMSIGHT_FORCE_CODEC")   # benchmarks force one codec so builds are comparable
        if forced:
            order = [c for c in _CODECS if c[0] == forced]
        else:
            order = ([_WORKING[0]] if _WORKING else []) + [c for c in _CODECS if not _WORKING or c != _WORKING[0]]
        for fourcc, ext in order:
            p = stem + ext
            if os.path.exists(p):
                os.remove(p)
            w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*fourcc), fps, size)
            if w.isOpened():
                self.writer, self.path, self.codec = w, p, fourcc
                _WORKING[:] = [(fourcc, ext)]
                break
            w.release()
        if self.writer is None:
            raise RuntimeError("no usable VideoWriter codec in this OpenCV build")

    def write(self, frame_bgr: np.ndarray) -> None:
        self.writer.write(frame_bgr)

    def close(self) -> str:
        self.writer.release()
        if self.codec == "mp4v":
            self.path = _make_browser_playable(self.path)
        return self.path


def _make_browser_playable(path: str) -> str:
    """mp4v rarely plays in browsers: transcode to H.264 when ffmpeg exists."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return path
    out = path[:-4] + "_h264.mp4"
    try:
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", path, "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                       check=True, timeout=120)
        os.replace(out, path)
    except Exception:
        pass
    return path


def write_video(frames_bgr, stem: str, fps: float = config.PLAYBACK_FPS) -> tuple[str, str]:
    """Write an iterable of BGR frames. Returns (path, codec)."""
    it = iter(frames_bgr)
    first = next(it)
    h, w = first.shape[:2]
    sink = VideoSink(stem, (w, h), fps)
    sink.write(first)
    for f in it:
        sink.write(f)
    return sink.close(), sink.codec


def probe_codecs(tmp_dir: str) -> dict[str, bool]:
    """Day-1 check: which codecs actually open in this OpenCV build."""
    res = {}
    for fourcc, ext in _CODECS:
        p = os.path.join(tmp_dir, f"codec_probe_{fourcc}{ext}")
        w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*fourcc), 30, (64, 64))
        res[fourcc] = bool(w.isOpened())
        w.release()
        if os.path.exists(p):
            os.remove(p)
    return res


def nyquist_bins(fps: float, n: int) -> tuple[float, float]:
    return fps / 2.0, fps / n


def required_fps(f_expected: float) -> int:
    return int(math.ceil(2.5 * f_expected))
