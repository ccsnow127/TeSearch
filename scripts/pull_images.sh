#!/usr/bin/env bash
# Pull the testbed images of a subset before running (default: demo2), so the
# first run of each module does not pay for — or time out on — the download.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python}
SUBSET=${1:-demo2}
"$PY" scripts/run_tesearch.py --list --subset "$SUBSET" | awk '{print $3}' | sort -u | while read -r img; do
  echo ">> $img"
  docker pull --platform linux/amd64 "$img"
done
