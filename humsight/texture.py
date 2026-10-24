"""Patch grids and texture scoring: which patches can be trusted."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from . import config


@dataclass
class PatchGrid:
    boxes: np.ndarray          # (N, 4) x, y, w, h  (processed-pixel units)
    rows: int
    cols: int
    texture: np.ndarray        # (N,)
    valid: np.ndarray          # (N,) bool
    is_background: np.ndarray  # (N,) bool

    @property
    def n(self) -> int:
        return len(self.boxes)

    def centers(self) -> np.ndarray:
        b = self.boxes
        return np.column_stack([b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2])


def reference_frame(frames_y: np.ndarray, n: int = 8) -> np.ndarray:
    return frames_y[: min(len(frames_y), n)].mean(0).astype(np.float32)


def texture_map(ref: np.ndarray) -> np.ndarray:
    """Per-pixel gradient energy Sobel_x^2 + Sobel_y^2 on a lightly smoothed reference."""
    r = cv2.GaussianBlur(ref, (0, 0), 1.0)
    gx = cv2.Sobel(r, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(r, cv2.CV_32F, 0, 1, ksize=3)
    return gx * gx + gy * gy


def _score(emap: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    return np.array([emap[y:y + h, x:x + w].mean() for x, y, w, h in boxes], np.float32)


def make_grid(ref: np.ndarray, cols: int, rows: int,
              bg_roi: tuple[int, int, int, int] | None = None) -> PatchGrid:
    """Tile the whole frame into cols x rows patches.

    Background = outer ring of the grid, or everything outside bg_roi's
    complement when the user marks the machine ("this is the machine").
    """
    H, W = ref.shape
    pw, ph = W // cols, H // rows
    boxes = np.array([[c * pw, r * ph, pw, ph] for r in range(rows) for c in range(cols)], np.int32)
    emap = texture_map(ref)
    tex = _score(emap, boxes)
    valid = tex > config.TEXTURE_MIN
    idx = np.arange(len(boxes))
    r_i, c_i = idx // cols, idx % cols
    if bg_roi is None:
        bg = (r_i == 0) | (r_i == rows - 1) | (c_i == 0) | (c_i == cols - 1)
    else:
        rx, ry, rw, rh = bg_roi
        cx = boxes[:, 0] + boxes[:, 2] / 2
        cy = boxes[:, 1] + boxes[:, 3] / 2
        inside = (cx >= rx) & (cx <= rx + rw) & (cy >= ry) & (cy <= ry + rh)
        bg = ~inside
    return PatchGrid(boxes, rows, cols, tex, valid, bg & valid)


def make_roi_grid(ref: np.ndarray, roi: tuple[int, int, int, int],
                  patch_px: int = config.FINE_PATCH_PX) -> PatchGrid:
    """Fine grid of patch_px squares inside roi (clipped to the frame)."""
    H, W = ref.shape
    x0, y0, w, h = [int(v) for v in roi]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x0 + w), min(H, y0 + h)
    cols = max(1, (x1 - x0) // patch_px)
    rows = max(1, (y1 - y0) // patch_px)
    pw = min(patch_px, x1 - x0)
    ph = min(patch_px, y1 - y0)
    # centre the grid inside the ROI
    ox = x0 + ((x1 - x0) - cols * pw) // 2
    oy = y0 + ((y1 - y0) - rows * ph) // 2
    boxes = np.array([[ox + c * pw, oy + r * ph, pw, ph] for r in range(rows) for c in range(cols)],
                     np.int32)
    tex = _score(texture_map(ref), boxes)
    valid = tex > config.TEXTURE_MIN
    return PatchGrid(boxes, rows, cols, tex, valid, np.zeros(len(boxes), bool))


def patches_overlapping(grid: PatchGrid, rect: tuple[int, int, int, int]) -> np.ndarray:
    rx, ry, rw, rh = rect
    b = grid.boxes
    return ~((b[:, 0] + b[:, 2] <= rx) | (b[:, 0] >= rx + rw) |
             (b[:, 1] + b[:, 3] <= ry) | (b[:, 1] >= ry + rh))


def contour_mask(ref: np.ndarray, grid: PatchGrid, min_area_frac: float = 0.002) -> np.ndarray:
    """P2: keep patches overlapping large Canny contours (structural parts)."""
    g = np.clip(ref * 255, 0, 255).astype(np.uint8)
    edges = cv2.Canny(cv2.GaussianBlur(g, (0, 0), 1.2), 40, 120)
    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    min_area = min_area_frac * ref.size
    keep = np.zeros(grid.n, bool)
    for c in cnts:
        if cv2.contourArea(c) + cv2.arcLength(c, False) < min_area:
            continue
        keep |= patches_overlapping(grid, cv2.boundingRect(c))
    return keep
