"""Camera-shake estimation and compensation (subtract | warp)."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from . import spectrum
from .motion import MotionSeries, patch_shifts
from .texture import PatchGrid


@dataclass
class Compensated:
    dx: np.ndarray                       # (N, T) compensated motion, original px
    dy: np.ndarray
    info: dict
    bg_dx: np.ndarray                    # (T,) background signal that was removed (zeros for warp)
    bg_dy: np.ndarray
    frames_y: np.ndarray | None = None   # stabilised frames (warp only)
    method: str = "subtract"
    extra: dict = field(default_factory=dict)


def background_signal(ms: MotionSeries, grid: PatchGrid) -> tuple[np.ndarray, np.ndarray]:
    """Median over valid background patches of dx(t), dy(t)."""
    bg = grid.is_background & grid.valid
    if not bg.any():
        bg = grid.valid
    if not bg.any():
        z = np.zeros(ms.dx.shape[1])
        return z, z
    return np.median(ms.dx[bg], axis=0), np.median(ms.dy[bg], axis=0)


def background_peaks(bg_dx: np.ndarray, bg_dy: np.ndarray, fps: float, n: int = 3,
                     f_min: float | None = None, f_max: float | None = None) -> list[dict]:
    _, s = spectrum.dominant_axis(bg_dx, bg_dy)
    return spectrum.top_peaks(s, fps, n, f_min, f_max)


def residual_rms(dx: np.ndarray, dy: np.ndarray, grid: PatchGrid) -> float:
    """Median over background patches of RMS(detrended compensated motion)."""
    bg = grid.is_background & grid.valid
    if not bg.any():
        return 0.0
    vals = []
    for i in np.where(bg)[0]:
        a = spectrum.detrend(dx[i].astype(np.float64))
        b = spectrum.detrend(dy[i].astype(np.float64))
        vals.append(float(np.sqrt(np.mean(a * a + b * b))))
    return float(np.median(vals))


def residual_at_hz(dx: np.ndarray, dy: np.ndarray, grid: PatchGrid, fps: float,
                   f_hz: float | None) -> float:
    """Median over background patches of the motion amplitude left at the shake frequency."""
    bg = grid.is_background & grid.valid
    if f_hz is None or not bg.any():
        return 0.0
    return float(np.median(spectrum.amp_at_frequency(dx[bg], dy[bg], fps, f_hz)))


def _bg_info(bg_dx, bg_dy, fps, f_min=None, f_max=None) -> dict:
    pk = background_peaks(bg_dx, bg_dy, fps, 1, f_min, f_max)
    if pk:
        return {"bg_peak_hz": pk[0]["f_hz"], "bg_amp_px": pk[0]["amp_px"]}
    return {"bg_peak_hz": None, "bg_amp_px": 0.0}


def subtract(ms: MotionSeries, grid: PatchGrid, fps: float,
             f_min: float | None = None, f_max: float | None = None) -> Compensated:
    """Method A: subtract the median background displacement from every patch."""
    bx, by = background_signal(ms, grid)
    dx, dy = ms.dx - bx[None, :], ms.dy - by[None, :]
    info = {"method": "subtract", **_bg_info(bx, by, fps, f_min, f_max),
            "residual_px_rms": round(residual_rms(dx, dy, grid), 5), "inlier_ratio": None}
    info["residual_at_shake_px"] = round(residual_at_hz(dx, dy, grid, fps, info["bg_peak_hz"]), 5)
    return Compensated(dx.astype(np.float32), dy.astype(np.float32), info, bx, by, None, "subtract")


def warp(frames_y: np.ndarray, grid: PatchGrid, ms_before: MotionSeries, fps: float,
         scale: float = 1.0, f_min: float | None = None, f_max: float | None = None,
         workers: int = 1) -> Compensated:
    """Method B: track background features, fit a homography per frame (USAC_MAGSAC),
    warp frames back to the reference and re-measure the patch shifts.

    Interpolation slightly smooths sub-pixel signals; the residual is reported so
    the agent can compare it with method A.
    """
    T, H, W = frames_y.shape
    bg = grid.is_background & grid.valid
    mask = np.zeros((H, W), np.uint8)
    for x, y, w, h in grid.boxes[bg]:
        mask[y:y + h, x:x + w] = 255
    to8 = lambda f: np.clip(f * 255.0 + 0.5, 0, 255).astype(np.uint8)
    ref8 = to8(frames_y[0])
    pts0 = cv2.goodFeaturesToTrack(ref8, maxCorners=400, qualityLevel=0.01, minDistance=8, mask=mask)
    stab = np.empty_like(frames_y)
    stab[0] = frames_y[0]
    inl = []
    if pts0 is None or len(pts0) < 8:
        raise ValueError("not enough background features for warp stabilisation")
    for t in range(1, T):
        cur8 = to8(frames_y[t])
        pts1, st, _ = cv2.calcOpticalFlowPyrLK(ref8, cur8, pts0, None, winSize=(21, 21), maxLevel=3)
        ok = st.ravel() == 1
        if ok.sum() < 8:
            stab[t] = frames_y[t]
            inl.append(0.0)
            continue
        Hm, inliers = cv2.findHomography(pts1[ok], pts0[ok], cv2.USAC_MAGSAC, 1.0)
        if Hm is None:
            stab[t] = frames_y[t]
            inl.append(0.0)
            continue
        inl.append(float(inliers.mean()))
        stab[t] = cv2.warpPerspective(frames_y[t], Hm, (W, H), flags=cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_REPLICATE)
    ms = patch_shifts(stab, grid, scale=scale, workers=workers)
    bx, by = background_signal(ms_before, grid)
    z = np.zeros(T)
    info = {"method": "warp", **_bg_info(bx, by, fps, f_min, f_max),
            "residual_px_rms": round(residual_rms(ms.dx, ms.dy, grid), 5),
            "inlier_ratio": round(float(np.mean(inl)) if inl else 0.0, 3)}
    info["residual_at_shake_px"] = round(residual_at_hz(ms.dx, ms.dy, grid, fps, info["bg_peak_hz"]), 5)
    return Compensated(ms.dx, ms.dy, info, z, z, stab, "warp")
