"""Agent tools: every function returns only values measured by OpenCV/NumPy code."""
from __future__ import annotations

import json
import os
import time

import numpy as np

from .. import config, detect, magnify as mag_mod, report, severity as sev_mod, shake, spectrum
from ..motion import patch_shifts
from ..texture import make_grid, make_roi_grid, patches_overlapping, reference_frame
from . import guard
from .state import JobState
from .trace import jsonable

TERMINAL = {"request_review", "file_report"}

_ROI = {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4,
        "description": "[x, y, w, h] in processed-frame pixels"}

TOOLS: list[dict] = [
    {"name": "probe_clip",
     "description": "Always first. Reports fps, duration, size, Nyquist frequency, frequency "
                    "resolution, texture coverage and warnings (fps from metadata, low texture, "
                    "lighting flicker, aliasing risk).",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "scan_motion",
     "description": "Measure sub-pixel patch motion and spectra. grid='coarse' scans an 8x6 grid over "
                    "the frame (returns top patch peaks, background peaks, noise floor). grid='fine' "
                    "scans 32 px patches inside roi around a candidate fault and returns a refined "
                    "frequency, amplitude and ROI.",
     "parameters": {"type": "object", "properties": {
         "grid": {"type": "string", "enum": ["coarse", "fine"]},
         "roi": _ROI,
         "f_min": {"type": "number", "minimum": 0}, "f_max": {"type": "number", "minimum": 0}},
         "required": ["grid"], "additionalProperties": False}},
    {"name": "compensate_shake",
     "description": "Remove camera shake. 'subtract' removes the median background displacement (best "
                    "for translation). 'warp' tracks background features, fits a homography (USAC_MAGSAC) "
                    "and stabilises frames (use for rotation/zoom shake). Returns bg peak, residual left "
                    "at the shake frequency, and inlier ratio.",
     "parameters": {"type": "object", "properties": {
         "method": {"type": "string", "enum": ["subtract", "warp"]}},
         "required": ["method"], "additionalProperties": False}},
    {"name": "classify_peaks",
     "description": "Classify spectral peaks as shake / fault / noise on the (compensated) motion, "
                    "cluster fault patches into an ROI, and report aliasing and lighting-flicker flags.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "magnify",
     "description": "Band-limited Eulerian magnification inside roi only. Returns artifact_ratio "
                    "(background vs ROI amplified energy; > 0.5 means noise/shake is being amplified), "
                    "effective alpha and the output video name. At most 3 calls.",
     "parameters": {"type": "object", "properties": {
         "f_center": {"type": "number", "minimum": 0.5}, "bandwidth_hz": {"type": "number", "minimum": 0.2, "maximum": 20},
         "alpha": {"type": "number", "minimum": 1, "maximum": 100}, "roi": _ROI},
         "required": ["f_center", "bandwidth_hz", "alpha", "roi"], "additionalProperties": False}},
    {"name": "assess_severity",
     "description": "Indicative severity: displacement in mm, velocity RMS in mm/s and zone, if the job "
                    "has a scale reference. Never a certified ISO assessment.",
     "parameters": {"type": "object", "properties": {
         "f_hz": {"type": "number", "minimum": 0}, "amp_px": {"type": "number", "minimum": 0}},
         "required": ["f_hz", "amp_px"], "additionalProperties": False}},
    {"name": "request_review",
     "description": "Terminal. Use when evidence is insufficient or unsafe to interpret (aliasing, "
                    "lighting flicker, motion below the noise floor, ambiguous peak).",
     "parameters": {"type": "object", "properties": {
         "reason": {"type": "string"}, "suggestion": {"type": "string"}},
         "required": ["reason", "suggestion"], "additionalProperties": False}},
    {"name": "file_report",
     "description": "Terminal. File the work order with verdict FAULT or NO_FAULT and a short summary. "
                    "Every number in the summary must come from a tool result.",
     "parameters": {"type": "object", "properties": {
         "verdict": {"type": "string", "enum": ["FAULT", "NO_FAULT"]}, "summary": {"type": "string"}},
         "required": ["verdict", "summary"], "additionalProperties": False}},
]
TOOL_NAMES = {t["name"] for t in TOOLS}
_SCHEMA = {t["name"]: t["parameters"] for t in TOOLS}


# --- schema validation -------------------------------------------------------

def validate_args(tool: str, args: dict) -> str | None:
    """Return an error string, or None when args satisfy the tool's schema."""
    if tool not in _SCHEMA:
        return f"unknown tool '{tool}'"
    sch = _SCHEMA[tool]
    props = sch.get("properties", {})
    for r in sch.get("required", []):
        if r not in args:
            return f"missing required arg '{r}'"
    for k, v in args.items():
        if k not in props:
            return f"unexpected arg '{k}'"
        e = _check(props[k], v, k)
        if e:
            return e
    return None


