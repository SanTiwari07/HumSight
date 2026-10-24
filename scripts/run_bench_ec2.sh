#!/usr/bin/env bash
# COOL vs stock benchmark on the same instance. Push bench/*.json and RESULTS.md to git immediately after.
# Usage: INSTANCE_TYPE=c8g.large AMI_ID=ami-... bash scripts/run_bench_ec2.sh [extra bench.py args, e.g. --runs 7]
set -eo pipefail
cd "$(dirname "$0")/.."
uname -a | tee bench/uname.txt
COOL_PY=/opt/cool/venvs/python_3.12/bin/python
STOCK_PY=$HOME/stock/bin/python
"$COOL_PY"  bench/bench.py --label cool  --out bench/cool.json  "$@"
"$STOCK_PY" bench/bench.py --label stock --out bench/stock.json "$@"
"$STOCK_PY" bench/bench.py --compare bench/cool.json bench/stock.json --md bench/RESULTS.md ${SPOT_PRICE:+--spot-price $SPOT_PRICE}
