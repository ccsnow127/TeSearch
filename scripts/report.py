"""Summarise a run directory: one row per module plus the mean.

    python scripts/report.py runs/demo2 [--csv runs/demo2/summary.csv]
    python scripts/report.py example_run

cov, mut and hv describe the delivered suite, both on the mutants the search used
and on the held-out ones. size is how many tests the model wrote for it. seed_hv
is the best of the opening generations, so the gap to hv is what searching added.
"""
import argparse
import csv
import json
import statistics as st
import sys
from pathlib import Path


def load(run_dir: Path) -> list[dict]:
    rows = []
    for res in sorted(run_dir.glob("*/result.json")):
        r = json.loads(res.read_text())
        d = r["delivered"]
        events = [json.loads(l) for l in (res.parent / "events.jsonl").read_text().splitlines()]
        seeds = [e["hv"] for e in events if e["kind"] == "seed" and e.get("measured")]
        sizes = [e["size"] for e in events if e.get("measured")]
        breeds = [e for e in events if e["kind"] == "breed"]
        on_target = [e for e in breeds if e.get("measured") and e["landed"] == e["arm"]]
        rows.append({
            "module": r["module"], "instance": r["instance_id"],
            "seed_hv": max(seeds) if seeds else 0.0,
            "cov": d["cov"], "mut": d["mut"], "hv": d["hv"],
            "eval_cov": d.get("eval_cov"), "eval_mut": d.get("eval_mut"), "eval_hv": d.get("eval_hv"),
            "size": d["size"], "max_size": max(sizes) if sizes else 0,
            "moqd": r["moqd"], "calls": r["calls"],
            "on_target": len(on_target) / max(1, sum(1 for e in breeds if e.get("measured"))),
            "minutes": r.get("wall_minutes"),
        })
    return rows


def fmt(v, nd=3):
    return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--csv")
    args = ap.parse_args()
    rows = load(Path(args.run_dir))
    if not rows:
        print(f"no result.json under {args.run_dir}")
        return 1
    cols = ["seed_hv", "cov", "mut", "hv", "eval_cov", "eval_mut", "eval_hv", "size",
            "max_size", "moqd", "on_target", "minutes"]
    print(f"{'module':58s} " + " ".join(f"{c:>9s}" for c in cols))
    for r in rows:
        print(f"{r['module'][:58]:58s} " + " ".join(f"{fmt(r[c]):>9s}" for c in cols))
    mean = {c: (st.mean(v) if (v := [r[c] for r in rows if r[c] is not None]) else None)
            for c in cols}
    print(f"{'MEAN over ' + str(len(rows)) + ' modules':58s} "
          + " ".join(f"{fmt(None if mean[c] is None else float(mean[c]), 3 if c not in ('size', 'max_size', 'minutes') else 1):>9s}"
                     for c in cols))
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
