"""Heatmap, spectrum JSON and the work order (JSON + Markdown)."""
from __future__ import annotations

import datetime as dt
import json
import os

import cv2
import numpy as np

from . import config, spectrum
from .texture import PatchGrid


def heatmap_png(ref_y: np.ndarray, grid: PatchGrid, values: np.ndarray,
                roi: list[int] | None, path: str, label: str = "") -> str:
    """Patch grid coloured by amplitude (px), ROI boxed. ref_y is float [0,1]."""
    base = cv2.cvtColor(np.clip(ref_y * 255, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    layer = np.zeros_like(base)
    vmax = float(np.max(values)) if len(values) and np.max(values) > 0 else 1.0
    for (x, y, w, h), v in zip(grid.boxes, values):
        c = cv2.applyColorMap(np.array([[int(255 * min(v / vmax, 1.0))]], np.uint8), cv2.COLORMAP_JET)[0, 0]
        cv2.rectangle(layer, (int(x), int(y)), (int(x + w) - 1, int(y + h) - 1), tuple(int(k) for k in c), -1)
    out = cv2.addWeighted(base, 0.5, layer, 0.5, 0)
    if roi:
        x, y, w, h = roi
        cv2.rectangle(out, (x, y), (x + w, y + h), (255, 255, 255), 2)
    if label:
        cv2.putText(out, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(path, out)
    return path


def _downsample(f: np.ndarray, a: np.ndarray, n: int = 1000):
    if len(f) <= n:
        return f, a
    step = int(np.ceil(len(f) / n))
    return f[::step], a[::step]


def spectrum_payload(dx: np.ndarray, dy: np.ndarray, fps: float, roi_patches: list[int],
                     bg_dx: np.ndarray, bg_dy: np.ndarray, band_hz: list[float] | None,
                     path: str | None = None) -> dict:
    """ROI-median vs background amplitude spectra (px), for the Chart.js plot."""
    out = {"fps": fps, "f_nyquist": fps / 2, "band_hz": band_hz, "roi": None, "bg": None}
    if roi_patches:
        u, _ = spectrum.dominant_axis(dx[roi_patches].mean(0), dy[roi_patches].mean(0))
        sig = np.median(np.stack([u[0] * dx[i] + u[1] * dy[i] for i in roi_patches]), axis=0)
        f, a = spectrum.amp_spectrum(spectrum.detrend(sig), fps)
        f, a = _downsample(f, a)
        out["f"] = [round(float(v), 3) for v in f]
        out["roi"] = [float(f"{v:.6g}") for v in a]
    _, bs = spectrum.dominant_axis(bg_dx, bg_dy)
    fb, ab = spectrum.amp_spectrum(spectrum.detrend(bs), fps)
    fb, ab = _downsample(fb, ab)
    if "f" not in out:
        out["f"] = [round(float(v), 3) for v in fb]
    out["bg"] = [float(f"{v:.6g}") for v in ab]
    if path:
        with open(path, "w") as fh:
            json.dump(out, fh)
    return out


LIMITATIONS = [
    "Indicative, camera-based measurement. Not a certified ISO assessment.",
    "Frequency is valid only up to Nyquist (fps/2); record at >= 2.5x the fault frequency.",
    "Amplitude is in image pixels unless a scale reference was given.",
    "Compression, low texture and lighting flicker can mask or fake sub-pixel motion.",
]


def build_work_order(verdict: str, summary: str, findings: list[dict], capture: dict,
                     severity: dict | None = None, reason: str | None = None,
                     suggestion: str | None = None, warnings: list[str] | None = None,
                     outputs: dict | None = None, policy: str | None = None) -> dict:
    return {
        "verdict": verdict,
        "summary": summary,
        "reason": reason,
        "suggestion": suggestion,
        "findings": findings,
        "severity": severity,
        "capture": capture,
        "warnings": warnings or [],
        "limitations": LIMITATIONS,
        "outputs": outputs or {},
        "policy": policy,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def work_order_md(wo: dict) -> str:
    L = [f"# HumSight work order: {wo['verdict']}", "", f"_{wo['timestamp']}_ · policy: {wo.get('policy')}", ""]
    L += ["## Summary", wo.get("summary") or "", ""]
    if wo.get("reason"):
        L += [f"**Reason:** {wo['reason']}", ""]
    if wo.get("suggestion"):
        L += [f"**Suggestion:** {wo['suggestion']}", ""]
    if wo["findings"]:
        L += ["## Findings", "", "| f (Hz) | amplitude (px) | SNR | ROI [x,y,w,h] |", "|---|---|---|---|"]
        for f in wo["findings"]:
            L.append(f"| {f['f_hz']} | {f['amp_px']} | {f['snr']} | {f.get('roi')} |")
        L.append("")
    sev = wo.get("severity")
    if sev:
        L += ["## Severity (indicative)", ""]
        for k in ("amp_mm", "v_rms_mm_s", "zone"):
            L.append(f"- {k}: {sev.get(k)}")
        L += [f"- note: {sev.get('note')}", ""]
    c = wo["capture"]
    L += ["## Capture", "", f"- fps: {c.get('fps')}", f"- duration: {c.get('duration_s')} s",
          f"- resolution: {c.get('width')}x{c.get('height')}", ""]
    if wo["warnings"]:
        L += ["## Warnings", ""] + [f"- {w}" for w in wo["warnings"]] + [""]
    L += ["## Limitations", ""] + [f"- {x}" for x in wo["limitations"]]
    return "\n".join(L) + "\n"


def write_work_order(wo: dict, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    pj, pm = os.path.join(out_dir, "work_order.json"), os.path.join(out_dir, "work_order.md")
    with open(pj, "w") as fh:
        json.dump(wo, fh, indent=2, default=_json_default)
    with open(pm, "w", encoding="utf-8") as fh:
        fh.write(work_order_md(wo))
    return {"json": pj, "md": pm}


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))
