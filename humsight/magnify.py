"""Band-limited linear Eulerian magnification (Wu et al., SIGGRAPH 2012), ROI only."""
from __future__ import annotations

import os

import cv2
import numpy as np

from . import config
from .io import Clip, VideoSink

MAX_LEVEL_PX = 0.5   # keep (1 + alpha_l) * displacement_l under this, in level pixels


def lap_pyr(img: np.ndarray, L: int) -> list[np.ndarray]:
    g = [img]
    for _ in range(L):
        g.append(cv2.pyrDown(g[-1]))
    lap = [g[i] - cv2.pyrUp(g[i + 1], dstsize=(g[i].shape[1], g[i].shape[0])) for i in range(L)]
    return lap + [g[L]]


def _levels_for(h: int, w: int, want: int) -> int:
    L = want
    while L > 1 and min(h, w) >> L < 6:
        L -= 1
    return L


def band_delta(frames: np.ndarray, fps: float, f1: float, f2: float, alpha: float,
               amp_px_proc: float, levels: int = config.PYRAMID_LEVELS) -> tuple[np.ndarray, float]:
    """Amplified temporal band-pass component, same shape as frames (T, h, w).

    out_frame = frame + delta. Linear in the pyramid, so each level's band-passed
    signal is upsampled back to full size and summed. Returns (delta, alpha_effective).
    """
    T, h, w = frames.shape
    L = _levels_for(h, w, levels)
    stacks: list[list[np.ndarray]] = [[] for _ in range(L)]
    for t in range(T):
        pyr = lap_pyr(frames[t], L)
        for l in range(L):
            stacks[l].append(pyr[l])
    freqs = np.fft.rfftfreq(T, 1.0 / fps)
    keep = (freqs >= f1) & (freqs <= f2)
    delta = np.zeros_like(frames, dtype=np.float32)
    alpha_eff = 0.0
    for l in range(1, L):                       # level 0 (finest) is mostly noise: alpha_0 = 0
        delta_l = amp_px_proc / (2 ** l)        # displacement in this level's pixels
        a_l = alpha if delta_l <= 0 else min(alpha, MAX_LEVEL_PX / delta_l - 1.0)
        a_l = max(a_l, 0.0)
        if l == 1:
            alpha_eff = a_l
        if a_l == 0.0:
            continue
        S = np.stack(stacks[l]).astype(np.float32)
        F = np.fft.rfft(S, axis=0)
        F[~keep] = 0
        band = np.fft.irfft(F, n=T, axis=0).astype(np.float32) * a_l
        for t in range(T):
            up = band[t]
            for k in range(l):
                tgt = stacks[l - 1 - k][0].shape
                up = cv2.pyrUp(up, dstsize=(tgt[1], tgt[0]))
            delta[t] += up
    return delta, float(alpha_eff)


def feather_mask(h: int, w: int, margin: int, sigma: float = config.FEATHER_SIGMA_PX) -> np.ndarray:
    m = np.zeros((h, w), np.float32)
    mm = min(margin, h // 2 - 1, w // 2 - 1)
    m[mm:h - mm, mm:w - mm] = 1.0
    return cv2.GaussianBlur(m, (0, 0), sigma)


def _crop_rect(roi, shape, margin) -> tuple[int, int, int, int]:
    H, W = shape
    x, y, w, h = [int(v) for v in roi]
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(W, x + w + margin), min(H, y + h + margin)
    return x0, y0, x1 - x0, y1 - y0


def magnify_roi(frames_y: np.ndarray, fps: float, roi, f_center: float, bandwidth_hz: float,
                alpha: float, amp_px_orig: float, scale: float = 1.0,
                bg_rect: tuple[int, int, int, int] | None = None) -> dict:
    """Magnify motion near f_center inside roi (processed-pixel coords).

    Returns delta (masked, ready to add to the original luma), crop rect,
    alpha_effective and the artifact ratio measured on a background patch.
    """
    T = frames_y.shape[0]
    f1 = max(f_center - bandwidth_hz / 2, 0.0)
    f2 = f_center + bandwidth_hz / 2
    x0, y0, w, h = _crop_rect(roi, frames_y.shape[1:], config.ROI_MARGIN_PX)
    crop = np.ascontiguousarray(frames_y[:, y0:y0 + h, x0:x0 + w])
    amp_proc = amp_px_orig / scale
    delta, a_eff = band_delta(crop, fps, f1, f2, alpha, amp_proc)
    mask = feather_mask(h, w, config.ROI_MARGIN_PX)
    delta *= mask[None]

    ratio = None
    if bg_rect is not None and a_eff > 0:
        bx, by, bw, bh = bg_rect
        bg = np.ascontiguousarray(frames_y[:, by:by + bh, bx:bx + bw])
        bdelta, _ = band_delta(bg, fps, f1, f2, alpha, amp_proc)
        roi_std = float(delta[:, config.ROI_MARGIN_PX:-config.ROI_MARGIN_PX or None,
                              config.ROI_MARGIN_PX:-config.ROI_MARGIN_PX or None].std()) or float(delta.std())
        ratio = float(bdelta.std() / (roi_std + 1e-12))
    energy = delta.std(axis=0)
    energy = energy / (np.percentile(energy, 99) + 1e-12)
    return {"delta": delta, "rect": (x0, y0, w, h), "alpha_effective": a_eff,
            "artifact_ratio": ratio, "band_hz": [round(f1, 3), round(f2, 3)],
            "energy": np.clip(energy, 0, 1).astype(np.float32), "n_frames": T}


def render_videos(clip: Clip, mag: dict, out_dir: str, name: str = "magnified",
                  write_original: bool = True, overlay: bool = True) -> dict:
    """Stream the clip once, writing original (optional) and magnified videos at 30 fps."""
    os.makedirs(out_dir, exist_ok=True)
    x0, y0, w, h = mag["rect"]
    delta, energy = mag["delta"], mag["energy"]
    T, H, W = clip.frames_y.shape
    orig_sink = VideoSink(os.path.join(out_dir, "original"), (W, H)) if write_original else None
    mag_sink = VideoSink(os.path.join(out_dir, name), (W, H))
    red = np.zeros((h, w, 3), np.float32)
    red[..., 2] = 1.0
    for t, bgr in enumerate(clip.iter_bgr()):
        if t >= T:
            break
        if orig_sink:
            orig_sink.write(bgr)
        out = bgr.copy()
        crop = out[y0:y0 + h, x0:x0 + w]
        ycc = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb).astype(np.float32)
        ycc[..., 0] = np.clip(ycc[..., 0] + delta[t] * 255.0, 0, 255)
        res = cv2.cvtColor(ycc.astype(np.uint8), cv2.COLOR_YCrCb2BGR)
        if overlay:
            a = (0.45 * energy)[..., None]
            res = np.clip(res.astype(np.float32) * (1 - a) + red * 255.0 * a, 0, 255).astype(np.uint8)
        out[y0:y0 + h, x0:x0 + w] = res
        mag_sink.write(out)
    paths = {"magnified": mag_sink.close(), "codec": mag_sink.codec}
    if orig_sink:
        paths["original"] = orig_sink.close()
    paths["slowdown"] = round(clip.fps / config.PLAYBACK_FPS, 3)
    return paths