def _check(spec: dict, v, name: str) -> str | None:
    t = spec.get("type")
    if t == "string":
        if not isinstance(v, str):
            return f"'{name}' must be a string"
        if "enum" in spec and v not in spec["enum"]:
            return f"'{name}' must be one of {spec['enum']}"
    elif t in ("number", "integer"):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return f"'{name}' must be a number"
        if t == "integer" and float(v) != int(v):
            return f"'{name}' must be an integer"
        if "minimum" in spec and v < spec["minimum"]:
            return f"'{name}' must be >= {spec['minimum']}"
        if "maximum" in spec and v > spec["maximum"]:
            return f"'{name}' must be <= {spec['maximum']}"
    elif t == "array":
        if not isinstance(v, (list, tuple)):
            return f"'{name}' must be an array"
        if len(v) < spec.get("minItems", 0) or len(v) > spec.get("maxItems", 1 << 30):
            return f"'{name}' must have {spec.get('minItems')} items"
        for x in v:
            e = _check(spec["items"], x, name)
            if e:
                return e
    return None


# --- helpers ------------------------------------------------------------------

def _ensure_grid(state: JobState) -> None:
    if state.ref is None:
        state.ref = reference_frame(state.clip.frames_y)
    if state.grid is None:
        state.grid = make_grid(state.ref, *config.COARSE_GRID)


def _ensure_motion(state: JobState) -> bool:
    """Compute raw coarse motion once. Returns True if it was cached."""
    _ensure_grid(state)
    if state.ms is not None:
        return True
    state.ms = patch_shifts(state.clip.frames_y, state.grid, scale=state.clip.scale,
                            workers=state.params.workers, valid_only=True)
    return False


def _raw_bg(state: JobState) -> tuple[np.ndarray, np.ndarray]:
    return shake.background_signal(state.ms, state.grid)


def _top_patch_peaks(state: JobState, n: int = 5) -> list[dict]:
    dx, dy = state.motion()
    cand = state.grid.valid & ~state.grid.is_background
    f_min, f_max = state.band
    peaks = spectrum.analyze_patches(dx, dy, state.clip.fps, cand, f_min, f_max)
    peaks.sort(key=lambda p: -p.amp_px)
    return [{"patch": p.patch, "f_hz": round(p.f_hz, 3), "amp_px": round(p.amp_px, 5),
             "snr": round(p.snr, 2)} for p in peaks[:n]]


# --- tools --------------------------------------------------------------------

def probe_clip(state: JobState) -> dict:
    clip = state.clip
    _ensure_grid(state)
    if state.flicker is None:
        state.flicker = spectrum.lighting_flicker(clip.frames_y, clip.fps)
    cov = float(state.grid.valid.mean())
    warnings = list(clip.warnings)
    if cov < 0.4:
        warnings.append(f"low texture: only {cov * 100:.0f}% of patches are usable")
    if state.flicker["flag"]:
        warnings.append(f"lighting flicker suspected near {state.flicker['alias_hz']:.1f} Hz")
    nyq = spectrum.nyquist_check(clip.fps, state.params.expected_hz)
    if nyq["alias_risk"]:
        warnings.append("aliasing risk: " + "; ".join(nyq["reasons"]))
    state.warnings = warnings
    out = {"fps": clip.fps, "duration_s": round(clip.n_frames / clip.fps, 3),
           "width": clip.meta.get("width"), "height": clip.meta.get("height"),
           "n_frames": clip.n_frames, "f_nyquist": nyq["f_nyquist"],
           "delta_f": round(clip.fps / clip.n_frames, 4), "texture_coverage": round(cov, 3),
           "alias_risk": nyq["alias_risk"], "warnings": warnings}
    if state.params.expected_hz:
        out["expected_hz"] = round(state.params.expected_hz, 3)
    if nyq.get("suggestion"):
        out["suggestion"] = nyq["suggestion"]
    return out


