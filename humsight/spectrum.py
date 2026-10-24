"""From patch motion to frequency, amplitude and SNR."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import config


@dataclass
class PatchPeak:
    patch: int
    f_hz: float
    amp_px: float                 # zero-to-peak, from the sine fit
    snr: float                    # linear amplitude SNR vs median in-band spectrum
    axis: tuple[float, float]     # unit vector of dominant motion
    noise_px: float = 0.0         # median in-band spectral amplitude


def dominant_axis(dx: np.ndarray, dy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """PCA on [dx, dy]; returns (unit axis (2,), projection s(t))."""
    X = np.vstack([dx - dx.mean(), dy - dy.mean()]).astype(np.float64)
    C = X @ X.T
    w, v = np.linalg.eigh(C)
    u = v[:, np.argmax(w)]
    # fix sign so axes are comparable across patches
    if u[0] < 0 or (abs(u[0]) < 1e-9 and u[1] < 0):
        u = -u
    return u, u @ np.vstack([dx, dy]).astype(np.float64)


def detrend(s: np.ndarray) -> np.ndarray:
    t = np.arange(len(s), dtype=np.float64)
    p = np.polyfit(t, s, 1)
    return s - np.polyval(p, t)


def amp_spectrum(s: np.ndarray, fps: float, welch: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Zero-to-peak amplitude spectrum with a Hann window (px)."""
    s = np.asarray(s, np.float64)
    if welch and len(s) >= 64:
        n = len(s) // 4
        step = n // 2
        w = np.hanning(n)
        acc = []
        for a in range(0, len(s) - n + 1, step):
            seg = s[a:a + n]
            seg = seg - seg.mean()
            acc.append((2 * np.abs(np.fft.rfft(seg * w)) / w.sum()) ** 2)
        return np.fft.rfftfreq(n, 1.0 / fps), np.sqrt(np.mean(acc, axis=0))
    n = len(s)
    w = np.hanning(n)
    X = np.fft.rfft(s * w)
    return np.fft.rfftfreq(n, 1.0 / fps), 2 * np.abs(X) / w.sum()


def band_indices(f: np.ndarray, f_min: float, f_max: float) -> np.ndarray:
    idx = np.where((f >= f_min) & (f <= f_max))[0]
    return idx[(idx >= 1) & (idx <= len(f) - 2)]


def default_band(fps: float, f_min: float | None = None, f_max: float | None = None) -> tuple[float, float]:
    lo = config.F_MIN_HZ if f_min is None else max(f_min, 0.0)
    hi = config.F_MAX_FRAC * fps if f_max is None else min(f_max, 0.5 * fps)
    return lo, hi


def parabolic_peak(amp: np.ndarray, k: int, df: float) -> tuple[float, float]:
    a, b, c = amp[k - 1], amp[k], amp[k + 1]
    den = a - 2 * b + c
    delta = 0.0 if abs(den) < 1e-18 else 0.5 * (a - c) / den
    delta = float(np.clip(delta, -0.5, 0.5))
    return (k + delta) * df, float(b - 0.25 * (a - c) * delta)


def sine_fit(s: np.ndarray, t: np.ndarray, f: float) -> float:
    """Least-squares zero-to-peak amplitude of a sinusoid at f (plus offset)."""
    M = np.column_stack([np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t), np.ones_like(t)])
    coef, *_ = np.linalg.lstsq(M, s, rcond=None)
    return float(np.hypot(coef[0], coef[1]))


def refine_frequency(s: np.ndarray, t: np.ndarray, f0: float, df: float) -> tuple[float, float]:
    """Refine f within +-0.75 bin by maximising the sine-fit amplitude."""
    best_f, best_a = f0, sine_fit(s, t, f0)
    for width, n in ((0.75 * df, 13), (0.1 * df, 9)):
        for f in np.linspace(best_f - width, best_f + width, n):
            if f <= 0:
                continue
            a = sine_fit(s, t, f)
            if a > best_a:
                best_f, best_a = float(f), a
    return best_f, best_a


def analyze_signal(s: np.ndarray, fps: float, f_min: float | None = None,
                   f_max: float | None = None, welch: bool = False,
                   refine: bool = True) -> dict:
    """Peak frequency / amplitude / SNR of a 1-D displacement signal."""
    s = detrend(np.asarray(s, np.float64))
    n = len(s)
    t = np.arange(n) / fps
    f, amp = amp_spectrum(s, fps, welch)
    lo, hi = default_band(fps, f_min, f_max)
    idx = band_indices(f, lo, hi)
    if len(idx) < 8:
        return {"f_hz": 0.0, "amp_px": 0.0, "snr": 0.0, "noise_px": 0.0, "k": -1, "ok": False}
    df = f[1] - f[0]
    k = int(idx[np.argmax(amp[idx])])
    f_pk, _ = parabolic_peak(amp, k, df)
    ex = np.abs(idx - k) <= config.PEAK_EXCLUDE_BINS
    floor = float(np.median(amp[idx[~ex]])) if (~ex).any() else float(np.median(amp[idx]))
    snr = float(amp[k] / (floor + 1e-12))
    if refine and not welch:
        f_pk, a_fit = refine_frequency(s, t, f_pk, df)
    else:
        a_fit = sine_fit(s, t, f_pk)
    return {"f_hz": float(f_pk), "amp_px": float(a_fit), "snr": snr, "noise_px": floor,
            "k": k, "df": float(df), "ok": True}


