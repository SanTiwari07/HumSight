"""Sub-pixel patch shifts with phase correlation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np

from . import config
from .texture import PatchGrid, reference_frame


@dataclass
class MotionSeries:
    dx: np.ndarray        # (N, T) px (ORIGINAL pixel units), relative to the reference
    dy: np.ndarray        # (N, T)
    response: np.ndarray  # (N, T) phaseCorrelate peak response (quality)


def has_iterative() -> bool:
    return hasattr(cv2, "phaseCorrelateIterative")


def _pick_phase_correlate(use_iterative: bool | None):
    """Return fn(ref, cur, win) -> ((dx, dy), response)."""
    if use_iterative is None:
        # Measured on synthetic textures (see eval E2): the iterative variant with
        # a Hann pre-window and L2size=5 stays within ~8% amplitude at sigma=0.005;
        # plain cv2.phaseCorrelate gave gross outliers on blurred-noise textures.
        use_iterative = has_iterative()
    if use_iterative and has_iterative():
        def pc(r, c, win):
            sh = cv2.phaseCorrelateIterative(r * win, c * win, config.ITER_L2SIZE)
            return (sh[0], sh[1]), 1.0
        return pc

    def pc(r, c, win):
        return cv2.phaseCorrelate(r, c, win)
    return pc


def _run_patch(frames_y, box, ref, win, pc, T):
    x, y, w, h = [int(v) for v in box]
    r = np.ascontiguousarray(ref[y:y + h, x:x + w])
    out = np.empty((3, T), np.float32)
    for t in range(T):
        c = np.ascontiguousarray(frames_y[t, y:y + h, x:x + w])
        (sx, sy), rv = pc(r, c, win)
        out[0, t], out[1, t], out[2, t] = sx, sy, rv
    return out


def patch_shifts(frames_y: np.ndarray, grid_or_boxes, ref_mode: str = "first",
                 use_iterative: bool | None = None, scale: float = 1.0,
                 workers: int = 1, valid_only: bool = False) -> MotionSeries:
    """Phase-correlate every patch against the reference frame.

    Output is multiplied by `scale` so downstream amplitudes are in original
    pixels. Patches that are not valid keep zeros when valid_only is set.
    """
    boxes = grid_or_boxes.boxes if isinstance(grid_or_boxes, PatchGrid) else np.asarray(grid_or_boxes)
    T = frames_y.shape[0]
    N = len(boxes)
    dx = np.zeros((N, T), np.float32)
    dy = np.zeros_like(dx)
    resp = np.zeros_like(dx)
    ref = frames_y[0] if ref_mode == "first" else reference_frame(frames_y, 30)
    pc = _pick_phase_correlate(use_iterative)
    todo = list(range(N))
    if valid_only and isinstance(grid_or_boxes, PatchGrid):
        todo = [i for i in todo if grid_or_boxes.valid[i]]

    wins: dict[tuple[int, int], np.ndarray] = {}

    def job(i):
        w, h = int(boxes[i][2]), int(boxes[i][3])
        win = wins.setdefault((w, h), cv2.createHanningWindow((w, h), cv2.CV_32F))
        return i, _run_patch(frames_y, boxes[i], ref, win, pc, T)

    if workers > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(job, todo))
    else:
        results = [job(i) for i in todo]
    for i, o in results:
        dx[i], dy[i], resp[i] = o
    if scale != 1.0:
        dx *= scale
        dy *= scale
    return MotionSeries(dx, dy, resp)