def scan_motion(state: JobState, grid: str = "coarse", roi=None, f_min=None, f_max=None) -> dict:
    t0 = time.perf_counter()
    if grid == "coarse":
        if f_min is not None:
            state.params.f_min = float(f_min)
        if f_max is not None:
            state.params.f_max = float(f_max)
        cached = _ensure_motion(state)
        bx, by = _raw_bg(state)
        lo, hi = state.band
        all_pk = spectrum.analyze_patches(*state.motion(), state.clip.fps, state.grid.valid, lo, hi)
        floor = float(np.median([p.noise_px for p in all_pk])) if all_pk else 0.0
        return {"grid": "8x6", "cached": cached, "n_patches": int(state.grid.n),
                "n_valid": int(state.grid.valid.sum()),
                "top_peaks": _top_patch_peaks(state),
                "background_peaks": shake.background_peaks(bx, by, state.clip.fps, 3, lo, hi),
                "noise_floor_px": round(floor, 6),
                "runtime_ms": round((time.perf_counter() - t0) * 1000, 1)}

    # fine
    _ensure_motion(state)
    if roi is None:
        if state.cls and state.cls["faults"]:
            roi = state.cls["faults"][0]["roi"]
        else:
            return {"error": "fine scan needs roi (none classified yet)"}
    if f_min is not None and f_max is not None:
        fc = 0.5 * (f_min + f_max)
    elif state.cls and state.cls["faults"]:
        fc = state.cls["faults"][0]["f_hz"]
        f_min, f_max = max(fc - 3, 0.5), fc + 3
    else:
        return {"error": "fine scan needs f_min/f_max (no fault classified)"}
    fgrid = make_roi_grid(state.ref, tuple(roi))
    ms = patch_shifts(state.active_frames, fgrid, scale=state.clip.scale,
                      workers=state.params.workers, valid_only=True)
    dx, dy = ms.dx, ms.dy
    if state.comp is not None and state.comp.method == "subtract":
        dx = dx - state.comp.bg_dx[None, :]
        dy = dy - state.comp.bg_dy[None, :]
    res = detect.localize_fine(dx, dy, fgrid, state.clip.fps, fc, state.frame_hw, f_min, f_max)
    amp_map = res.pop("amp_map", None)
    state.fine = {"refined": res["refined"], "grid": fgrid, "amp_map": amp_map, "dx": dx, "dy": dy}
    return {"grid": f"fine {fgrid.cols}x{fgrid.rows}", "n_patches": int(fgrid.n),
            "n_valid": int(fgrid.valid.sum()), "top_peaks": res["top_peaks"],
            "refined": res["refined"],
            "runtime_ms": round((time.perf_counter() - t0) * 1000, 1)}


