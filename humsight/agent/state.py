"""Job state shared across tool calls so earlier computation is reused."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

import numpy as np

from .. import config
from ..io import Clip
from ..motion import MotionSeries
from ..shake import Compensated
from ..texture import PatchGrid
from .trace import Trace


@dataclass
class JobParams:
    f_min: float | None = None
    f_max: float | None = None
    expected_hz: float | None = None
    rpm: float | None = None
    mm_per_px: float | None = None
    policy: str = "rules"            # "llm" | "rules" | "fixed"
    write_original: bool = True      # False on Lambda: the UI plays the source clip
    render: bool = True              # False: skip video encoding (evaluation runs)
    workers: int = 1

    def __post_init__(self):
        if self.rpm and not self.expected_hz:
            self.expected_hz = self.rpm / 60.0

    def brief(self) -> dict:
        return {k: v for k, v in {
            "f_min": self.f_min, "f_max": self.f_max, "expected_hz": self.expected_hz,
            "mm_per_px": self.mm_per_px}.items() if v is not None}


@dataclass
class JobState:
    clip: Clip
    params: JobParams
    out_dir: str
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace: Trace = field(default_factory=Trace)

    # cached computation
    grid: PatchGrid | None = None
    ref: np.ndarray | None = None
    ms: MotionSeries | None = None              # raw coarse motion
    comp: Compensated | None = None
    cls: dict | None = None
    cls_extras: dict | None = None
    fine: dict | None = None
    flicker: dict | None = None
    mags: list[dict] = field(default_factory=list)
    severity: dict | None = None
    magnify_calls: int = 0
    outputs: dict = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)   # every tool result, for the number guard
    terminal: dict | None = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        os.makedirs(self.out_dir, exist_ok=True)

    # --- helpers ---
    @property
    def active_frames(self) -> np.ndarray:
        if self.comp is not None and self.comp.frames_y is not None:
            return self.comp.frames_y
        return self.clip.frames_y

    @property
    def frame_hw(self) -> tuple[int, int]:
        return self.clip.frames_y.shape[1:]

    @property
    def band(self) -> tuple[float | None, float | None]:
        return self.params.f_min, self.params.f_max

    def motion(self) -> tuple[np.ndarray, np.ndarray]:
        """Current (compensated if available) coarse patch motion."""
        if self.comp is not None:
            return self.comp.dx, self.comp.dy
        return self.ms.dx, self.ms.dy

    def capture(self) -> dict:
        m = self.clip.meta
        return {"fps": self.clip.fps, "duration_s": round(self.clip.n_frames / self.clip.fps, 3),
                "width": m.get("width"), "height": m.get("height"), "n_frames": self.clip.n_frames,
                "scale": round(self.clip.scale, 4)}

    def best_fault(self) -> dict | None:
        """Top classified fault, with fine-scan refinement applied if present."""
        if not self.cls or not self.cls["faults"]:
            return None
        f = dict(self.cls["faults"][0])
        if self.fine and self.fine.get("refined"):
            r = self.fine["refined"]
            f.update(f_hz=r["f_hz"], amp_px=r["amp_px"], snr=max(f["snr"], r["snr"]),
                     roi=r["roi"], refined=True)
        return f

    def invalidate_after_comp(self) -> None:
        self.cls = self.cls_extras = self.fine = None
        self.mags = []
        self.magnify_calls = 0
