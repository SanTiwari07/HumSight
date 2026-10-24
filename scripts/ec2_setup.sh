#!/usr/bin/env bash
# Run ON the COOL Graviton4 instance (c8g.large, Spot). Two environments on the SAME box:
#   COOL venv  : /opt/cool/venvs/python_3.12  (root-owned and left untouched; it already has cv2 + numpy)
#   stock venv : ~/stock                      (opencv-python-headless==5.0.0.93, the baseline)
# NumPy is pinned to whatever the COOL venv ships, so the OpenCV build is the only difference.
# Optional server extras for the COOL venv go to ~/cool_extra (run with PYTHONPATH=~/cool_extra).
# No `set -u`: the COOL venv's activate script reads an unset PYTHONPATH.
set -eo pipefail
REPO_DIR="${1:-$HOME/humsight}"
# run a command inside the activated COOL venv (activation sets PYTHONPATH and LD_LIBRARY_PATH for cv2 + COOL ffmpeg)
cool() { ( set +u; source /opt/cool/venvs/python_3.12/bin/activate; "$@" ); }

ls /opt/cool/venvs/                                       # expect python_3.10 python_3.11 python_3.12
cool python "$REPO_DIR/scripts/verify_cool.py"            # proof: COOL path + KleidiCV lines
NUMPY_PIN="${NUMPY_PIN:-$(cool python -c 'import numpy; print(numpy.__version__)')}"
echo "numpy pin (from the COOL venv): $NUMPY_PIN"

# server extras for live sessions (not needed for the benchmark)
python3.12 -m pip --version >/dev/null 2>&1 || sudo apt-get install -y python3-pip
python3.12 -m pip install -q --break-system-packages --target ~/cool_extra fastapi "uvicorn[standard]" python-multipart || \
  echo "WARNING: could not install server extras; the benchmark does not need them"

python3.12 -m venv ~/stock || (sudo apt-get update && sudo apt-get install -y python3.12-venv && python3.12 -m venv ~/stock)
~/stock/bin/pip install -q "opencv-python-headless==5.0.0.93" "numpy==$NUMPY_PIN"
~/stock/bin/python "$REPO_DIR/scripts/verify_cool.py"     # must show site-packages cv2, COOL path: False
echo "SETUP DONE. Next: bash scripts/run_bench_ec2.sh"
