#!/usr/bin/env bash
# COOL vs stock benchmark on the same instance. Push bench/*.json and RESULTS.md to git immediately after.
set -euo pipefail
cd "$(dirname "$0")/.."
uname -a | tee bench/uname.txt
source /opt/cool/venvs/python_3.12/bin/activate && python bench/bench.py --label cool --out bench/cool.json && deactivate
source ~/stock/bin/activate && python bench/bench.py --label stock --out bench/stock.json && deactivate
source ~/stock/bin/activate && python bench/bench.py --compare bench/cool.json bench/stock.json --md bench/RESULTS.md && deactivate
