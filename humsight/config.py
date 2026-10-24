"""Thresholds, limits and defaults. Every tunable lives here so evaluation can cite it."""
from __future__ import annotations

import os

# --- input limits ----------------------------------------------------------
MAX_DURATION_S = float(os.environ.get("MAX_DURATION_S", 10.0))  # Lambda sets 4
MAX_FRAMES = 1200
MAX_WIDTH = 960
MAX_UPLOAD_MB = 25
# Cap on frames*H*W so float32 luma stays within ~1.2 GB (Lambda has 3 GB).
MAX_VOLUME = 3.0e8

# --- spectrum / detection --------------------------------------------------
F_MIN_HZ = 2.0            # ignore drift and handheld breathing below this
F_MAX_FRAC = 0.45         # search up to this fraction of fps (aliasing guard)
SNR_MIN = 6.0             # linear amplitude SNR for a peak to count as real
SNR_AMBIGUOUS = 4.5       # between this and SNR_MIN the result is REVIEW (noise-only max is ~3.5)
K_LOCAL = 3.0             # fault amp must beat K_LOCAL x median amp at that f
SHAKE_BG_RATIO = 0.5      # bg amp >= ratio * patch amp => shake
BIN_TOL = 2.0             # frequency match tolerance, in bins
PEAK_EXCLUDE_BINS = 3     # bins around a peak excluded from the noise estimate

# --- patches ---------------------------------------------------------------
COARSE_GRID = (8, 6)      # cols, rows over the full frame
FINE_PATCH_PX = 32
ITER_L2SIZE = 5           # phaseCorrelateIterative neighbourhood (tuned on synthetic data)
TEXTURE_MIN = 2.0e-3      # mean Sobel gradient energy on the reference frame

# --- agent / rules ---------------------------------------------------------
BG_AMP_TRIGGER_PX = 0.05       # bg amplitude above this => compensate shake
WARP_RESIDUAL_PX = 0.02        # motion left at the shake freq after subtract => try warp
NOISE_FLOOR_REVIEW_PX = 0.1    # min detectable amp (SNR_MIN x floor) above this => REVIEW, not NO_FAULT
ARTIFACT_RATIO_MAX = 0.5
MAX_TOOL_CALLS = 10
MAX_MAGNIFY_CALLS = 3
ALIAS_SAFE_FRAC = 0.45
LIGHTING_FLICKER_HZ = 100.0    # 50 Hz mains -> 100 Hz flicker

# --- magnification ---------------------------------------------------------
PYRAMID_LEVELS = 4
ROI_MARGIN_PX = 16
FEATHER_SIGMA_PX = 8.0
PLAYBACK_FPS = 30

# --- severity (ISO 20816) ---------------------------------------------------
# Thresholds must only be filled from the ISO 20816 part and machine class you
# actually cite. Until then no zone is reported.
ZONES: list[dict] | None = None
ZONES_SOURCE = "not configured"
SEVERITY_DISCLAIMER = "Indicative, camera-based measurement. Not a certified ISO assessment."
