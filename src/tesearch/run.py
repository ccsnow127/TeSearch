"""Command line entry point (``scripts/run_tesearch.py`` is a thin wrapper).

    python scripts/run_tesearch.py --subset demo2 --jobs 2 --out runs/demo2
    python scripts/run_tesearch.py --module django__django-17087
    python scripts/run_tesearch.py --all --out runs/lite
    python scripts/run_tesearch.py --list [--subset demo2]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import DEFAULT_CONFIG, Config
from .data import ModuleTask, get_module, load_modules, load_subset
from .harness.executor import DockerExecutor
from .harness.llm import LLMClient
from .harness.measure import measure
from .search import TeSearch

log = logging.getLogger("tesearch")


class HarnessMeasurer:
    def __init__(self, executor: DockerExecutor) -> None:
        self.executor = executor

    def measure(self, src: str, fold: str = "search"):
        return measure(self.executor, src, fold)


def run_module(task: ModuleTask, cfg: Config, out_root: Path, resume: bool = True) -> dict | None:
    out = out_root / task.slug
    if (out / "result.json").exists():
        log.info("%s: already done, skipping", task.module_id)
        return json.loads((out / "result.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    llm = LLMClient(cfg.model, cfg.temperature, cfg.max_tokens, io_log=out / "llm_io.jsonl")
    with DockerExecutor(task, cfg.search_mutants, cfg.eval_mutants, cfg.mutant_seed) as dx:
        log.info("%s: container ready (%d search / %d eval mutants)",
                 task.module_id, dx.n_search, dx.n_eval)
        search = TeSearch(task, HarnessMeasurer(dx), llm, cfg, out)
        if resume and search.resume():
            log.info("%s: resumed at call %d", task.module_id, search.calls)
        delivered = search.run()
    if delivered is None:
        log.warning("%s: no suite could be measured", task.module_id)
        return None
    result = json.loads((out / "result.json").read_text())
    result["wall_minutes"] = round((time.time() - started) / 60, 1)
    (out / "result.json").write_text(json.dumps(result, indent=2))
    d = result["delivered"]
    log.info("%s: done in %.0f min — hv %.3f, size %d", task.module_id,
             result["wall_minutes"], d["hv"], d["size"])
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tesearch")
    target = ap.add_mutually_exclusive_group()
    target.add_argument("--module", help="instance id, row id, module id or dotted path")
    target.add_argument("--subset", help="a list in data/subsets/, e.g. demo2")
    target.add_argument("--all", action="store_true", help="every module of the split")
    ap.add_argument("--list", action="store_true", help="list the selected modules and exit")
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default="runs/lite")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="search configuration (default: configs/default.yaml)")
    ap.add_argument("--model", help=f"LLM backbone (default from --config: {Config.model})")
    ap.add_argument("--budget", type=int, help=f"LLM calls per module (default: {Config.budget})")
    ap.add_argument("--jobs", type=int, default=1, help="modules run in parallel")
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.module:
        tasks = [get_module(args.module, args.split)]
    elif args.subset:
        tasks = load_subset(args.subset, args.split)
    elif args.all or args.list:
        tasks = load_modules(args.split)
    else:
        ap.error("choose --module, --subset or --all")
    if args.list:
        for t in tasks:
            print(f"{t.instance_id:36s} {t.module_id:60s} {t.image}")
        return 0

    cfg = Config.from_yaml(args.config, model=args.model, budget=args.budget)
    out_root = Path(args.out)
    failed = []

    def job(task):
        try:
            return run_module(task, cfg, out_root, resume=not args.no_resume)
        except Exception:  # noqa: BLE001 — one module failing must not stop the others
            log.exception("%s: run failed (rerun the same command to resume)", task.module_id)
            failed.append(task.instance_id)
            return None

    if args.jobs <= 1:
        for t in tasks:
            job(t)
    else:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for f in as_completed([pool.submit(job, t) for t in tasks]):
                f.result()
    if failed:
        log.error("%d module(s) failed: %s", len(failed), " ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
