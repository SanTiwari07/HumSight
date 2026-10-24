"""Runtime environment facts: which OpenCV is loaded (COOL proof), LLM availability."""
from __future__ import annotations

import os
import platform

import cv2


def cv2_info() -> dict:
    info = cv2.getBuildInformation()
    return {
        "cv2_version": cv2.__version__,
        "cv2_path": cv2.__file__,
        "cool": "/opt/cool" in cv2.__file__.replace("\\", "/"),
        "kleidicv": "kleidicv" in info.lower(),
        "machine": platform.machine(),
        "threads": cv2.getNumThreads(),
        "has_iterative_phase_correlation": hasattr(cv2, "phaseCorrelateIterative"),
    }


def llm_mode() -> str:
    return "gemini" if (os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_PARAM")) else "rules"


def banner() -> str:
    i = cv2_info()
    return (f"[HumSight] cv2 {i['cv2_version']} @ {i['cv2_path']} | COOL={i['cool']} | "
            f"KleidiCV={i['kleidicv']} | {i['machine']}")


def load_dotenv(path: str = ".env") -> None:
    """Tiny .env reader (no dependency); never overrides existing variables."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
