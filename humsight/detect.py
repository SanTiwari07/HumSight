"""Classify spectral peaks as shake / fault / noise and cluster fault patches into an ROI."""
from __future__ import annotations

import cv2
import numpy as np

from . import config, spectrum
from .texture import PatchGrid


def _cluster_freqs(peaks: list[spectrum.PatchPeak], tol: float) -> list[list[spectrum.PatchPeak]]:
    """Greedy clustering by frequency, strongest SNR first."""
    clusters: list[list[spectrum.PatchPeak]] = []
    for pk in sorted(peaks, key=lambda p: -p.snr):
        for c in clusters:
            if abs(pk.f_hz - np.median([q.f_hz for q in c])) <= tol:
                c.append(pk)
                break
        else:
            clusters.append([pk])
    return clusters


def roi_from_mask(grid: PatchGrid, mask: np.ndarray, frame_hw: tuple[int, int],
                  pad_patches: int = 1) -> tuple[list[int], list[int]] | None:
    """Largest 8-connected component of a boolean per-patch mask -> padded pixel bbox.

    Returns (roi [x, y, w, h], member patch indices) or None.
    """
    if not mask.any():
        return None
    g = mask.reshape(grid.rows, grid.cols).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(g, connectivity=8)
    if n <= 1:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    members = np.where(lab.ravel() == best)[0]
    b = grid.boxes[members]
    x0, y0 = b[:, 0].min(), b[:, 1].min()
    x1, y1 = (b[:, 0] + b[:, 2]).max(), (b[:, 1] + b[:, 3]).max()
    pw, ph = int(b[0, 2]) * pad_patches, int(b[0, 3]) * pad_patches
    H, W = frame_hw
    x0, y0 = max(0, x0 - pw), max(0, y0 - ph)
    x1, y1 = min(W, x1 + pw), min(H, y1 + ph)
    return [int(x0), int(y0), int(x1 - x0), int(y1 - y0)], [int(i) for i in members]


