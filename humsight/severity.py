"""Displacement -> velocity -> indicative zone. Never a certified ISO assessment."""
from __future__ import annotations

import math

from . import config


def mm_per_px_from_length(length_mm: float, length_px: float) -> float:
    return float(length_mm) / float(length_px)


def assess(f_hz: float, amp_px: float, mm_per_px: float | None = None) -> dict:
    """amp_px is zero-to-peak displacement in original pixels."""
    out = {"f_hz": f_hz, "amp_px": amp_px, "amp_mm": None, "v_rms_mm_s": None,
           "zone": None, "note": config.SEVERITY_DISCLAIMER}
    if not mm_per_px:
        out["note"] = "no scale reference given: velocity and zone unavailable. " + config.SEVERITY_DISCLAIMER
        return out
    amp_mm = amp_px * mm_per_px
    v_peak = 2 * math.pi * f_hz * amp_mm            # mm/s, zero-to-peak
    v_rms = v_peak / math.sqrt(2)                   # single sinusoid
    out["amp_mm"] = amp_mm
    out["v_rms_mm_s"] = v_rms
    if config.ZONES:
        for z in config.ZONES:
            if v_rms <= z["max_mm_s"]:
                out["zone"] = z["name"]
                break
        else:
            out["zone"] = config.ZONES[-1]["name"]
        out["note"] = f"zone thresholds from {config.ZONES_SOURCE}. " + config.SEVERITY_DISCLAIMER
    else:
        out["note"] = "zone: n/a (thresholds not configured). " + config.SEVERITY_DISCLAIMER
    return out
