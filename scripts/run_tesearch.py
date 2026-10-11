"""Run TeSearch on one module, a subset, or the whole benchmark.

    python scripts/run_tesearch.py --subset demo2 --jobs 2 --model gpt-5.4 --out runs/demo2
    python scripts/run_tesearch.py --module pytest-dev__pytest-7373 --budget 10
    python scripts/run_tesearch.py --list --subset demo2

Search knobs default to configs/default.yaml; --model and --budget override it.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tesearch.run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
