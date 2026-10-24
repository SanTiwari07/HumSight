"""Prints which OpenCV is loaded. Run in BOTH the COOL venv and the stock venv; screenshot both."""
import platform
import sys

import cv2

info = cv2.getBuildInformation()
print("python", sys.version.split()[0], platform.machine())
print("cv2", cv2.__version__, cv2.__file__)
print("COOL path:", "/opt/cool" in cv2.__file__.replace("\\", "/"))
for line in info.splitlines():
    if any(k in line.lower() for k in ("kleidicv", "hal", "cpu/hw", "dispatched", "neon", "sve")):
        print("  ", line.strip())
print("threads:", cv2.getNumThreads())
print("phaseCorrelateIterative:", hasattr(cv2, "phaseCorrelateIterative"))
