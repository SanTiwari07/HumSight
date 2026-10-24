"""Fixed (non-agent) baseline: what most motion-magnification demos do.

One grid, no shake check, take the globally strongest peak, magnify around it at
a fixed alpha = 20, bw = 2 Hz. No review or aliasing logic. Used for E5.
"""
from __future__ import annotations

import os
import time

import numpy as np

from . import config, magnify, report, spectrum
from .io import Clip
from .motion import patch_shifts
from .texture import make_grid, reference_frame


def run_fixed(clip: Clip, out_dir: str, render: bool = True, workers: int = 1,
              f_min: float | None = None, f_max: float | None = None,
              write_original: bool = True) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.perf_counter()
    ref = reference_frame(clip.frames_y)
    grid = make_grid(ref, *config.COARSE_GRID)
    ms = patch_shifts(clip.frames_y, grid, scale=clip.scale, workers=workers)
    peaks = spectrum.analyze_patches(ms.dx, ms.dy, clip.fps, grid.valid, f_min, f_max)
    out = {"policy": "fixed", "verdict": "NO_FAULT", "findings": [], "roi": None,
           "outputs": {}, "runtime_ms": 0.0, "magnified_region": None}
    if peaks:
        top = max(peaks, key=lambda p: p.amp_px)
        if top.snr >= config.SNR_MIN:
            b = grid.boxes[top.patch]
            pad_x, pad_y = int(b[2]), int(b[3])
            H, W = clip.frames_y.shape[1:]
            x0, y0 = max(0, int(b[0]) - pad_x), max(0, int(b[1]) - pad_y)
            roi = [x0, y0, min(W, int(b[0]) + 2 * pad_x) - x0, min(H, int(b[1]) + 2 * pad_y) - y0]
            out.update(verdict="FAULT", roi=roi, magnified_region=roi,
                       findings=[{"f_hz": round(top.f_hz, 3), "amp_px": round(top.amp_px, 5),
                                  "snr": round(top.snr, 2), "roi": roi, "patch": top.patch}])
            if render:
                mag = magnify.magnify_roi(clip.frames_y, clip.fps, roi, top.f_hz, 2.0, 20.0,
                                          top.amp_px, clip.scale)
                out["outputs"] = magnify.render_videos(clip, mag, out_dir, "magnified_fixed",
                                                       write_original=write_original, overlay=False)
    out["runtime_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out