def compensate_shake(state: JobState, method: str = "subtract") -> dict:
    t0 = time.perf_counter()
    _ensure_motion(state)
    lo, hi = state.band
    try:
        if method == "subtract":
            comp = shake.subtract(state.ms, state.grid, state.clip.fps, lo, hi)
        else:
            comp = shake.warp(state.clip.frames_y, state.grid, state.ms, state.clip.fps,
                              state.clip.scale, lo, hi, state.params.workers)
    except Exception as e:  # e.g. too few background features
        return {"error": f"{method} failed: {e}"}
    state.comp = comp
    state.invalidate_after_comp()
    out = dict(comp.info)
    out["top_peaks_after"] = _top_patch_peaks(state, 3)
    out["runtime_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


def classify_peaks(state: JobState) -> dict:
    t0 = time.perf_counter()
    _ensure_motion(state)
    if state.flicker is None:
        state.flicker = spectrum.lighting_flicker(state.clip.frames_y, state.clip.fps)
    dx, dy = state.motion()
    bx, by = _raw_bg(state)
    lo, hi = state.band
    res, extras = detect.classify(dx, dy, state.grid, state.clip.fps, bx, by, state.frame_hw,
                                  lo, hi, state.params.expected_hz, state.flicker)
    state.cls, state.cls_extras = res, extras
    state.fine = None
    out = dict(res)
    out["compensation"] = state.comp.method if state.comp else None
    out["runtime_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


def magnify(state: JobState, f_center: float, bandwidth_hz: float, alpha: float, roi) -> dict:
    t0 = time.perf_counter()
    if state.magnify_calls >= config.MAX_MAGNIFY_CALLS:
        return {"error": f"magnify limit ({config.MAX_MAGNIFY_CALLS}) reached"}
    _ensure_motion(state)
    H, W = state.frame_hw
    x, y, w, h = [int(v) for v in roi]
    x, y = max(0, x), max(0, y)
    w, h = min(w, W - x), min(h, H - y)
    if w < 16 or h < 16:
        return {"error": "roi too small (< 16 px)"}
    roi = [x, y, w, h]
    dx, dy = state.motion()
    ov = patches_overlapping(state.grid, tuple(roi)) & state.grid.valid
    amp = float(np.median(spectrum.amp_at_frequency(dx[ov], dy[ov], state.clip.fps, f_center))) \
        if ov.any() else 0.05
    bg_ok = np.where(state.grid.is_background & state.grid.valid & ~patches_overlapping(state.grid, tuple(roi)))[0]
    bg_rect = None
    if len(bg_ok):
        j = bg_ok[np.argmax(state.grid.texture[bg_ok])]
        bg_rect = tuple(int(v) for v in state.grid.boxes[j])
    m = mag_mod.magnify_roi(state.active_frames, state.clip.fps, roi, f_center, bandwidth_hz,
                            alpha, amp, state.clip.scale, bg_rect)
    state.magnify_calls += 1
    if state.params.render:
        first = "original" not in state.outputs
        paths = mag_mod.render_videos(state.clip, m, state.out_dir, f"magnified_{state.magnify_calls}",
                                      write_original=first and state.params.write_original)
        state.outputs["magnified"] = os.path.basename(paths["magnified"])
        if "original" in paths:
            state.outputs["original"] = os.path.basename(paths["original"])
    else:
        paths = {"magnified": "(not rendered)", "codec": None, "slowdown": round(state.clip.fps / config.PLAYBACK_FPS, 3)}
    state.mags.append({"roi": roi, "f_center": f_center, "bandwidth_hz": bandwidth_hz,
                       "alpha": alpha, "alpha_effective": m["alpha_effective"],
                       "artifact_ratio": m["artifact_ratio"]})
    return {"video": state.outputs.get("magnified"), "roi": roi,
            "artifact_ratio": None if m["artifact_ratio"] is None else round(m["artifact_ratio"], 3),
            "alpha_effective": round(m["alpha_effective"], 2), "band_hz": m["band_hz"],
            "slowdown": paths["slowdown"], "codec": paths["codec"],
            "runtime_ms": round((time.perf_counter() - t0) * 1000, 1)}


def assess_severity(state: JobState, f_hz: float, amp_px: float) -> dict:
    state.severity = sev_mod.assess(f_hz, amp_px, state.params.mm_per_px)
    return dict(state.severity)


# --- terminal tools -------------------------------------------------------------

def _findings(state: JobState) -> list[dict]:
    if not state.cls or not state.cls["faults"]:
        return []
    out = []
    best = state.best_fault()
    for i, f in enumerate(state.cls["faults"]):
        d = best if i == 0 else f
        out.append({"f_hz": d["f_hz"], "amp_px": d["amp_px"], "snr": d["snr"], "roi": d["roi"],
                    "axis": d.get("axis")})
    return out


def known_numbers(state: JobState) -> list:
    consts = {"snr_min": config.SNR_MIN, "k_local": config.K_LOCAL, "alias_safe_frac": config.ALIAS_SAFE_FRAC,
              "artifact_ratio_max": config.ARTIFACT_RATIO_MAX, "max_tool_calls": config.MAX_TOOL_CALLS}
    return [state.results, state.params.brief(), state.capture(), consts]


def template_summary(state: JobState, verdict: str, reason: str | None = None) -> str:
    cls = state.cls or {}
    if verdict == "FAULT":
        f = state.best_fault()
        s = (f"Localized vibration at {f['f_hz']} Hz with amplitude {f['amp_px']} px "
             f"(SNR {f['snr']}) in ROI {f['roi']}.")
        if cls.get("shake") and state.comp:
            sh = cls["shake"][0]
            s += f" Camera shake at {sh['f_hz']} Hz ({sh['amp_px']} px) was compensated and rejected."
        return s
    if verdict == "NO_FAULT":
        return (f"No localized vibration above SNR {config.SNR_MIN} was found. Noise floor "
                f"{cls.get('noise_floor_px')} px; minimum detectable amplitude about "
                f"{cls.get('min_detectable_px')} px.")
    return reason or "Evidence is insufficient for an automatic verdict."


def _write_outputs(state: JobState, verdict: str, summary: str, reason=None, suggestion=None) -> dict:
    files: dict = {}
    best = state.best_fault()
    roi = best["roi"] if best else None
    try:
        if state.grid is not None and state.ms is not None:
            if state.cls_extras and state.cls_extras["fault_amp_maps"] and state.cls and state.cls["faults"]:
                vals = state.cls_extras["fault_amp_maps"][0]
            elif state.cls_extras and state.cls_extras["all_peaks"]:
                vals = np.zeros(state.grid.n)
                for p in state.cls_extras["all_peaks"]:
                    vals[p.patch] = p.amp_px
            else:
                vals = np.zeros(state.grid.n)
            label = f"{best['f_hz']} Hz" if best else "peak amplitude per patch"
            files["heatmap"] = os.path.basename(report.heatmap_png(
                state.ref, state.grid, vals, roi, os.path.join(state.out_dir, "heatmap.png"), label))
            dx, dy = state.motion()
            bx, by = _raw_bg(state)
            roi_p = best["patches"] if best and "patches" in best else (
                state.cls["faults"][0]["patches"] if state.cls and state.cls["faults"] else [])
            band = state.mags[-1]["band_hz"] if state.mags and "band_hz" in state.mags[-1] else None
            if state.mags:
                m = state.mags[-1]
                band = [round(m["f_center"] - m["bandwidth_hz"] / 2, 3), round(m["f_center"] + m["bandwidth_hz"] / 2, 3)]
            report.spectrum_payload(dx, dy, state.clip.fps, list(roi_p), bx, by, band,
                                    os.path.join(state.out_dir, "spectrum.json"))
            files["spectrum"] = "spectrum.json"
    except Exception as e:  # reporting must never lose the verdict
        state.trace.note(f"report artefact failed: {e}", source="system")
    wo = report.build_work_order(
        verdict, summary, _findings(state), state.capture(), state.severity, reason, suggestion,
        state.warnings or list(state.clip.warnings),
        {**state.outputs, **files}, state.params.policy)
    wo["trace_steps"] = len([e for e in state.trace.events if e.kind == "tool"])
    wf = report.write_work_order(wo, state.out_dir)
    files.update(work_order_json=os.path.basename(wf["json"]), work_order_md=os.path.basename(wf["md"]))
    state.outputs.update(files)
    return wo


def request_review(state: JobState, reason: str, suggestion: str) -> dict:
    wo = _write_outputs(state, "REVIEW", template_summary(state, "REVIEW", reason), reason, suggestion)
    state.terminal = {"verdict": "REVIEW", "reason": reason, "suggestion": suggestion}
    return {"state": "REVIEW", "reason": reason, "suggestion": suggestion,
            "work_order": state.outputs.get("work_order_md")}


def file_report(state: JobState, verdict: str, summary: str) -> dict:
    if state.cls is None:
        # Never classified, or compensate_shake invalidated the classification. Not terminal: the model can fix it.
        return {"error": "no current classification (compensate_shake resets it). "
                         "Call classify_peaks first, then call file_report again."}
    note = None
    cls = state.cls
    if verdict == "FAULT" and not cls.get("faults"):
        verdict, note = "REVIEW", "verdict FAULT without a classified fault was downgraded to REVIEW"
    elif verdict == "NO_FAULT" and cls.get("faults"):
        verdict, note = "REVIEW", "verdict NO_FAULT contradicts a classified fault; downgraded to REVIEW"
    elif verdict == "NO_FAULT" and cls.get("n_valid_patches", 1) == 0:
        verdict, note = "REVIEW", "NO_FAULT with no usable (textured) patches downgraded to REVIEW"
    if note:
        state.trace.note(note, source="guard")
    bad = guard.check(summary, known_numbers(state))
    if bad:
        state.trace.note(f"guard: replaced summary (unverified number {bad[0]})", source="guard",
                         unverified=bad, original=summary)
        summary = template_summary(state, verdict, note)
    wo = _write_outputs(state, verdict, summary, note)
    state.terminal = {"verdict": verdict, "summary": summary}
    return {"verdict": verdict, "summary": summary, "work_order": state.outputs.get("work_order_md")}


IMPL = {"probe_clip": probe_clip, "scan_motion": scan_motion, "compensate_shake": compensate_shake,
        "classify_peaks": classify_peaks, "magnify": magnify, "assess_severity": assess_severity,
        "request_review": request_review, "file_report": file_report}


def run_tool(state: JobState, name: str, args: dict) -> dict:
    err = validate_args(name, args)
    if err:
        return {"error": f"invalid arguments: {err}"}
    res = jsonable(IMPL[name](state, **args))
    state.results.append(res)
    return res


# --- compact result for the LLM (<= 1.5 KB) ---------------------------------------------

_DROP = {"patches", "alias", "shake_rejected_peaks", "roi_tight", "axis", "work_order"}


def _round(o, nd=5):
    if isinstance(o, float):
        return float(f"{o:.{nd}g}")
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items() if k not in _DROP}
    if isinstance(o, list):
        return [_round(v, nd) for v in o[:5]]
    return o


def compact(result: dict, max_bytes: int = 1500) -> dict:
    r = _round(result)
    while len(json.dumps(r)) > max_bytes and isinstance(r, dict) and r:
        biggest = max(r, key=lambda k: len(json.dumps(r[k])))
        if len(json.dumps(r[biggest])) < 80:
            break
        r[biggest] = str(r[biggest])[:60] + "...(truncated)"
    return r
