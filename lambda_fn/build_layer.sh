#!/usr/bin/env bash
# Build the arm64 deployment packages WITHOUT Docker, from any OS, by targeting the
# manylinux aarch64 wheels. Run from the repo root:  bash lambda_fn/build_layer.sh
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf build && mkdir -p build/python
pip install \
  --platform manylinux_2_28_aarch64 --platform manylinux_2_17_aarch64 --platform manylinux2014_aarch64 \
  --implementation cp --python-version 3.12 \
  --only-binary=:all: --target build/python \
  -r requirements-lambda.txt
# trim (keep *.dist-info: google-genai reads its own metadata)
find build/python -name "__pycache__" -type d -prune -exec rm -rf {} + || true
find build/python -name "tests" -type d -prune -exec rm -rf {} + || true
du -sh build/python   # Lambda limit: 250 MB unzipped (function + layers)
(cd build && python -c "import shutil; shutil.make_archive('layer', 'zip', '.', 'python')" && mv layer.zip ../layer.zip)
# function code: the humsight package + handler (no server/, web/, eval/)
rm -rf build/fn && mkdir -p build/fn
cp -r humsight build/fn/humsight && cp lambda_fn/handler.py build/fn/handler.py
find build/fn -name "__pycache__" -type d -prune -exec rm -rf {} + || true
(cd build/fn && python -c "import shutil; shutil.make_archive('function', 'zip', '.')" && mv function.zip ../../function.zip)
ls -lh layer.zip function.zip
echo "Handler: handler.handler | Runtime python3.12 | Architecture arm64 | Memory 3008 MB | Timeout 120 s"
