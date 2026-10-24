import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from humsight import synth
from humsight.io import clip_from_gray

W, H, FPS, DUR = 256, 192, 240.0, 2.0
BBOX = (88, 48, 96, 80)
SHAKE = synth.ShakeSpec(3.5, 0.6, drift=True)


def _make(parts, shake, noise=0.005, fps=FPS):
    p = synth.SynthParams(fps=fps, duration_s=DUR, width=W, height=H, noise_sigma=noise,
                          parts=parts, shake=shake)
    return synth.generate(p)


@pytest.fixture(scope="session")
def shake_fault():
    return _make([synth.default_part(58.5, 0.08, bbox=BBOX)], SHAKE)


@pytest.fixture(scope="session")
def shake_only():
    return _make([], SHAKE)


@pytest.fixture(scope="session")
def quiet():
    return _make([], None)


@pytest.fixture(scope="session")
def fault_only():
    return _make([synth.default_part(24.5, 0.1, bbox=BBOX)], None)


def make_clip(frames_gt, fps=FPS):
    return clip_from_gray(frames_gt[0], fps)
