"""Group the lite rows into modules and write data/modules_lite.jsonl.

Sanity-checks the split while it is at it: 160 instances, 129 distinct modules,
and the expected number of modules per repository.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tesearch.data import DATA_ROOT, load_modules, load_rows, summary  # noqa: E402

EXPECTED_PER_REPO = {"django/django": 48, "sympy/sympy": 31, "scikit-learn/scikit-learn": 20,
           "pytest-dev/pytest": 10, "matplotlib/matplotlib": 7, "astropy/astropy": 3,
           "pydata/xarray": 3, "mwaskom/seaborn": 2, "sphinx-doc/sphinx": 2,
           "pylint-dev/pylint": 2, "pallets/flask": 1}


def main() -> int:
    rows = load_rows("test")
    tasks = load_modules("test")
    counts = dict(summary(tasks))
    print(f"instances: {len(rows)}   modules: {len(tasks)}")
    for repo, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {repo:28s} {n:3d}")
    out = DATA_ROOT.parent / "modules_lite.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps({"module_id": t.module_id, "repo": t.repo, "version": t.version,
                                "instance_id": t.instance_id, "row_id": t.row_id,
                                "code_file": t.code_file, "test_file": t.test_file,
                                "dotted": t.dotted, "image": t.image, "s_min": t.s_min,
                                "instance_ids": list(t.instance_ids)}) + "\n")
    print(f"wrote {out}")
    ok = len(rows) == 160 and len(tasks) == 129 and counts == EXPECTED_PER_REPO
    print("split looks right" if ok else "SPLIT DOES NOT MATCH what is expected")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
