"""Deterministic fallback policy: the decision rules the LLM is also asked to follow."""
from __future__ import annotations

import math

from .. import config
from .state import JobParams


def _last(history: list[dict], tool: str, pred=None) -> dict | None:
    for h in reversed(history):
        if h["tool"] == tool and "error" not in h["result"] and (pred is None or pred(h)):
            return h
    return None


def _count(history: list[dict], tool: str) -> int:
    return sum(1 for h in history if h["tool"] == tool)


class RulesProvider:
    name = "rules"

    def __init__(self, params: JobParams):
        self.params = params

    def next_action(self, system: str, history: list[dict], tools: list[dict]) -> dict:
        P, H = self.params, history

        def act(tool, args, why):
            return {"tool": tool, "args": args, "rationale": why}

        # 1. probe
        if not H:
            return act("probe_clip", {}, "Start by probing fps, Nyquist limit, texture and warnings.")
        probe = _last(H, "probe_clip")["result"]
        fps = probe["fps"]
        if P.expected_hz and P.expected_hz > config.ALIAS_SAFE_FRAC * fps:
            sug = probe.get("suggestion") or f"record at >= {math.ceil(2.5 * P.expected_hz)} fps"
            return act("request_review", {
                "reason": f"aliasing risk: expected {P.expected_hz:.1f} Hz exceeds "
                          f"{config.ALIAS_SAFE_FRAC} x fps ({fps} fps, Nyquist {probe['f_nyquist']} Hz)",
                "suggestion": sug}, "Expected frequency is above the safe fraction of fps.")

        if probe["texture_coverage"] < config.MIN_TEXTURE_COVERAGE:
            return act("request_review", {
                "reason": f"low texture: only {probe['texture_coverage'] * 100:.0f}% of patches have enough "
                          "gradient energy for sub-pixel tracking",
                "suggestion": "film a surface with visible texture or edges, add a tape or marker, or move closer"},
                "Too few textured patches: a negative result would be meaningless.")

        # 2. coarse scan
        scan = _last(H, "scan_motion", lambda h: h["args"].get("grid") == "coarse")
        if scan is None:
            args = {"grid": "coarse"}
            if P.f_min is not None:
                args["f_min"] = P.f_min
            if P.f_max is not None:
                args["f_max"] = P.f_max
            return act("scan_motion", args, "Coarse 8x6 scan to find where and at what frequency things move.")
        s = scan["result"]

        # 3. shake handling (measurement-driven)
        comps = [h for h in H if h["tool"] == "compensate_shake" and "error" not in h["result"]]
        if not comps and _count(H, "classify_peaks") == 0:
            bg = s["background_peaks"][0]["amp_px"] if s["background_peaks"] else 0.0
            top = s["top_peaks"][0]["amp_px"] if s["top_peaks"] else 0.0
            if bg > config.SHAKE_BG_RATIO * top or bg > config.BG_AMP_TRIGGER_PX:
                return act("compensate_shake", {"method": "subtract"},
                           f"Background peak of {bg:.3f} px vs strongest patch {top:.3f} px: "
                           "the whole frame moves, so remove camera shake first.")
        if comps:
            last = comps[-1]["result"]
            sub = next((c["result"] for c in reversed(comps) if c["result"]["method"] == "subtract"), None)
            warp = next((c["result"] for c in reversed(comps) if c["result"]["method"] == "warp"), None)
            if last["method"] == "subtract" and warp is None and \
                    last.get("residual_at_shake_px", 0) > config.WARP_RESIDUAL_PX and _count(H, "classify_peaks") == 0:
                return act("compensate_shake", {"method": "warp"},
                           f"Residual {last['residual_at_shake_px']} px left at the shake frequency after "
                           "subtract: rotation or zoom shake suspected, try warp.")
            if last["method"] == "warp" and sub is not None and \
                    last["residual_at_shake_px"] >= sub["residual_at_shake_px"] and _count(H, "classify_peaks") == 0:
                return act("compensate_shake", {"method": "subtract"},
                           f"Warp residual {last['residual_at_shake_px']} px is not better than subtract "
                           f"({sub['residual_at_shake_px']} px): go back to subtract.")

        # 4. classify
        last_comp_idx = max([i for i, h in enumerate(H) if h["tool"] == "compensate_shake"], default=-1)
        last_cls_idx = max([i for i, h in enumerate(H) if h["tool"] == "classify_peaks"], default=-1)
        if last_cls_idx < last_comp_idx or last_cls_idx < 0:
            return act("classify_peaks", {}, "Classify peaks as shake, fault or noise on the compensated motion.")
        cls = H[last_cls_idx]["result"]

        if cls["lighting_flicker"] and (cls["flicker_conflict"] or not cls["faults"]):
            return act("request_review", {
                "reason": "lighting flicker coincides with the detected peak (mean frame brightness oscillates)",
                "suggestion": "re-record in daylight or with DC / flicker-free lighting"},
                "The brightness signal oscillates at the same frequency, so the peak may be light, not motion.")

        if not cls["faults"]:
            if cls.get("ambiguous"):
                a = cls["ambiguous"]
                return act("request_review", {
                    "reason": f"ambiguous peak at {a['f_hz']} Hz with SNR {a['snr']} below the {config.SNR_MIN} threshold",
                    "suggestion": "record a longer clip, a closer shot, or a more textured view"},
                    "A peak exists but is below the confidence threshold.")
            if cls["min_detectable_px"] > config.NOISE_FLOOR_REVIEW_PX:
                return act("request_review", {
                    "reason": f"motion below noise floor: minimum detectable amplitude {cls['min_detectable_px']} px",
                    "suggestion": "closer shot, more texture, tripod or lower-noise lighting"},
                    "The noise floor is too high to say the machine is quiet.")
            return act("file_report", {
                "verdict": "NO_FAULT",
                "summary": f"No localized vibration above SNR {config.SNR_MIN}. Noise floor "
                           f"{cls['noise_floor_px']} px; minimum detectable amplitude about "
                           f"{cls['min_detectable_px']} px."},
                "No fault peak and the noise floor is low enough to trust the negative.")

        fault = cls["faults"][0]
        if cls.get("alias_risk"):
            return act("request_review", {
                "reason": f"strongest peak lies near the Nyquist limit ({cls['alias']['f_nyquist']} Hz): possible aliasing",
                "suggestion": cls["alias"].get("suggestion", "record at a higher fps")},
                "A peak near fps/2 may be an alias.")

        # 5. coarse -> fine (active perception)
        fine = _last(H, "scan_motion", lambda h: h["args"].get("grid") == "fine")
        if fine is None:
            return act("scan_motion", {"grid": "fine", "roi": fault["roi"],
                                       "f_min": max(fault["f_hz"] - 3, 0.5), "f_max": fault["f_hz"] + 3},
                       f"Fault candidate at {fault['f_hz']} Hz: refine with 32 px patches inside its region.")
        ref = fine["result"].get("refined")
        f_hz = ref["f_hz"] if ref else fault["f_hz"]
        amp = ref["amp_px"] if ref else fault["amp_px"]
        snr = max(fault["snr"], ref["snr"]) if ref else fault["snr"]   # same rule as JobState.best_fault
        roi = ref["roi"] if ref else fault.get("roi_tight", fault["roi"])

        # 6. magnify (reduce alpha / narrow band if artifacts)
        mags = [h for h in H if h["tool"] == "magnify" and "error" not in h["result"]]
        if not mags:
            return act("magnify", {"f_center": f_hz, "bandwidth_hz": 2.0, "alpha": 20.0, "roi": roi},
                       "Magnify only the isolated band inside the ROI.")
        m = mags[-1]["result"]
        if m.get("artifact_ratio") is not None and m["artifact_ratio"] > config.ARTIFACT_RATIO_MAX and len(mags) < 2:
            return act("magnify", {"f_center": f_hz, "bandwidth_hz": 1.0, "alpha": 10.0, "roi": roi},
                       f"artifact_ratio {m['artifact_ratio']} is high: narrow the band and lower alpha.")

        # 7. severity (only meaningful with a scale)
        if P.mm_per_px and _count(H, "assess_severity") == 0:
            return act("assess_severity", {"f_hz": f_hz, "amp_px": amp}, "A scale reference exists: compute indicative velocity.")

        # 8. report
        shake_txt = ""
        if cls["shake"]:
            sh = cls["shake"][0]
            shake_txt = f" Camera shake at {sh['f_hz']} Hz ({sh['amp_px']} px) was compensated and rejected."
        return act("file_report", {
            "verdict": "FAULT",
            "summary": f"Localized vibration at {f_hz} Hz with amplitude {amp} px (SNR {snr}) "
                       f"in ROI {roi}.{shake_txt}"},
            "Evidence is sufficient: file the work order.")