def top_peaks(s: np.ndarray, fps: float, n: int = 3, f_min: float | None = None,
              f_max: float | None = None) -> list[dict]:
    """Top-n local maxima (separated by > 3 bins) of the amplitude spectrum."""
    s = detrend(np.asarray(s, np.float64))
    t = np.arange(len(s)) / fps
    f, amp = amp_spectrum(s, fps)
    lo, hi = default_band(fps, f_min, f_max)
    idx = band_indices(f, lo, hi)
    if len(idx) < 8:
        return []
    df = f[1] - f[0]
    order = idx[np.argsort(amp[idx])[::-1]]
    floor = float(np.median(amp[idx]))
    picked: list[int] = []
    for k in order:
        if all(abs(int(k) - p) > config.PEAK_EXCLUDE_BINS for p in picked):
            picked.append(int(k))
        if len(picked) == n:
            break
    out = []
    for k in picked:
        f_pk, _ = parabolic_peak(amp, k, df)
        f_pk, a_fit = refine_frequency(s, t, f_pk, df)
        out.append({"f_hz": round(float(f_pk), 3), "amp_px": round(float(a_fit), 5),
                    "snr": round(float(amp[k] / (floor + 1e-12)), 2)})
    return out


def amp_at_frequency(dx: np.ndarray, dy: np.ndarray, fps: float, f_hz: float) -> np.ndarray:
    """(N,) 2-D amplitude of each patch's motion at a given frequency."""
    N, T = dx.shape
    t = np.arange(T) / fps
    out = np.zeros(N)
    for i in range(N):
        out[i] = math.hypot(sine_fit(detrend(dx[i].astype(np.float64)), t, f_hz),
                            sine_fit(detrend(dy[i].astype(np.float64)), t, f_hz))
    return out


def analyze_patches(dx: np.ndarray, dy: np.ndarray, fps: float, which: np.ndarray,
                    f_min: float | None = None, f_max: float | None = None) -> list[PatchPeak]:
    peaks = []
    for i in np.where(which)[0]:
        u, s = dominant_axis(dx[i], dy[i])
        r = analyze_signal(s, fps, f_min, f_max)
        if not r["ok"]:
            continue
        peaks.append(PatchPeak(int(i), r["f_hz"], r["amp_px"], r["snr"],
                               (float(u[0]), float(u[1])), r["noise_px"]))
    return peaks


# --- guards ----------------------------------------------------------------

def nyquist_check(fps: float, f_expected: float | None, strongest_hz: float | None = None) -> dict:
    f_nyq = fps / 2.0
    risk = False
    reasons = []
    if f_expected and f_expected > config.ALIAS_SAFE_FRAC * fps:
        risk = True
        reasons.append(f"expected {f_expected:.1f} Hz > {config.ALIAS_SAFE_FRAC} x fps")
    if strongest_hz and abs(strongest_hz - f_nyq) <= 0.05 * f_nyq:
        risk = True
        reasons.append("strongest peak lies within 5% of Nyquist")
    out = {"f_nyquist": f_nyq, "alias_risk": risk, "reasons": reasons}
    if risk:
        ref = f_expected or strongest_hz or f_nyq
        out["suggestion"] = f"record at >= {math.ceil(2.5 * ref)} fps"
    return out


def lighting_flicker(frames_y: np.ndarray, fps: float) -> dict:
    """Detect mains-light flicker (100 Hz in India) in the mean frame brightness."""
    b = frames_y.mean(axis=(1, 2)).astype(np.float64)
    f_true = config.LIGHTING_FLICKER_HZ
    m = round(f_true / fps)
    alias = abs(f_true - m * fps) if m >= 1 else f_true
    out = {"flag": False, "alias_hz": float(alias), "snr": 0.0}
    b = detrend(b)
    f, amp = amp_spectrum(b, fps)
    idx = band_indices(f, config.F_MIN_HZ, 0.5 * fps)
    if len(idx) < 8:
        return out
    df = f[1] - f[0]
    near = idx[np.abs(f[idx] - alias) <= config.BIN_TOL * df]
    if len(near) == 0:
        return out
    floor = float(np.median(amp[idx]))
    snr = float(amp[near].max() / (floor + 1e-12))
    out["snr"] = round(snr, 2)
    out["flag"] = bool(snr >= config.SNR_MIN)
    return out
