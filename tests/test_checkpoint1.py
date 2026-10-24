"""Checkpoint 1: recover f within 1 bin and amplitude within tolerance on synthetic clips.

Clean (noise-free, unquantised) clips must hit +-10%. Realistic uint8 clips with
sensor noise sigma=0.005 are held to +-15% at amplitudes >= 0.05 px. Noise-free
*quantised* clips are deliberately not tested: uint8 rounding error is then
deterministic, correlates with the signal, and biases phase correlation (see
README failure cases).
"""
import numpy as np
import pytest

from humsight import spectrum, synth
from humsight.io import clip_from_gray
from humsight.motion import patch_shifts
from humsight.texture import make_grid, reference_frame


def _run(f, amp, noise, quantize, fps=240.0):
    p = synth.SynthParams(fps=fps, duration_s=4.0, width=320, height=240, noise_sigma=noise,
                          quantize=quantize,
                          parts=[synth.default_part(f, amp, bbox=(100, 40, 160, 160))])
    frames, gt = synth.generate(p)
    clip = clip_from_gray(frames, fps)
    grid = make_grid(reference_frame(clip.frames_y), 5, 4)
    ms = patch_shifts(clip.frames_y, grid)
    x, y, w, h = gt["parts"][0]["bbox"]
    b = grid.boxes
    inside = (b[:, 0] >= x) & (b[:, 0] + b[:, 2] <= x + w) & (b[:, 1] >= y) & (b[:, 1] + b[:, 3] <= y + h)
    assert inside.sum() >= 2
    return clip, spectrum.analyze_patches(ms.dx, ms.dy, clip.fps, inside)


@pytest.mark.parametrize("f,amp", [(58.5, 0.05), (24.5, 0.1), (40.0, 0.3)])
def test_clean_unquantised(f, amp):
    clip, peaks = _run(f, amp, 0.0, False)
    df = clip.fps / clip.n_frames
    for pk in peaks:
        assert abs(pk.f_hz - f) <= df, pk
    assert abs(np.median([p.amp_px for p in peaks]) - amp) / amp <= 0.10


@pytest.mark.parametrize("f,amp", [(58.5, 0.05), (24.5, 0.1), (7.5, 0.1)])
def test_realistic_noise(f, amp):
    clip, peaks = _run(f, amp, 0.005, True)
    df = clip.fps / clip.n_frames
    for pk in peaks:
        assert abs(pk.f_hz - f) <= df, pk
        assert pk.snr >= 6
    assert abs(np.median([p.amp_px for p in peaks]) - amp) / amp <= 0.15
