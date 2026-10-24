"""Synthetic ground-truth vibration video generator.

Sub-pixel motion is applied with the Fourier shift theorem (exact, no
interpolation blur), so the true frequency / amplitude / location is known.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np


@dataclass
class PartSpec:
    id: str
    bbox: tuple[int, int, int, int]       # x, y, w, h in output (cropped) coordinates
    f_hz: float
    amp_px: float                          # zero-to-peak
    dir: tuple[float, float] = (1.0, 0.0)
    phase: float = 0.3
    harmonics: bool = False


@dataclass
class ShakeSpec:
    f_hz: float = 3.5
    amp_px: float = 0.6
    dir: tuple[float, float] = (0.7071, 0.7071)
    phase: float = 0.0
    drift: bool = False
    drift_amp_px: float = 0.5


@dataclass
class SynthParams:
    fps: float = 240.0
    duration_s: float = 4.0
    width: int = 640
    height: int = 360
    parts: list[PartSpec] = field(default_factory=list)
    shake: ShakeSpec | None = None
    noise_sigma: float = 0.004
    jpeg_q: int | None = None
    codec_roundtrip: bool = False
    quantize: bool = True   # False: return float32 on a 0..255 scale (unit tests only)
    seed: int = 42


def fourier_shift(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    H, W = img.shape
    F = np.fft.fft2(img)
    ky = np.fft.fftfreq(H)[:, None]
    kx = np.fft.fftfreq(W)[None, :]
    F *= np.exp(-2j * np.pi * (kx * dx + ky * dy))
    return np.real(np.fft.ifft2(F)).astype(np.float32)


def _texture(H: int, W: int, rng: np.random.Generator, lo: float, hi: float,
             sigma: float = 1.5) -> np.ndarray:
    t = cv2.GaussianBlur(rng.standard_normal((H, W)).astype(np.float32), (0, 0), sigma)
    t = (t - t.min()) / (t.max() - t.min() + 1e-9)
    return (lo + (hi - lo) * t).astype(np.float32)


class _Shifter:
    """Reusable rfft2-based Fourier shifter for a fixed image size."""

    def __init__(self, H: int, W: int):
        self.H, self.W = H, W
        self.ky = np.fft.fftfreq(H).astype(np.float64)
        self.kx = np.fft.rfftfreq(W).astype(np.float64)

    def spectrum(self, img: np.ndarray) -> np.ndarray:
        return np.fft.rfft2(img)

    def shifted(self, F: np.ndarray, dx: float, dy: float) -> np.ndarray:
        ramp = np.exp(-2j * np.pi * self.ky * dy)[:, None] * np.exp(-2j * np.pi * self.kx * dx)[None, :]
        return np.fft.irfft2(F * ramp, s=(self.H, self.W)).astype(np.float32)


def _unit(v) -> np.ndarray:
    v = np.asarray(v, np.float64)
    return v / (np.linalg.norm(v) + 1e-12)


def _drift_signal(T: int, fps: float, amp: float, rng: np.random.Generator) -> np.ndarray:
    """Low-frequency (<2 Hz) random walk, scaled to the given peak amplitude, shape (T, 2)."""
    out = np.zeros((T, 2))
    freqs = np.fft.rfftfreq(T, 1.0 / fps)
    for a in range(2):
        X = np.fft.rfft(rng.standard_normal(T))
        X[(freqs > 2.0) | (freqs < 0.1)] = 0
        s = np.fft.irfft(X, n=T)
        out[:, a] = amp * s / (np.abs(s).max() + 1e-12)
    return out


def part_displacement(p: PartSpec, t: np.ndarray) -> np.ndarray:
    """(T, 2) displacement of a part at times t."""
    u = _unit(p.dir)
    s = p.amp_px * np.sin(2 * np.pi * p.f_hz * t + p.phase)
    if p.harmonics:
        s = s + p.amp_px / 3.0 * np.sin(2 * np.pi * 2 * p.f_hz * t)
    return s[:, None] * u[None, :]


def shake_displacement(s: ShakeSpec | None, t: np.ndarray, fps: float,
                       rng: np.random.Generator) -> np.ndarray:
    if s is None:
        return np.zeros((len(t), 2))
    u = _unit(s.dir)
    d = (s.amp_px * np.sin(2 * np.pi * s.f_hz * t + s.phase))[:, None] * u[None, :]
    if s.drift:
        d = d + _drift_signal(len(t), fps, s.drift_amp_px, rng)
    return d


def _codec_roundtrip(frames: np.ndarray, fps: float) -> np.ndarray:
    T, H, W = frames.shape
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "rt.mp4")
        w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
        if not w.isOpened():
            raise RuntimeError("mp4v writer unavailable for codec round-trip")
        for f in frames:
            w.write(cv2.cvtColor(f, cv2.COLOR_GRAY2BGR))
        w.release()
        cap = cv2.VideoCapture(p)
        out = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            out.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
        cap.release()
    return np.stack(out[:T])


def generate(params: SynthParams) -> tuple[np.ndarray, dict]:
    """Return (frames uint8 (T,H,W), ground-truth dict)."""
    rng = np.random.default_rng(params.seed)
    T = int(round(params.fps * params.duration_s))
    t = np.arange(T) / params.fps

    max_shift = 0.0
    for p in params.parts:
        max_shift = max(max_shift, p.amp_px * (4 / 3 if p.harmonics else 1.0))
    if params.shake:
        max_shift += params.shake.amp_px + (params.shake.drift_amp_px if params.shake.drift else 0)
    m = int(math.ceil(max_shift)) + 8
    Hp, Wp = params.height + 2 * m, params.width + 2 * m

    bg = _texture(Hp, Wp, rng, 0.1, 0.9)
    sh = _Shifter(Hp, Wp)

    # drift needs its own rng stream so it does not depend on the part count
    shake_rng = np.random.default_rng(params.seed + 1)
    d_shake = shake_displacement(params.shake, t, params.fps, shake_rng)

    layers = []
    for p in params.parts:
        x, y, w, h = p.bbox
        tex = _texture(Hp, Wp, rng, 0.2, 0.95)
        # dark outline inset a few px so it stays inside the (static) mask
        cv2.rectangle(tex, (x + m + 4, y + m + 4), (x + m + w - 5, y + m + h - 5), 0.05, 2)
        mask = np.zeros((Hp, Wp), np.float32)
        mask[y + m:y + m + h, x + m:x + m + w] = 1.0
        mask = cv2.GaussianBlur(mask, (0, 0), 1.5)
        layers.append((p, sh.spectrum(tex), mask, part_displacement(p, t)))

    frames = np.empty((T, params.height, params.width), np.float32)
    for i in range(T):
        frame = bg.copy()
        for p, F, mask, d in layers:
            part_t = sh.shifted(F, d[i, 0], d[i, 1])
            frame = frame * (1 - mask) + part_t * mask
        if params.shake is not None:
            frame = sh.shifted(sh.spectrum(frame), d_shake[i, 0], d_shake[i, 1])
        frames[i] = frame[m:m + params.height, m:m + params.width]

    noise_rng = np.random.default_rng(params.seed + 2)
    if params.noise_sigma > 0:
        frames += noise_rng.normal(0.0, params.noise_sigma, frames.shape).astype(np.float32)
    if not params.quantize:
        u8 = (frames * 255.0).astype(np.float32)
    else:
        u8 = np.clip(frames * 255.0 + 0.5, 0, 255).astype(np.uint8)

    if params.jpeg_q and params.quantize:
        for i in range(T):
            ok, buf = cv2.imencode(".jpg", u8[i], [cv2.IMWRITE_JPEG_QUALITY, int(params.jpeg_q)])
            u8[i] = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    if params.codec_roundtrip and params.quantize:
        u8 = _codec_roundtrip(u8, params.fps)

    gt = {
        "fps": params.fps, "n_frames": T, "width": params.width, "height": params.height,
        "parts": [{"id": p.id, "bbox": list(p.bbox), "f_hz": p.f_hz, "amp_px": p.amp_px,
                   "dir": list(_unit(p.dir).round(4)), "phase": p.phase,
                   "harmonics": p.harmonics} for p in params.parts],
        "shake": None if params.shake is None else {
            "f_hz": params.shake.f_hz, "amp_px": params.shake.amp_px,
            "dir": list(_unit(params.shake.dir).round(4)), "drift": params.shake.drift},
        "noise_sigma": params.noise_sigma, "jpeg_q": params.jpeg_q,
        "codec_roundtrip": params.codec_roundtrip, "quantized": params.quantize,
        "seed": params.seed,
    }
    return u8, gt


def default_part(f: float, amp: float, bbox=(400, 100, 192, 144), **kw) -> PartSpec:
    return PartSpec(id="bearing_cap", bbox=bbox, f_hz=f, amp_px=amp, **kw)


def save(frames: np.ndarray, gt: dict, out_dir: str, mp4: bool = True, npz: bool = False) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    with open(os.path.join(out_dir, "gt.json"), "w") as fh:
        json.dump(gt, fh, indent=2)
    paths["gt"] = os.path.join(out_dir, "gt.json")
    if npz:
        p = os.path.join(out_dir, "clip.npz")
        np.savez_compressed(p, frames=frames, fps=gt["fps"])
        paths["npz"] = p
    if mp4:
        from .io import VideoSink
        T, H, W = frames.shape
        p = os.path.join(out_dir, "clip.mp4")
        w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), gt["fps"], (W, H))
        for f in frames:
            w.write(cv2.cvtColor(f, cv2.COLOR_GRAY2BGR))
        w.release()
        paths["mp4"] = p
    return paths


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="HumSight synthetic vibration video")
    ap.add_argument("--f", type=float, default=58.5)
    ap.add_argument("--amp", type=float, default=0.05)
    ap.add_argument("--fps", type=float, default=240)
    ap.add_argument("--dur", type=float, default=4.0)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=360)
    ap.add_argument("--bbox", type=int, nargs=4, default=[400, 100, 192, 144])
    ap.add_argument("--dir", type=float, nargs=2, default=[1.0, 0.0])
    ap.add_argument("--harmonics", action="store_true")
    ap.add_argument("--shake-f", type=float, default=0.0)
    ap.add_argument("--shake-amp", type=float, default=0.0)
    ap.add_argument("--drift", action="store_true")
    ap.add_argument("--noise", type=float, default=0.004)
    ap.add_argument("--jpeg", type=int, default=0)
    ap.add_argument("--codec", action="store_true", help="mp4v round-trip degradation")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--npz", action="store_true", help="also write lossless clip.npz")
    ap.add_argument("--no-mp4", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    shake = None
    if a.shake_amp > 0 or a.drift:
        shake = ShakeSpec(f_hz=a.shake_f or 3.5, amp_px=a.shake_amp, drift=a.drift)
    params = SynthParams(
        fps=a.fps, duration_s=a.dur, width=a.width, height=a.height,
        parts=[default_part(a.f, a.amp, tuple(a.bbox), dir=tuple(a.dir), harmonics=a.harmonics)],
        shake=shake, noise_sigma=a.noise, jpeg_q=a.jpeg or None,
        codec_roundtrip=a.codec, seed=a.seed)
    frames, gt = generate(params)
    paths = save(frames, gt, a.out, mp4=not a.no_mp4, npz=a.npz)
    print(json.dumps(paths, indent=2))


if __name__ == "__main__":
    main()
