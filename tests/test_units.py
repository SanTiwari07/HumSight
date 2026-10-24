import json
import math

import numpy as np
import pytest

from humsight import config, severity, spectrum
from humsight.agent import guard, tools


def test_analyze_signal_pure_sine():
    fps, n, f, a = 240.0, 960, 37.3, 0.07
    t = np.arange(n) / fps
    r = spectrum.analyze_signal(a * np.sin(2 * np.pi * f * t + 0.4) + 3.0 * t, fps)
    assert abs(r["f_hz"] - f) < 0.05
    assert abs(r["amp_px"] - a) / a < 0.02
    assert r["snr"] > 100


def test_noise_only_snr_below_threshold():
    rng = np.random.default_rng(0)
    snrs = [spectrum.analyze_signal(rng.normal(0, 0.02, 960), 240.0)["snr"] for _ in range(200)]
    assert np.percentile(snrs, 99) < config.SNR_MIN


def test_nyquist_check_flags_and_suggests():
    r = spectrum.nyquist_check(240.0, 130.0)
    assert r["alias_risk"] and r["suggestion"] == f"record at >= {math.ceil(2.5 * 130)} fps"
    assert not spectrum.nyquist_check(240.0, 50.0)["alias_risk"]
    assert spectrum.nyquist_check(240.0, None, 119.0)["alias_risk"]   # strongest peak near fps/2


def test_severity_formulae_and_no_zone_without_thresholds():
    s = severity.assess(10.0, 5.0, mm_per_px=0.02)       # 0.1 mm at 10 Hz
    assert s["amp_mm"] == pytest.approx(0.1)
    assert s["v_rms_mm_s"] == pytest.approx(2 * math.pi * 10 * 0.1 / math.sqrt(2))
    assert s["zone"] is None and "not configured" in s["note"]
    assert severity.assess(10.0, 5.0)["v_rms_mm_s"] is None


def test_guard_accepts_measured_and_rejects_invented():
    results = [{"f_hz": 58.497, "amp_px": 0.04657, "snr": 25.31}]
    assert guard.check("Vibration at 58.5 Hz, amplitude 0.0466 px, SNR 25.3, 3 patches.", [results]) == []
    assert guard.check("Fault at 61 Hz", [results]) == ["61"]
    assert guard.check("amplitude 0.9 px", [results]) == ["0.9"]


def test_validate_args():
    assert tools.validate_args("probe_clip", {}) is None
    assert "missing" in tools.validate_args("scan_motion", {})
    assert "one of" in tools.validate_args("scan_motion", {"grid": "huge"})
    assert "unexpected" in tools.validate_args("probe_clip", {"x": 1})
    ok = {"f_center": 58, "bandwidth_hz": 2, "alpha": 20, "roi": [1, 2, 3, 4]}
    assert tools.validate_args("magnify", ok) is None
    assert "array" in tools.validate_args("magnify", {**ok, "roi": "x"})
    assert ">=" in tools.validate_args("magnify", {**ok, "alpha": 0})


def test_compact_result_is_small():
    big = {"top_peaks": [{"patch": i, "f_hz": 1.23456789 * i, "amp_px": 0.123456789, "snr": 9.87654321}
                         for i in range(40)], "note": "x" * 5000, "faults": [{"patches": list(range(50))}]}
    assert len(json.dumps(tools.compact(big))) <= 1500