def classify(dx: np.ndarray, dy: np.ndarray, grid: PatchGrid, fps: float,
             bg_dx: np.ndarray, bg_dy: np.ndarray, frame_hw: tuple[int, int],
             f_min: float | None = None, f_max: float | None = None,
             expected_hz: float | None = None, flicker: dict | None = None,
             bg_peaks: list[dict] | None = None) -> tuple[dict, dict]:
    """Return (json-able result, extras with arrays for reporting).

    dx, dy are the *compensated* patch motions. bg_dx, bg_dy is the background
    signal BEFORE compensation, used to recognise shake peaks.
    """
    N, T = dx.shape
    df = fps / T
    tol = config.BIN_TOL * df
    valid = grid.valid
    cand = valid & ~grid.is_background

    all_peaks = spectrum.analyze_patches(dx, dy, fps, valid, f_min, f_max)
    cand_peaks = [p for p in all_peaks if cand[p.patch]]
    noise_floor = float(np.median([p.noise_px for p in all_peaks])) if all_peaks else 0.0

    if bg_peaks is None:
        _, s = spectrum.dominant_axis(bg_dx, bg_dy)
        bg_peaks = spectrum.top_peaks(s, fps, 3, f_min, f_max)

    def shake_match(pk: spectrum.PatchPeak) -> dict | None:
        for b in bg_peaks:
            if abs(b["f_hz"] - pk.f_hz) <= tol and b["amp_px"] >= config.SHAKE_BG_RATIO * pk.amp_px:
                return b
        return None

    strong = [p for p in cand_peaks if p.snr >= config.SNR_MIN]
    shake_peaks, fault_pool = [], []
    for p in strong:
        (shake_peaks if shake_match(p) else fault_pool).append(p)

    faults, fault_mask_by_f = [], []
    for cl in _cluster_freqs(fault_pool, tol):
        f_rep = float(np.median([q.f_hz for q in cl]))
        a_all = spectrum.amp_at_frequency(dx[valid], dy[valid], fps, f_rep)
        med = float(np.median(a_all))
        amp_full = np.zeros(N)
        amp_full[np.where(valid)[0]] = a_all
        members = np.zeros(N, bool)
        for q in cl:
            if amp_full[q.patch] > config.K_LOCAL * med:
                members[q.patch] = True
        if not members.any():
            continue  # global (non-local) motion: indistinguishable from residual shake
        res = roi_from_mask(grid, members, frame_hw)
        if res is None:
            continue
        roi, comp = res
        roi_tight = roi_from_mask(grid, members, frame_hw, pad_patches=0)[0]
        comp_pk = [q for q in cl if q.patch in set(comp)] or [q for q in cl if members[q.patch]]
        faults.append({
            "f_hz": round(float(np.median([q.f_hz for q in comp_pk])), 3),
            "amp_px": round(float(np.median([q.amp_px for q in comp_pk])), 5),
            "snr": round(float(np.max([q.snr for q in comp_pk])), 2),
            "patches": sorted(int(q.patch) for q in comp_pk),
            "roi": roi, "roi_tight": roi_tight,
            "axis": [round(float(np.mean([q.axis[0] for q in comp_pk])), 3),
                     round(float(np.mean([q.axis[1] for q in comp_pk])), 3)],
        })
        fault_mask_by_f.append(amp_full)
    order = np.argsort([-f["amp_px"] * f["snr"] for f in faults]) if faults else []
    faults = [faults[i] for i in order]
    fault_amp_maps = [fault_mask_by_f[i] for i in order]

    ambiguous = [p for p in cand_peaks
                 if config.SNR_AMBIGUOUS <= p.snr < config.SNR_MIN and not shake_match(p)]
    amb = None
    if ambiguous and not faults:
        a = max(ambiguous, key=lambda p: p.snr)
        amb = {"f_hz": round(a.f_hz, 3), "amp_px": round(a.amp_px, 5), "snr": round(a.snr, 2)}

    strongest = max(all_peaks, key=lambda p: p.amp_px).f_hz if all_peaks else None
    nyq = spectrum.nyquist_check(fps, expected_hz, strongest)
    fl = flicker or {"flag": False, "alias_hz": None}
    flicker_conflict = bool(fl.get("flag") and any(
        fl.get("alias_hz") is not None and abs(f["f_hz"] - fl["alias_hz"]) <= tol for f in faults))

    result = {
        "faults": faults,
        "shake": [{"f_hz": b["f_hz"], "amp_px": b["amp_px"]} for b in bg_peaks[:2]
                  if b["snr"] >= config.SNR_MIN],
        "ambiguous": amb,
        "noise_floor_px": round(noise_floor, 6),
        "min_detectable_px": round(config.SNR_MIN * noise_floor, 6),
        "alias_risk": nyq["alias_risk"],
        "alias": nyq,
        "lighting_flicker": bool(fl.get("flag")),
        "flicker_conflict": flicker_conflict,
        "shake_rejected_peaks": [{"f_hz": round(p.f_hz, 3), "amp_px": round(p.amp_px, 5)}
                                 for p in shake_peaks[:3]],
        "n_valid_patches": int(valid.sum()),
    }
    extras = {"fault_amp_maps": fault_amp_maps, "all_peaks": all_peaks}
    return result, extras


def localize_fine(dx: np.ndarray, dy: np.ndarray, grid: PatchGrid, fps: float, f_hz: float,
                  frame_hw: tuple[int, int], f_min: float, f_max: float) -> dict:
    """Refine f, amplitude and ROI inside a fine grid around a known fault frequency."""
    valid = grid.valid
    peaks = spectrum.analyze_patches(dx, dy, fps, valid, f_min, f_max)
    df = fps / dx.shape[1]
    near = [p for p in peaks if abs(p.f_hz - f_hz) <= config.BIN_TOL * df and p.snr >= config.SNR_MIN]
    out = {"top_peaks": [{"patch": p.patch, "f_hz": round(p.f_hz, 3), "amp_px": round(p.amp_px, 5),
                          "snr": round(p.snr, 2)}
                         for p in sorted(peaks, key=lambda q: -q.amp_px)[:5]],
           "refined": None}
    if not near:
        return out
    a_all = np.zeros(grid.n)
    a_all[np.where(valid)[0]] = spectrum.amp_at_frequency(dx[valid], dy[valid], fps,
                                                          float(np.median([p.f_hz for p in near])))
    mask = a_all >= 0.5 * a_all.max()
    res = roi_from_mask(grid, mask, frame_hw, pad_patches=0)
    if res is None:
        return out
    roi, comp = res
    sel = [p for p in near if p.patch in set(comp)] or near
    out["refined"] = {
        "f_hz": round(float(np.median([p.f_hz for p in sel])), 3),
        "amp_px": round(float(np.median([p.amp_px for p in sel])), 5),
        "snr": round(float(np.max([p.snr for p in sel])), 2),
        "roi": roi, "n_patches": len(comp),
    }
    out["amp_map"] = a_all
    return out
