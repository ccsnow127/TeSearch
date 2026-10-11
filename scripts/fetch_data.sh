#!/usr/bin/env bash
# Fetch TestGenEval (harness reference) and the TestGenEval-lite split, then build
# the module manifest. Idempotent: existing files are kept.
set -euo pipefail
cd "$(dirname "$0")/.."

# Reference only: the benchmark's own harness, handy to look things up in. A run
# does not need it, so a failure here is a warning rather than an error.
if [ ! -d third_party/testgeneval/.git ]; then
  mkdir -p third_party
  git clone --depth 1 https://github.com/facebookresearch/testgeneval third_party/testgeneval \
    || echo "note: could not clone the reference repository; continuing without it"
fi

mkdir -p data/testgenevallite
BASE=https://huggingface.co/datasets/kjain14/testgenevallite/resolve/main/data
for split in test dev; do
  f=data/testgenevallite/$split.parquet
  if [ ! -s "$f" ]; then
    curl -fsSL -o "$f" "$BASE/$split-00000-of-00001.parquet"
  fi
done

PY=${PYTHON:-python}
"$PY" scripts/build_modules.py
