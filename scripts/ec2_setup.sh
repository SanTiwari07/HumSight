#!/usr/bin/env bash
# Run ON the COOL Graviton4 instance (c8g.large, Spot). Two environments on the SAME box:
#   COOL venv  : /opt/cool/venvs/python_3.12  (do NOT pip install opencv-python* into it)
#   stock venv : ~/stock                      (opencv-python-headless==5.0.0.93, the baseline)
set -euo pipefail
REPO_DIR="${1:-$HOME/humsight}"
NUMPY_PIN="${NUMPY_PIN:-2.5.4}"       # same pin in both envs: pip freeze | grep numpy

ls /opt/cool/venvs/                                       # expect python_3.10 python_3.11 python_3.12
source /opt/cool/venvs/python_3.12/bin/activate
python "$REPO_DIR/scripts/verify_cool.py"                 # screenshot: COOL path + KleidiCV lines
pip install fastapi "uvicorn[standard]" python-multipart google-genai "numpy==$NUMPY_PIN"   # NOT opencv
deactivate

python3.12 -m venv ~/stock || (sudo apt-get update && sudo apt-get install -y python3.12-venv && python3.12 -m venv ~/stock)
source ~/stock/bin/activate
pip install "opencv-python-headless==5.0.0.93" "numpy==$NUMPY_PIN" fastapi "uvicorn[standard]" python-multipart google-genai
python "$REPO_DIR/scripts/verify_cool.py"                 # must show site-packages cv2, COOL path: False
deactivate
echo "Next: python scripts/make_demo_clips.py ; bash scripts/run_bench_ec2.sh"
